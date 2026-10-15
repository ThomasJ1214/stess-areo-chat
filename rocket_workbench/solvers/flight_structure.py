"""Transient original-fin beam FEM driven by recorded flight loads.

This is an actual Euler--Bernoulli finite-element dynamics calculation, with
consistent mass and exact first-order-hold or legacy Newmark propagation in a
complete modal basis.
Its load history remains an original-reference aerodynamic engineering estimate;
it is neither 3D transient solid FEA, CFD coupling, laminate analysis nor flutter.
Source component geometry, materials and the input trajectory are never modified.
"""
from __future__ import annotations

import math
import time

import numpy as np
from scipy.linalg import eigh, expm
from scipy.spatial.transform import Rotation

from ..models import Project, active_components

FIDELITY = ("Dynamic Euler–Bernoulli fin beam finite-element analysis; consistent mass, "
            "full modal coordinates; original-reference aerodynamic load estimates")
_FINS = {"finset", "trapezoidfinset", "freeformfinset", "ellipticalfinset", "fin"}
_SUPPORTED_FINS = {"finset", "trapezoidfinset", "fin"}


def _number(options, key, default, low, high, integer=False):
    value = options.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number.")
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be a number.") from error
    if not math.isfinite(value) or not low <= value <= high or (integer and value != int(value)):
        raise ValueError(f"{key} must be {'an integer' if integer else 'a number'} between {low} and {high}.")
    return int(value) if integer else value


def _hermite(r, length):
    shape = np.array([1 - 3*r*r + 2*r**3, length*(r - 2*r*r + r**3),
                      3*r*r - 2*r**3, length*(-r*r + r**3)])
    curvature = np.array([(-6 + 12*r)/length**2, (-4 + 6*r)/length,
                          (6 - 12*r)/length**2, (-2 + 6*r)/length])
    return shape, curvature


def beam_matrices(span, root_chord, tip_chord, thickness, youngs_modulus, density, elements=12):
    """Assemble variable-chord Hermite beam K, consistent M and unit span load.

    DOFs are [normal displacement, span derivative] at each node. Four-point
    Gaussian integration exactly integrates the polynomial tapered-section
    stiffness, mass and chord-proportional load terms. Root DOFs 0 and 1 clamp
    the actual fin attachment; the rocket body is never clamped by this model.
    """
    dimensions = (span, root_chord, thickness, youngs_modulus, density)
    if (not all(math.isfinite(x) and x > 0 for x in dimensions)
            or not math.isfinite(tip_chord) or tip_chord < 0
            or isinstance(elements, bool) or int(elements) != elements or not 1 <= elements <= 128):
        raise ValueError("Beam dimensions, density and modulus must be positive; tip chord nonnegative; elements 1–128.")
    elements = int(elements)
    nodes = np.linspace(0, span, elements + 1)
    ndof = 2 * len(nodes)
    stiffness, mass, unit_force = np.zeros((ndof, ndof)), np.zeros((ndof, ndof)), np.zeros(ndof)
    gauss, weights = np.polynomial.legendre.leggauss(4)
    length = span / elements
    planform_area = span * (root_chord + tip_chord) / 2
    for element in range(elements):
        dofs = np.arange(2*element, 2*element + 4)
        for point, weight in zip(gauss, weights):
            r = (point + 1) / 2
            station = nodes[element] + r * length
            chord = root_chord + (tip_chord - root_chord) * station / span
            shape, curvature = _hermite(r, length)
            jacobian_weight = weight * length / 2
            stiffness[np.ix_(dofs, dofs)] += youngs_modulus * chord * thickness**3 / 12 * np.outer(curvature, curvature) * jacobian_weight
            mass[np.ix_(dofs, dofs)] += density * chord * thickness * np.outer(shape, shape) * jacobian_weight
            unit_force[dofs] += shape * chord / planform_area * jacobian_weight
    return {"stiffness": stiffness, "mass": mass, "unit_force": unit_force, "span_m": nodes,
            "chord_m": root_chord + (tip_chord - root_chord) * nodes / span,
            "thickness_m": thickness, "youngs_modulus_pa": youngs_modulus,
            "density_kg_m3": density, "planform_area_m2": planform_area,
            "mass_kg": density * thickness * planform_area, "elements": elements}


