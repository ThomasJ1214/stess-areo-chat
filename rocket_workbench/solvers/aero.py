"""Transparent preliminary aerodynamics and SI mass properties.

This module deliberately does not infer CFD pressure or CAD-resolved drag from a
render mesh.  Barrowman's small-angle method is applied to the original rocket
reference geometry; replacement meshes affect mass, but invalidate that reference
shape's aerodynamic predictions. See docs/PHYSICS.md for equations and limits.
"""
from __future__ import annotations

import math
import hashlib
import json

import numpy as np
import trimesh
from scipy.integrate import quad
from scipy.spatial.transform import Rotation

from rocket_workbench.models import Component, Conditions, Project, active_components, configuration

G0 = 9.80665
GAS_CONSTANT = 287.05287
EARTH_RADIUS = 6_356_766.0
FINS = {"finset", "trapezoidfinset", "freeformfinset", "ellipticalfinset"}
ASSEMBLIES = {"stage", "parallelstage", "podset", "rocket", "assembly"}
BODY = {"bodytube", "nosecone", "transition", "boattail"}


def atmosphere(altitude: float, temperature_delta: float = 0) -> dict:
    """US Standard Atmosphere 1976 layers; geometric altitude in metres.

    Pressure follows the standard hydrostatic profile. A temperature offset only
    changes local density, sound speed and viscosity, not the pressure profile.
    """
    if not math.isfinite(altitude) or not -500 <= altitude <= 50_000:
        raise ValueError("Atmosphere supports geometric altitudes from -500 to 50,000 m.")
    if not math.isfinite(temperature_delta):
        raise ValueError("Temperature offset must be finite.")
    h = EARTH_RADIUS * altitude / (EARTH_RADIUS + altitude)
    heights = [0.0, 11_000.0, 20_000.0, 32_000.0, 47_000.0, 51_000.0]
    lapse = [-0.0065, 0.0, 0.001, 0.0028, 0.0]
    tb, pb = 288.15, 101_325.0
    temperature, pressure = tb, pb
    for i, rate in enumerate(lapse):
        base = heights[i]
        upper = heights[i + 1]
        local_h = min(h, upper)
        delta_h = local_h - base
        temperature = tb + rate * delta_h
        if rate == 0:
            pressure = pb * math.exp(-G0 * delta_h / (GAS_CONSTANT * tb))
        else:
            pressure = pb * (tb / temperature) ** (G0 / (GAS_CONSTANT * rate))
        if h <= upper:
            break
        tb, pb = temperature, pressure
    temperature += temperature_delta
    if temperature <= 0:
        raise ValueError("Atmospheric temperature must be above absolute zero.")
    density = pressure / (GAS_CONSTANT * temperature)
    viscosity = 1.716e-5 * (temperature / 273.15) ** 1.5 * (273.15 + 110.4) / (temperature + 110.4)
    return {
        "temperature_k": temperature,
        "pressure_pa": pressure,
        "density_kg_m3": density,
        "speed_of_sound_m_s": math.sqrt(1.4 * GAS_CONSTANT * temperature),
        "dynamic_viscosity_pa_s": viscosity,
        "gravity_m_s2": G0 * (EARTH_RADIUS / (EARTH_RADIUS + altitude)) ** 2,
        "geopotential_altitude_m": h,
        "fidelity": "US Standard Atmosphere 1976, local temperature offset",
    }


def freestream(conditions: Conditions) -> np.ndarray:
    """Body-frame relative flow: +X nose to tail, alpha in XY, beta in XZ.

    Lateral wind direction is a *toward* angle: zero +Y, 90 degrees +Z.
    Specified Mach sets the primary stream speed before lateral wind is added.
    """
    atm = atmosphere(conditions.altitude, conditions.temperature_delta)
    speed = conditions.mach * atm["speed_of_sound_m_s"] if conditions.mach is not None else conditions.speed
    alpha, beta, wind_angle = map(math.radians, (conditions.angle_of_attack, conditions.sideslip, conditions.wind_direction))
    return np.array([
        speed * math.cos(alpha) * math.cos(beta),
        speed * math.sin(alpha) * math.cos(beta) + conditions.wind_speed * math.cos(wind_angle),
        speed * math.sin(beta) + conditions.wind_speed * math.sin(wind_angle),
    ], dtype=float)


def _nose_radius(c: Component, fraction: float) -> float:
    """Canonical visible nose/transition profile; fraction runs fore to aft."""
    from rocket_workbench.geometry import radius_profile
    return float(radius_profile(c, np.array([min(1.0, max(0.0, fraction)) * c.length]))[0])


