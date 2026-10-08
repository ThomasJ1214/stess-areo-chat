"""Transparent beam estimates and small-strain, isotropic tetrahedral FEA.

The finite-element implementation solves actual solid volume elements; it does
not represent a surface mesh as a solid bounding box. Boundary conditions and
loads are part of the result, because they matter as much as the stress colour.
"""
from __future__ import annotations

import math
import multiprocessing
import threading
import time
import warnings as pywarnings

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import MatrixRankWarning, spsolve
from scipy.spatial import cKDTree

from ..models import Conditions, Material, Project, active_components

_GMSH_LOCK = threading.Lock()
_FINS = {"trapezoidfinset", "freeformfinset", "ellipticalfinset", "finset", "fin"}
_TUBES = {"bodytube", "innertube", "tube", "launchlug"}


def _material(project, component):
    material = next((m for m in project.materials if m.id == component.material_id), None)
    return material or (project.materials[0] if project.materials else Material())


def _notify(progress, fraction, message):
    if progress:
        progress(float(fraction), message)


def _check_cancel(cancelled):
    if cancelled and cancelled():
        raise RuntimeError("Structural calculation cancelled.")


def tube_section(radius: float, thickness: float) -> tuple[float, float]:
    """Return annular cross-section area and diametral second moment (SI)."""
    if (not math.isfinite(radius) or not math.isfinite(thickness) or
            radius <= 0 or thickness <= 0 or thickness > radius):
        raise ValueError("Tube radius must be positive and thickness no greater than radius.")
    # Expanded differences avoid subtracting almost equal powers for thin walls.
    area = math.pi * thickness * (2 * radius - thickness)
    inertia = math.pi / 4 * thickness * (4 * radius**3 - 6 * radius**2 * thickness +
                                        4 * radius * thickness**2 - thickness**3)
    return area, inertia


def cantilever_tip_load(force: float, length: float, youngs_modulus: float,
                        second_moment: float, surface_distance: float) -> dict:
    """Euler-Bernoulli beam, fixed root and force at free tip; signs retained."""
    if (not all(math.isfinite(value) for value in
                (force, length, youngs_modulus, second_moment, surface_distance)) or
            min(length, youngs_modulus, second_moment, surface_distance) <= 0):
        raise ValueError("Beam dimensions, modulus and inertia must be positive.")
    return {"moment_nm": force * length,
            "stress_pa": abs(force * length * surface_distance / second_moment),
            "deflection_m": force * length**3 / (3 * youngs_modulus * second_moment)}


def analyze(project: Project, conditions: Conditions, configuration_id: str | None = None) -> dict:
    """Global tube beam and fin strip estimates driven by the aero solver loads.

    Tube reactions represent a tail-fixed cantilever under component point loads.
    Fin forces are shared equally between fins. Neither estimate is laminate FEA.
    """
    from .aero import analyze as analyze_aero

    aero = analyze_aero(project, conditions, configuration_id)
    parts = active_components(project, configuration_id)
    loads = {p.get("component_id", p.get("id")): p for p in aero.get("components", [])}
    result = []
    notes = ["Beam/fin estimates use tail-fixed cantilevers and small deflections; joints, local shell buckling, recovery shock, and attachment stress concentrations are excluded.",
             "Materials are homogeneous isotropic surrogates; a fiberglass/carbon laminate strength ratio is not a composite failure criterion."]
    for part in parts:
        material = _material(project, part)
        load = loads.get(part.id, {})
        force = math.hypot(float(load.get("normal_force_n", 0)), float(load.get("side_force_n", 0)))
        drag = float(load.get("drag_n", 0))
        row = {"component_id": part.id, "name": part.name, "material": material.name,
               "material_id": material.id, "load_n": force, "drag_n": drag,
               "stress_pa": 0.0, "deflection_m": 0.0, "safety_factor": None,
               "fidelity": "unsupported", "supported": False, "warnings": []}
        if part.asset_id and part.geometry_mode == "replacement":
            row["warnings"].append("Detailed replacement geometry is not reduced to a bounding-box beam; use solid FEA with suitable boundary conditions.")
            result.append(row)
            continue
        if part.kind in (_TUBES | _FINS) and part.thickness <= 0:
            row["warnings"].append("Zero-thickness OpenRocket reference surface has no supported load-bearing cross-section; specify measured wall/fin thickness before structural analysis.")
            result.append(row)
            continue
        if part.kind in _TUBES and part.thickness > part.radius:
            row["warnings"].append("Wall thickness exceeds the outer radius; this part has no valid annular section. Correct its dimensions before structural analysis.")
            result.append(row)
            continue
        if part.kind in _TUBES and part.length > 0 and part.radius > 0:
            area, inertia = tube_section(part.radius, part.thickness)
            # Evaluate a section at the aft end of this tube. All noseward
            # loads contribute to its moment in a tail-supported load path.
            moment_y = moment_z = axial = 0.0
            for other in parts:
                other_load = loads.get(other.id, {})
                cp = float(other_load.get("cp_m", other.x + other.length / 2))
                if cp <= part.x + part.length:
                    arm = max(0.0, part.x + part.length - cp)
                    moment_y += float(other_load.get("normal_force_n", 0)) * arm
                    moment_z += float(other_load.get("side_force_n", 0)) * arm
                    axial += float(other_load.get("drag_n", 0))
            moment = math.hypot(moment_y, moment_z)
            bending = moment * part.radius / inertia
            axial_stress = abs(axial / area)
            # Equivalent moment over the local segment. Its displacement is a
            # local estimate and must not be interpreted as assembled tip motion.
            displacement = moment * part.length**2 / (2 * material.youngs_modulus * inertia)
            row.update(stress_pa=bending + axial_stress, deflection_m=displacement,
                       bending_stress_pa=bending, axial_stress_pa=axial_stress,
                       moment_nm=moment, section_area_m2=area, second_moment_m4=inertia,
                       fidelity="Euler-Bernoulli tube section estimate",
                       boundary_condition="tail-supported section; noseward component loads",
                       warnings=["Deflection is the local constant-moment segment estimate, not a globally assembled displacement."])
        elif part.kind in _FINS and part.span > 0 and part.root_chord > 0:
            per_fin = force / part.fin_count
            # Constant-width equivalent strip; resultant acts at half-span.
            width = max(1e-8, (part.root_chord + part.tip_chord) / 2)
            inertia = width * part.thickness**3 / 12
            moment = per_fin * part.span / 2
            bending = moment * (part.thickness / 2) / inertia
            # Uniform-load cantilever displacement, q L^4 / (8 E I).
            displacement = per_fin * part.span**3 / (8 * material.youngs_modulus * inertia)
            shear = 1.5 * abs(per_fin) / (width * part.thickness)
            vm = math.sqrt(bending**2 + 3 * shear**2)
            row.update(stress_pa=vm, deflection_m=displacement,
                       bending_stress_pa=bending, shear_stress_pa=shear,
                       moment_nm=moment, force_per_fin_n=per_fin,
                       second_moment_m4=inertia, fidelity="uniform-load fin cantilever strip estimate",
                       boundary_condition="fixed fin root; equal load per fin",
                       warnings=["Equivalent constant-chord strip omits sweep, taper, root fillets, flutter and asymmetric individual-fin loading."])
        else:
            row["warnings"].append("No supported beam idealization for this component; use an explicit solid FEA model.")
        if row["fidelity"] != "unsupported":
            row["supported"] = True
            row["safety_factor"] = material.yield_strength / row["stress_pa"] if row["stress_pa"] > 0 else None
            if row["deflection_m"] > 0.05 * max(part.length, part.span, 1e-8):
                row["warnings"].append("Predicted deformation exceeds 5% of component scale; linear small-deflection assumptions need review.")
        result.append(row)
    return {"components": result, "fidelity": "simplified isotropic beam/fin engineering estimates",
            "backend": "CPU NumPy", "warnings": notes, "aerodynamic_fidelity": aero.get("fidelity"),
            "max_stress_pa": max((p["stress_pa"] for p in result), default=0.0)}


