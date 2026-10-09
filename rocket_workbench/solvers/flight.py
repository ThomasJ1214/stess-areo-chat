"""Passive three-dimensional point-mass flight with explicit recovery events.

Not a six-degree-of-freedom attitude solver. The propulsion axis follows the
launch rail while constrained, then the inertial velocity (a gravity-turn model).
Ambient wind changes relative aerodynamic velocity; weathercocking and angular
motion are not resolved. All returned stress is labelled quasi-static estimation.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

from rocket_workbench.models import Conditions, Project, configuration
from rocket_workbench.solvers import aero


# Local integration tolerances are expressed in SI and applied independently to
# position and velocity. They control numerical truncation error, not uncertainty
# in aerodynamic coefficients, motor data, recovery parameters or attitude.
_RELATIVE_TOLERANCE = 1e-7
_POSITION_ABSOLUTE_TOLERANCE_M = 1e-5
_VELOCITY_ABSOLUTE_TOLERANCE_M_S = 1e-5


def _validated_motor(project: Project, configuration_id: str | None) -> tuple:
    cfg = configuration(project, configuration_id)
    if not cfg.recovery_defined:
        raise ValueError("Recovery is not defined for this configuration. Enter and confirm supported parachute Cd×area and deployment settings before running a flight; recovery must not be inferred from default values.")
    unsupported = aero._configuration_features(project, configuration_id)
    forbidden = unsupported & {"multistage", "cluster", "parallelstage", "podset", "active_guidance", "motor_ignition_event", "deployment_event"}
    if forbidden:
        raise ValueError("Point-mass flight does not support this configuration: " + ", ".join(sorted(forbidden)) + ".")
    motor = next((m for m in project.motors if m.id == cfg.motor_id), None)
    if motor is None:
        raise ValueError("Select/import a motor with a real thrust curve for this flight configuration. ORK motor designations alone are insufficient.")
    curve = np.asarray(motor.curve, dtype=float)
    if curve.ndim != 2 or curve.shape[1] != 2 or len(curve) < 2 or not np.all(np.isfinite(curve)):
        raise ValueError("A flight motor needs at least two finite (time, thrust) curve points.")
    if np.any(curve[:, 0] < 0) or np.any(curve[:, 1] < 0) or np.any(np.diff(curve[:, 0]) <= 0):
        raise ValueError("Motor times must strictly increase from zero or later, and thrust must be nonnegative.")
    impulse_segments = (curve[:-1, 1] + curve[1:, 1]) / 2 * np.diff(curve[:, 0])
    cumulative = np.r_[0.0, np.cumsum(impulse_segments)]
    impulse = float(cumulative[-1])
    if impulse <= 0:
        raise ValueError("Motor thrust curve must have positive integrated impulse.")
    return cfg, motor, curve, cumulative, impulse


def simulate(
    project: Project,
    conditions: Conditions,
    configuration_id: str | None = None,
    progress: Callable[[float, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    if cancelled and cancelled():
        raise RuntimeError("Simulation cancelled.")
    if progress:
        progress(0.0, "Preparing reference geometry, motor and mass properties on CPU")
    cfg, motor, curve, cumulative, impulse = _validated_motor(project, configuration_id)
    prepared = aero._prepare(project, configuration_id)
    if prepared["cna_per_rad"] <= 0 and prepared.get("polar") is None:
        raise ValueError("Flight needs a supported original nose/fin reference with positive normal-force slope, or a geometry-matched supplied aerodynamic polar. CAD/tube-only mass/drag diagnostics do not establish passive flight stability.")
    mass0 = aero.mass_properties(project, configuration_id)
    motor_state0 = mass0["motor"]
    motor_center = motor_state0["cg_m"]
    dry_mass = mass0["mass_kg"] - motor_state0["mass_kg"] + motor.dry_mass
    dry_moment = mass0["mass_kg"] * mass0["cg_m"] - motor_state0["mass_kg"] * motor_center + motor.dry_mass * motor_center
    if dry_mass <= 0:
        raise ValueError("The burnout rocket mass must be positive.")
    burnout_time = cfg.ignition_delay + float(curve[-1, 0])
    if cfg.primary_deploy_event == "motor_ejection" and cfg.motor_ejection_delay is None:
        raise ValueError("Motor-ejection deployment needs the configured motor's actual ejection delay. Select an apogee trigger or enter the measured/nominal ejection delay; a plugged/unknown delay cannot be simulated.")
    warnings = prepared["warnings"] + mass0["warnings"] + [
        "Point-mass gravity-turn flight: no attitude dynamics, weathercocking, spin, angle-of-attack history or fin flutter. Stability margin is an original-reference indicator, not a prediction of dynamic stability.",
        "Recovery uses instantaneous constant Cd×area deployment; opening shock, line stretch, canopy inflation, pendulum motion and component separation are not modeled.",
        "Propellant consumption is proportional to integrated thrust (constant effective specific impulse); motor CG is held at its geometric/measured center.",
        "Post-rail aerodynamic drag uses zero-incidence reference coefficients; normal forces are not applied by this point-mass model.",
    ]
    if conditions.turbulence:
        warnings.append("Turbulence is a reproducible smooth sinusoidal gust model, not a calibrated Dryden/von Karman atmosphere or a resolved turbulent flow.")
    if prepared["cp_m"] is not None and (prepared["cp_m"] - mass0["cg_m"]) / prepared["diameter_m"] <= 0:
        warnings.append("Initial static stability is nonpositive. This point-mass model cannot predict tumbling and its trajectory should not be used as a stable-flight prediction.")
    # Import only here: structure itself depends on aero, and absence of supported
    # stress estimates must remain visible rather than becoming a fabricated zero.
    stress_model = None
    try:
        from rocket_workbench.solvers.structure import flight_stress_model, evaluate_flight_stress
        stress_model = flight_stress_model(project, configuration_id, conditions)
        warnings.extend(stress_model.get("warnings", []))
    except (ImportError, ValueError, RuntimeError) as exc:
        warnings.append(f"Flight stress estimates unavailable: {exc}")

    tilt, azimuth = math.radians(conditions.launch_angle), math.radians(conditions.launch_azimuth)
    rail_direction = np.array([math.sin(tilt) * math.sin(azimuth), math.sin(tilt) * math.cos(azimuth), math.cos(tilt)])
    wind_angle = math.radians(conditions.wind_direction)
    mean_wind = np.array([conditions.wind_speed * math.sin(wind_angle), conditions.wind_speed * math.cos(wind_angle), 0.0])
    rng = np.random.default_rng(conditions.seed)
    gust_phase = rng.uniform(0, 2 * math.pi, (3, 3))
    gust_frequency = np.array([0.23, 0.71, 1.9])
    gust_amplitude = max(1.0, conditions.wind_speed) * conditions.turbulence / math.sqrt(3)
    def wind(time):
        return mean_wind + gust_amplitude * np.sin(2 * math.pi * gust_frequency[None, :] * time + gust_phase).sum(axis=1)

    def motor_at(time):
        local_time = time - cfg.ignition_delay
        thrust = float(np.interp(local_time, curve[:, 0], curve[:, 1], left=0, right=0)) if local_time < curve[-1, 0] else 0.0
        if local_time <= curve[0, 0]:
            fraction = 0.0
        elif local_time >= curve[-1, 0]:
            fraction = 1.0
        else:
            i = int(np.searchsorted(curve[:, 0], local_time, side="right") - 1)
            elapsed = local_time - curve[i, 0]
            slope = (curve[i + 1, 1] - curve[i, 1]) / (curve[i + 1, 0] - curve[i, 0])
            consumed_impulse = cumulative[i] + curve[i, 1] * elapsed + 0.5 * slope * elapsed * elapsed
            fraction = float(np.clip(consumed_impulse / impulse, 0, 1))
        remaining = motor.propellant_mass * (1 - fraction)
        mass = dry_mass + remaining
        return thrust, mass, (dry_moment + remaining * motor_center) / mass

    on_rail = True
    chute = "none"
    apogee_time = None
    deploy_time = burnout_time + cfg.motor_ejection_delay + cfg.apogee_delay if cfg.primary_deploy_event == "motor_ejection" else None
    landed = False
    events: list[dict] = []
    trajectory: list[dict] = []
    state = np.zeros(6, dtype=float)
    time = 0.0
    steps = 0
    last_progress_time = -1.0
    exceeded_mach = False
    polar_outside_coverage = False
    any_polar_used = False
    nonpositive_stability = False
    undefined_stability = False
    rejected_steps = 0
    next_step = conditions.dt
    minimum_accepted_step = None
    maximum_accepted_step = None
    maximum_accepted_error_norm = 0.0
    last_body_axis = rail_direction.copy()
    # Events are located inside accepted error-controlled steps, independently
    # of the trajectory's output sampling grid.
    def dynamics(at_time, at_state, details=False):
        altitude_msl = conditions.altitude + max(0.0, float(at_state[2]))
        atm = aero.atmosphere(altitude_msl, conditions.temperature_delta)
        thrust, mass, cg = motor_at(at_time)
        relative = at_state[3:] - wind(at_time)
        speed = float(np.linalg.norm(relative))
        aerodynamic = aero._evaluate(prepared, atm, speed)
        canopy_area = cfg.main_cd_area if chute == "main" else cfg.drogue_cd_area if chute == "drogue" else 0.0
        drag = aerodynamic["drag_n"] + aerodynamic["dynamic_pressure_pa"] * canopy_area
        force_drag = -relative / speed * drag if speed > 1e-10 else np.zeros(3)
        velocity_norm = float(np.linalg.norm(at_state[3:]))
        direction = rail_direction if on_rail or velocity_norm < 1e-10 else at_state[3:] / velocity_norm
        gravity = np.array([0.0, 0.0, -atm["gravity_m_s2"]])
        acceleration = gravity + (force_drag + thrust * direction) / mass
        velocity = at_state[3:].copy()
        if on_rail:
            rail_velocity = float(np.dot(velocity, rail_direction))
            rail_acceleration = float(np.dot(acceleration, rail_direction))
            if float(np.dot(at_state[:3], rail_direction)) <= 1e-10 and rail_velocity <= 0 and rail_acceleration < 0:
                rail_acceleration, rail_velocity = 0.0, 0.0
            velocity = rail_direction * rail_velocity
            acceleration = rail_direction * rail_acceleration
        derivative = np.r_[velocity, acceleration]
        if details:
            return derivative, aerodynamic, thrust, mass, cg, drag, gravity, relative
        return derivative

    def pad_balance(at_time):
        """Unclamped axial force at a stationary pad for exact liftoff timing."""
        atm = aero.atmosphere(conditions.altitude, conditions.temperature_delta)
        thrust, mass, _ = motor_at(at_time)
        relative = -wind(at_time)
        speed = float(np.linalg.norm(relative))
        drag = aero._evaluate(prepared, atm, speed)["drag_n"]
        drag_axial = float(np.dot(-relative / speed * drag, rail_direction)) if speed > 1e-10 else 0.0
        return thrust + drag_axial - mass * atm["gravity_m_s2"] * rail_direction[2]

    def integrate(at_time, at_state, dt):
        k1 = dynamics(at_time, at_state)
        k2 = dynamics(at_time + dt / 2, at_state + dt * k1 / 2)
        k3 = dynamics(at_time + dt / 2, at_state + dt * k2 / 2)
        end_time = at_time + dt
        # When a curve ends at a nonzero last measured thrust, the preceding
        # interval uses the left-hand limit and the next interval uses zero.
        # The same convention handles an ignition thrust step without adding a
        # spurious dt/6 impulse at the discontinuity.
        curve_boundaries = (cfg.ignition_delay + float(curve[0, 0]), burnout_time)
        if any(abs(end_time - boundary) < 1e-10 and at_time < boundary - 1e-10 for boundary in curve_boundaries):
            end_time = math.nextafter(end_time, -math.inf)
        k4 = dynamics(end_time, at_state + dt * k3)
        return at_state + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)

    def refined_step(at_time, at_state, dt):
        """Two RK4 half steps, also used by event roots for consistent states."""
        midpoint = integrate(at_time, at_state, dt / 2)
        return integrate(at_time + dt / 2, midpoint, dt / 2)

    def controlled_step(at_time, at_state, requested_dt):
        """Accept RK4 step doubling only after a measured local-error check.

        The difference divided by 2**4-1 estimates the error in the two-half-step
        solution. No extrapolated state is substituted; the accepted state is
        the actually integrated refined solution. Boundaries and drag stability
        have already capped requested_dt.
        """
        nonlocal rejected_steps, next_step, maximum_accepted_error_norm
        dt = requested_dt
        absolute = np.array([_POSITION_ABSOLUTE_TOLERANCE_M] * 3 +
                            [_VELOCITY_ABSOLUTE_TOLERANCE_M_S] * 3)
        while True:
            if cancelled and cancelled():
                raise RuntimeError("Simulation cancelled.")
            if at_time + dt <= at_time:
                raise ValueError("Flight accuracy control requires a time step below floating-point resolution. Check the motor, aerodynamic and recovery data; no valid trajectory can be returned.")
            coarse = integrate(at_time, at_state, dt)
            refined = refined_step(at_time, at_state, dt)
            if np.all(np.isfinite(coarse)) and np.all(np.isfinite(refined)):
                scale = absolute + _RELATIVE_TOLERANCE * np.maximum(np.abs(at_state), np.abs(refined))
                error_norm = float(np.max(np.abs(refined - coarse) / (15 * scale)))
            else:
                error_norm = math.inf
            factor = min(2.0, max(0.1, 0.9 * error_norm ** -0.2)) if error_norm > 0 else 2.0
            if error_norm <= 1.0:
                maximum_accepted_error_norm = max(maximum_accepted_error_norm, error_norm)
                next_step = min(conditions.dt, dt * factor)
                return dt, refined
            rejected_steps += 1
            dt *= min(0.5, factor)

    def event_root(at_time, at_state, dt, measure, threshold):
        low, high = 0.0, dt
        start = measure(at_state) - threshold
        for _ in range(28):
            middle = (low + high) / 2
            candidate = refined_step(at_time, at_state, middle)
            if (measure(candidate) - threshold) * start > 0:
                low = middle
            else:
                high = middle
        duration = (low + high) / 2
        return duration, refined_step(at_time, at_state, duration)

    def phase(at_time):
        if landed:
            return "landed"
        if chute != "none":
            return chute
        if on_rail:
            return "pad" if np.linalg.norm(state[:3]) < 1e-9 else "rail"
        return "powered" if at_time < burnout_time and at_time >= cfg.ignition_delay else "coast"

    def append_row():
        nonlocal exceeded_mach, polar_outside_coverage, any_polar_used, nonpositive_stability, undefined_stability, last_body_axis
        derivative, aerodynamic, thrust, mass, cg, drag, gravity, relative = dynamics(time, state, True)
        altitude_msl = conditions.altitude + max(0.0, float(state[2]))
        local_atmosphere = aero.atmosphere(altitude_msl, conditions.temperature_delta)
        ground_speed = float(np.linalg.norm(state[3:]))
        thrust_axis = rail_direction if on_rail or ground_speed < 1e-10 else state[3:] / ground_speed
        if on_rail:
            last_body_axis = rail_direction.copy()
        elif ground_speed > 1e-6:
            last_body_axis = state[3:] / ground_speed
        air_speed = float(np.linalg.norm(relative))
        drag_direction = -relative / air_speed if air_speed > 1e-10 else np.zeros(3)
        body_drag_vector = drag_direction * aerodynamic["drag_n"]
        recovery_drag = drag - aerodynamic["drag_n"]
        recovery_drag_vector = drag_direction * recovery_drag
        thrust_vector = thrust_axis * thrust
        gravity_force = gravity * mass
        net_force = derivative[3:] * mass
        # Includes the pad support and transverse launch-rail reaction. The
        # reaction disappears after rail exit; no rail friction is assumed.
        rail_reaction = net_force - (body_drag_vector + recovery_drag_vector + thrust_vector + gravity_force) if on_rail else np.zeros(3)
        specific_acceleration = float(np.linalg.norm(derivative[3:] - gravity))
        stress = None
        structural_components = []
        if stress_model is not None and any(row.get("supported", True) for row in stress_model.get("components", [])):
            estimate = evaluate_flight_stress(stress_model, aerodynamic["dynamic_pressure_pa"], specific_acceleration)
            stress = estimate.get("max_stress_pa")
            structural_components = estimate.get("components", [])
        exceeded_mach |= aerodynamic["mach"] > 2 + 1e-9
        any_polar_used |= aerodynamic["polar_applied"]
        polar_outside_coverage |= prepared.get("polar") is not None and not aerodynamic["polar_applied"]
        static_margin = (aerodynamic["cp_m"] - cg) / prepared["diameter_m"] if aerodynamic["cp_m"] is not None else None
        nonpositive_stability |= static_margin is not None and static_margin <= 0
        undefined_stability |= static_margin is None
        row = {
            "time": time, "altitude": max(0.0, float(state[2])), "altitude_msl": altitude_msl,
            "east": float(state[0]), "north": float(state[1]), "velocity": float(np.linalg.norm(state[3:])),
            "vertical_velocity": float(state[5]), "velocity_vector": state[3:].tolist(),
            "air_relative_speed": air_speed, "air_relative_velocity_vector": relative.tolist(),
            "density_kg_m3": local_atmosphere["density_kg_m3"], "pressure_pa": local_atmosphere["pressure_pa"],
            "temperature_k": local_atmosphere["temperature_k"], "sound_speed_m_s": local_atmosphere["speed_of_sound_m_s"],
            "body_axis_world": last_body_axis.tolist(), "thrust_axis_world": thrust_axis.tolist(),
            "acceleration": float(np.linalg.norm(derivative[3:])),
            "acceleration_vector": derivative[3:].tolist(), "specific_acceleration": specific_acceleration,
            "specific_acceleration_vector": (derivative[3:] - gravity).tolist(),
            "force_vectors_n": {"body_aerodynamic_drag": body_drag_vector.tolist(),
                                "recovery_drag": recovery_drag_vector.tolist(), "thrust": thrust_vector.tolist(),
                                "gravity": gravity_force.tolist(), "rail_reaction": rail_reaction.tolist(),
                                "net": net_force.tolist()},
            "load_breakdown": {"body_drag_n": aerodynamic["drag_n"], "recovery_drag_n": recovery_drag,
                               "total_drag_n": drag, "thrust_n": thrust, "gravity_n": float(np.linalg.norm(gravity_force)),
                               "rail_reaction_n": float(np.linalg.norm(rail_reaction)), "net_force_n": float(np.linalg.norm(net_force))},
            "mach": aerodynamic["mach"], "dynamic_pressure": aerodynamic["dynamic_pressure_pa"],
            "mass": mass, "cg": cg, "cp": aerodynamic["cp_m"], "stability": static_margin,
            "drag": drag, "thrust": thrust, "stress": stress, "structural_components": structural_components,
            "stress_fidelity": "Quasi-static beam/fin and axial inertia estimate" if stress is not None else "unavailable",
            "phase": phase(time), "wind_vector": wind(time).tolist(), "polar_applied": aerodynamic["polar_applied"],
            "aerodynamic_basis": "user supplied geometry-matched polar" if aerodynamic["polar_applied"] else "original reference estimate",
        }
        if trajectory and abs(trajectory[-1]["time"] - time) < 1e-9:
            trajectory[-1] = row
        else:
            trajectory.append(row)

    def record_event(name):
        if not any(e["name"] == name for e in events):
            events.append({"name": name, "time": time})

    if progress:
        progress(0.0, "Integrating point-mass flight and quasi-static loads on CPU")
    if cfg.ignition_delay == 0:
        record_event("ignition")
    if pad_balance(0.0) > 0:
        record_event("liftoff")
    append_row()
    while time < conditions.max_time - 1e-10 and not landed:
        if cancelled and cancelled():
            raise RuntimeError("Simulation cancelled.")
        dt = min(conditions.dt, next_step, conditions.max_time - time)
        pending_times = [t for t in (cfg.ignition_delay, burnout_time, deploy_time) if t is not None and t > time + 1e-9]
        knot_index = int(np.searchsorted(curve[:, 0], time - cfg.ignition_delay + 1e-9, side="right"))
        if knot_index < len(curve):
            pending_times.append(cfg.ignition_delay + float(curve[knot_index, 0]))
        if pending_times:
            dt = min(dt, min(pending_times) - time)
        liftoff_crossing_time = None
        if on_rail and np.linalg.norm(state[:3]) < 1e-9 and np.linalg.norm(state[3:]) < 1e-9:
            if pad_balance(time) >= -1e-10 and pad_balance(time + dt) > 0:
                record_event("liftoff")
            if pad_balance(time) < -1e-10 and pad_balance(time + dt) > 0:
                low, high = 0.0, dt
                for _ in range(32):
                    middle = (low + high) / 2
                    if pad_balance(time + middle) <= 0:
                        low = middle
                    else:
                        high = middle
                dt = high
                liftoff_crossing_time = time + dt
        # Quadratic drag can be stiff for large canopies, high supplied Cd, or
        # light rockets. Account for both body and canopy drag, rather than only
        # stabilizing descent. The user's dt remains an upper bound.
        atm_now = aero.atmosphere(conditions.altitude + max(0.0, float(state[2])), conditions.temperature_delta)
        mass_now = motor_at(time)[1]
        speed_now = float(np.linalg.norm(state[3:] - wind(time)))
        body_area = prepared["reference_area_m2"] * aero._evaluate(prepared, atm_now, max(1.0, speed_now))["cd"]
        canopy_area = cfg.main_cd_area if chute == "main" else cfg.drogue_cd_area if chute == "drogue" else 0.0
        drag_derivative = atm_now["density_kg_m3"] * (body_area + canopy_area) * max(1.0, speed_now)
        if drag_derivative > 0:
            dt = min(dt, 0.5 * mass_now / drag_derivative)
        dt, candidate = controlled_step(time, state, dt)
        event_name = None
        if on_rail and float(np.dot(candidate[:3], rail_direction)) >= conditions.rail_length:
            dt, candidate = event_root(time, state, dt, lambda s: float(np.dot(s[:3], rail_direction)), conditions.rail_length)
            event_name = "rail_exit"
        elif not on_rail and apogee_time is None and state[5] > 0 and candidate[5] <= 0:
            dt, candidate = event_root(time, state, dt, lambda s: float(s[5]), 0.0)
            event_name = "apogee"
        elif chute == "drogue" and cfg.main_deploy_altitude > 0 and state[5] < 0 and state[2] > cfg.main_deploy_altitude and candidate[2] <= cfg.main_deploy_altitude:
            dt, candidate = event_root(time, state, dt, lambda s: float(s[2]), cfg.main_deploy_altitude)
            event_name = "main_deployment"
        elif not on_rail and state[2] > 0 and candidate[2] <= 0 and candidate[5] < 0:
            dt, candidate = event_root(time, state, dt, lambda s: float(s[2]), 0.0)
            candidate[2] = 0.0
            event_name = "recovery"
        state, time = candidate, time + dt
        minimum_accepted_step = dt if minimum_accepted_step is None else min(minimum_accepted_step, dt)
        maximum_accepted_step = dt if maximum_accepted_step is None else max(maximum_accepted_step, dt)
        if liftoff_crossing_time is not None and abs(time - liftoff_crossing_time) < 1e-8:
            record_event("liftoff")
        if on_rail and np.dot(state[:3], rail_direction) < 0:
            state = np.zeros(6)
        if event_name == "rail_exit":
            on_rail = False
            record_event(event_name)
        elif event_name == "apogee":
            apogee_time = time
            if cfg.primary_deploy_event == "apogee":
                deploy_time = time + cfg.apogee_delay
            record_event(event_name)
            if chute == "drogue" and state[2] <= cfg.main_deploy_altitude:
                chute = "main"
                record_event("main_deployment")
        elif event_name == "main_deployment":
            chute = "main"
            record_event(event_name)
        elif event_name == "recovery":
            landed = True
            record_event(event_name)
            if chute == "drogue" and cfg.main_deploy_altitude == 0:
                warnings.append("Main deployment altitude is zero: ground contact occurs before main canopy descent.")
        if abs(time - cfg.ignition_delay) < 1e-8:
            record_event("ignition")
        if abs(time - burnout_time) < 1e-8:
            record_event("burnout")
        if deploy_time is not None and abs(time - deploy_time) < 1e-8:
            chute = "main" if cfg.deployment == "single" else "drogue"
            if cfg.primary_deploy_event == "motor_ejection":
                record_event("motor_ejection")
            record_event("main_deployment" if chute == "main" else "drogue_deployment")
            if chute == "drogue" and state[2] <= cfg.main_deploy_altitude and state[5] <= 1e-7:
                chute = "main"
                record_event("main_deployment")
            deploy_time = None
            if time < burnout_time:
                warnings.append("Recovery deployed before motor burnout; propulsion/recovery interactions are not modeled.")
        if on_rail and time > burnout_time + 0.1:
            if np.dot(state[:3], rail_direction) <= 0.0:
                raise ValueError("The motor cannot lift this rocket off the rail at the selected conditions.")
            if np.dot(state[3:], rail_direction) <= 0.0:
                raise ValueError("The rocket stops or falls back before rail exit; select adequate thrust and rail conditions.")
        append_row()
        steps += 1
        if progress and time - last_progress_time >= 0.5:
            progress(min(0.99, time / conditions.max_time), f"{phase(time).replace('_', ' ').capitalize()} at {time:.1f} s; {state[2]:.0f} m AGL")
            last_progress_time = time
    if not landed:
        warnings.append("Maximum simulation time reached before ground recovery; trajectory is incomplete. Increase max_time to complete the flight.")
    elif chute == "none":
        warnings.append("Ground contact occurred before recovery deployment: this is an undeployed ground impact, not a successful parachute recovery. Inspect the ejection/deployment delay and landing speed.")
    if exceeded_mach:
        warnings.append("Trajectory exceeds Mach 2; aerodynamic coefficients outside the supported range are extrapolated estimates and those results are out of scope.")
    if polar_outside_coverage:
        warnings.append("Part of the flight lies outside supplied aerodynamic polar Mach coverage; those rows use the original reference-geometry estimates and are labelled polar_applied=false.")
    if nonpositive_stability:
        warnings.append("Part of the trajectory has a nonpositive static stability margin. This point-mass solver cannot predict tumbling, so its smooth trajectory does not establish stable physical flight.")
    if undefined_stability:
        warnings.append("Part of the trajectory has no positive normal-force slope, so CP and static stability are undefined for those rows. The point-mass trajectory does not establish stable physical flight.")
    for name, key in [("max_acceleration", "acceleration"), ("max_q", "dynamic_pressure"),
                      ("max_velocity", "velocity"), ("max_airspeed", "air_relative_speed"),
                      ("max_mach", "mach"), ("max_specific_acceleration", "specific_acceleration")]:
        index = max(range(len(trajectory)), key=lambda i: trajectory[i][key])
        events.append({"name": name, "time": trajectory[index]["time"], "index": index})
    supported_stress_rows = [i for i, row in enumerate(trajectory) if row.get("stress") is not None]
    if supported_stress_rows:
        index = max(supported_stress_rows, key=lambda i: trajectory[i]["stress"])
        events.append({"name": "max_estimated_stress", "time": trajectory[index]["time"], "index": index})
    for event in events:
        if "index" not in event:
            event["index"] = min(range(len(trajectory)), key=lambda i: abs(trajectory[i]["time"] - event["time"]))
    events.sort(key=lambda e: (e["time"], e["name"]))
    rail_event = next((e for e in events if e["name"] == "rail_exit"), None)
    rail_row = trajectory[rail_event["index"]] if rail_event else None
    stresses = [r["stress"] for r in trajectory if r["stress"] is not None]
    summary = {
        "apogee_m": max(r["altitude"] for r in trajectory), "max_velocity_m_s": max(r["velocity"] for r in trajectory),
        "max_acceleration_m_s2": max(r["acceleration"] for r in trajectory), "max_mach": max(r["mach"] for r in trajectory),
        "max_dynamic_pressure_pa": max(r["dynamic_pressure"] for r in trajectory), "max_stress_pa": max(stresses) if stresses else None,
        "flight_time_s": time, "burn_time_s": float(curve[-1, 0]), "total_impulse_ns": impulse,
        "rail_exit_velocity_m_s": rail_row["velocity"] if rail_row else None, "rail_exit_time_s": rail_row["time"] if rail_row else None,
        "landing_east_m": float(state[0]) if landed else None, "landing_north_m": float(state[1]) if landed else None,
        "landing_velocity_m_s": float(np.linalg.norm(state[3:])) if landed else None,
        "recovery_deployed": chute != "none",
        "recovery_reached": landed, "complete": landed, "integration_steps": steps,
        "initial_mass_kg": mass0["mass_kg"], "burnout_mass_kg": dry_mass,
        "primary_deploy_event": cfg.primary_deploy_event,
    }
    if progress:
        progress(1.0, "Flight simulation complete" if landed else "Flight integration complete; maximum time reached")
    return {"trajectory": trajectory, "events": events, "summary": summary,
            "fidelity": "Adaptive RK4 passive 3D point-mass gravity-turn flight; " + ("user-supplied geometry-matched polar where covered; " if any_polar_used else "original-reference drag; ") + "optional quasi-static beam/fin stress estimates",
            "warnings": list(dict.fromkeys(warnings)), "backend": "CPU",
            "conventions": {"altitude": "AGL; altitude_msl is geometric MSL", "wind_direction": "toward; 0 north, 90 east",
                            "acceleration": "inertial magnitude; specific_acceleration excludes gravity", "stress": "quasi-static estimate in Pa; null when unavailable",
                            "air_relative_velocity_vector": "world [east,north,up], vehicle velocity minus the actual ambient wind",
                            "body_axis_world": "assumed nose-directed axis: rail direction while constrained, then ground-velocity direction; last valid axis retained at zero speed. Attitude is not integrated, including during recovery",
                            "thrust_axis_world": "axis actually used by the point-mass thrust law; not a resolved attitude",
                            "force_vectors_n": "world [east,north,up], newtons. Body and recovery drag are separate; rail_reaction includes ideal frictionless rail/pad constraints",
                            "peak_events": "max Q, max acceleration and max velocity are maxima of accepted trajectory samples; recovery force steps are not resolved opening shocks"},
            "numerical_integration": {
                "method": "adaptive_rk4_step_doubling", "order": 4,
                "relative_tolerance": _RELATIVE_TOLERANCE,
                "position_absolute_tolerance_m": _POSITION_ABSOLUTE_TOLERANCE_M,
                "velocity_absolute_tolerance_m_s": _VELOCITY_ABSOLUTE_TOLERANCE_M_S,
                "maximum_step_s": conditions.dt,
                "minimum_accepted_step_s": minimum_accepted_step,
                "maximum_accepted_step_s": maximum_accepted_step,
                "accepted_steps": steps, "rejected_steps": rejected_steps,
                "maximum_accepted_error_norm": maximum_accepted_error_norm,
                "event_root_iterations": 28,
                "liftoff_root_iterations": 32,
                "maximum_event_time_bracket_s": conditions.dt / 2**28,
                "error_scope": "measured local numerical error estimate; not a global trajectory error bound or physical validation",
            },
            "validity": {"max_mach": 2, "within_operating_range": not exceeded_mach,
                         "six_dof": False, "cad_resolved_aerodynamics": False,
                         "geometry_matched_polar_used": any_polar_used,
                         "positive_static_margin_throughout": not nonpositive_stability and not undefined_stability,
                         "polar_covers_full_flight": any_polar_used and not polar_outside_coverage, "recovery_opening_shock": False}}
