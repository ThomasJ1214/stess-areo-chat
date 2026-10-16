"""Original-fin static plate adapter; geometry and source project stay read-only."""

from __future__ import annotations
import math
from dataclasses import dataclass
from ..models import Component, Material
import numpy as np
from scipy.spatial.transform import Rotation
from .plate_elements import polygon_quad_mesh, solve_plate

FIDELITY = "Linear-static isotropic MITC4 Reissner–Mindlin fin plate FEA; clamped original external planforms"


@dataclass(frozen=True)
class PlateSetup:
    component: Component
    material: Material
    composite: bool
    polygon: np.ndarray
    mesh_size: float
    recommended_mesh_size: float
    max_elements: int
    element_count: int
    recommended_element_count: int
    acceleration: np.ndarray
    pressure: float
    load_mode: str


def inspect(project, component_id, options):
    component = next((c for c in project.components if c.id == component_id), None)
    if component is None:
        raise ValueError("Select an existing component for plate FEA.")
    if (
        component.kind not in {"trapezoidfinset", "finset", "fin"}
        or component.geometry_mode == "replacement"
        or not component.external
    ):
        raise ValueError(
            "Plate FEA currently supports original trapezoidal/triangular fins only; no CAD midsurface is inferred."
        )
    if (
        component.metadata.get("unsupported")
        or component.metadata.get("instance_count", 1) != 1
    ):
        raise ValueError(
            "Unsupported/instanced fin assemblies require an explicit structural model."
        )
    if (
        not np.isfinite(
            [
                component.span,
                component.root_chord,
                component.thickness,
                component.tip_chord,
                component.sweep,
                component.x,
                component.radius,
            ]
        ).all()
        or min(component.span, component.root_chord, component.thickness) <= 0
        or component.tip_chord < 0
    ):
        raise ValueError(
            "Fin span, root chord and thickness must be positive; tip chord must be nonnegative."
        )
    if not np.isfinite(
        [
            float(component.metadata.get(k, 0))
            for k in [
                "cant",
                "angleoffset",
                "rotation",
                "radialposition",
                "radialdirection",
            ]
        ]
    ).all():
        raise ValueError("Fin placement angles and offsets must be finite.")
    if component.thickness / min(component.root_chord, component.span) > 0.1:
        raise ValueError(
            "Plate thickness exceeds 10% of the span/root chord; use solid FEA and verify shear assumptions."
        )
    material = next(
        (m for m in project.materials if m.id == component.material_id), None
    )
    if material is None:
        raise ValueError("Assign an explicit fin material before plate FEA.")
    if (
        not np.isfinite(
            [
                material.youngs_modulus,
                material.density,
                material.poisson_ratio,
                material.yield_strength,
            ]
        ).all()
        or min(material.youngs_modulus, material.density, material.yield_strength) <= 0
        or not -1 < material.poisson_ratio < 0.5
    ):
        raise ValueError(
            "Plate material requires positive E/density and -1 < Poisson ratio < 0.5."
        )
    composite = any(
        word in (material.name + " " + material.description).lower()
        for word in [
            "fiberglass",
            "carbon",
            "laminate",
            "composite",
            "surrogate",
            "glass fiber",
            "glass fibre",
        ]
    )
    if composite and options.get("plate_allow_isotropic_surrogate") is not True:
        raise ValueError(
            "Explicitly acknowledge an isotropic composite surrogate, or select a verified homogeneous material."
        )
    if "load_mode" in options:
        raise ValueError(
            "Plate FEA uses plate_load_mode; solid traction/CFD pressure transfer modes are unsupported."
        )
    mode = options.get("plate_load_mode", "pressure")
    if mode not in {"pressure", "aero_resultant"}:
        raise ValueError("Plate load mode must be pressure or aero_resultant.")
    if mode == "aero_resultant" and (
        component.fin_count < 3 or abs(float(component.metadata.get("cant", 0))) > 1e-9
    ):
        raise ValueError(
            "Aerodynamic plate loads require at least three equally spaced, uncanted fins."
        )
    if options.get("backend", "auto") not in {"auto", "cpu"}:
        raise ValueError(
            "Plate FEA currently uses the CPU sparse solver; select CPU or automatic."
        )
    pressure = float(options.get("plate_pressure_pa", 1000))
    acceleration = np.asarray(options.get("acceleration_m_s2", [0, 0, 0]), dtype=float)
    if (
        not math.isfinite(pressure)
        or acceleration.shape != (3,)
        or not np.isfinite(acceleration).all()
    ):
        raise ValueError(
            "Plate pressure and three support-specific-acceleration components must be finite."
        )
    raw = options.get("max_elements", 20000)
    budget = int(raw)
    if isinstance(raw, bool) or budget != raw or not 20 <= budget <= 20000:
        raise ValueError(
            "Plate element limit must be an integer from 20 to 20000 across all fins."
        )
    polygon = np.array(
        [
            [0.0, 0.0],
            [component.root_chord, 0.0],
            [component.sweep + component.tip_chord, component.span],
            [component.sweep, component.span],
        ]
    )
    if component.tip_chord == 0:
        polygon = polygon[[0, 1, 2]]
    recommendation = max(component.root_chord, component.span, component.tip_chord) / 16
    size = float(options.get("mesh_size", recommendation))
    if not math.isfinite(size) or size <= 0:
        raise ValueError("Plate mesh size must be positive and finite.")

    # Closed-form count of the same conforming patch mesh; no volume mesher.
    def count(h):
        center = polygon.mean(axis=0)
        mids = (polygon + np.roll(polygon, -1, axis=0)) / 2
        patches = [
            np.array([polygon[i], mids[i], center, mids[i - 1]])
            for i in range(len(polygon))
        ]
        length = max(
            np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1).max() for p in patches
        )
        ratio = length / h
        if not math.isfinite(ratio) or ratio > 1e8:
            return 10**18
        return len(polygon) * max(1, math.ceil(ratio)) ** 2 * component.fin_count

    return PlateSetup(
        component,
        material,
        composite,
        polygon,
        size,
        recommendation,
        budget,
        count(size),
        count(recommendation),
        acceleration,
        pressure,
        mode,
    )