def flight_stress_model(project: Project, configuration_id: str | None = None,
                        conditions: Conditions | None = None) -> dict:
    """Precompute quasi-static load sensitivities without remeshing each frame.

    Coefficients retain the chosen aerodynamic incidence, Mach and temperature.
    They are pressure-scaled surrogates, not a transient structural solve.
    """
    from .aero import analyze as analyze_aero

    reference = conditions.model_copy(deep=True) if conditions else Conditions(speed=100, wind_speed=0)
    reference.speed = max(reference.speed, 20)
    if reference.mach is not None and reference.mach == 0:
        reference.mach = None
    estimates = analyze(project, reference, configuration_id)
    aero = analyze_aero(project, reference, configuration_id)
    q = max(float(aero["dynamic_pressure_pa"]), 1e-8)
    parts = active_components(project, configuration_id)
    aero_parts = {row["component_id"]: row for row in aero["components"]}
    rows = []
    for estimate in estimates["components"]:
        component = next(p for p in parts if p.id == estimate["component_id"])
        axial_sensitivity = 0.0
        if estimate["fidelity"] != "unsupported" and component.kind in _TUBES:
            forward_mass = sum(float(aero_parts.get(p.id, {}).get("mass_kg", 0))
                               for p in parts if p.x + p.length / 2 <= component.x + component.length)
            axial_sensitivity = forward_mass / estimate["section_area_m2"]
        rows.append({"component_id": component.id, "name": component.name,
                     "stress_pa_per_pa": estimate["stress_pa"] / q,
                     "deflection_m_per_pa": estimate["deflection_m"] / q,
                     "axial_stress_pa_per_m_s2": axial_sensitivity,
                     "yield_strength_pa": _material(project, component).yield_strength,
                     "supported": estimate["fidelity"] != "unsupported"})
    return {"components": rows, "reference_angle_of_attack_deg": reference.angle_of_attack,
            "reference_sideslip_deg": reference.sideslip, "reference_mach": aero["mach"],
            "reference_dynamic_pressure_pa": q,
            "fidelity": "quasi-static pressure-scaled beam/fin plus longitudinal inertial stress estimates",
            "warnings": ["Flight stresses scale reference-incidence aerodynamic loads with instantaneous dynamic pressure; no attitude-dependent stiffness, aeroelasticity or transient FEA.",
                         "Tube longitudinal acceleration loads use the forward component masses. Motor thrust transfer, recovery shock and joints require dedicated models.",
                         "Fixed reference Mach/angle coefficients are an engineering surrogate across the trajectory, especially through transonic flight."]}


def evaluate_flight_stress(model: dict, dynamic_pressure_pa: float,
                           acceleration_m_s2: float) -> dict:
    """Evaluate pressure and inertial coefficients; scalar acceleration is axial."""
    q = float(dynamic_pressure_pa)
    acceleration = abs(float(acceleration_m_s2))
    if not math.isfinite(q) or q < 0 or not math.isfinite(acceleration):
        raise ValueError("Flight stress inputs must be finite, with nonnegative dynamic pressure.")
    components = []
    for row in model["components"]:
        stress = q * row["stress_pa_per_pa"] + acceleration * row["axial_stress_pa_per_m_s2"]
        components.append({"component_id": row["component_id"], "name": row["name"],
                           "stress_pa": stress, "deflection_m": q * row["deflection_m_per_pa"],
                           "safety_factor": row["yield_strength_pa"] / stress if stress > 0 else None,
                           "supported": row["supported"]})
    return {"max_stress_pa": max((p["stress_pa"] for p in components), default=0.0),
            "components": components, "fidelity": model["fidelity"]}


def elasticity_matrix(youngs_modulus: float, poisson_ratio: float) -> np.ndarray:
    if (not math.isfinite(youngs_modulus) or not math.isfinite(poisson_ratio) or
            youngs_modulus <= 0 or not -1 < poisson_ratio < 0.5):
        raise ValueError("Elastic modulus must be positive; Poisson ratio must be between -1 and 0.5.")
    mu = youngs_modulus / (2 * (1 + poisson_ratio))
    lam = youngs_modulus * poisson_ratio / ((1 + poisson_ratio) * (1 - 2 * poisson_ratio))
    d = np.zeros((6, 6), dtype=float)
    d[:3, :3] = lam
    np.fill_diagonal(d[:3, :3], lam + 2 * mu)
    d[3:, 3:] = np.eye(3) * mu
    return d