def beam_eigenmodes(model):
    """Mass-orthonormal complete free-DOF basis; roots remain exactly fixed."""
    eigenvalues, free_modes = eigh(model["stiffness"][2:, 2:], model["mass"][2:, 2:], check_finite=True)
    if np.any(eigenvalues <= 0) or not np.isfinite(eigenvalues).all():
        raise ValueError("Fin beam has a nonpositive elastic eigenvalue; inspect dimensions/material properties.")
    modes = np.zeros((len(model["mass"]), len(eigenvalues)))
    modes[2:] = free_modes
    return np.sqrt(eigenvalues), modes


def newmark_step(displacement, velocity, acceleration, next_force, mass, damping, stiffness, dt):
    """Average acceleration, beta=1/4 and gamma=1/2, for diagonal coordinates.

    Each coordinate solves the actual dynamic equilibrium equation. All modal
    coordinates of the beam are retained; no animation or stress interpolation
    substitutes for the time integration.
    """
    predicted_displacement = displacement + dt*velocity + 0.25*dt*dt*acceleration
    predicted_velocity = velocity + 0.5*dt*acceleration
    new_acceleration = (next_force - damping*predicted_velocity - stiffness*predicted_displacement) / (mass + 0.5*dt*damping + 0.25*dt*dt*stiffness)
    return (predicted_displacement + 0.25*dt*dt*new_acceleration,
            predicted_velocity + 0.5*dt*new_acceleration, new_acceleration)


def exact_foh_step(displacement, velocity, force_start, force_end, omega, damping_ratio, dt):
    """Exact mass-normalized modal response to a linearly varying imposed force.

    All modes are propagated; no assumption that a flight sample resolves the
    modal period is made. This does not recover unrecorded load fluctuations or
    extrema between output samples. Small phase increments use a dimensionless
    augmented exponential to avoid cancellation in the ramp particular solution.
    """
    omega = np.asarray(omega, dtype=float)
    if dt <= 0 or not math.isfinite(dt) or not np.isfinite(omega).all() or np.any(omega <= 0) or not 0 <= damping_ratio < 1:
        raise ValueError("Exact modal propagation requires positive finite dt/frequencies and undercritical damping.")
    q, v, f0, f1 = np.broadcast_arrays(displacement, velocity, force_start, force_end)
    if q.ndim < 1 or q.shape[0] != len(omega) or not all(np.isfinite(value).all() for value in (q, v, f0, f1)):
        raise ValueError("Modal states/forces must be finite and match the frequency count.")
    w = omega.reshape((-1,) + (1,) * (q.ndim - 1))
    decay = np.exp(-damping_ratio*w*dt)
    wd = w*math.sqrt(1-damping_ratio**2)
    sine, cosine = np.sin(wd*dt), np.cos(wd*dt)
    ramp = (f1-f0)/dt
    slope = ramp/w**2
    intercept = (f0-2*damping_ratio*w*slope)/w**2
    a, b = q-intercept, v-slope
    next_q = decay*((cosine+damping_ratio*w*sine/wd)*a+sine/wd*b)+intercept+slope*dt
    next_v = decay*(-w**2*sine/wd*a+(cosine-damping_ratio*w*sine/wd)*b)+slope
    for i in np.flatnonzero(omega*dt < .05):
        # Dimensionless [q, v/w, f/w², f_dot/w³]. Matrix magnitudes stay O(1)
        # even for very high frequencies or a root-located very short interval.
        matrix = np.array([[0., 1., 0., 0.], [-1., -2*damping_ratio, 1., 0.],
                           [0., 0., 0., 1.], [0., 0., 0., 0.]])
        transfer = expm(matrix*(omega[i]*dt))
        initial = np.stack((q[i], v[i]/omega[i], f0[i]/omega[i]**2, ramp[i]/omega[i]**3))
        propagated = np.tensordot(transfer[:2], initial, axes=(1, 0))
        next_q[i], next_v[i] = propagated[0], propagated[1]*omega[i]
    next_a = f1-2*damping_ratio*w*next_v-w**2*next_q
    return next_q, next_v, next_a