def _fin_polygon(c: Component) -> np.ndarray:
    points = c.metadata.get("fin_points")
    if c.kind == "freeformfinset" and points:
        polygon = np.asarray(points, dtype=float)
        if polygon.ndim == 2 and polygon.shape[1] >= 2 and len(polygon) >= 3:
            return polygon[:, :2]
    if c.kind == "ellipticalfinset":
        theta = np.linspace(math.pi, 0, 65)
        return np.column_stack((c.root_chord / 2 * (1 + np.cos(theta)), c.span * np.sin(theta)))
    return np.array([[0, 0], [c.root_chord, 0], [c.sweep + c.tip_chord, c.span], [c.sweep, c.span]], dtype=float)


def _polygon_properties(polygon: np.ndarray) -> tuple[float, np.ndarray]:
    following = np.roll(polygon, -1, axis=0)
    cross = polygon[:, 0] * following[:, 1] - following[:, 0] * polygon[:, 1]
    signed_area = float(cross.sum() / 2)
    if abs(signed_area) < 1e-15:
        return 0.0, np.zeros(2)
    centroid = ((polygon + following) * cross[:, None]).sum(axis=0) / (6 * signed_area)
    return abs(signed_area), centroid


def _analytic_mass(c: Component, density: float) -> tuple[float, float]:
    if c.kind in ASSEMBLIES:
        return 0.0, c.x
    if c.kind in FINS:
        area, center = _polygon_properties(_fin_polygon(c))
        return area * c.thickness * c.fin_count * density, c.x + float(center[0])
    if c.kind == "nosecone":
        if c.length <= 0 or c.radius <= 0:
            return 0.0, c.x
        filled = bool(c.metadata.get("filled", False))
        def area(u):
            r = _nose_radius(c, u)
            return math.pi * (r * r - (0.0 if filled else max(0.0, r - c.thickness) ** 2))
        integral = quad(area, 0, 1, epsabs=1e-12, limit=100)[0]
        moment = quad(lambda u: u * area(u), 0, 1, epsabs=1e-12, limit=100)[0]
        return integral * c.length * density, c.x + c.length * moment / integral if integral > 0 else c.x
    if c.kind in {"transition", "boattail"}:
        r2 = c.radius_end if c.radius_end is not None else c.radius
        filled = bool(c.metadata.get("filled", False))
        def area(u):
            r = _nose_radius(c, u)
            return math.pi * (r * r - (0 if filled else max(0, r - c.thickness) ** 2))
        integral = quad(area, 0, 1, epsabs=1e-12)[0]
        moment = quad(lambda u: u * area(u), 0, 1, epsabs=1e-12)[0]
        return integral * c.length * density, c.x + c.length * moment / integral if integral > 0 else c.x
    if c.kind in {"masscomponent", "parachute", "streamer", "shockcord"}:
        # Their physical mass must come from ORK/user data, never guessed from a
        # parachute's packed cylinder or a cord's display shape.
        return 0.0, c.x + c.length / 2
    inner = float(c.metadata.get("inner_radius", max(0.0, c.radius - c.thickness)))
    if c.kind in {"bulkhead", "railbutton"} or c.metadata.get("filled"):
        inner = 0.0
    inner = min(c.radius, max(0.0, inner))
    volume = math.pi * (c.radius * c.radius - inner * inner) * c.length
    return volume * density, c.x + c.length / 2