def _element(vertices):
    # Form shape-function gradients in element-local coordinates. Inverting
    # [1, X, Y, Z] at a large imported CAD origin loses precision unnecessarily.
    edges = (vertices[1:] - vertices[0]).T
    volume = abs(np.linalg.det(edges)) / 6
    if volume <= max(float(np.ptp(vertices, axis=0).max())**3, 1e-30) * 1e-12:
        raise ValueError("FEA mesh contains a degenerate tetrahedron.")
    other_gradients = np.linalg.inv(edges)
    grad = np.vstack((-other_gradients.sum(axis=0), other_gradients))
    b = np.zeros((6, 12), dtype=float)
    for i, (gx, gy, gz) in enumerate(grad):
        col = 3 * i
        b[0, col] = gx
        b[1, col + 1] = gy
        b[2, col + 2] = gz
        b[3, col:col + 2] = [gy, gx]
        b[4, col + 1:col + 3] = [gz, gy]
        b[5, col] = gz
        b[5, col + 2] = gx
    return b, volume


def _integer_indices(values, label):
    """Reject fractional/NaN indices instead of silently truncating connectivity."""
    original = np.asarray(values)
    if original.dtype.kind not in "iu":
        try:
            numeric = np.asarray(values, dtype=float)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} must contain integer indices.") from error
        if (not np.isfinite(numeric).all() or np.any(numeric != np.floor(numeric)) or
                np.any(np.abs(numeric) >= 2**63)):
            raise ValueError(f"{label} must contain finite integer indices.")
    try:
        return np.asarray(values, dtype=np.int64)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{label} must contain valid integer indices.") from error


def solve_tetrahedral(vertices, tetrahedra, youngs_modulus, poisson_ratio, forces,
                      fixed_dofs, *, density=0.0, acceleration=None,
                      backend="cpu", progress=None, cancelled=None) -> dict:
    """Assemble/solve 4-node constant-strain tetrahedra with zero essential BCs.

    This lower-level function permits specific fixed DOFs for patch/benchmark
    tests. Public component jobs use a fully fixed root surface.
    """
    xyz = np.asarray(vertices, dtype=float)
    tets = _integer_indices(tetrahedra, "Tetrahedral connectivity")
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) < 4 or not np.isfinite(xyz).all():
        raise ValueError("FEA vertices must be finite 3D coordinates.")
    if tets.ndim != 2 or tets.shape[1] != 4 or not len(tets) or tets.min() < 0 or tets.max() >= len(xyz):
        raise ValueError("FEA requires valid 4-node tetrahedral connectivity.")
    f = np.asarray(forces, dtype=float).reshape(-1).copy()
    ndof = 3 * len(xyz)
    if len(f) != ndof or not np.isfinite(f).all():
        raise ValueError("Nodal force array must match the mesh and contain finite forces.")
    fixed = np.unique(_integer_indices(fixed_dofs, "Fixed DOFs"))
    if not len(fixed) or fixed.min() < 0 or fixed.max() >= ndof:
        raise ValueError("A valid root constraint is required for static FEA.")
    accel = np.asarray(acceleration if acceleration is not None else [0, 0, 0], dtype=float)
    if accel.shape != (3,) or not np.isfinite(accel).all() or not math.isfinite(density) or density < 0:
        raise ValueError("Acceleration must be a finite three-vector and density nonnegative.")
    d = elasticity_matrix(youngs_modulus, poisson_ratio)
    row_indices = np.empty(len(tets) * 144, dtype=np.int64)
    col_indices = np.empty_like(row_indices)
    values = np.empty(len(row_indices), dtype=float)
    volumes = np.empty(len(tets), dtype=float)
    for e, tet in enumerate(tets):
        if e % 256 == 0:
            _check_cancel(cancelled)
            _notify(progress, 0.3 + 0.3 * e / len(tets), "Assembling tetrahedral stiffness")
        b, vol = _element(xyz[tet])
        volumes[e] = vol
        dof = (tet[:, None] * 3 + np.arange(3)).ravel()
        sl = slice(e * 144, (e + 1) * 144)
        row_indices[sl] = np.repeat(dof, 12)
        col_indices[sl] = np.tile(dof, 12)
        values[sl] = (b.T @ d @ b * vol).ravel()
        f[dof] += np.tile(density * vol / 4 * accel, 4)
    stiffness = sparse.coo_matrix((values, (row_indices, col_indices)), shape=(ndof, ndof)).tocsr()
    # The COO assembly buffers are much larger than the compressed matrix.
    # Release them before factorization rather than retaining them to return.
    del row_indices, col_indices, values
    free = np.setdiff1d(np.arange(ndof), fixed)
    if not len(free):
        raise ValueError("All nodes are constrained; select a smaller root surface.")
    kff = stiffness[free][:, free]
    rhs = f[free]
    _check_cancel(cancelled)
    _notify(progress, 0.65, "Solving linear elastic equilibrium")
    displacement = np.zeros(ndof)
    executed = "CPU SciPy sparse direct"
    if backend not in {"cpu", "auto", "cuda"}:
        raise ValueError("FEA backend must be cpu, auto, or cuda.")
    gpu = None
    if backend in {"auto", "cuda"}:
        try:
            import cupy as cp
            from cupyx.scipy import sparse as gpu_sparse
            from cupyx.scipy.sparse.linalg import cg as gpu_cg
            if cp.cuda.runtime.getDeviceCount() > 0:
                gpu = (cp, gpu_sparse, gpu_cg)
        except (ImportError, OSError, RuntimeError):
            pass
        if gpu is None and backend == "cuda":
            raise RuntimeError("CUDA FEA requested, but a working NVIDIA CUDA/CuPy installation is unavailable.")
    if gpu is not None:
        cp, gpu_sparse, gpu_cg = gpu
        matrix = gpu_sparse.csr_matrix(kff)
        diagonal = matrix.diagonal()
        preconditioner = gpu_sparse.diags(1 / diagonal)
        iterations = [0]
        def iteration(_):
            iterations[0] += 1
            if iterations[0] % 20 == 0:
                _check_cancel(cancelled)
                _notify(progress, 0.7, f"CUDA conjugate gradient iteration {iterations[0]}")
        solution, info = gpu_cg(matrix, cp.asarray(rhs), tol=1e-10,
                                maxiter=max(1000, min(20000, len(free) * 2)),
                                M=preconditioner, callback=iteration)
        if info != 0:
            raise RuntimeError(f"CUDA equilibrium solver did not converge (status {info}); refine/check constraints or use CPU.")
        displacement[free] = cp.asnumpy(solution)
        executed = "NVIDIA CUDA CuPy conjugate gradient (float64)"
    else:
        with pywarnings.catch_warnings():
            pywarnings.simplefilter("error", MatrixRankWarning)
            try:
                displacement[free] = spsolve(kff, rhs)
            except MatrixRankWarning as error:
                raise ValueError("FEA stiffness is singular: each disconnected solid must have an adequate root constraint.") from error
    _check_cancel(cancelled)
    if not np.isfinite(displacement).all():
        raise ValueError("FEA has an unstable or singular constraint system.")
    residual = stiffness @ displacement - f
    relative_residual = float(np.linalg.norm(residual[free]) / max(np.linalg.norm(rhs), 1e-12))
    if relative_residual > 1e-5:
        raise RuntimeError(f"FEA equilibrium residual {relative_residual:.3g} exceeds tolerance; results withheld.")
    stress = np.empty((len(tets), 6))
    for e, tet in enumerate(tets):
        if e % 512 == 0:
            _check_cancel(cancelled)
            _notify(progress, 0.8 + 0.17 * e / len(tets), "Recovering element stresses")
        b, _ = _element(xyz[tet])
        dof = (tet[:, None] * 3 + np.arange(3)).ravel()
        stress[e] = d @ (b @ displacement[dof])
    sx, sy, sz, txy, tyz, txz = stress.T
    vm = np.sqrt(np.maximum(0, 0.5 * ((sx - sy)**2 + (sy - sz)**2 + (sz - sx)**2)
                           + 3 * (txy**2 + tyz**2 + txz**2)))
    nodal_vm = np.zeros(len(xyz))
    nodal_weight = np.zeros(len(xyz))
    for i in range(4):
        np.add.at(nodal_vm, tets[:, i], vm * volumes)
        np.add.at(nodal_weight, tets[:, i], volumes)
    nodal_vm /= np.maximum(nodal_weight, 1e-30)
    reactions = np.zeros(ndof)
    reactions[fixed] = residual[fixed]
    applied = f.reshape(-1, 3).sum(axis=0)
    reaction = reactions.reshape(-1, 3).sum(axis=0)
    balance = np.linalg.norm(applied + reaction) / max(np.linalg.norm(applied), np.linalg.norm(f), 1e-12)
    applied_moment = np.cross(xyz, f.reshape(-1, 3)).sum(axis=0)
    reaction_moment = np.cross(xyz, reactions.reshape(-1, 3)).sum(axis=0)
    # Check balance around the mesh centroid, avoiding cancellation of huge
    # origin-dependent moments when a small imported solid is far from zero.
    moment_reference = xyz.mean(axis=0)
    local_applied_moment = np.cross(xyz - moment_reference, f.reshape(-1, 3)).sum(axis=0)
    local_reaction_moment = np.cross(xyz - moment_reference, reactions.reshape(-1, 3)).sum(axis=0)
    moment_balance = np.linalg.norm(local_applied_moment + local_reaction_moment) / max(
        np.linalg.norm(local_applied_moment), np.linalg.norm(f) * float(np.ptp(xyz, axis=0).max()), 1e-12)
    strain_energy = float(displacement @ (stiffness @ displacement) / 2)
    external_work = float(displacement @ f)
    return {"displacements": displacement.reshape(-1, 3), "von_mises_pa": nodal_vm,
            "element_von_mises_pa": vm, "element_stress_pa": stress,
            "volume_m3": float(volumes.sum()), "backend": executed,
            "relative_equilibrium_residual": relative_residual,
            "force_balance_relative_error": float(balance),
            "moment_balance_relative_error": float(moment_balance),
            "moment_balance_reference_m": moment_reference,
            "strain_energy_j": strain_energy, "external_work_j": external_work,
            "applied_force_n": applied, "reaction_force_n": reaction,
            "applied_moment_nm": applied_moment, "reaction_moment_nm": reaction_moment}