def preflight(project, component_id, options):
    result = dict(
        component_id=component_id,
        can_run=False,
        geometry_valid=False,
        errors=[],
        warnings=[],
        element_model="plate",
        cad_thickness_unknown=False,
        beam_estimate_available=False,
        recommended_mesh_size_m=None,
        maximum_bending_mesh_size_m=None,
        recommended_within_maximum_budget=False,
        recommended_within_budget=False,
        scope="Original-fin midsurface, material and exact quadrilateral count; support/load and convergence still require review.",
    )
    try:
        setup = inspect(project, component_id, options)
        c, m = setup.component, setup.material
        size, recommend = setup.mesh_size, setup.recommended_mesh_size
        budget, count, recommended = (
            setup.max_elements,
            setup.element_count,
            setup.recommended_element_count,
        )
        result.update(
            geometry_valid=True,
            component_name=c.name,
            material=m.model_dump(),
            requested_mesh_size_m=size,
            recommended_mesh_size_m=recommend,
            max_elements=budget,
            estimated_elements=count,
            recommended_estimated_elements=recommended,
            budget_screening_elements=count,
            recommended_budget_screening_elements=recommended,
            recommended_within_budget=recommended <= budget,
            recommended_within_maximum_budget=recommended <= 20000,
            recommended_max_elements=(
                max(budget, recommended) if recommended <= 20000 else None
            ),
            procedural_thickness_m=c.thickness,
            material_volume_m3=(c.root_chord + c.tip_chord)
            * c.span
            / 2
            * c.thickness
            * c.fin_count,
            recommended_clamp_type="radial_root",
        )
        if count > budget:
            result["errors"].append(
                f"Plate mesh needs {count:,} quadrilaterals across all fins, exceeding the {budget:,}-element budget. Increase surface mesh size or budget (maximum 20000)."
            )
        result["can_run"] = not result["errors"]
        result["warnings"] = [
            "Plate mesh size controls in-plane resolution; thickness is integrated analytically. Refine the mesh to check displacement, energy and stresses away from the clamp.",
            "Only external fin planforms are solved. Root is fully clamped at the body surface; tabs, adhesive, body flexibility, membrane forces and joints are excluded.",
        ]
    except (ValueError, TypeError, OverflowError) as e:
        result["errors"].append(str(e))
    return result