def _mesh_mass(project: Project, c: Component, density: float) -> tuple[float, float, str | None]:
    asset = next((a for a in project.assets if a.id == c.asset_id), None)
    if asset is None:
        raise ValueError(f"Replacement asset for {c.name} is missing.")
    if not asset.watertight or not asset.faces or not asset.vertices:
        return 0.0, c.x, f"{c.name}: open/non-watertight CAD has no reliable solid mass; set a measured mass override."
    vertices = np.asarray(asset.vertices, dtype=float)
    faces = np.asarray(asset.faces, dtype=int)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError(f"{c.name}: CAD mass requires a triangular 3D mesh.")
    if np.any(faces < 0) or np.any(faces >= len(vertices)):
        raise ValueError(f"{c.name}: mesh triangle indices are out of bounds.")
    # Project JSON can be edited independently of its saved import metadata. A
    # stale watertight flag must not authorize integrating an actually open or
    # inconsistently wound surface as a solid.
    topology = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if not topology.is_watertight or not topology.is_winding_consistent:
        return 0.0, c.x, f"{c.name}: CAD mesh closure/winding is invalid; no reliable solid mass/CG is available. Set measured mass/CG overrides."
    rotation = Rotation.from_euler("xyz", c.transform.rotation, degrees=True).as_matrix()
    vertices = vertices * c.transform.scale @ rotation.T + np.asarray(c.transform.translation) + np.array([c.x, 0, 0])
    # Center the tetrahedral integration near the part, avoiding cancellation
    # when the CAD origin/placement is far from the small solid itself. Closed
    # surface mass/volume is invariant to the integration origin.
    integration_origin = vertices.mean(axis=0)
    triangles = (vertices - integration_origin)[faces]
    signed = np.einsum("ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])) / 6
    volume = float(signed.sum())
    if abs(volume) <= 1e-15:
        return 0.0, c.x, f"{c.name}: CAD enclosed volume is zero; set a measured mass override."
    center = integration_origin + (signed[:, None] * triangles.sum(axis=1) / 4).sum(axis=0) / volume
    return abs(volume) * density, float(center[0]), None


def _motor_state(project: Project, configuration_id: str | None, time: float) -> dict | None:
    cfg = configuration(project, configuration_id)
    motor = next((m for m in project.motors if m.id == cfg.motor_id), None)
    if motor is None:
        return None
    curve = np.asarray(motor.curve, dtype=float)
    fraction = 0.0
    if len(curve) >= 2:
        if curve.ndim != 2 or curve.shape[1] != 2 or np.any(curve[:, 0] < 0) or np.any(curve[:, 1] < 0) or np.any(np.diff(curve[:, 0]) <= 0):
            raise ValueError(f"Motor {motor.name}: thrust curve must have strictly increasing nonnegative times and nonnegative thrust.")
        cumulative = np.r_[0.0, np.cumsum((curve[:-1, 1] + curve[1:, 1]) / 2 * np.diff(curve[:, 0]))]
        impulse = float(cumulative[-1])
        burn_time = time - cfg.ignition_delay
        if impulse > 0 and burn_time > curve[0, 0]:
            idx = min(len(curve) - 2, int(np.searchsorted(curve[:, 0], burn_time, side="right") - 1))
            if burn_time >= curve[-1, 0]:
                fraction = 1.0
            else:
                elapsed = burn_time - float(curve[idx, 0])
                slope = (curve[idx + 1, 1] - curve[idx, 1]) / (curve[idx + 1, 0] - curve[idx, 0])
                partial = float(cumulative[idx] + curve[idx, 1] * elapsed + slope * elapsed * elapsed / 2)
                fraction = min(1.0, max(0.0, partial / impulse))
    mount = next((c for c in project.components if c.id == cfg.motor_mount_id), None)
    if cfg.motor_mount_id is not None and (mount is None or mount.id not in {c.id for c in active_components(project, configuration_id)}):
        raise ValueError("The configured motor mount is missing or inactive in the selected configuration. Select an active mount or remove the motor assignment.")
    # cfg.motor_position, when supplied, is the absolute motor *center*. For an
    # ORK mount the imported metadata contains its rear overhang.
    if cfg.motor_position is not None:
        center = cfg.motor_position
    elif mount is not None:
        center = mount.x + mount.length - motor.length / 2 + float(mount.metadata.get("motor_overhang", 0))
    else:
        tail = max((c.x + c.length for c in active_components(project, configuration_id) if c.kind in BODY), default=motor.length)
        center = tail - motor.length / 2
    return {"mass_kg": motor.dry_mass + motor.propellant_mass * (1 - fraction), "cg_m": center, "burn_fraction": fraction, "motor_id": motor.id}


def mass_properties(project: Project, configuration_id: str | None = None, time: float = 0) -> dict:
    if not math.isfinite(time) or time < 0:
        raise ValueError("Mass-property time must be finite and nonnegative.")
    components = active_components(project, configuration_id)
    by_id = {c.id: c for c in components}
    materials = {m.id: m for m in project.materials}
    warnings = []
    rows = []
    fallback = project.materials[0].density if project.materials else 1850.0
    def ancestors(c):
        seen = {c.id}
        parent = by_id.get(c.parent_id)
        while parent is not None:
            if parent.id in seen:
                raise ValueError("Component parent links contain a cycle.")
            seen.add(parent.id)
            yield parent
            parent = by_id.get(parent.parent_id)
    for c in components:
        density = materials[c.material_id].density if c.material_id in materials else fallback
        covered = any(p.mass_override is not None and p.metadata.get("mass_subcomponents_overridden") for p in ancestors(c))
        if covered:
            mass, cg = 0.0, c.x
        elif c.mass_override is not None:
            if c.geometry_mode == "replacement" and c.asset_id:
                _, cg, warning = _mesh_mass(project, c, density)
                if warning and c.cg_override is None:
                    warnings.append(f"{c.name}: measured mass applied to CAD, but reliable CAD CG is unavailable; set a measured CG override.")
            else:
                cg = _analytic_mass(c, density)[1]
            mass = c.mass_override
        elif c.geometry_mode == "replacement" and c.asset_id:
            mass, cg, warning = _mesh_mass(project, c, density)
            if warning:
                warnings.append(warning)
        else:
            mass, cg = _analytic_mass(c, density)
            if c.kind in {"masscomponent", "parachute", "streamer", "shockcord"} and c.mass_override is None:
                warnings.append(f"{c.name}: no measured/assigned mass; contributes zero mass.")
        if c.kind not in FINS and not covered:
            count = max(1, int(c.metadata.get("instance_count", 1)))
            # A measured override applies to one component instance, just as in
            # ORK. Fins already multiply by fin_count inside their mass formula.
            mass *= count
            cg += float(c.metadata.get("instance_separation", c.metadata.get("instanceseparation", 0))) * (count - 1) / 2
        if c.mass_override is None and any(float(c.metadata.get(key, 0) or 0) > 0 for key in (
            "aftshoulderlength", "foreheadshoulderlength", "foreshoulderlength", "shoulderlength", "tabheight", "tablength")):
            warnings.append(f"{c.name}: analytic component mass omits shoulders/fin tabs; assign a measured total mass/CG for those details.")
        if c.cg_override is not None:
            cg = c.cg_override
        rows.append({"component_id": c.id, "id": c.id, "name": c.name, "mass_kg": float(mass), "cg_m": float(cg), "included_in_parent_override": covered})
    # A subtree CG override is a moment override, not an extra mass. Descendant
    # CGs are shifted together so their moments sum to the specified group CG.
    # Process deepest first so a parent override takes final precedence.
    for c in sorted(components, key=lambda item: len(list(ancestors(item))), reverse=True):
        if c.cg_override is None or not c.metadata.get("cg_subcomponents_overridden"):
            continue
        descendants = [r for r in rows if r["component_id"] == c.id or c.id in {p.id for p in ancestors(by_id[r["component_id"]])}]
        total = sum(r["mass_kg"] for r in descendants)
        if total > 0:
            center = sum(r["mass_kg"] * r["cg_m"] for r in descendants) / total
            for row in descendants:
                row["cg_m"] += c.cg_override - center
    motor = _motor_state(project, configuration_id, time)
    total_mass = sum(r["mass_kg"] for r in rows) + (motor["mass_kg"] if motor else 0)
    moment = sum(r["mass_kg"] * r["cg_m"] for r in rows) + (motor["mass_kg"] * motor["cg_m"] if motor else 0)
    if total_mass <= 0:
        raise ValueError("The selected configuration must have positive mass. Assign component masses or materials.")
    if any(c.geometry_mode == "replacement" and c.asset_id and c.mass_override is None for c in components):
        warnings.append("CAD mass assumes a uniformly filled isotropic solid. For assemblies, cavities, shells or heterogeneous parts assign measured mass/CG overrides.")
    return {"mass_kg": total_mass, "cg_m": moment / total_mass, "components": rows, "motor": motor,
            "warnings": warnings, "fidelity": "Analytic original volumes / watertight triangular CAD solid volumes; measured overrides", "backend": "CPU"}


def geometry_signature(project: Project, configuration_id: str | None = None) -> str:
    """Invalidate supplied polars when selected geometry or CAD alignment changes.

    Material/mass changes do not invalidate the aerodynamic shape. Geometry IDs
    are included intentionally: replacing an asset requires explicit new consent.
    """
    keys = ("id", "kind", "parent_id", "x", "length", "radius", "radius_end", "thickness", "fin_count",
            "root_chord", "tip_chord", "span", "sweep", "external", "asset_id", "transform", "geometry_mode")
    components = active_components(project, configuration_id)
    selected = []
    for component in components:
        raw = component.model_dump()
        row = {key: raw[key] for key in keys}
        mass_only_keys = {"mass_subcomponents_overridden", "cg_subcomponents_overridden", "mass", "cg", "density", "material", "material_id"}
        # Preserve every importer-specific geometry key, including shoulder/tab
        # dimensions, radial placement, clipping, cant and replicated instances.
        # Conservative invalidation is safer than a stale coefficient table.
        row["metadata"] = {key: value for key, value in component.metadata.items() if key not in mass_only_keys}
        if component.geometry_mode == "replacement" and component.asset_id:
            asset = next((asset for asset in project.assets if asset.id == component.asset_id), None)
            row["asset"] = {"vertices": asset.vertices, "faces": asset.faces} if asset else None
        selected.append(row)
    data = json.dumps(selected, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def _polar(project: Project, configuration_id: str | None, warnings: list[str]) -> dict | None:
    cfg = configuration(project, configuration_id)
    candidates = [row for row in project.metadata.get("aerodynamic_polars", [])
                  if row.get("configuration_id") in {None, cfg.id}]
    if not candidates:
        return None
    signature = geometry_signature(project, configuration_id)
    matching = [row for row in candidates if row.get("geometry_signature") == signature]
    if len(matching) != len(candidates):
        warnings.append("Aerodynamic polar rows with a missing/stale geometry signature are ignored. Re-import coefficients after geometry changes.")
    if not matching:
        return None
    values = []
    for row in matching:
        try:
            values.append([float(row[key]) for key in ("mach", "cd", "cna", "cp_m")])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Aerodynamic polar rows require finite mach, cd, cna (per radian), cp_m.") from exc
    array = np.array(sorted(values, key=lambda row: row[0]), dtype=float)
    if not np.all(np.isfinite(array)) or np.any(array[:, 0] < 0) or np.any(array[:, 0] > 2) or np.any(array[:, 1] < 0) or np.any(array[:, 2] <= 0):
        raise ValueError("Polar Mach must be in [0,2], Cd nonnegative and CNa strictly positive; all values must be finite.")
    if len(array) < 2 or np.any(np.diff(array[:, 0]) <= 0):
        raise ValueError("A polar needs at least two distinct increasing Mach points; duplicate Mach values are ambiguous.")
    sources = sorted({str(row.get("source", "unspecified")) for row in matching})
    warnings.append("User-supplied aerodynamic polar used only within its Mach coverage; source/geometry agreement is recorded, but coefficient accuracy is not independently verified. Per-component force breakdown remains a reference estimate.")
    return {"values": array, "source": "; ".join(sources), "geometry_signature": signature}


def _cone_pressure_cd(mach: float, sine_angle: float) -> float:
    """Conical-envelope pressure estimate used by published rocket methods.

    Subsonic power interpolation, a Hermite transonic bridge, and supersonic
    approximation as documented in OpenRocket SymmetricComponentCalc. This is
    not a shape-resolved CFD solution for a curved or replacement nose.
    """
    sine = max(0.0, min(1.0, sine_angle))
    if sine <= 0:
        return 0.0
    at_zero = 0.8 * sine * sine
    at_one = sine
    slope_one = 4 / 2.4 * (1 - 0.5 * sine)
    if mach <= 1:
        exponent = max(1.0, slope_one / max(at_one - at_zero, 1e-12))
        return at_zero + (at_one - at_zero) * mach ** exponent
    if mach >= 1.3:
        return 2.1 * sine * sine + 0.5 * sine / math.sqrt(mach * mach - 1)
    at_high = 2.1 * sine * sine + 0.6019 * sine
    slope_high = -1.1341 * sine
    u = (mach - 1) / 0.3
    return max(0.0, (2*u**3 - 3*u*u + 1)*at_one + (u**3 - 2*u*u + u)*0.3*slope_one
               + (-2*u**3 + 3*u*u)*at_high + (u**3 - u*u)*0.3*slope_high)


def _configuration_features(project: Project, configuration_id: str | None = None) -> set[str]:
    """Selected import limitations plus unsupported geometry currently enabled.

    New ORK imports preserve feature limits per configuration. The global union
    remains a legacy fallback, so one unsupported configuration cannot prevent a
    different, supported one from running.
    """
    cfg = configuration(project, configuration_id)
    scoped = project.metadata.get("unsupported_features_by_configuration")
    features = set(scoped.get(cfg.id, [])) if isinstance(scoped, dict) else set(project.metadata.get("unsupported_features", []))
    components = active_components(project, configuration_id)
    features.update(c.kind for c in components if c.kind in {"parallelstage", "podset"})
    if any(str(c.metadata.get("cluster_configuration", "single")) not in {"single", "1", ""} for c in components):
        features.add("cluster")
    if sum(c.kind == "stage" for c in components) > 1:
        features.add("multistage")
    return features


def _prepare(project: Project, configuration_id: str | None = None) -> dict:
    components = active_components(project, configuration_id)
    outer = [c for c in components if c.external and c.kind in BODY]
    radius = max((max(c.radius, c.radius_end or 0) for c in outer), default=0.0)
    if radius <= 0:
        raise ValueError("Aerodynamics requires a positive external body/nose reference diameter.")
    area, diameter = math.pi * radius * radius, 2 * radius
    length = max((c.x + c.length for c in outer), default=diameter) - min((c.x for c in outer), default=0)
    length = max(length, diameter)
    warnings = list(project.import_warnings)
    for feature in sorted(_configuration_features(project, configuration_id)):
        warnings.append(f"Unsupported reference-model feature: {feature}.")
    items = []
    for c in components:
        cn, cp, wetted, pressure_cd = 0.0, c.x + c.length / 2, 0.0, 0.0
        extra = {}
        if c.external and c.kind == "nosecone" and c.radius > 0 and c.length > 0:
            volume = math.pi * c.length * quad(lambda u: _nose_radius(c, u) ** 2, 0, 1, epsabs=1e-12)[0]
            fore_area = math.pi * _nose_radius(c, 0) ** 2
            local_area = math.pi * _nose_radius(c, 1) ** 2
            delta_area = local_area - fore_area
            cn = 2 * delta_area / area
            cp = c.x + (c.length * local_area - volume) / delta_area if abs(delta_area) > 1e-15 else c.x + c.length / 2
            # Conical wetted-area surrogate is explicit for all nose families.
            wetted = math.pi * c.radius * math.hypot(c.radius, c.length)
            extra = {"nose_sine_angle": c.radius / math.hypot(c.radius, c.length), "nose_area_ratio": local_area / area}
            if str(c.metadata.get("nose_shape", "conical")).lower() not in {"conical", "cone"}:
                warnings.append(f"{c.name}: pressure drag uses a conical-envelope surrogate; original nose family is used for CP/volume.")
        elif c.external and c.kind in {"transition", "boattail"}:
            aft = c.radius_end if c.radius_end is not None else c.radius
            cn = 2 * math.pi * (aft * aft - c.radius * c.radius) / area
            if abs(aft - c.radius) > 1e-12:
                volume = math.pi * c.length * quad(lambda u: _nose_radius(c, u) ** 2, 0, 1, epsabs=1e-12)[0]
                cp = c.x + (c.length * math.pi * aft*aft - volume) / (math.pi * (aft*aft - c.radius*c.radius))
            wetted = math.pi * (c.radius + aft) * math.hypot(c.length, aft - c.radius)
            # Separation is not represented. A blunt-expansion pressure term is
            # an estimate, not a validated boattail model.
            slope = abs(aft - c.radius) / max(c.length, 1e-9)
            pressure_cd = 0.05 * slope * abs(math.pi * (aft * aft - c.radius * c.radius)) / area
        elif c.external and c.kind in FINS:
            polygon = _fin_polygon(c)
            fin_area, centroid = _polygon_properties(polygon)
            root, tip, span, sweep = c.root_chord, c.tip_chord, c.span, c.sweep
            if c.kind != "trapezoidfinset" and c.kind != "finset":
                warnings.append(f"{c.name}: equivalent trapezoid Barrowman lift/CP estimate for {c.kind}; real polygon is used for mass and skin area.")
            if c.fin_count < 3:
                warnings.append(f"{c.name}: one/two-fin directional lift is represented by an azimuth-averaged slope, not a full directional stability prediction.")
            if c.fin_count > 4:
                warnings.append(f"{c.name}: fin-to-fin interference for more than four fins is omitted.")
            if root + tip > 0 and span > 0:
                mid = math.hypot(span, sweep + (tip - root) / 2)
                cn = (1 + c.radius / (c.radius + span)) * 4 * c.fin_count * (span / diameter) ** 2 / (1 + math.sqrt(1 + (2 * mid / (root + tip)) ** 2))
                cp = c.x + sweep / 3 * (root + 2 * tip) / (root + tip) + (root + tip - root * tip / (root + tip)) / 6
                extra = {"fin_mid_ratio": 2 * mid / (root + tip), "fin_area_ratio": fin_area / area,
                         "fin_interference": 1 + c.radius / (c.radius + span), "fin_count": c.fin_count,
                         "fin_mac_m": 2 / 3 * (root * root + root * tip + tip * tip) / (root + tip)}
            wetted = 2 * fin_area * c.fin_count
            perimeter = float(np.linalg.norm(polygon - np.roll(polygon, -1, axis=0), axis=1).sum())
            wetted += perimeter * c.thickness * c.fin_count
            pressure_cd = 0.01 * c.fin_count * span * c.thickness / area
        elif c.external and c.kind == "bodytube":
            wetted = 2 * math.pi * c.radius * c.length
        elif c.external and c.kind not in ASSEMBLIES:
            wetted = 2 * math.pi * c.radius * c.length
            warnings.append(f"{c.name}: external {c.kind} lift and interference drag are not modeled.")
        items.append({"component_id": c.id, "id": c.id, "name": c.name, "kind": c.kind,
                      "cp_m": cp, "cna_per_rad": cn, "wetted_area_m2": wetted, "pressure_cd": pressure_cd,
                      "external": c.external, **extra})
    cn_total = sum(r["cna_per_rad"] for r in items)
    if cn_total <= 0:
        warnings.append("No positive Barrowman normal-force slope: CP and stability are undefined. Mass/drag diagnostics remain available; a supported reference shape or supplied aerodynamic polar is required for flight.")
    cp = sum(r["cp_m"] * r["cna_per_rad"] for r in items) / cn_total if cn_total > 0 else None
    if not any(c.external and c.kind in FINS for c in components):
        warnings.append("No supported external fins: passive flight stability is not assured.")
    replacements = [c.name for c in components if c.external and c.geometry_mode == "replacement" and c.asset_id]
    if replacements:
        warnings.append("External CAD replacement: empirical drag/CP still describe the ORIGINAL OpenRocket reference shape; real CAD affects mass/CG only. Run mesh-resolved CFD to evaluate aerodynamic geometry changes. Components: " + ", ".join(replacements))
    warnings.extend([
        "Drag is a preliminary smooth-surface engineering estimate, not measured or CFD-resolved; roughness, protuberance interference, fin flutter and separated flow are omitted.",
        "Barrowman CP is a small-angle slender-rocket reference. Finite-wing subsonic lift and linearized supersonic fin lift are bridged through transonic flow; these and the quarter-to-half chord CP shift are preliminary, not validated Mach-2 stability predictions.",
    ])
    aft = max(outer, key=lambda c: c.x + c.length)
    base_radius = aft.radius_end if aft.kind in {"transition", "boattail"} and aft.radius_end is not None else aft.radius
    polar = _polar(project, configuration_id, warnings)
    return {"components": items, "reference_area_m2": area, "diameter_m": diameter, "length_m": length,
            "cp_m": cp, "cna_per_rad": cn_total, "warnings": list(dict.fromkeys(warnings)),
            "replacement": bool(replacements), "base_area_ratio": math.pi * base_radius * base_radius / area, "polar": polar}


def _evaluate(prepared: dict, atm: dict, speed: float, alpha_rad: float = 0, beta_rad: float = 0) -> dict:
    """Cheap reusable aerodynamic evaluation for trajectory integration."""
    mach = speed / atm["speed_of_sound_m_s"]
    q = 0.5 * atm["density_kg_m3"] * speed * speed
    reynolds = max(1.0, atm["density_kg_m3"] * speed * prepared["length_m"] / atm["dynamic_viscosity_pa_s"])
    if speed <= 0:
        cf = 0.0
    elif reynolds < 5e5:
        cf = 1.328 / math.sqrt(reynolds)
    else:
        cf = 0.455 / math.log10(reynolds) ** 2.58 / (1 + 0.144 * mach * mach) ** 0.65
    fineness = prepared["length_m"] / prepared["diameter_m"]
    form = 1 + 60 / fineness ** 3 + 0.0025 * fineness
    base_cd = (0.12 + 0.13 * min(mach, 1) ** 2) / max(1, mach) * prepared["base_area_ratio"]
    wave_cd = 0.0
    rows = []
    for item in prepared["components"]:
        skin_cd = cf * form * item["wetted_area_m2"] / prepared["reference_area_m2"]
        cn, cp = item["cna_per_rad"], item["cp_m"]
        if "fin_mid_ratio" in item:
            k = item["fin_mid_ratio"]
            sub = item["cna_per_rad"] * (1 + math.sqrt(1 + k*k)) / (1 + math.sqrt(1 + (1 - min(mach, .9)**2)*k*k))
            sup = 4 / math.sqrt(max(1.5, mach)**2 - 1) * item["fin_area_ratio"] * item["fin_count"] / 2 * item["fin_interference"]
            u = min(1.0, max(0.0, (mach - .9) / .6))
            blend = u*u*(3 - 2*u)
            cn = sub * (1 - blend) + sup * blend
            # Subsonic quarter chord and supersonic half-chord endpoint. The
            # transonic bridge is identified as an approximation, not ORK parity.
            cp_shift = min(1.0, max(0.0, (mach - .5) / 1.5))
            cp += .25 * item["fin_mac_m"] * cp_shift*cp_shift*(3 - 2*cp_shift)
        pressure_cd = item["pressure_cd"]
        if "nose_sine_angle" in item:
            pressure_cd = _cone_pressure_cd(mach, item["nose_sine_angle"]) * item["nose_area_ratio"]
            wave_cd += max(0.0, pressure_cd - _cone_pressure_cd(0, item["nose_sine_angle"]) * item["nose_area_ratio"])
        induced_cd = 0.5 * abs(cn) * (alpha_rad * alpha_rad + beta_rad * beta_rad)
        cd = skin_cd + pressure_cd + induced_cd
        rows.append({**item, "cp_m": cp, "pressure_cd": pressure_cd, "skin_cd": skin_cd, "induced_cd": induced_cd, "cd": cd,
                     "cna_per_rad": cn, "drag_n": q * prepared["reference_area_m2"] * cd,
                     "normal_force_n": q * prepared["reference_area_m2"] * cn * alpha_rad,
                     "side_force_n": q * prepared["reference_area_m2"] * cn * beta_rad,
                     "reference_area_m2": prepared["reference_area_m2"]})
    # Base drag remains a global contribution. Wave contribution is diagnostic
    # and already included in the individual nose pressure-drag term.
    cd = sum(r["cd"] for r in rows) + base_cd
    total_cn = sum(row["cna_per_rad"] for row in rows)
    cp = sum(row["cna_per_rad"] * row["cp_m"] for row in rows) / total_cn if total_cn > 0 else None
    result = {"cd": cd, "drag_n": q * prepared["reference_area_m2"] * cd,
            "normal_force_n": sum(r["normal_force_n"] for r in rows),
            "side_force_n": sum(r["side_force_n"] for r in rows), "dynamic_pressure_pa": q,
            "mach": mach, "speed_m_s": speed, "density_kg_m3": atm["density_kg_m3"],
            "reynolds": reynolds, "base_cd": base_cd, "wave_cd": wave_cd, "components": rows,
            "cp_m": cp, "cna_per_rad": total_cn, "polar_applied": False, "component_breakdown_valid": True}
    polar = prepared.get("polar")
    if polar is not None:
        table = polar["values"]
        if table[0, 0] - 1e-9 <= mach <= table[-1, 0] + 1e-9:
            coefficient, slope, cp = [float(np.interp(mach, table[:, 0], table[:, i])) for i in (1, 2, 3)]
            result.update(cd=coefficient, cp_m=cp, cna_per_rad=slope,
                          drag_n=q * prepared["reference_area_m2"] * coefficient,
                          normal_force_n=q * prepared["reference_area_m2"] * slope * alpha_rad,
                          side_force_n=q * prepared["reference_area_m2"] * slope * beta_rad,
                          polar_applied=True, component_breakdown_valid=False, polar_source=polar["source"])
    return result


def analyze(project: Project, conditions: Conditions, configuration_id: str | None = None) -> dict:
    prepared = _prepare(project, configuration_id)
    mass = mass_properties(project, configuration_id)
    atm = atmosphere(conditions.altitude, conditions.temperature_delta)
    vector = freestream(conditions)
    speed = float(np.linalg.norm(vector))
    alpha = math.atan2(float(vector[1]), float(vector[0])) if speed else 0
    beta = math.asin(float(np.clip(vector[2] / speed, -1, 1))) if speed else 0
    incidence = math.atan2(float(np.linalg.norm(vector[1:])), float(vector[0])) if speed else 0
    result = _evaluate(prepared, atm, speed, alpha, beta)
    warnings = prepared["warnings"] + mass["warnings"]
    if result["mach"] > 2 + 1e-9:
        warnings.append("Actual resultant flow exceeds Mach 2: this aerodynamic model is outside its supported operating range.")
    if incidence > math.radians(10):
        warnings.append("Resultant flow angle exceeds 10 degrees: small-angle CP/lift estimates are outside their useful scope.")
    if result["cna_per_rad"] <= 0:
        warnings.append("Total normal-force slope at this Mach is nonpositive: CP and static stability are undefined.")
    mass_map = {r["component_id"]: r for r in mass["components"]}
    for row in result["components"]:
        row.update({"mass_kg": mass_map[row["component_id"]]["mass_kg"], "cg_m": mass_map[row["component_id"]]["cg_m"]})
    if prepared["polar"] is not None and not result["polar_applied"]:
        warnings.append("Flow Mach is outside supplied aerodynamic polar coverage; original-reference estimates are returned instead.")
    cp_valid = result["cp_m"] is not None and (result["polar_applied"] or (not prepared["replacement"] and result["mach"] < 0.7)) and incidence <= math.radians(10)
    return {**result, "mass_kg": mass["mass_kg"], "cg_m": mass["cg_m"],
            "reference_area_m2": prepared["reference_area_m2"], "reference_diameter_m": prepared["diameter_m"],
            "stability_calibers": (result["cp_m"] - mass["cg_m"]) / prepared["diameter_m"] if result["cp_m"] is not None else None,
            "effective_angle_of_attack_deg": math.degrees(alpha), "effective_sideslip_deg": math.degrees(beta),
            "effective_total_incidence_deg": math.degrees(incidence),
            "freestream_m_s": vector.tolist(), "cp_valid": cp_valid,
            "geometry_basis": "User supplied aerodynamic polar matched to current geometry" if result["polar_applied"] else "original Barrowman reference geometry", "mass_basis": mass["fidelity"],
            "atmosphere": atm, "warnings": list(dict.fromkeys(warnings)),
            "fidelity": "User supplied aerodynamic polar (not independently validated)" if result["polar_applied"] else "Preliminary Barrowman small-angle stability / empirical component drag estimate",
            "validity": {"max_mach": 2, "preferred_mach_below": 0.7, "max_small_angle_deg": 10,
                         "within_operating_range": result["mach"] <= 2 + 1e-9,
                         "within_small_angle_range": incidence <= math.radians(10), "cad_resolved": False}, "backend": "CPU"}