def _boundary_faces(xyz, tets):
    faces = np.concatenate([tets[:, [0, 1, 2]], tets[:, [0, 1, 3]],
                            tets[:, [0, 2, 3]], tets[:, [1, 2, 3]]])
    sorted_faces = np.sort(faces, axis=1)
    _, indices, counts = np.unique(sorted_faces, axis=0, return_index=True, return_counts=True)
    boundary = faces[indices[counts == 1]].copy()
    # Outward orientation is obtained from the opposite node of its parent tet.
    owners = np.tile(np.arange(len(tets)), 4)[indices[counts == 1]]
    triangles = xyz[boundary]
    outward = triangles.mean(axis=1) - xyz[tets[owners]].mean(axis=1)
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    reverse = np.einsum("ij,ij->i", normals, outward) < 0
    boundary[reverse, 1], boundary[reverse, 2] = boundary[reverse, 2].copy(), boundary[reverse, 1].copy()
    return boundary


def _volume_mesh_inline(surface, mesh_size, max_elements, progress, cancelled):
    """Mesh each real connected watertight triangle solid using Gmsh."""
    try:
        import gmsh
    except (ImportError, OSError) as error:
        raise RuntimeError("Solid FEA requires the bundled Gmsh mesher and its system libraries.") from error
    all_vertices, all_tets = [], []
    offset = 0
    solids = surface.split(only_watertight=False)
    if any(not solid.is_watertight or not solid.is_winding_consistent or solid.volume <= 0 for solid in solids):
        raise ValueError("Every FEA solid must be a closed watertight surface with consistent outward winding and positive volume.")
    with _GMSH_LOCK:
        for number, solid in enumerate(solids):
            _check_cancel(cancelled)
            _notify(progress, 0.06 + 0.19 * number / len(solids), f"Meshing solid {number + 1}/{len(solids)}")
            # Gmsh's parametrizable-patch splitter can fail to partition a tiny
            # closed 4-triangle surface. Subdivision preserves the actual planar
            # geometry and gives its partitioner enough faces to work reliably.
            while len(solid.faces) < 64:
                solid = solid.subdivide()
            initialized = False
            try:
                # Gmsh often runs in a server worker thread. Its default SIGINT
                # handler is forbidden there, hence interruptible=False.
                gmsh.initialize(interruptible=False)
                initialized = True
                gmsh.option.setNumber("General.Terminal", 0)
                gmsh.option.setNumber("General.NumThreads", 2)
                gmsh.model.add("rocket-solid")
                # Direct transfer avoids STL float32 roundoff and temporary-file
                # visibility issues in packaged/native mesher environments.
                entity = gmsh.model.addDiscreteEntity(2)
                gmsh.model.mesh.addNodes(2, entity, np.arange(1, len(solid.vertices) + 1),
                                         np.asarray(solid.vertices).ravel())
                gmsh.model.mesh.addElementsByType(entity, 2, np.arange(1, len(solid.faces) + 1),
                                                  (np.asarray(solid.faces) + 1).ravel())
                gmsh.model.mesh.classifySurfaces(math.radians(40), True, True, math.pi)
                gmsh.model.mesh.createGeometry()
                surfaces = [tag for dim, tag in gmsh.model.getEntities(2)]
                loop = gmsh.model.geo.addSurfaceLoop(surfaces)
                gmsh.model.geo.addVolume([loop])
                gmsh.model.geo.synchronize()
                gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size * 0.5)
                gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
                gmsh.option.setNumber("Mesh.ElementOrder", 1)
                gmsh.option.setNumber("Mesh.Algorithm3D", 1)
                gmsh.model.mesh.generate(3)
                _check_cancel(cancelled)
                tags, coords, _ = gmsh.model.mesh.getNodes()
                indices = {int(tag): i for i, tag in enumerate(tags)}
                element_types, _, connectivities = gmsh.model.mesh.getElements(3)
                blocks = []
                for typ, connectivity in zip(element_types, connectivities):
                    if typ != 4:
                        raise ValueError("Gmsh returned unsupported non-linear/non-tetrahedral elements.")
                    block = np.array([indices[int(tag)] for tag in connectivity], dtype=np.int64).reshape(-1, 4)
                    blocks.append(block)
                if not blocks:
                    raise ValueError("Gmsh could not form a solid volume; check surface topology and thickness.")
                tets = np.concatenate(blocks)
                if sum(len(t) for t in all_tets) + len(tets) > max_elements:
                    raise ValueError(f"Mesh exceeds {max_elements:,} elements. Use a smaller solid region or coarser mesh; thin shells need a dedicated shell solver.")
                used = np.unique(tets)
                remap = np.full(len(tags), -1, dtype=np.int64)
                remap[used] = np.arange(len(used))
                vertices = np.asarray(coords).reshape(-1, 3)[used]
                all_vertices.append(vertices)
                all_tets.append(remap[tets] + offset)
                offset += len(vertices)
            except Exception as error:
                if isinstance(error, (ValueError, RuntimeError)):
                    raise
                raise ValueError(f"Gmsh could not mesh this actual solid geometry: {error}") from error
            finally:
                if initialized:
                    gmsh.finalize()
    return np.concatenate(all_vertices), np.concatenate(all_tets)