def _span_stress(model, displacements):
    """Signed surface bending stress from actual FE curvature; average shared nodes."""
    result = np.zeros((len(model["span_m"]), displacements.shape[1]))
    counts = np.zeros(len(result))
    length = model["span_m"][1]
    for element in range(model["elements"]):
        local = displacements[2*element:2*element + 4]
        for end, r in ((element, 0), (element + 1, 1)):
            _, curvature = _hermite(r, length)
            result[end] += model["youngs_modulus_pa"] * model["thickness_m"] / 2 * (curvature @ local)
            counts[end] += 1
    return result / counts[:, None]


def _vector(value, label):
    array = np.array(value, dtype=float, copy=True)
    if array.shape != (3,) or not np.isfinite(array).all():
        raise ValueError(f"{label} must contain three finite world-coordinate values.")
    return array


def _frame(row):
    """Return original-geometry axes in world ENU, preferring resolved attitude.

    Hamilton quaternion is [w,x,y,z] and maps nose body (+X=-geometry X,
    +Y=geometry Y,+Z=-geometry Z) to world. Legacy point-mass rows use an
    explicitly assumed zero-roll reference and cannot establish actual attitude.
    """
    quaternion = row.get("body_quaternion_world")
    if quaternion is not None:
        q = np.asarray(quaternion, dtype=float)
        if q.shape != (4,) or not np.isfinite(q).all() or np.linalg.norm(q) < 1e-12:
            raise ValueError("body_quaternion_world must be a finite nonzero [w,x,y,z] quaternion.")
        basis = Rotation.from_quat(q[[1, 2, 3, 0]]).as_matrix() @ np.diag([-1., 1., -1.])
        return basis, True
    nose = _vector(row.get("body_axis_world"), "body_axis_world")
    length = np.linalg.norm(nose)
    if length < 1e-12:
        raise ValueError("body_axis_world cannot be zero.")
    nose /= length
    radial = np.array([1., 0., 0.])
    if abs(np.dot(radial, nose)) > 0.9:
        radial = np.array([0., 1., 0.])
    radial -= np.dot(radial, nose) * nose
    radial /= np.linalg.norm(radial)
    tail = -nose
    return np.column_stack((tail, radial, np.cross(tail, radial))), False


def _original_slope(component, reference_radius, mach):
    """Same documented original-reference fin slope used by the fast aero model."""
    diameter = 2 * reference_radius
    span, root, tip = component.span, component.root_chord, component.tip_chord
    mid = math.hypot(span, component.sweep + (tip - root) / 2)
    ratio = 2 * mid / (root + tip)
    interference = 1 + component.radius / (component.radius + span)
    reference = interference * 4 * component.fin_count * (span / diameter)**2 / (1 + math.sqrt(1 + ratio*ratio))
    subsonic = reference * (1 + math.sqrt(1 + ratio*ratio)) / (1 + math.sqrt(1 + (1 - min(mach, .9)**2)*ratio*ratio))
    area_ratio = span * (root + tip) / 2 / (math.pi * reference_radius**2)
    supersonic = 4 / math.sqrt(max(1.5, mach)**2 - 1) * area_ratio * component.fin_count / 2 * interference
    u = min(1., max(0., (mach - .9) / .6))
    blend = u*u*(3 - 2*u)
    return subsonic*(1 - blend) + supersonic*blend