def solve(project, component_id, conditions, options, progress=None, cancelled=None):
    ready = preflight(project, component_id, options)
    if not ready["can_run"]:
        raise ValueError(ready["errors"][0])
    setup = inspect(project, component_id, options)
    c, m, composite, poly = (
        setup.component,
        setup.material,
        setup.composite,
        setup.polygon,
    )
    size, budget = setup.mesh_size, setup.max_elements
    acceleration, pressure, mode = setup.acceleration, setup.pressure, setup.load_mode
    xy, quads = polygon_quad_mesh(poly, size, budget // c.fin_count)
    root = np.flatnonzero(np.isclose(xy[:, 1], 0, atol=c.span * 1e-10, rtol=0))
    fixed = (3 * root[:, None] + np.arange(3)).ravel()
    area = (c.root_chord + c.tip_chord) * c.span / 2
    notes = list(ready["warnings"]) + [
        "Only transverse support-specific-acceleration loads are included; in-plane acceleration, gravity and membrane forces are not added automatically.",
        "Linear static isotropic bending/shear only: no laminate failure, membrane response, buckling, plasticity, flutter, transient plate dynamics or coupled flight response.",
        "Displayed midsurface colors average adjacent element peak stresses. Through-thickness bending and assumed parabolic transverse shear are recovered at Gauss points; local clamp singularities require refinement.",
    ]
    angle = float(c.metadata.get("angleoffset", c.metadata.get("rotation", 0)))
    cant = Rotation.from_euler("y", float(c.metadata.get("cant", 0)), degrees=True)
    radial = float(c.metadata.get("radialposition", 0))
    direction = math.radians(float(c.metadata.get("radialdirection", 0)))
    shift = np.array([c.x, radial * math.cos(direction), radial * math.sin(direction)])
    origin = np.array([c.root_chord / 2, c.radius, 0])
    base = np.column_stack((xy[:, 0], xy[:, 1] + c.radius, np.zeros(len(xy))))
    base = cant.apply(base - origin) + origin
    cross = poly[:, 0] * np.roll(poly[:, 1], -1) - poly[:, 1] * np.roll(poly[:, 0], -1)
    plan_centroid = ((poly + np.roll(poly, -1, axis=0)) * cross[:, None]).sum(
        axis=0
    ) / (3 * cross.sum())
    base_centroid = (
        cant.apply(
            np.array([plan_centroid[0], plan_centroid[1] + c.radius, 0]) - origin
        )
        + origin
    )
    resultant = None
    if mode == "aero_resultant":
        from .aero import analyze

        aero = analyze(project, conditions)
        load = next(
            (
                a
                for a in aero["components"]
                if a.get("component_id", a.get("id")) == c.id
            ),
            None,
        )
        if (
            load is None
            or not aero.get("cp_valid", True)
            or not aero.get("component_breakdown_valid", True)
            or any(
                aero.get("validity", {}).get(key) is False
                for key in ["within_operating_range", "within_small_angle_range"]
            )
        ):
            raise ValueError(
                "Original-reference aerodynamic fin loading is unavailable."
            )
        resultant = np.array(
            [
                0.0,
                float(load.get("normal_force_n", 0)),
                float(load.get("side_force_n", 0)),
            ]
        )
        notes += aero.get("warnings", []) + [
            "Aerodynamic load is an original-reference engineering finset resultant, directionally partitioned and spread uniformly over each actual planform. It is not CFD pressure or a resolved chordwise/spanwise distribution."
        ]
    vertices = []
    displacements = []
    stress = []
    faces = []
    all_quads = []
    fin_results = []
    element_stress = []
    total_force = np.zeros(3)
    total_reaction = np.zeros(3)
    total_moment = np.zeros(3)
    total_reaction_moment = np.zeros(3)
    total_energy = 0.0
    total_work = 0.0
    max_residual = 0.0
    peak = 0.0
    for i in range(c.fin_count):
        if cancelled and cancelled():
            raise RuntimeError("Plate FEA cancelled.")
        rotate = Rotation.from_euler("x", angle + 360 * i / c.fin_count, degrees=True)
        rotation = rotate * cant
        normal = rotation.apply([0.0, 0.0, 1.0])
        applied_pressure = (
            pressure
            if mode == "pressure"
            else float(2 / c.fin_count * np.dot(normal, resultant) / area)
        )
        inertial_pressure = (
            -m.density * c.thickness * float(np.dot(acceleration, normal))
        )
        answer = solve_plate(
            xy,
            quads,
            m.youngs_modulus,
            m.poisson_ratio,
            c.thickness,
            applied_pressure + inertial_pressure,
            fixed,
            cancelled=cancelled,
            progress=(
                (lambda f, msg: progress((i + f) / c.fin_count, msg))
                if progress
                else None
            ),
        )
        world = rotate.apply(base) + shift
        movement = answer["dofs"][:, 0, None] * normal
        nodal_force = answer["nodal_loads"][:, 0, None] * normal
        nodal_reaction = answer["nodal_reactions"][:, 0, None] * normal
        # Work-conjugate beta couples: local [Mx,My]=[load_beta_y,-load_beta_x].
        couples = np.column_stack(
            (
                answer["nodal_loads"][:, 2],
                -answer["nodal_loads"][:, 1],
                np.zeros(len(xy)),
            )
        )
        reaction_couples = np.column_stack(
            (
                answer["nodal_reactions"][:, 2],
                -answer["nodal_reactions"][:, 1],
                np.zeros(len(xy)),
            )
        )
        force = nodal_force.sum(axis=0)
        reaction = nodal_reaction.sum(axis=0)
        moment = (np.cross(world, nodal_force) + rotation.apply(couples)).sum(axis=0)
        reaction_moment = (
            np.cross(world, nodal_reaction) + rotation.apply(reaction_couples)
        ).sum(axis=0)
        weights = answer["nodal_loads"][:, 0]
        denominator = float(weights.sum())
        centroid = rotate.apply(base_centroid) + shift
        centroid_movement = (
            (movement * weights[:, None]).sum(axis=0) / denominator
            if denominator
            else np.zeros(3)
        )
        offset = len(vertices)
        vertices.extend(world.tolist())
        displacements.extend(movement.tolist())
        stress.extend(answer["von_mises_pa"].tolist())
        all_quads.extend((quads + offset).tolist())
        faces.extend((quads[:, [0, 1, 2]] + offset).tolist())
        faces.extend((quads[:, [0, 2, 3]] + offset).tolist())
        element_stress.extend(answer["element_von_mises_pa"].tolist())
        fin_results.append(
            dict(
                fin_index=i,
                normal_world=normal.tolist(),
                load_centroid_world_m=centroid.tolist(),
                load_centroid_displacement_m=centroid_movement.tolist(),
                basis_world=rotation.apply(np.eye(3)).tolist(),
                rotations_local_rad=answer["dofs"][:, 1:].tolist(),
                surface_pressure_pa=applied_pressure,
                inertial_pressure_pa=inertial_pressure,
                applied_force_n=force.tolist(),
                reaction_force_n=reaction.tolist(),
                applied_moment_nm=moment.tolist(),
                reaction_moment_nm=reaction_moment.tolist(),
                fixed_node_indices=(root + offset).tolist(),
                strain_energy_j=answer["strain_energy_j"],
                force_balance_relative_error=answer["force_balance_relative_error"],
                moment_balance_relative_error=answer["moment_balance_relative_error"],
                relative_equilibrium_residual=answer["relative_equilibrium_residual"],
                gauss_top_stress_pa=answer["gauss_top_stress_pa"].tolist(),
                gauss_average_transverse_shear_pa=answer[
                    "gauss_average_transverse_shear_pa"
                ].tolist(),
            )
        )
        total_force += force
        total_reaction += reaction
        total_moment += moment
        total_reaction_moment += reaction_moment
        total_energy += answer["strain_energy_j"]
        total_work += answer["external_work_j"]
        max_residual = max(max_residual, answer["relative_equilibrium_residual"])
        peak = max(peak, float(answer["element_von_mises_pa"].max()))
    displacement = float(np.linalg.norm(displacements, axis=1).max())
    if displacement > 0.05 * min(c.span, c.root_chord):
        notes.append(
            "Displacement exceeds 5% of fin span/root chord: linear small-deflection geometry is unreliable."
        )
    if peak == 0:
        notes.append(
            "No transverse load is applied: the zero response is an unloaded solution, not a strength validation."
        )
    if composite:
        notes.append(
            "Explicit isotropic composite surrogate: no laminate strength/safety factor is calculated."
        )
    if c.mass_override is not None:
        notes.append(
            "Plate body loads use selected material density and actual planform/thickness, not the component mass override."
        )
    if peak > m.yield_strength:
        notes.append(
            "Stress exceeds supplied isotropic strength; yielding/failure is not simulated."
        )
    if progress:
        progress(1.0, "Plate FEA complete; inspect support, load and mesh convergence")
    return dict(
        component_id=c.id,
        mesh_kind="plate_midsurface",
        vertices=vertices,
        surface_faces=faces,
        plate_quads=all_quads,
        tetrahedra=[],
        displacements=displacements,
        von_mises_pa=stress,
        element_von_mises_pa=element_stress,
        fins=fin_results,
        fidelity=FIDELITY,
        backend="scipy-cpu",
        warnings=list(dict.fromkeys(notes)),
        conventions=dict(
            coordinates="World rocket X nose to tail; fin-local coordinates are axial X and outward semispan Y",
            pressure="Signed differential pressure along each exported normal_world; applied independently to each fin",
            rotation="rotations_local_rad stores beta_x/beta_y positive transverse slopes, not world Euler angles",
            stress="Gauss top-plane bending stress and average transverse shear; peak von Mises uses top/bottom bending and assumed parabolic center shear",
            display="Element peak stresses area-averaged at midsurface nodes; no material geometry is deformed or rewritten",
        ),
        summary=dict(
            nodes=len(vertices),
            elements=len(all_quads),
            fin_count=c.fin_count,
            material=m.model_dump(),
            volume_m3=area * c.thickness * c.fin_count,
            mass_kg=area * c.thickness * c.fin_count * m.density,
            mesh_size_m=size,
            thickness_m=c.thickness,
            max_displacement_m=displacement,
            max_von_mises_pa=peak,
            safety_factor=None if composite or peak == 0 else m.yield_strength / peak,
            boundary_condition="Each exposed fin root fully clamped at body surface; tabs and attachment excluded",
            load_mode="plate_" + mode,
            plate_pressure_pa=pressure if mode == "pressure" else None,
            acceleration_m_s2=acceleration.tolist(),
            applied_force_n=total_force.tolist(),
            reaction_force_n=total_reaction.tolist(),
            applied_moment_nm=total_moment.tolist(),
            reaction_moment_nm=total_reaction_moment.tolist(),
            moment_balance_reference_m=[0.0, 0.0, 0.0],
            strain_energy_j=total_energy,
            external_work_j=total_work,
            relative_equilibrium_residual=max_residual,
            force_balance_relative_error=max(
                f["force_balance_relative_error"] for f in fin_results
            ),
            moment_balance_relative_error=max(
                f["moment_balance_relative_error"] for f in fin_results
            ),
        ),
    )