def _mesh_process(vertices, faces, mesh_size, max_elements, connection):
    import trimesh
    try:
        surface = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        def report(fraction, message):
            connection.send(("progress", (fraction, message)))
        result = _volume_mesh_inline(surface, mesh_size, max_elements, report, None)
        connection.send(("result", result))
    except BaseException as error:
        connection.send(("error", str(error)))
    finally:
        connection.close()


def _volume_mesh(surface, mesh_size, max_elements, progress, cancelled, timeout_seconds=120):
    """Isolate the native mesher so even a pathological CAD job can be cancelled."""
    if not math.isfinite(timeout_seconds) or not 5 <= timeout_seconds <= 900:
        raise ValueError("mesh_timeout_seconds must be between 5 and 900.")
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    worker = context.Process(target=_mesh_process,
                             args=(np.asarray(surface.vertices), np.asarray(surface.faces),
                                   mesh_size, max_elements, sending), daemon=True)
    worker.start()
    sending.close()
    started = time.monotonic()
    try:
        while True:
            _check_cancel(cancelled)
            if time.monotonic() - started > timeout_seconds:
                raise RuntimeError("Solid meshing exceeded its time budget; simplify/import a valid smaller solid or revise mesh size.")
            if receiving.poll(0.1):
                try:
                    kind, payload = receiving.recv()
                except EOFError as error:
                    raise RuntimeError("The native mesher exited unexpectedly; inspect geometry topology.") from error
                if kind == "progress":
                    _notify(progress, *payload)
                elif kind == "error":
                    raise ValueError(payload)
                elif kind == "result":
                    return payload
            elif not worker.is_alive():
                raise RuntimeError("The native mesher exited before returning a volume mesh.")
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=2)
            if worker.is_alive():
                worker.kill()
        worker.join(timeout=2)
        receiving.close()