def _fin_load(row, component, radius, maximum_incidence):
    if component.fin_count < 3:
        return None, "Directional load partition requires at least three equally spaced fins.", None, False
    phase = str(row.get("phase", "powered"))
    if phase in {"drogue", "main", "recovery", "landed"}:
        return None, "Recovery/landing fin loads are unavailable: canopy attachment and recovery attitude/opening shock are not modeled.", None, False
    basis, resolved = _frame(row)
    relative = _vector(row.get("air_relative_velocity_vector"), "air_relative_velocity_vector")
    speed = float(np.linalg.norm(relative))
    axial = float(np.dot(relative, -basis[:, 0]))
    lateral = relative - axial * (-basis[:, 0])
    incidence = math.degrees(math.atan2(float(np.linalg.norm(lateral)), axial)) if speed > 1e-12 else 0.
    if incidence > maximum_incidence + 1e-9:
        return None, f"Recorded incidence {incidence:.3g}° exceeds the {maximum_incidence:g}° original-fin aerodynamic load limit.", incidence, resolved
    q = float(row.get("dynamic_pressure", 0))
    mach = float(row.get("mach", 0))
    if not math.isfinite(q) or q < 0 or not math.isfinite(mach) or mach < 0:
        raise ValueError("Trajectory dynamic pressure/Mach must be finite and nonnegative.")
    if mach > 2 + 1e-9:
        return None, "Recorded Mach exceeds the original-reference Mach-2 load model range.", incidence, resolved
    record = next((item for item in row.get("aerodynamic_components", []) if item.get("component_id") == component.id), None)
    if record is not None:
        vector = record.get("normal_force_vector_n")
        if vector is None:
            return None, "Trajectory marks this component's normal force unavailable; no fin load is invented.", incidence, resolved
        resultant = _vector(vector, "Component normal_force_vector_n")
        fidelity = str(record.get("force_fidelity", "Recorded original-reference fin normal-force estimate"))
    else:
        # Fallback remains an explicit estimate from actual recorded incidence,
        # never from the launch-condition slider or a supplied total polar.
        slope = _original_slope(component, radius, mach)
        resultant = (-lateral / np.linalg.norm(lateral) * q * math.pi * radius**2 * slope * math.radians(incidence)) if np.linalg.norm(lateral) > 1e-12 else np.zeros(3)
        fidelity = "Original-reference fin CNa with actual recorded relative velocity/incidence; not a resolved flight normal force"
    rotation = math.radians(float(component.metadata.get("angleoffset", component.metadata.get("rotation", 0))))
    angles = rotation + np.arange(component.fin_count) * 2*math.pi/component.fin_count
    normals = np.column_stack((np.zeros(len(angles)), -np.sin(angles), np.cos(angles))) @ basis.T
    # Uniform radial finsets have sum(n*n.T)=N/2 in the transverse plane (N>=3).
    # This resolves different individual-fin forces instead of equal-load colors.
    per_fin = 2 / component.fin_count * (normals @ resultant)
    if not np.allclose(normals.T @ per_fin, resultant, rtol=1e-9, atol=1e-10):
        return None, "Recorded component force cannot be reconstructed by the fin-normal basis.", incidence, resolved
    return per_fin, fidelity, incidence, resolved


def _unavailable(component, reason):
    return {"component_id": component.id, "name": component.name, "supported": False,
            "stress_pa": None, "deflection_m": None, "safety_factor": None,
            "fidelity": "unavailable", "reason": reason, "fins": []}


