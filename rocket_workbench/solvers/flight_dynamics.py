"""Experimental passive six-degree-of-freedom rocket flight.

Actual rigid-body equations do not validate the aerodynamic coefficients. This
solver enforces an explicit small-angle domain and reports incomplete results at
meaningful unsupported incidence instead of inventing post-stall/tumbling loads.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

from rocket_workbench.models import Conditions, Project, active_components, configuration
from rocket_workbench.solvers import aero, attitude

GEOMETRY_TO_BODY = np.diag([-1.0, 1.0, -1.0])
ANGLE_LIMIT_RAD = math.radians(10)
NORMAL_LIMIT_WEIGHT_FRACTION = .01


def _parallel_axis(vector: np.ndarray) -> np.ndarray:
    return float(np.dot(vector, vector))*np.eye(3) - np.outer(vector, vector)


class InertiaModel:
    """Dry mesh/point-distribution tensor plus changing motor propellant.

    Known mass/CG overrides define component weights. Closed uniformly filled
    meshes supply normalized second moments; this is not a laminate/shell survey.
    """
    def __init__(self, project: Project, configuration_id: str | None, motor, mass_properties: dict):
        from rocket_workbench.geometry import component_mesh
        cfg = configuration(project, configuration_id)
        rows = {row["component_id"]: row for row in mass_properties["components"]}
        mass_sum = 0.0
        moment_sum = np.zeros(3)
        inertia_origin = np.zeros((3, 3))
        self.provenance = []
        self.warnings = []
        for part in active_components(project, configuration_id):
            row = rows[part.id]
            mass = row["mass_kg"]
            if mass <= 0:
                continue
            centroid = np.array([row["cg_m"], 0.0, 0.0])
            normalized_inertia = np.zeros((3, 3))
            basis = "Point-mass at assigned axial CG; unresolved local mass distribution"
            try:
                mesh = component_mesh(project, part)
                ambiguous_volume = mesh.metadata.get("volume_ambiguous")
                if ambiguous_volume:
                    inertia_fallback = ("The supplied complete dry-rocket tensor replaces component inertia estimates."
                                        if cfg.inertia_override_kg_m2 is not None else
                                        "The disclosed point/cylinder surrogate is used; supply a measured complete dry-rocket tensor for reliable inertia.")
                    self.warnings.append(f"{part.name}: imported CAD has no reliable material volume ({ambiguous_volume}); mesh-derived inertia and lateral CG are unavailable. {inertia_fallback} Assigned axial CG is retained with an on-axis lateral CG assumption.")
                if not ambiguous_volume and len(mesh.vertices) and mesh.is_watertight and mesh.is_winding_consistent and abs(float(mesh.volume)) > 1e-15:
                    normalized_inertia = np.asarray(mesh.moment_inertia, dtype=float)/abs(float(mesh.volume))
                    # A consistently inward whole solid has negative density-one
                    # inertia; correct its global sign, not individual cavities.
                    if float(mesh.volume) < 0:
                        normalized_inertia *= -1
                    centroid[1:] = np.asarray(mesh.center_mass)[1:]
                    basis = "Closed component triangular-mesh volume moments normalized to assigned component mass; uniform density"
                elif part.kind in aero.BODY | {"innertube", "tubecoupler", "launchlug", "centeringring", "bulkhead", "engineblock"}:
                    radius = part.radius
                    normalized_inertia = np.diag([radius*radius/2, (3*radius*radius+part.length*part.length)/12,
                                                   (3*radius*radius+part.length*part.length)/12])
                    basis = ("Uniform circular-cylinder inertia surrogate; CAD material volume is ambiguous"
                             if ambiguous_volume else "Uniform circular-cylinder inertia surrogate; component mesh is not a closed solid")
                    self.warnings.append(f"{part.name}: inertia uses a circular-cylinder surrogate, not a measured distribution.")
                else:
                    self.warnings.append(f"{part.name}: unresolved local inertia is represented by a point mass at its assigned CG.")
            except (ValueError, RuntimeError) as exc:
                self.warnings.append(f"{part.name}: mesh inertia unavailable ({exc}); point-mass local inertia used.")
            if not np.all(np.isfinite(normalized_inertia)) or np.min(np.linalg.eigvalsh(normalized_inertia)) < -1e-9:
                raise ValueError(f"{part.name}: closed mesh has nonphysical inertia; check surface orientation and assigned mass.")
            inertia_origin += mass*(normalized_inertia + _parallel_axis(centroid))
            moment_sum += mass*centroid
            mass_sum += mass
            self.provenance.append({"component_id": part.id, "name": part.name, "mass_kg": mass, "basis": basis})
        self.motor_center = np.array([mass_properties["motor"]["cg_m"], 0.0, 0.0])
        motor_radius = motor.diameter/2
        self.motor_normalized_inertia = np.diag([motor_radius*motor_radius/2,
            (3*motor_radius*motor_radius+motor.length*motor.length)/12,
            (3*motor_radius*motor_radius+motor.length*motor.length)/12])
        inertia_origin += motor.dry_mass*(self.motor_normalized_inertia + _parallel_axis(self.motor_center))
        moment_sum += motor.dry_mass*self.motor_center
        mass_sum += motor.dry_mass
        if mass_sum <= 0:
            raise ValueError("Rigid-body dry mass must be positive.")
        self.dry_mass = mass_sum
        self.dry_cg = moment_sum/mass_sum
        self.dry_inertia_geometry = inertia_origin - mass_sum*_parallel_axis(self.dry_cg)
        if cfg.inertia_override_kg_m2 is not None:
            self.dry_inertia_geometry = GEOMETRY_TO_BODY @ np.array(cfg.inertia_override_kg_m2) @ GEOMETRY_TO_BODY
            self.basis = "User-supplied complete dry-rocket inertia about dry CG: " + cfg.inertia_override_source
        else:
            self.basis = "Estimated component-mesh volume moments plus disclosed point/cylinder and motor surrogates"
            self.warnings.append("Rigid-body inertia is estimated from component mass-normalized geometry, not a measured tensor. Packed hardware and heterogeneous/CAD assemblies need a measured dry-rocket inertia override.")
        self.warnings.append("Motor dry and propellant inertia use uniform cylinders at a fixed motor center; grain geometry, propellant slosh, jet damping and changing exhaust angular momentum are not resolved.")
        self.at(0)

    def at(self, propellant_mass: float) -> tuple[float, np.ndarray, np.ndarray]:
        mass = self.dry_mass + propellant_mass
        cg = (self.dry_mass*self.dry_cg + propellant_mass*self.motor_center)/mass
        tensor = (self.dry_inertia_geometry + self.dry_mass*_parallel_axis(self.dry_cg-cg)
                  + propellant_mass*(self.motor_normalized_inertia + _parallel_axis(self.motor_center-cg)))
        tensor = GEOMETRY_TO_BODY @ tensor @ GEOMETRY_TO_BODY
        if not np.all(np.isfinite(tensor)) or np.min(np.linalg.eigvalsh(tensor)) <= 1e-12:
            raise ValueError("Rigid-body inertia is singular/nonpositive; enter a measured symmetric positive dry tensor.")
        return mass, cg, tensor


def simulate(project: Project, conditions: Conditions, configuration_id: str | None = None,
             progress: Callable | None = None, cancelled: Callable | None = None) -> dict:
    from rocket_workbench.solvers.flight import _validated_motor
    from rocket_workbench.solvers.wind import WindField
    if cancelled and cancelled():
        raise RuntimeError("Simulation cancelled.")
    if progress:
        progress(0, "Preparing rigid-body inertia and small-angle force model")
    cfg, motor, curve, cumulative, impulse = _validated_motor(project, configuration_id)
    prepared = aero._prepare(project, configuration_id)
    if prepared["cna_per_rad"] <= 0 and prepared.get("polar") is None:
        raise ValueError("Rigid-body flight requires positive supported CNa/CP or a geometry-matched supplied polar.")
    mass0 = aero.mass_properties(project, configuration_id)
    inertia_model = InertiaModel(project, configuration_id, motor, mass0)
    wind_field = WindField(conditions)
    warnings = prepared["warnings"] + mass0["warnings"] + inertia_model.warnings + wind_field.warnings + [
        "Experimental rigid-body 6DOF with reference small-angle aerodynamic slopes and CP; no validated arbitrary-CAD or post-stall/tumbling aerodynamics.",
        "No aerodynamic roll/cant/roll-damping model is supplied. Roll can evolve from initial spin, mass asymmetry and Euler gyroscopic coupling, but no invented roll coefficients are applied.",
        "Propellant inertia changes through a uniform on-axis cylinder with co-rotating symmetric removal; no jet damping or measured exhaust angular-momentum model.",
        "Recovery is a point drag load at CG with user-assumed linear Cd-area inflation. No opening shock, line stretch, canopy CFD, pendulum or recovery attitude moment model.",
    ]
    if cfg.pitch_damping_coefficient is None:
        warnings.append("No measured/supplied pitch/yaw damping coefficient: empirical angular damping is zero. Undamped restoring oscillations are a model limitation, not a prediction of actual damping.")
    else:
        warnings.append("Pitch/yaw damping uses the user-supplied Cmq with rate normalization omega*L/(2V); its applicability is the user's responsibility.")
    burnout_time = cfg.ignition_delay + float(curve[-1, 0])
    if cfg.primary_deploy_event == "motor_ejection" and cfg.motor_ejection_delay is None:
        raise ValueError("Motor-ejection deployment needs the actual motor ejection delay.")
    def propulsion(t):
        local = t-cfg.ignition_delay
        thrust = float(np.interp(local, curve[:, 0], curve[:, 1], left=0, right=0)) if local < curve[-1, 0] else 0.0
        if local <= curve[0, 0]:
            fraction = 0.0
        elif local >= curve[-1, 0]:
            fraction = 1.0
        else:
            i = int(np.searchsorted(curve[:, 0], local, side="right")-1)
            elapsed = local-curve[i, 0]
            slope = (curve[i+1, 1]-curve[i, 1])/(curve[i+1, 0]-curve[i, 0])
            fraction = float(np.clip((cumulative[i]+curve[i, 1]*elapsed+.5*slope*elapsed**2)/impulse, 0, 1))
        mass, cg, inertia = inertia_model.at(motor.propellant_mass*(1-fraction))
        return thrust, mass, cg, inertia
    tilt, azimuth = math.radians(conditions.launch_angle), math.radians(conditions.launch_azimuth)
    rail_axis = np.array([math.sin(tilt)*math.sin(azimuth), math.sin(tilt)*math.cos(azimuth), math.cos(tilt)])
    state = np.r_[np.zeros(6), attitude.quaternion_from_axis(rail_axis), np.zeros(3)]
    initial_omega = np.array(conditions.initial_angular_velocity_body_rad_s, dtype=float)
    if not np.all(np.isfinite(initial_omega)):
        raise ValueError("Initial angular velocity must be finite.")
    on_rail, landed = True, False
    chute = "none"
    chute_start, chute_base_area = None, 0.0
    apogee_time = None
    deploy_time = burnout_time+cfg.motor_ejection_delay+cfg.apogee_delay if cfg.primary_deploy_event == "motor_ejection" else None
    time, next_step = 0.0, conditions.dt
    rows, events = [], []
    steps, rejected = 0, 0
    max_error, min_step, max_step = 0.0, None, 0.0
    max_quaternion_error = 0.0
    terminal_reason = None
    exceeded_mach, omitted_normal, used_polar, polar_gap = False, False, False, False
    last_progress = -1.0
    stress_model = None
    try:
        from rocket_workbench.solvers.structure import flight_stress_model, evaluate_flight_stress
        stress_model = flight_stress_model(project, configuration_id, conditions)
        warnings.extend(stress_model.get("warnings", []))
    except (ImportError, ValueError, RuntimeError) as exc:
        warnings.append(f"Flight quasi-static stress unavailable: {exc}")

    def canopy(at_time):
        if chute == "none":
            return 0.0, 0.0
        duration = cfg.main_inflation_time if chute == "main" else cfg.drogue_inflation_time
        fraction = 1.0 if duration == 0 else float(np.clip((at_time-chute_start)/duration, 0, 1))
        target = cfg.main_cd_area if chute == "main" else cfg.drogue_cd_area
        return chute_base_area+(target-chute_base_area)*fraction, fraction

    def deploy(mode):
        nonlocal chute, chute_start, chute_base_area
        prior_area = canopy(time)[0]
        chute, chute_start, chute_base_area = mode, time, prior_area

    def evaluate(at_time, s, integration_stage=False):
        atm = aero.atmosphere(conditions.altitude+max(0.0, float(s[2])), wind_field.temperature_delta(at_time))
        thrust, mass, cg_geometry, tensor = propulsion(at_time)
        rotation = attitude.rotation_matrix(s[6:10])
        nose = rotation[:, 0]
        wind = wind_field.velocity(at_time, max(0.0, float(s[2])), s[:3])
        relative = s[3:6]-wind
        speed = float(np.linalg.norm(relative))
        aero_result = aero._evaluate(prepared, atm, speed)
        normal, alpha = attitude.aerodynamic_normal(nose, relative, aero_result["dynamic_pressure_pa"], prepared["reference_area_m2"], aero_result["cna_per_rad"])
        in_domain = alpha <= ANGLE_LIMIT_RAD+1e-10
        limit_force = aero_result["dynamic_pressure_pa"]*prepared["reference_area_m2"]*max(0, aero_result["cna_per_rad"])*ANGLE_LIMIT_RAD
        meaningful = limit_force > NORMAL_LIMIT_WEIGHT_FRACTION*mass*atm["gravity_m_s2"]
        # Do not extrapolate CNa to 90/180-degree crossflow on the pad, near
        # apogee or under recovery. These omitted loads are explicitly recorded.
        linear_stage = integration_stage and meaningful and not on_rail and chute == "none"
        if (not in_domain and not linear_stage) or chute != "none":
            normal = np.zeros(3)
        area, inflation = canopy(at_time)
        drag_axis = -relative/speed if speed > 1e-9 else np.zeros(3)
        drag_body = drag_axis*aero_result["drag_n"]
        drag_recovery = drag_axis*aero_result["dynamic_pressure_pa"]*area
        thrust_force = nose*thrust
        gravity = np.array([0.0, 0.0, -atm["gravity_m_s2"]])
        force = drag_body+normal+drag_recovery+thrust_force+mass*gravity
        normal_moment = np.zeros(3)
        if (in_domain or linear_stage) and chute == "none" and aero_result["cp_m"] is not None:
            normal_moment = attitude.cp_moment(normal, rotation, aero_result["cp_m"], cg_geometry)
        thrust_arm = GEOMETRY_TO_BODY @ (inertia_model.motor_center-cg_geometry)
        thrust_moment = np.cross(thrust_arm, np.array([thrust, 0.0, 0.0]))
        damping_moment = np.zeros(3)
        if cfg.pitch_damping_coefficient is not None and in_domain and speed > 1 and chute == "none":
            damp = aero_result["dynamic_pressure_pa"]*prepared["reference_area_m2"]*prepared["length_m"]**2/(2*speed)*cfg.pitch_damping_coefficient
            damping_moment[1:] = damp*s[11:13]
        moment = normal_moment+thrust_moment+damping_moment
        acceleration = force/mass
        dq, domega = attitude.derivatives(s[6:10], s[10:13], moment, tensor)
        velocity = s[3:6].copy()
        reaction = np.zeros(3)
        if on_rail:
            rail_speed = float(np.dot(velocity, rail_axis))
            rail_acceleration = float(np.dot(acceleration, rail_axis))
            if float(np.dot(s[:3], rail_axis)) <= 1e-10 and rail_speed <= 0 and rail_acceleration < 0:
                rail_speed, rail_acceleration = 0.0, 0.0
            velocity = rail_axis*rail_speed
            acceleration = rail_axis*rail_acceleration
            reaction = mass*acceleration-force
            dq, domega = np.zeros(4), np.zeros(3)
        return {"derivative": np.r_[velocity, acceleration, dq, domega], "aero": aero_result, "atmosphere": atm,
                "relative": relative, "wind": wind, "speed": speed, "thrust": thrust, "mass": mass, "cg": cg_geometry,
                "inertia": tensor, "normal": normal, "angle": alpha, "in_domain": in_domain,
                "meaningful_angle": meaningful, "moment": moment, "normal_moment": normal_moment,
                "thrust_moment": thrust_moment, "damping_moment": damping_moment, "unconstrained_force": force,
                "nose": nose, "rotation": rotation,
                "body_drag": drag_body, "recovery_drag": drag_recovery, "thrust_force": thrust_force,
                "gravity": gravity, "reaction": reaction, "canopy_area": area, "inflation": inflation}

    def rhs(t, s):
        # A trial stage may briefly cross the linear domain to locate its first
        # boundary. That trial is discarded at the root; no out-of-domain
        # meaningful normal-force state is accepted as a completed prediction.
        return evaluate(t, s, integration_stage=True)["derivative"]

    def rk4(t, s, dt):
        k1 = rhs(t, s)
        k2 = rhs(t+dt/2, s+dt*k1/2)
        k3 = rhs(t+dt/2, s+dt*k2/2)
        end = t+dt
        discontinuities = [cfg.ignition_delay+curve[0, 0], burnout_time] + [change.time_s for change in conditions.wind_events if change.transition_s == 0]
        if any(abs(end-edge) < 1e-10 and t < edge-1e-10 for edge in discontinuities):
            end = math.nextafter(end, -math.inf)
        k4 = rhs(end, s+dt*k3)
        out = s+dt*(k1+2*k2+2*k3+k4)/6
        out[6:10] = attitude.normalize(out[6:10])
        return out

    def controlled_step(dt):
        nonlocal rejected, next_step, max_error, max_quaternion_error
        scale_abs = np.r_[np.full(6, 1e-5), np.full(4, 1e-8), np.full(3, 1e-7)]
        for _ in range(24):
            if cancelled and cancelled():
                raise RuntimeError("Simulation cancelled.")
            coarse = rk4(time, state, dt)
            half = rk4(time, state, dt/2)
            fine = rk4(time+dt/2, half, dt/2)
            # q and -q represent the same physical attitude.
            if np.dot(coarse[6:10], fine[6:10]) < 0:
                coarse[6:10] *= -1
            norm = float(np.max(np.abs(fine-coarse)/15/(scale_abs+1e-7*np.maximum(np.abs(fine), np.abs(state)))))
            if not np.all(np.isfinite(fine)) or not math.isfinite(norm):
                raise RuntimeError("Nonfinite rigid-body integration state; inspect inertia and force inputs.")
            if norm <= 1:
                max_error = max(max_error, norm)
                max_quaternion_error = max(max_quaternion_error, abs(float(np.linalg.norm(fine[6:10]))-1))
                next_step = min(conditions.dt, dt*(2 if norm < 1e-12 else min(2, max(.5, .9*norm**(-.2)))))
                return dt, fine
            rejected += 1
            dt *= max(.1, .9*norm**(-.2))
            if dt < 1e-8:
                raise RuntimeError("Rigid-body numerical tolerance requires a sub-nanosecond-scale step; inspect tensor/coefficient inputs.")
        raise RuntimeError("Rigid-body adaptive integration failed to meet local tolerances.")

    def event_root(dt, measure, threshold):
        low, high = 0.0, dt
        start = measure(state, time)-threshold
        for _ in range(28):
            mid = (low+high)/2
            candidate = rk4(time, state, mid/2)
            candidate = rk4(time+mid/2, candidate, mid/2)
            if (measure(candidate, time+mid)-threshold)*start > 0:
                low = mid
            else:
                high = mid
        dt = (low+high)/2
        candidate = rk4(time, state, dt/2)
        return dt, rk4(time+dt/2, candidate, dt/2)

    def record(name):
        if not any(e["name"] == name for e in events):
            events.append({"name": name, "time": time})

    def environment_events():
        for index, change in enumerate(conditions.wind_events):
            if abs(time-change.time_s) < 1e-8 and not any(e.get("environment_event_index") == index for e in events):
                events.append({"name": "environment_change", "time": time, "environment_event_index": index, "settings": change.model_dump()})

    def append_row():
        nonlocal exceeded_mach, omitted_normal, used_polar, polar_gap
        d = evaluate(time, state)
        a, atm = d["aero"], d["atmosphere"]
        specific = d["derivative"][3:6]-d["gravity"]
        static_margin = (a["cp_m"]-d["cg"][0])/prepared["diameter_m"] if a["cp_m"] is not None else None
        stress, structural_components = None, []
        if stress_model is not None and any(row.get("supported", True) for row in stress_model.get("components", [])):
            estimate = evaluate_flight_stress(stress_model, a["dynamic_pressure_pa"], float(np.linalg.norm(specific)))
            stress, structural_components = estimate.get("max_stress_pa"), estimate.get("components", [])
        phase = "landed" if landed else chute if chute != "none" else "pad" if on_rail and np.linalg.norm(state[:3]) < 1e-9 else "rail" if on_rail else "powered" if time < burnout_time-1e-8 else "coast"
        normal_loads_supported = d["in_domain"] and chute == "none"
        component_rows = []
        for component in a["components"]:
            force, _ = attitude.aerodynamic_normal(d["nose"], d["relative"], a["dynamic_pressure_pa"], prepared["reference_area_m2"], component["cna_per_rad"])
            component_rows.append({"component_id": component["component_id"], "name": component["name"],
                "cna_per_rad": component["cna_per_rad"], "cp_m": component["cp_m"], "drag_n": component["drag_n"],
                "normal_force_n": float(np.linalg.norm(force)) if normal_loads_supported else None,
                "normal_force_vector_n": force.tolist() if normal_loads_supported else None,
                "force_fidelity": "Original-reference per-component small-angle estimate; not supplied total-polar load distribution",
                "supported": normal_loads_supported})
        row = {"time": time, "altitude": max(0.0, float(state[2])), "altitude_msl": conditions.altitude+max(0.0, float(state[2])),
            "east": float(state[0]), "north": float(state[1]), "velocity": float(np.linalg.norm(state[3:6])), "vertical_velocity": float(state[5]),
            "velocity_vector": state[3:6].tolist(), "air_relative_speed": d["speed"], "air_relative_velocity_vector": d["relative"].tolist(),
            "density_kg_m3": atm["density_kg_m3"], "pressure_pa": atm["pressure_pa"], "temperature_k": atm["temperature_k"],
            "sound_speed_m_s": atm["speed_of_sound_m_s"], "body_axis_world": d["nose"].tolist(), "thrust_axis_world": d["nose"].tolist(),
            "body_quaternion_world": state[6:10].tolist(), "angular_velocity_body_rad_s": state[10:13].tolist(),
            "angle_of_attack_deg": math.degrees(d["angle"]), "aerodynamic_angle_supported": normal_loads_supported,
            "attitude_fidelity": "Integrated rigid-body quaternion/Euler equations; reference small-angle moments only; recovery torque-free surrogate",
            "inertia_tensor_body_kg_m2": d["inertia"].tolist(), "cg_geometry_m": d["cg"].tolist(),
            "aerodynamic_moment_body_nm": (d["normal_moment"]+d["damping_moment"]).tolist(), "aerodynamic_components": component_rows,
            "total_moment_body_nm": d["moment"].tolist(), "thrust_moment_body_nm": d["thrust_moment"].tolist(),
            "moment_vectors_body_nm": {"aerodynamic_normal": d["normal_moment"].tolist(), "pitch_yaw_damping": d["damping_moment"].tolist(),
                                       "thrust": d["thrust_moment"].tolist(), "net": d["moment"].tolist()},
            "acceleration": float(np.linalg.norm(d["derivative"][3:6])), "acceleration_vector": d["derivative"][3:6].tolist(),
            "specific_acceleration": float(np.linalg.norm(specific)), "specific_acceleration_vector": specific.tolist(),
            "force_vectors_n": {"body_aerodynamic_drag": d["body_drag"].tolist(), "aerodynamic_normal": d["normal"].tolist(),
                "recovery_drag": d["recovery_drag"].tolist(), "thrust": d["thrust_force"].tolist(), "gravity": (d["mass"]*d["gravity"]).tolist(),
                "rail_reaction": d["reaction"].tolist(), "net": (d["mass"]*d["derivative"][3:6]).tolist()},
            "load_breakdown": {"body_drag_n": a["drag_n"], "aerodynamic_normal_n": float(np.linalg.norm(d["normal"])),
                "recovery_drag_n": float(np.linalg.norm(d["recovery_drag"])), "total_drag_n": a["drag_n"]+float(np.linalg.norm(d["recovery_drag"])),
                "thrust_n": d["thrust"], "gravity_n": d["mass"]*atm["gravity_m_s2"], "net_force_n": d["mass"]*float(np.linalg.norm(d["derivative"][3:6]))},
            "mach": a["mach"], "dynamic_pressure": a["dynamic_pressure_pa"], "mass": d["mass"], "cg": float(d["cg"][0]), "cp": a["cp_m"],
            "stability": static_margin, "drag": a["drag_n"]+float(np.linalg.norm(d["recovery_drag"])), "thrust": d["thrust"],
            "stress": stress, "structural_components": structural_components, "stress_fidelity": "Fixed-reference quasi-static estimate, not attitude-dependent transient FEA" if stress is not None else "unavailable",
            "phase": phase, "wind_vector": d["wind"].tolist(), "polar_applied": a["polar_applied"],
            "aerodynamic_basis": "User-supplied geometry-matched polar" if a["polar_applied"] else "Original-reference small-angle coefficients",
            "recovery_cd_area_m2": d["canopy_area"], "recovery_inflation_fraction": d["inflation"],
            "canopy_load_n": float(np.linalg.norm(d["recovery_drag"])), "canopy_opening_load_n": float(np.linalg.norm(d["recovery_drag"]))}
        exceeded_mach |= a["mach"] > 2+1e-9
        omitted_normal |= not d["in_domain"] and not on_rail
        used_polar |= a["polar_applied"]
        polar_gap |= prepared.get("polar") is not None and not a["polar_applied"]
        if rows and abs(rows[-1]["time"]-time) < 1e-9:
            rows[-1] = row
        else:
            rows.append(row)
        return d

    if cfg.ignition_delay == 0:
        record("ignition")
    if float(np.dot(evaluate(0, state)["unconstrained_force"], rail_axis)) > 0:
        record("liftoff")
    environment_events()
    append_row()
    while time < conditions.max_time-1e-10 and not landed and terminal_reason is None:
        if cancelled and cancelled():
            raise RuntimeError("Simulation cancelled.")
        now = evaluate(time, state)
        if not on_rail and chute == "none" and not now["in_domain"] and now["meaningful_angle"]:
            terminal_reason = "aerodynamic_angle_limit"
            record("aerodynamic_model_limit")
            break
        if not on_rail and chute == "none" and now["aero"]["cp_m"] is None and now["aero"]["dynamic_pressure_pa"] > 1:
            terminal_reason = "undefined_aerodynamic_cp"
            record("aerodynamic_model_limit")
            break
        dt = min(conditions.dt, next_step, conditions.max_time-time)
        scheduled = [edge for edge in [cfg.ignition_delay, burnout_time, deploy_time] if edge is not None and edge > time+1e-9]
        scheduled.extend(edge for edge in wind_field.event_times if edge > time+1e-9)
        knot = int(np.searchsorted(curve[:, 0], time-cfg.ignition_delay+1e-9, side="right"))
        if knot < len(curve):
            scheduled.append(cfg.ignition_delay+float(curve[knot, 0]))
        if chute_start is not None:
            inflation_end = chute_start+(cfg.main_inflation_time if chute == "main" else cfg.drogue_inflation_time)
            if inflation_end > time+1e-9:
                scheduled.append(inflation_end)
        if scheduled:
            dt = min(dt, min(scheduled)-time)
        liftoff_time = None
        if on_rail and np.linalg.norm(state[:6]) < 1e-9:
            def balance(at_time):
                return float(np.dot(evaluate(at_time, state)["unconstrained_force"], rail_axis))
            if balance(time) >= -1e-10 and balance(time+dt) > 0:
                record("liftoff")
            elif balance(time) < -1e-10 and balance(time+dt) > 0:
                low, high = 0.0, dt
                for _ in range(32):
                    middle = (low+high)/2
                    if balance(time+middle) <= 0:
                        low = middle
                    else:
                        high = middle
                dt = high
                liftoff_time = time+dt
        # Translation and angular rotation both constrain timestep independently
        # of the user's requested output resolution.
        drag_area = prepared["reference_area_m2"]*now["aero"]["cd"]+now["canopy_area"]
        drag_stiffness = now["atmosphere"]["density_kg_m3"]*drag_area*max(1, now["speed"])
        if drag_stiffness > 0:
            dt = min(dt, .5*now["mass"]/drag_stiffness)
        omega = float(np.linalg.norm(state[10:13]))
        if omega > 0:
            dt = min(dt, .05/omega)
        dt, candidate = controlled_step(dt)
        candidate_events = []
        if on_rail and np.dot(candidate[:3], rail_axis) >= conditions.rail_length:
            candidate_events.append((*event_root(dt, lambda s, _t: float(np.dot(s[:3], rail_axis)), conditions.rail_length), "rail_exit"))
        if not on_rail and apogee_time is None and state[5] > 0 and candidate[5] <= 0:
            candidate_events.append((*event_root(dt, lambda s, _t: float(s[5]), 0), "apogee"))
        if chute == "drogue" and cfg.main_deploy_altitude > 0 and state[5] < 0 and state[2] > cfg.main_deploy_altitude and candidate[2] <= cfg.main_deploy_altitude:
            candidate_events.append((*event_root(dt, lambda s, _t: float(s[2]), cfg.main_deploy_altitude), "main_deployment"))
        if not on_rail and state[2] > 0 and candidate[2] <= 0 and candidate[5] < 0:
            candidate_events.append((*event_root(dt, lambda s, _t: float(s[2]), 0), "recovery"))
        final_trial = evaluate(time+dt, candidate)
        if not on_rail and chute == "none" and now["in_domain"] and not final_trial["in_domain"] and final_trial["meaningful_angle"]:
            candidate_events.append((*event_root(dt, lambda s, at_t: evaluate(at_t, s)["angle"], ANGLE_LIMIT_RAD), "aerodynamic_model_limit"))
        event_name = None
        if candidate_events:
            dt, candidate, event_name = min(candidate_events, key=lambda event: event[0])
            if event_name == "recovery":
                candidate[2] = 0
        time, state = time+dt, candidate
        min_step = dt if min_step is None else min(min_step, dt)
        max_step = max(max_step, dt)
        if liftoff_time is not None and abs(time-liftoff_time) < 1e-8:
            record("liftoff")
        if event_name == "rail_exit":
            on_rail = False
            state[10:13] = initial_omega
            record(event_name)
        elif event_name == "apogee":
            apogee_time = time
            if cfg.primary_deploy_event == "apogee":
                deploy_time = time+cfg.apogee_delay
            record(event_name)
            if chute == "drogue" and state[2] <= cfg.main_deploy_altitude:
                deploy("main")
                record("main_deployment")
        elif event_name == "main_deployment":
            deploy("main")
            record(event_name)
        elif event_name == "recovery":
            landed = True
            record(event_name)
        elif event_name == "aerodynamic_model_limit":
            terminal_reason = "aerodynamic_angle_limit"
            record(event_name)
        if abs(time-cfg.ignition_delay) < 1e-8:
            record("ignition")
        if abs(time-burnout_time) < 1e-8:
            record("burnout")
        if deploy_time is not None and abs(time-deploy_time) < 1e-8:
            deploy("main" if cfg.deployment == "single" else "drogue")
            if cfg.primary_deploy_event == "motor_ejection":
                record("motor_ejection")
            record("main_deployment" if chute == "main" else "drogue_deployment")
            if chute == "drogue" and state[2] <= cfg.main_deploy_altitude and state[5] <= 1e-7:
                deploy("main")
                record("main_deployment")
            deploy_time = None
        if on_rail and time > burnout_time+.1 and np.dot(state[3:6], rail_axis) <= 0:
            raise ValueError("The motor cannot lift/clear this rocket from its launch rail.")
        environment_events()
        append_row()
        steps += 1
        if progress and time-last_progress >= .5:
            progress(min(.99, time/conditions.max_time), f"Rigid-body {rows[-1]['phase']} at {time:.1f} s; AoA {rows[-1]['angle_of_attack_deg']:.1f}°")
            last_progress = time
    if terminal_reason == "aerodynamic_angle_limit":
        warnings.append("Rigid-body integration stopped at the aerodynamic model limit. Small-angle normal/CP moments are unsupported above 10° when the estimated normal force at that boundary exceeds 1% of weight; this partial trajectory is not a completed launch or tumbling prediction.")
    elif terminal_reason == "undefined_aerodynamic_cp":
        warnings.append("Rigid-body integration stopped because CP became undefined in unrecovered free flight at dynamic pressure above 1 Pa. This partial trajectory cannot establish aerodynamic attitude behavior.")
    elif not landed:
        terminal_reason = "maximum_time"
        warnings.append("Maximum simulation time reached before ground contact; trajectory is incomplete.")
    if omitted_normal:
        warnings.append("Unsupported high-incidence body normal forces/moments were omitted only on the constrained rail, during recovery, or at low loads (10° boundary force ≤1% of weight). This does not validate high-angle attitude near apogee or under a canopy.")
    if exceeded_mach:
        warnings.append("Trajectory exceeded Mach 2; aerodynamic coefficients are outside the supported operating range.")
    if polar_gap:
        warnings.append("Some flight rows lie outside supplied polar coverage and use original-reference coefficients.")
    if landed and chute == "none":
        warnings.append("Ground contact occurred before recovery deployment: undeployed impact, not a successful parachute recovery.")
    if any(event["name"] in {"main_deployment", "drogue_deployment"} and event["time"] < burnout_time-1e-8 for event in events):
        warnings.append("Recovery deployment precedes burnout. Continuing thrust is integrated, but opening shocks, motor exhaust/canopy interaction and line loads are not resolved.")
    positive_stability = all(row["stability"] is not None and row["stability"] > 0 for row in rows)
    if not positive_stability:
        warnings.append("Part of the trajectory has nonpositive or undefined static stability. Rigid-body restoring moments use the declared coefficients within their small-angle domain; this does not validate stable flight or post-limit tumbling.")
    for name, key in [("max_acceleration", "acceleration"), ("max_q", "dynamic_pressure"), ("max_velocity", "velocity"),
                      ("max_mach", "mach"), ("max_airspeed", "air_relative_speed"), ("max_specific_acceleration", "specific_acceleration")]:
        index = max(range(len(rows)), key=lambda i: rows[i][key])
        events.append({"name": name, "time": rows[index]["time"], "index": index})
    stress_indices = [i for i, row in enumerate(rows) if row["stress"] is not None]
    if stress_indices:
        index = max(stress_indices, key=lambda i: rows[i]["stress"])
        events.append({"name": "max_estimated_stress", "time": rows[index]["time"], "index": index})
    for event in events:
        event.setdefault("index", min(range(len(rows)), key=lambda i: abs(rows[i]["time"]-event["time"])))
    events.sort(key=lambda e: (e["time"], e["name"]))
    rail_event = next((event for event in events if event["name"] == "rail_exit"), None)
    rail_row = rows[rail_event["index"]] if rail_event else None
    summary = {"apogee_m": max(row["altitude"] for row in rows), "max_velocity_m_s": max(row["velocity"] for row in rows),
        "max_acceleration_m_s2": max(row["acceleration"] for row in rows), "max_mach": max(row["mach"] for row in rows),
        "max_dynamic_pressure_pa": max(row["dynamic_pressure"] for row in rows),
        "max_stress_pa": max((row["stress"] for row in rows if row["stress"] is not None), default=None),
        "flight_time_s": time, "burn_time_s": float(curve[-1, 0]), "total_impulse_ns": impulse, "integration_steps": steps,
        "initial_mass_kg": mass0["mass_kg"], "burnout_mass_kg": inertia_model.dry_mass,
        "rail_exit_velocity_m_s": rail_row["velocity"] if rail_row else None, "rail_exit_time_s": rail_row["time"] if rail_row else None,
        "landing_east_m": float(state[0]) if landed else None, "landing_north_m": float(state[1]) if landed else None,
        "landing_velocity_m_s": float(np.linalg.norm(state[3:6])) if landed else None, "recovery_deployed": chute != "none",
        "recovery_reached": landed, "complete": landed, "termination_reason": terminal_reason,
        "primary_deploy_event": cfg.primary_deploy_event, "max_angle_of_attack_deg": max(row["angle_of_attack_deg"] for row in rows)}
    if progress:
        progress(1, "Rigid-body flight complete" if landed else "Rigid-body partial result: "+str(terminal_reason))
    return {"trajectory": rows, "events": events, "summary": summary, "backend": "CPU",
        "fidelity": "Experimental adaptive 6DOF quaternion/Euler rigid body; small-angle reference coefficients; lumped recovery drag",
        "warnings": list(dict.fromkeys(warnings)), "wind": wind_field.metadata,
        "inertia": {"basis": inertia_model.basis, "override_reference": "complete dry rocket about dry CG", "components": inertia_model.provenance},
        "conventions": {"body_quaternion_world": "Hamilton [w,x,y,z] nose-body→worldENU; body [+nose,+geometryY,-geometryZ]",
            "body_axis_world": "Actual integrated nose axis in world[east,north,up]", "angular_velocity_body_rad_s": "Body rates about [+nose,+geometryY,-geometryZ]",
            "altitude": "AGL; altitude_msl is geometric MSL", "wind_direction": "toward; 0 north,90 east",
            "canopy_load_n": "Lumped q*effectiveCdArea load under user-assumed inflation; not opening-shock/line-load CFD",
            "force_vectors_n": "WorldENU Newtons; aerodynamic_normal is actually applied reference normal force",
            "high_angle_policy": "Stop un-recovered free flight above10° if q*A*CNa*10deg exceeds .01*m*g; below that threshold omitted normal/moment loads are unvalidated"},
        "numerical_integration": {"method": "adaptive_rk4_step_doubling_6dof", "relative_tolerance": 1e-7,
            "quaternion_absolute_tolerance": 1e-8, "angular_velocity_absolute_tolerance_rad_s": 1e-7,
            "accepted_steps": steps, "rejected_steps": rejected, "maximum_accepted_error_norm": max_error,
            "maximum_quaternion_norm_error": max_quaternion_error, "minimum_accepted_step_s": min_step,
            "maximum_accepted_step_s": max_step, "event_root_iterations": 28},
        "validity": {"six_dof": True, "within_operating_range": not exceeded_mach and terminal_reason not in {"aerodynamic_angle_limit", "undefined_aerodynamic_cp"},
            "positive_static_margin_throughout": positive_stability,
            "small_angle_aerodynamic_domain": not omitted_normal, "cad_resolved_aerodynamics": False,
            "geometry_matched_polar_used": used_polar, "polar_covers_full_flight": used_polar and not polar_gap,
            "recovery_opening_shock": False, "resolved_recovery_attitude": False}}