def _transfer_cfd_pressure(xyz, faces, options, cancelled=None):
    """Normal-compatible nearest-wall transfer of absolute CFD gauge pressure."""
    rows = options.get("cfd_surface", [])
    if not rows:
        raise ValueError("CFD pressure loading requires surface samples from a completed CFD job.")
    if not options.get("cfd_converged", False):
        raise ValueError("CFD pressure loading requires a job that passed its configured pressure-force convergence check.")
    try:
        positions = np.asarray([r["position"] for r in rows], dtype=float)
        pressures = np.asarray([r["pressure_pa"] for r in rows], dtype=float)
        normals = np.asarray([r["normal"] for r in rows], dtype=float)
        ambient = float(options["cfd_freestream_pressure_pa"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("CFD transfer requires finite position, pressure_pa, outward normal and freestream pressure metadata.") from error
    if (positions.shape != (len(rows), 3) or normals.shape != positions.shape or
            not np.isfinite(positions).all() or not np.isfinite(normals).all() or
            not np.isfinite(pressures).all() or np.any(pressures <= 0) or not math.isfinite(ambient) or ambient <= 0):
        raise ValueError("Invalid CFD pressure sample coordinates, normals, pressures or ambient pressure.")
    norm = np.linalg.norm(normals, axis=1)
    if np.any(norm < 1e-12):
        raise ValueError("CFD surface samples require nonzero outward normals.")
    normals = normals / norm[:, None]
    spacing = np.asarray(options.get("cfd_cell_spacing_m", []), dtype=float)
    valid_spacing = spacing.shape == (3,) and np.isfinite(spacing).all() and np.all(spacing > 0)
    default_distance = 1.5 * float(np.linalg.norm(spacing)) if valid_spacing else None
    explicit_distance = options.get("cfd_max_transfer_distance_m")
    max_distance = explicit_distance if explicit_distance is not None else default_distance
    if max_distance is None or not math.isfinite(float(max_distance)) or float(max_distance) <= 0:
        raise ValueError("CFD transfer needs positive cell spacing metadata or cfd_max_transfer_distance_m.")
    max_distance = float(max_distance)
    triangle = xyz[faces]
    cross = np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2
    face_normals = cross / np.maximum(2 * area[:, None], 1e-30)
    centroids = triangle.mean(axis=1)
    count = min(16, len(rows))
    # Slender-rocket grids have coarse axial and fine radial spacing. A sphere
    # sized from their diagonal can wrongly transfer the opposite exterior wall
    # onto an inner bore face. Use cell-normalized ellipsoidal neighborhoods.
    metric_scale = spacing if explicit_distance is None and valid_spacing else np.ones(3)
    tree = cKDTree(positions / metric_scale)
    metric_centroids = centroids / metric_scale
    metric_distance, nearest = tree.query(metric_centroids, k=count)
    if count == 1:
        metric_distance, nearest = metric_distance[:, None], nearest[:, None]
    distance = np.linalg.norm(positions[nearest] - centroids[:, None], axis=2)
    allowed = metric_distance <= (1.5 if explicit_distance is None else max_distance)
    compatible = (np.einsum("ijk,ik->ij", normals[nearest], face_normals) >= 0.25) & allowed
    candidates = np.where(compatible, distance, np.inf)
    chosen = np.argmin(candidates, axis=1)
    chosen_distances = candidates[np.arange(len(faces)), chosen]
    mapped = np.isfinite(chosen_distances)
    selected = nearest[np.arange(len(faces)), chosen]
    gauge = np.where(mapped, pressures[selected] - ambient, 0.0)
    # Thin double-sided surfaces can have more than 16 nearby samples facing
    # the wrong way. Search the full allowed neighborhood before declaring such
    # a face unmapped, retaining the same geometric cutoff and normal criterion.
    fallback_faces = np.flatnonzero(~mapped) if count < len(rows) else np.array([], dtype=int)
    cutoff = 1.5 if explicit_distance is None else max_distance
    for fallback_index, face_index in enumerate(fallback_faces):
        if fallback_index % 256 == 0:
            _check_cancel(cancelled)
        neighborhood = np.asarray(tree.query_ball_point(metric_centroids[face_index], cutoff), dtype=int)
        if not len(neighborhood):
            continue
        compatible_nodes = neighborhood[normals[neighborhood] @ face_normals[face_index] >= 0.25]
        if not len(compatible_nodes):
            continue
        physical_distance = np.linalg.norm(positions[compatible_nodes] - centroids[face_index], axis=1)
        best = int(np.argmin(physical_distance))
        chosen_distances[face_index] = physical_distance[best]
        selected[face_index] = compatible_nodes[best]
        mapped[face_index] = True
        gauge[face_index] = pressures[selected[face_index]] - ambient
    result = {"mapped_faces": int(mapped.sum()), "total_faces": len(faces),
              "fallback_search_faces": len(fallback_faces),
              "mapped_surface_area_m2": float(area[mapped].sum()),
              "total_surface_area_m2": float(area.sum()),
              "mapped_surface_area_fraction": float(area[mapped].sum() / area.sum()),
              "max_allowed_distance_m": max_distance,
              "distance_metric": "cell-spacing-scaled ellipsoid" if explicit_distance is None else "explicit Euclidean cutoff",
              "max_cell_scaled_distance": 1.5 if explicit_distance is None else None,
              "mean_transfer_distance_m": float(np.mean(chosen_distances[mapped])) if mapped.any() else None,
              "max_transfer_distance_m": float(np.max(chosen_distances[mapped])) if mapped.any() else None,
              "freestream_pressure_pa": ambient,
              "cfd_fidelity": options.get("cfd_fidelity", "experimental CFD"),
              "cfd_warnings": list(options.get("cfd_warnings", []))}
    if not mapped.any():
        raise ValueError("No CFD wall samples match the selected FEA component geometry/normals within the transfer distance.")
    return gauge, result


def solve_fea(project: Project, component_id: str, conditions: Conditions, options: dict,
              progress=None, cancelled=None) -> dict:
    """Real linear-static isotropic solid FEA of a selected actual component."""
    from ..geometry import component_mesh
    from .aero import atmosphere, freestream

    options = options or {}
    component = next((p for p in project.components if p.id == component_id), None)
    if component is None:
        raise ValueError("Select an existing component for FEA.")
    material = _material(project, component)
    _check_cancel(cancelled)
    _notify(progress, 0.01, "Inspecting actual solid geometry and material")
    # Validate declared loads/support/backend before a potentially expensive
    # native mesh operation, so incorrect inputs fail promptly and predictably.
    clamp_type = options.get("clamp_type", "plane")
    if clamp_type not in {"plane", "radial_root"}:
        raise ValueError("clamp_type must be plane or radial_root.")
    if clamp_type == "radial_root" and (component.kind not in _FINS or
            (component.asset_id and component.geometry_mode == "replacement")):
        raise ValueError("radial_root is defined only for original procedural finsets; choose a plane for imported CAD.")
    axis_name = options.get("clamp_axis", "x")
    if axis_name not in {"x", "y", "z"}:
        raise ValueError("clamp_axis must be x, y or z.")
    axis = {"x": 0, "y": 1, "z": 2}[axis_name]
    side = options.get("clamp_side", "min")
    if side not in {"min", "max"}:
        raise ValueError("clamp_side must be min or max.")
    mode = options.get("load_mode", "aero_pressure")
    if mode not in {"aero_pressure", "uniform_pressure", "traction", "cfd_pressure"}:
        raise ValueError("load_mode must be aero_pressure, uniform_pressure, traction or cfd_pressure.")
    backend = options.get("backend", "auto")
    if backend not in {"cpu", "auto", "cuda"}:
        raise ValueError("FEA backend must be cpu, auto, or cuda.")
    air = atmosphere(conditions.altitude, conditions.temperature_delta)
    flow_vector = freestream(conditions)
    speed = float(np.linalg.norm(flow_vector))
    dynamic_pressure = 0.5 * float(air["density_kg_m3"]) * speed**2
    load_pressure = float(options.get("load_pressure_pa", dynamic_pressure))
    if not math.isfinite(load_pressure) or load_pressure < 0:
        raise ValueError("load_pressure_pa must be finite and nonnegative.")
    traction = np.asarray(options.get("traction_pa", [load_pressure, 0, 0]), dtype=float)
    if traction.shape != (3,) or not np.isfinite(traction).all():
        raise ValueError("traction_pa must be a finite [x,y,z] vector.")
    acceleration = np.asarray(options.get("acceleration_m_s2", [0, 0, 0]), dtype=float)
    if acceleration.shape != (3,) or not np.isfinite(acceleration).all():
        raise ValueError("acceleration_m_s2 must be a finite [x,y,z] vector.")
    if component.geometry_mode == "replacement":
        asset = next((asset for asset in project.assets if asset.id == component.asset_id), None)
        if asset is not None and not asset.watertight:
            raise ValueError("Solid FEA requires a replacement asset with verified enclosed material volume. Repair open/overlapping CAD geometry or provide a valid unioned solid before meshing.")
    surface = component_mesh(project, component)
    if (not len(surface.faces) or not surface.is_watertight or not surface.is_winding_consistent or
            not math.isfinite(float(surface.volume)) or surface.volume <= 0 or surface.metadata.get("volume_ambiguous")):
        raise ValueError("Solid FEA requires watertight outward-oriented solid geometry; open STL surfaces and zero-thickness shells are unsupported.")
    scale = float(surface.extents.max())
    default_size = scale / 12
    if not (component.asset_id and component.geometry_mode == "replacement"):
        default_size = min(default_size, component.thickness / 2)
    mesh_size = float(options.get("mesh_size", default_size))
    max_elements = int(options.get("max_elements", 100000))
    if not math.isfinite(mesh_size) or mesh_size <= 0 or not 20 <= max_elements <= 300000:
        raise ValueError("mesh_size must be positive; max_elements must be between 20 and 300000.")
    notes = ["Linear static 4-node tetrahedral FEA: homogeneous isotropic material, small strain/displacement; no plasticity, shell buckling, contact, laminate failure, flutter or transient structural response.",
             "Verify the root clamp and load directions. CAD geometry alone does not define supports, joints, or reliable material properties.",
             "Element stresses are constant per tetrahedron. Displayed nodal von Mises values are volume-weighted averages, not additional solved quantities.",
             "A single mesh is not a convergence study; repeat with finer meshes and compare displacement/strain energy away from clamp singularities."]
    if material.poisson_ratio > 0.45:
        notes.append("Near-incompressible material: linear tetrahedra can exhibit volumetric locking; use a mixed/high-order solver for reliable results.")
    if not (component.asset_id and component.geometry_mode == "replacement") and mesh_size > component.thickness / 2 * 1.001:
        raise ValueError("Solid bending FEA requires mesh_size <= thickness/2 for this thin component; a coarse volume mesh would give misleading stiffness. Select a local region or shell solver for large thin structures.")
    # Budget check prevents multi-million-cell thin-tube jobs before meshing.
    minimum_budget_size = (float(surface.volume) * 6 / (max_elements * 4))**(1 / 3)
    if mesh_size < minimum_budget_size:
        raise ValueError(f"Estimated solid mesh is too large for the {max_elements:,}-element budget. Analyze a local region; a thin-shell solver is required for a whole thin rocket body.")
    tolerance = float(options.get("clamp_tolerance", max(scale * 1e-7, mesh_size * 0.08)))
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("clamp_tolerance must be positive and finite.")
    xyz, tets = _volume_mesh(surface, mesh_size, max_elements, progress, cancelled,
                              float(options.get("mesh_timeout_seconds", 120)))
    _check_cancel(cancelled)
    faces = _boundary_faces(xyz, tets)
    _check_cancel(cancelled)
    boundary_nodes = np.unique(faces)
    links = np.vstack([tets[:, [0, 1]], tets[:, [0, 2]], tets[:, [0, 3]]])
    graph = sparse.coo_matrix((np.ones(len(links)), (links[:, 0], links[:, 1])),
                              shape=(len(xyz), len(xyz))).tocsr()
    solid_count, groups = sparse.csgraph.connected_components(graph, directed=False)
    if clamp_type == "radial_root":
        # A finite-thickness root is a plane tangent to the body, not a circle:
        # sqrt(Y²+Z²)<=R would leave extrusion edges/canted root points free.
        rotation = float(component.metadata.get("angleoffset", component.metadata.get("rotation", 0)))
        angles = np.radians(rotation + np.arange(component.fin_count) * 360 / component.fin_count)
        root_directions = np.column_stack((np.cos(angles), np.sin(angles)))
        radial_offset = float(component.metadata.get("radialposition", 0))
        radial_angle = math.radians(float(component.metadata.get("radialdirection", 0)))
        local_yz = xyz[:, 1:] - radial_offset * np.array([math.cos(radial_angle), math.sin(radial_angle)])
        clamped_groups = []
        for group in range(solid_count):
            nodes = boundary_nodes[groups[boundary_nodes] == group]
            direction = root_directions[np.argmax(root_directions @ local_yz[nodes].mean(axis=0))]
            projected = local_yz[nodes] @ direction
            clamped_groups.append(nodes[projected <= component.radius + tolerance])
        fixed_nodes = np.concatenate(clamped_groups)
        clamp_description = f"Procedural fin root planes at radius {component.radius:g} m (interior tabs included); all displacement DOFs fixed"
    elif clamp_type == "plane":
        position = float(xyz[:, axis].min() if side == "min" else xyz[:, axis].max())
        fixed_nodes = boundary_nodes[np.abs(xyz[boundary_nodes, axis] - position) <= tolerance]
        clamp_description = f"{side}-{axis_name} boundary at {position:g} m; all displacement DOFs fixed"
    if len(fixed_nodes) < 3:
        raise ValueError("Root selection contains fewer than three nodes. Choose another clamp plane or a justified tolerance.")
    fixed_dofs = (fixed_nodes[:, None] * 3 + np.arange(3)).ravel()
    for group in range(solid_count):
        clamped = fixed_nodes[groups[fixed_nodes] == group]
        if len(clamped) < 3 or np.linalg.matrix_rank(xyz[clamped] - xyz[clamped].mean(axis=0),
                                                   tol=scale * 1e-10) < 2:
            raise ValueError("Each disconnected solid needs at least three noncollinear clamped nodes; choose radial fin roots or a suitable support plane. Contact/bonding between solids is not inferred.")
    forces = np.zeros_like(xyz)
    flow = flow_vector / speed if speed > 0 else np.array([1.0, 0.0, 0.0])
    face_pressures = []
    cfd_pressures, transfer_summary = (None, None)
    if mode == "cfd_pressure":
        cfd_pressures, transfer_summary = _transfer_cfd_pressure(xyz, faces, options, cancelled)
        notes.append("CFD pressure is mapped from nearby normal-compatible voxel wall samples as p minus ambient. Unmapped faces receive zero gauge pressure; inspect coverage and transfer distances, especially for hollow interior surfaces.")
        notes.append("This is one-way loading from experimental compressible inviscid Euler CFD; it inherits grid/convergence limitations and excludes viscous traction or deformation-to-flow feedback.")
        notes.append("Nearest pressure transfer is not force-conservative; compare integrated mapped forces and repeat both flow-grid and structural-mesh refinement.")
        notes.extend(transfer_summary["cfd_warnings"])
    free_end_position = xyz[:, axis].max() if side == "min" else xyz[:, axis].min()
    traction_faces = 0
    for face_index, face in enumerate(faces):
        if face_index % 512 == 0:
            _check_cancel(cancelled)
        cross = np.cross(xyz[face[1]] - xyz[face[0]], xyz[face[2]] - xyz[face[0]])
        twice_area = float(np.linalg.norm(cross))
        if twice_area == 0:
            continue
        normal = cross / twice_area
        area = twice_area / 2
        if mode == "aero_pressure":
            # Newtonian-style projected windward loading is explicit, and is not
            # substituted for CFD or claimed valid for subsonic/transonic flow.
            pressure = load_pressure * 2 * max(0, -float(np.dot(normal, flow)))**2
            force = -normal * pressure * area
        elif mode == "uniform_pressure":
            pressure = load_pressure
            force = -normal * pressure * area
        elif mode == "traction":
            on_end = np.all(np.abs(xyz[face, axis] - free_end_position) <= tolerance)
            traction_faces += int(on_end)
            pressure = 0.0
            force = traction * area if on_end else np.zeros(3)
        elif mode == "cfd_pressure":
            pressure = float(cfd_pressures[face_index])
            force = -normal * pressure * area
        else:
            raise ValueError("load_mode must be aero_pressure, uniform_pressure, traction or cfd_pressure.")
        forces[face] += force / 3
        face_pressures.append(float(pressure))
    if mode == "traction" and np.any(traction) and not traction_faces:
        raise ValueError("No boundary faces lie on the selected opposite end plane for prescribed traction. Choose another clamp axis/side or a justified tolerance.")
    surface_force = forces.sum(axis=0)
    if not np.any(forces) and not np.any(acceleration):
        notes.append("No nonzero structural load was applied. Zero displacement/stress is an unloaded solution, not a demonstrated strength margin.")
    if mode == "aero_pressure":
        notes.append("FEA aerodynamic load is a windward projected Newtonian-style pressure surrogate (Cp=2 cos² incidence), not CFD or a validated Mach-2 pressure solution; import/derive reliable loads for design decisions.")
        if conditions.turbulence:
            notes.append("The static pressure surrogate uses the mean freestream including lateral wind; turbulent/time-varying loads are not resolved.")
    elif mode == "uniform_pressure":
        notes.append("Uniform pressure acts on every closed boundary face, including hollow-tube interior surfaces. It is not a differential internal/external vessel-pressure model.")
    solved = solve_tetrahedral(xyz, tets, material.youngs_modulus, material.poisson_ratio,
                              forces, fixed_dofs, density=material.density,
                              acceleration=acceleration, backend=backend,
                              progress=progress, cancelled=cancelled)
    displacement = solved["displacements"]
    maximum_displacement = float(np.linalg.norm(displacement, axis=1).max())
    maximum_stress = float(solved["element_von_mises_pa"].max())
    source_volume = float(surface.volume)
    volume_difference = abs(solved["volume_m3"] - source_volume) / source_volume
    if volume_difference > .01:
        notes.append(f"Tetrahedral material volume differs from the imported/procedural triangle surface by {volume_difference:.1%}. Inspect surface remeshing and demonstrate convergence before using this result.")
    if maximum_displacement > scale * 0.05:
        notes.append("Maximum displacement exceeds 5% of component scale; linear geometry is not reliable at this load.")
    if maximum_stress > material.yield_strength:
        notes.append("Predicted isotropic von Mises stress exceeds the supplied material strength. Plasticity/failure is not simulated.")
    if component.mass_override is not None:
        notes.append("FEA mass and body acceleration loads use the selected material density and actual tetrahedral volume. A component mass override is not distributed into this elastic solid model.")
    summary = {"nodes": len(xyz), "elements": len(tets), "volume_m3": solved["volume_m3"],
               "source_surface_volume_m3": source_volume,
               "relative_volume_difference": volume_difference,
               "mass_kg": solved["volume_m3"] * material.density,
               "max_displacement_m": maximum_displacement, "max_von_mises_pa": maximum_stress,
               "safety_factor": material.yield_strength / maximum_stress if maximum_stress > 0 else None,
               "material": material.model_dump(), "boundary_condition": clamp_description,
               "fixed_nodes": len(fixed_nodes), "mesh_size_m": mesh_size,
               "clamp_tolerance_m": tolerance,
               "load_mode": mode, "load_pressure_pa": load_pressure if mode != "cfd_pressure" else None,
               "freestream_velocity_m_s": flow_vector.tolist(), "dynamic_pressure_pa": dynamic_pressure,
               "traction_pa": traction.tolist() if mode == "traction" else None,
               "acceleration_m_s2": acceleration.tolist(),
               "surface_force_n": surface_force.tolist(),
               "body_force_n": (solved["applied_force_n"] - surface_force).tolist(),
               "traction_faces": traction_faces if mode == "traction" else None,
               "strain_energy_j": solved["strain_energy_j"],
               "external_work_j": solved["external_work_j"],
               "moment_balance_reference_m": solved["moment_balance_reference_m"].tolist(),
               "applied_force_n": solved["applied_force_n"].tolist(),
               "reaction_force_n": solved["reaction_force_n"].tolist(),
               "applied_moment_nm": solved["applied_moment_nm"].tolist(),
               "reaction_moment_nm": solved["reaction_moment_nm"].tolist(),
               "relative_equilibrium_residual": solved["relative_equilibrium_residual"],
               "force_balance_relative_error": solved["force_balance_relative_error"],
               "moment_balance_relative_error": solved["moment_balance_relative_error"]}
    if transfer_summary is not None:
        summary["cfd_pressure_transfer"] = transfer_summary
    _notify(progress, 1.0, "FEA complete; inspect supports, loads and convergence")
    return {"component_id": component.id, "vertices": xyz.tolist(), "tetrahedra": tets.tolist(),
            "surface_faces": faces.tolist(), "displacements": displacement.tolist(),
            "von_mises_pa": solved["von_mises_pa"].tolist(),
            "element_von_mises_pa": solved["element_von_mises_pa"].tolist(),
            "surface_pressure_pa": face_pressures, "summary": summary,
            "fidelity": "linear-static isotropic solid FEA; actual geometry, 4-node tetrahedra",
            "warnings": notes, "backend": solved["backend"]}