def analyze_flight_structure(project: Project, trajectory, configuration_id=None,
                             options=None, progress=None, cancelled=None):
    """Analyze original fin dynamics over actual recorded trajectory timestamps.

    Unsupported fins remain unavailable independently. Missing/out-of-range load
    intervals are never bridged: analysis ends at the first such gap after its
    first valid load. Initial state is static equilibrium at that first valid
    input, with zero velocity; that declared assumption is not flight validation.
    Work exhaustion/cancellation returns aligned partial rows with explicit status.
    """
    options = dict(options or {})
    integrator = options.get("time_integrator", "exact_foh")
    if integrator not in {"exact_foh", "newmark"}:
        raise ValueError("Fin time_integrator must be exact_foh or newmark.")
    elements = _number(options, "elements", 12, 2, 64, True)
    damping_ratio = _number(options, "damping_ratio", .01, 0, .2)
    steps_per_period = _number(options, "steps_per_period", 30, 12, 100)
    max_substeps = _number(options, "max_substeps", 300000, 1, 2000000, True)
    maximum_incidence = _number(options, "maximum_incidence_deg", 10, 1, 10)
    surrogate = options.get("allow_isotropic_surrogate", False)
    if not isinstance(surrogate, bool):
        raise ValueError("allow_isotropic_surrogate must be a boolean acknowledgement.")
    rows = trajectory.get("trajectory", []) if isinstance(trajectory, dict) else trajectory
    if not isinstance(rows, list) or not rows:
        raise ValueError("Dynamic fin analysis requires a nonempty recorded trajectory.")
    times = np.asarray([row["time"] for row in rows], dtype=float)
    if not np.isfinite(times).all() or times[0] < 0 or np.any(np.diff(times) <= 0):
        raise ValueError("Trajectory times must be finite, nonnegative and strictly increasing.")
    start_time = _number(options, "start_time_s", float(times[0]), float(times[0]), float(times[-1]))
    end_time = _number(options, "end_time_s", float(times[-1]), start_time, float(times[-1]))
    parts = active_components(project, configuration_id)
    fins = [component for component in parts if component.kind in _FINS]
    if len(rows) * max(1, sum(component.fin_count for component in fins)) * (elements + 1) > 4000000:
        raise ValueError("Dynamic fin output exceeds four million span values. Reduce elements, trajectory samples or fin count.")
    outer = [component for component in parts if component.external and component.kind in {"bodytube", "nosecone", "transition", "boattail"}]
    reference_radius = max((max(component.radius, component.radius_end or 0) for component in outer), default=0.)
    warnings = ["Beam FEM resolves fin span bending only: no plate/torsion coupling, fillets, attachment compliance, flutter, thermal stress, yielding, buckling or composite failure criterion.",
                "Uniform modal damping is an explicit user assumption, not measured damping. All finite-element modes are retained; time-step targets resolve the fundamental mode, so higher-mode response and sampled load changes require time/mesh convergence.",
                "Loads are piecewise-linear original-reference aerodynamic estimates at recorded flight timestamps, not CFD pressure or recovery-opening shock. Initial state assumes static equilibrium at the first valid load with zero velocity.",
                "Recorded transverse specific acceleration supplies translational fin-root inertial loading (gravity excluded). Rotating-frame Euler, centrifugal, gyroscopic and geometric-stiffening terms are not solved."]
    if integrator == "exact_foh":
        warnings[1] = "Uniform modal damping is a user assumption. Every finite-element mode is propagated exactly for the prescribed piecewise-linear recorded loads; unrecorded high-frequency forcing and between-sample stress extrema remain unresolved."
    if any(component.external and component.asset_id and component.geometry_mode == "replacement" for component in parts):
        warnings.append("Other exterior CAD replacements are preserved; fin loads retain original-reference body/fin interference. Changed CAD interference is unresolved and these loads cannot establish CAD-resolved aerodynamics.")
    if any(row.get("polar_applied") for row in rows):
        warnings.append("A supplied whole-rocket polar does not provide a fin force partition: individual-fin loads remain explicitly original-reference estimates.")
    output = [{"time": float(stamp), "components": [], "max_stress_pa": None} for stamp in times]
    descriptors = []
    total_steps, status, max_stress, max_deflection = 0, "completed", None, None
    started = time.perf_counter()
    for part_index, component in enumerate(fins):
        material = next((item for item in project.materials if item.id == component.material_id), None)
        reason = None
        if not component.external:
            reason = "Internal fins do not receive an exterior aerodynamic load in this model."
        elif component.asset_id and component.geometry_mode == "replacement":
            reason = "CAD replacement fin geometry requires an explicit structural model; no bounding-box beam is substituted."
        elif component.kind not in _SUPPORTED_FINS:
            reason = "Freeform/elliptical fins require a verified span section model; no trapezoid geometry is substituted."
        elif component.fin_count < 3:
            reason = "Directional fin load partition requires at least three equally spaced fins; one/two-fin systems need an independently justified directional aerodynamic model."
        elif min(component.span, component.root_chord, component.thickness) <= 0:
            reason = "Fin span, root chord and measured thickness must be positive."
        elif component.span / component.thickness < 10:
            reason = "Fin span/thickness is below 10: shear and rotary inertia need a Timoshenko/plate model, outside this slender Euler–Bernoulli beam scope."
        elif abs(float(component.metadata.get("cant", 0))) > 1e-9:
            reason = "Canted-fin torsion and roll-coupled loading require a verified plate/attitude structural model."
        elif material is None:
            reason = "Select an explicit material for the fin; no fallback material is assigned."
        elif reference_radius <= 0:
            reason = "Original-fin aerodynamic loads require a positive body reference radius."
        elif component.mass_override == 0:
            reason = "A zero measured fin mass cannot define physical structural inertia."
        composite = material is not None and any(word in (material.name + " " + material.description).lower()
                                                for word in ("surrogate", "fiberglass", "carbon", "laminate", "composite", "glass fibre", "glass fiber"))
        if reason is None and composite and not surrogate:
            reason = "Composite/laminate properties are unavailable for this isotropic model. Explicitly acknowledge an isotropic surrogate or choose a verified homogeneous material."
        if reason:
            descriptors.append({"component_id": component.id, "name": component.name, "supported": False, "reason": reason})
            for output_row in output:
                output_row["components"].append(_unavailable(component, reason))
            continue
        density = material.density
        mass_assumption = "Material density times actual trapezoid thickness/planform"
        if component.mass_override is not None:
            density = component.mass_override / (component.fin_count * component.thickness * component.span * (component.root_chord + component.tip_chord) / 2)
            mass_assumption = "Measured finset mass shared uniformly among fins and over the actual trapezoid planform; material density is unchanged"
        model = beam_matrices(component.span, component.root_chord, component.tip_chord, component.thickness, material.youngs_modulus, density, elements)
        omega, modes = beam_eigenmodes(model)
        damping = 2 * damping_ratio * omega
        stiffness = omega**2
        unit_modal = modes.T @ model["unit_force"]
        mass_modes, stiffness_modes = model["mass"] @ modes, model["stiffness"] @ modes
        maximum_dt = 1 / (steps_per_period * omega[0] / (2*math.pi))
        descriptor = {"component_id": component.id, "name": component.name, "supported": True,
                      "fidelity": FIDELITY, "span_m": model["span_m"].tolist(), "chord_m": model["chord_m"].tolist(),
                      "root_radius_m": component.radius, "thickness_m": component.thickness,
                      "sweep_m": component.sweep, "component_x_m": component.x,
                      "elements": elements, "free_dofs": len(omega), "retained_modes": len(omega),
                      "natural_frequencies_hz": (omega / (2*math.pi)).tolist(),
                      "damping_ratio": damping_ratio, "damping_model": "Same assumed viscous damping ratio in every complete-basis mode",
                      "material_id": material.id, "material": material.name, "isotropic_surrogate_acknowledged": composite,
                      "youngs_modulus_pa": material.youngs_modulus, "density_kg_m3": density, "mass_per_fin_kg": model["mass_kg"],
                      "mass_assumption": mass_assumption, "root_constraint": "Physical fin attachment: zero normal displacement and span slope",
                      "load_distribution": "Recorded directional per-fin force distributed proportional to actual span chord",
                      "base_inertia": "Translational D'Alembert load from recorded specific_acceleration_vector; rotating-frame terms excluded",
                      "maximum_internal_step_s": maximum_dt, "steps_per_fundamental_period": steps_per_period,
                      "initial_condition": "Static equilibrium at first valid input; zero modal velocity",
                      "initial_time_s": None, "final_time_s": None, "substeps": 0}
        descriptor["time_integrator"] = integrator
        descriptor["maximum_internal_step_s"] = maximum_dt if integrator == "newmark" else None
        descriptors.append(descriptor)
        displacement = velocity = acceleration = None
        previous_load, previous_time, closed_reason = None, None, None
        for index, (row, stamp) in enumerate(zip(rows, times)):
            if cancelled and cancelled():
                status, closed_reason = "cancelled", "Dynamic fin analysis cancelled; this and later states are unavailable."
            if stamp < start_time or stamp > end_time:
                output[index]["components"].append(_unavailable(component, "Outside the requested structural analysis interval."))
                continue
            if closed_reason:
                output[index]["components"].append(_unavailable(component, closed_reason))
                continue
            load, load_fidelity, incidence, resolved = _fin_load(row, component, reference_radius, maximum_incidence)
            if load is None:
                output[index]["components"].append(_unavailable(component, load_fidelity))
                if displacement is not None:
                    closed_reason = "Dynamic state cannot be reconstructed after an unavailable aerodynamic/recovery load interval. " + load_fidelity
                continue
            if not resolved and not any("point-mass" in warning for warning in warnings):
                warnings.append("Legacy point-mass rows have no resolved roll/attitude: directional fin loads use the recorded nose axis with an assumed zero-roll reference; this does not establish real fin motion.")
            aerodynamic_load = load.copy()
            inertial_load = np.zeros_like(load)
            attitude_basis, _ = _frame(row)
            azimuth = float(component.metadata.get("angleoffset", component.metadata.get("rotation", 0)))
            inertia_recorded = row.get("specific_acceleration_vector") is not None
            if inertia_recorded:
                specific = _vector(row["specific_acceleration_vector"], "specific_acceleration_vector")
                angles = np.radians(azimuth + np.arange(component.fin_count) * 360/component.fin_count)
                normals_world = np.column_stack((np.zeros(len(angles)), -np.sin(angles), np.cos(angles))) @ attitude_basis.T
                inertial_load = -model["mass_kg"] * (normals_world @ specific)
                load = load + inertial_load
            elif not any("specific acceleration was not recorded" in warning for warning in warnings):
                warnings.append("Translational specific acceleration was not recorded: these states have aerodynamic forcing only; fin-root inertial loads are unavailable and are not inferred from gravity or scalar acceleration.")
            force_modal = unit_modal[:, None] * load[None, :]
            if displacement is None:
                displacement = force_modal / stiffness[:, None]
                velocity = np.zeros_like(displacement)
                acceleration = np.zeros_like(displacement)
                descriptor["initial_time_s"] = float(stamp)
            else:
                count = max(1, math.ceil((stamp - previous_time) / maximum_dt)) if integrator == "newmark" else 1
                if total_steps + count > max_substeps:
                    status, closed_reason = "work_budget", "Structural substep budget exhausted; increase max_substeps or narrow the analysis interval. No later states were simulated."
                    output[index]["components"].append(_unavailable(component, closed_reason))
                    continue
                dt = (stamp - previous_time) / count
                for substep in range(1, count + 1):
                    if substep % 256 == 0:
                        if cancelled and cancelled():
                            status, closed_reason = "cancelled", "Dynamic fin analysis cancelled during an internal step; later states are unavailable."
                            break
                        if progress:
                            fraction = (part_index + (index + substep/count)/len(rows)) / max(1, len(fins))
                            progress(min(.99, fraction), f"Dynamic fin FEM: {component.name}, t={stamp:.2f} s, {total_steps:,} internal steps")
                    fraction = substep / count
                    step_load = previous_load + fraction * (load - previous_load)
                    step_force = unit_modal[:, None] * step_load[None, :]
                    if integrator == "exact_foh":
                        displacement, velocity, acceleration = exact_foh_step(displacement, velocity,
                            unit_modal[:, None]*previous_load[None, :], step_force, omega, damping_ratio, dt)
                    else:
                        displacement, velocity, acceleration = newmark_step(displacement, velocity, acceleration, step_force,
                            1., damping[:, None], stiffness[:, None], dt)
                    total_steps += 1
                    descriptor["substeps"] += 1
                if closed_reason:
                    output[index]["components"].append(_unavailable(component, closed_reason))
                    continue
            full_displacement = modes @ displacement
            full_velocity = modes @ velocity
            full_acceleration = modes @ acceleration
            stress = _span_stress(model, full_displacement)
            balance = mass_modes @ acceleration + (mass_modes * damping[None, :]) @ velocity + stiffness_modes @ displacement - model["unit_force"][:, None] * load[None, :]
            scale = max(float(np.linalg.norm(model["unit_force"][:, None] * load[None, :])),
                        float(np.linalg.norm(stiffness_modes @ displacement)), 1e-12)
            residual = float(np.linalg.norm(balance[2:])) / scale
            if not np.isfinite(full_displacement).all() or not np.isfinite(stress).all() or residual > 1e-5:
                raise RuntimeError("Dynamic fin FEM failed equilibrium/finite-state checks; no nonphysical result was accepted.")
            fin_rows = []
            for fin in range(component.fin_count):
                angle = math.radians(azimuth + fin * 360/component.fin_count)
                normal_body = np.array([0., -math.sin(angle), math.cos(angle)])
                normal_world = attitude_basis @ normal_body
                kinetic = .5 * np.dot(full_velocity[:, fin], model["mass"] @ full_velocity[:, fin])
                elastic = .5 * np.dot(full_displacement[:, fin], model["stiffness"] @ full_displacement[:, fin])
                fin_rows.append({"fin_index": fin, "force_n": float(load[fin]),
                    "aerodynamic_force_n": float(aerodynamic_load[fin]),
                    "base_inertial_force_n": float(inertial_load[fin]) if inertia_recorded else None,
                    "span_m": model["span_m"].tolist(), "nodal_displacement_m": full_displacement[::2, fin].tolist(),
                    "nodal_bending_stress_pa": stress[:, fin].tolist(), "stress_pa": float(np.max(np.abs(stress[:, fin]))),
                    "tip_deflection_m": float(full_displacement[-2, fin]),
                    "root_reaction_force_n": float(balance[0, fin]), "root_reaction_moment_nm": float(balance[1, fin]),
                    "normal_direction_body": normal_body.tolist(), "normal_direction_world": normal_world.tolist(),
                    "root_reaction_vector_n": (balance[0, fin] * normal_world).tolist(),
                    "root_reaction_moment_vector_nm": (balance[1, fin] * attitude_basis[:, 0]).tolist(),
                    "kinetic_energy_j": float(kinetic), "elastic_energy_j": float(elastic)})
            peak = max(item["stress_pa"] for item in fin_rows)
            deflection = float(np.max(np.abs(full_displacement[::2])))
            output[index]["components"].append({"component_id": component.id, "name": component.name,
                "supported": True, "stress_pa": peak, "deflection_m": deflection,
                "safety_factor": material.yield_strength / peak if peak > 0 and not composite else None,
                "fidelity": FIDELITY + "; " + integrator, "load_fidelity": load_fidelity, "angle_of_attack_deg": incidence,
                "resolved_attitude": resolved, "translational_base_inertia_included": inertia_recorded,
                "relative_dynamic_equilibrium_residual": residual,
                "small_deflection_within_range": deflection <= .05 * component.span, "fins": fin_rows})
            descriptor["final_time_s"] = float(stamp)
            previous_load, previous_time = load, stamp
            max_stress = peak if max_stress is None else max(max_stress, peak)
            max_deflection = deflection if max_deflection is None else max(max_deflection, deflection)
            if progress and index % 32 == 0:
                progress(min(.99, (part_index + index/len(rows))/max(1, len(fins))), f"Dynamic fin FEM: {component.name}, t={stamp:.2f} s, {total_steps:,} internal steps")
        if any(item["supported"] and not item["small_deflection_within_range"] for result in output for item in result["components"] if item["component_id"] == component.id):
            warnings.append(f"{component.name}: predicted deflection exceeds 5% of span; linear beam assumptions are outside their small-deformation range.")
        if descriptor["initial_time_s"] is None:
            warnings.append(f"{component.name}: no valid original-fin aerodynamic load interval was available; every dynamic state remains unavailable.")
        elif closed_reason and status == "completed":
            warnings.append(f"{component.name}: structural coverage ends at t={descriptor['final_time_s']:.6g} s because a later load is unavailable. No structural state was carried through that gap.")
    for result in output:
        stresses = [item["stress_pa"] for item in result["components"] if item["supported"]]
        result["max_stress_pa"] = max(stresses) if stresses else None
    if not fins:
        warnings.append("No active original fin components are available for dynamic beam analysis.")
    if status != "completed":
        warnings.append(f"Stopping reason: {status}. Unsolved states remain unavailable and are not interpolated or labeled complete.")
    if progress:
        progress(1., f"Dynamic fin analysis {status}; {total_steps:,} actual {integrator} propagations")
    return {"trajectory": output, "components": descriptors, "fidelity": FIDELITY + "; " + integrator,
            "backend": "CPU NumPy/SciPy; complete beam modal basis", "warnings": list(dict.fromkeys(warnings)),
            "summary": {"status": status, "complete": status == "completed", "substeps": total_steps,
                "elapsed_seconds": time.perf_counter() - started, "max_stress_pa": max_stress,
                "max_deflection_m": max_deflection, "supported_components": sum(item["supported"] for item in descriptors),
                "unavailable_components": sum(not item["supported"] for item in descriptors),
                "analysis_interval_s": [start_time, end_time], "rows_with_available_results": sum(row["max_stress_pa"] is not None for row in output),
                "unavailable_rows": sum(row["max_stress_pa"] is None for row in output),
                "coverage": "Original-fin small-angle pre-recovery load intervals only; unavailable states are null",
                "recovery_loads_modeled": False, "cad_fin_geometry_modeled": False, "composite_layups_modeled": False}}
