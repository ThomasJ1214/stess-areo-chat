"""Closed-form and patch benchmarks for actual engineering calculations."""
import math

import numpy as np
import pytest

from rocket_workbench.solvers.structure import (
    _boundary_faces,
    cantilever_tip_load,
    elasticity_matrix,
    solve_tetrahedral,
    tube_section,
)


def box_tetrahedra(length=1.0, width=0.1, height=0.1):
    vertices = np.array([[0, 0, 0], [length, 0, 0], [length, width, 0], [0, width, 0],
                         [0, 0, height], [length, 0, height], [length, width, height], [0, width, height]], float)
    tetrahedra = np.array([[0, 1, 2, 6], [0, 2, 3, 6], [0, 3, 7, 6],
                          [0, 7, 4, 6], [0, 4, 5, 6], [0, 5, 1, 6]])
    return vertices, tetrahedra


def test_tube_section_and_closed_form_cantilever():
    area, inertia = tube_section(0.05, 0.002)
    assert area == pytest.approx(math.pi * (0.05**2 - 0.048**2))
    assert inertia == pytest.approx(math.pi / 4 * (0.05**4 - 0.048**4))
    result = cantilever_tip_load(100, 1.2, 25e9, inertia, 0.05)
    assert result["moment_nm"] == 120
    assert result["stress_pa"] == pytest.approx(120 * 0.05 / inertia)
    assert result["deflection_m"] == pytest.approx(100 * 1.2**3 / (3 * 25e9 * inertia))


def test_tetrahedral_uniaxial_patch_matches_exact_elasticity():
    """Uniform traction and minimally constrained Poisson contraction: exact affine field."""
    vertices, tetrahedra = box_tetrahedra()
    youngs_modulus, poisson_ratio, traction = 70e9, 0.3, 1e6
    forces = np.zeros_like(vertices)
    boundary = _boundary_faces(vertices, tetrahedra)
    for face in boundary:
        if np.all(vertices[face, 0] == 1):
            area = np.linalg.norm(np.cross(vertices[face[1]] - vertices[face[0]],
                                           vertices[face[2]] - vertices[face[0]])) / 2
            forces[face, 0] += traction * area / 3
    # Fix x=0 normal displacements, pin origin y,z and pin y-axis node z.
    # This eliminates rigid motion while allowing exact Poisson contraction.
    fixed = [3 * i for i in [0, 3, 4, 7]] + [1, 2, 3 * 3 + 2]
    result = solve_tetrahedral(vertices, tetrahedra, youngs_modulus, poisson_ratio, forces, fixed)
    axial_strain = traction / youngs_modulus
    expected = vertices * [axial_strain, -poisson_ratio * axial_strain, -poisson_ratio * axial_strain]
    assert np.allclose(result["displacements"], expected, rtol=1e-9, atol=1e-13)
    assert result["element_stress_pa"][:, 0] == pytest.approx(np.full(6, traction), rel=1e-9)
    assert result["element_von_mises_pa"] == pytest.approx(np.full(6, traction), rel=1e-9)
    assert result["volume_m3"] == pytest.approx(0.01)
    assert result["applied_force_n"] == pytest.approx([10000, 0, 0])
    assert result["reaction_force_n"] == pytest.approx([-10000, 0, 0], abs=1e-6)
    assert result["relative_equilibrium_residual"] < 1e-9
    assert result["force_balance_relative_error"] < 1e-9
    assert result["moment_balance_relative_error"] < 1e-9


def test_body_force_is_distributed_by_real_element_volume():
    vertices, tetrahedra = box_tetrahedra()
    root_nodes = np.flatnonzero(vertices[:, 0] == 0)
    fixed = (root_nodes[:, None] * 3 + np.arange(3)).ravel()
    result = solve_tetrahedral(vertices, tetrahedra, 70e9, 0.3, np.zeros_like(vertices),
                              fixed, density=2700, acceleration=[30, 0, 0])
    assert result["applied_force_n"] == pytest.approx([2700 * 0.01 * 30, 0, 0])
    assert result["reaction_force_n"] == pytest.approx([-810, 0, 0], abs=1e-6)
    assert result["displacements"][:, 0].max() > 0


def test_invalid_mesh_constraints_and_cancel_are_rejected():
    vertices, tetrahedra = box_tetrahedra()
    with pytest.raises(ValueError, match="constraint"):
        solve_tetrahedral(vertices, tetrahedra, 1e9, 0.3, np.zeros_like(vertices), [])
    with pytest.raises(ValueError, match="degenerate"):
        solve_tetrahedral(vertices, [[0, 0, 1, 2]], 1e9, 0.3, np.zeros_like(vertices), [0, 1, 2])
    with pytest.raises(RuntimeError, match="cancelled"):
        solve_tetrahedral(vertices, tetrahedra, 1e9, 0.3, np.zeros_like(vertices), [0, 1, 2],
                          cancelled=lambda: True)


def test_elasticity_has_positive_energy_and_expected_shear():
    d = elasticity_matrix(70e9, 0.3)
    assert np.linalg.eigvalsh(d).min() > 0
    assert d[3, 3] == pytest.approx(70e9 / 2.6)
    with pytest.raises(ValueError):
        elasticity_matrix(70e9, 0.5)


def test_gmsh_meshes_actual_closed_box_not_bounding_box():
    pytest.importorskip("trimesh")
    try:
        import gmsh  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("Gmsh system library unavailable")
    import trimesh
    from rocket_workbench.solvers.structure import _volume_mesh

    # Non-cubical tetrahedral shape volume differs from its bounding box by 6x.
    tetra = trimesh.Trimesh(vertices=[[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0], [0, 0, 0.1]],
                            faces=[[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
    vertices, tets = _volume_mesh(tetra, 0.025, 10000, None, None)
    volumes = [abs(np.linalg.det(np.column_stack((np.ones(4), vertices[tet])))) / 6 for tet in tets]
    assert sum(volumes) == pytest.approx(tetra.volume, rel=1e-5)
    assert np.all(vertices.sum(axis=1) <= 0.100001)
    assert len(tets) > 1


def test_full_component_fea_under_prescribed_end_traction():
    import trimesh
    from rocket_workbench.models import Component, Conditions, GeometryAsset, Material, Project
    from rocket_workbench.solvers.structure import solve_fea

    mesh = trimesh.creation.box(extents=[0.1, 0.01, 0.01])
    material = Material(id="al", name="Aluminum", density=2700, youngs_modulus=70e9,
                        poisson_ratio=0.3, yield_strength=250e6)
    asset = GeometryAsset(id="bar", name="Actual bar", format="stl", vertices=mesh.vertices.tolist(),
                          faces=mesh.faces.tolist(), watertight=True, volume=mesh.volume)
    component = Component(id="bar", name="Test bar", kind="masscomponent", material_id="al",
                          asset_id="bar", geometry_mode="replacement")
    project = Project(components=[component], assets=[asset], materials=[material])
    result = solve_fea(project, component.id, Conditions(speed=0),
                       {"mesh_size": 0.003, "load_mode": "traction", "traction_pa": [1e6, 0, 0],
                        "backend": "cpu", "max_elements": 10000})
    assert result["summary"]["applied_force_n"] == pytest.approx([100, 0, 0], rel=1e-5, abs=1e-9)
    assert result["summary"]["volume_m3"] == pytest.approx(mesh.volume, rel=1e-5)
    assert result["summary"]["max_displacement_m"] == pytest.approx(1e6 / 70e9 * 0.1, rel=0.06)
    assert result["summary"]["relative_equilibrium_residual"] < 1e-8
    assert len(result["von_mises_pa"]) == len(result["vertices"])
    assert len(result["surface_pressure_pa"]) == len(result["surface_faces"])


def test_flight_stress_specific_acceleration_and_pressure_scaling():
    from rocket_workbench.models import Component, Conditions, Material, Project
    from rocket_workbench.solvers.structure import evaluate_flight_stress, flight_stress_model

    part = Component(id="tube", kind="bodytube", x=0.2, length=1, radius=0.05, thickness=0.002,
                     material_id="al")
    nose = Component(id="nose", kind="nosecone", length=0.2, radius=0.05, thickness=0.002,
                     material_id="al")
    project = Project(components=[nose, part], materials=[Material(id="al")])
    model = flight_stress_model(project, conditions=Conditions(speed=100, wind_speed=0))
    unloaded = evaluate_flight_stress(model, 0, 0)
    loaded = evaluate_flight_stress(model, 1000, 0)
    twice = evaluate_flight_stress(model, 2000, 0)
    accelerated = evaluate_flight_stress(model, 0, 10)
    assert unloaded["max_stress_pa"] == 0
    assert loaded["max_stress_pa"] > 0
    assert twice["max_stress_pa"] == pytest.approx(2 * loaded["max_stress_pa"])
    assert accelerated["max_stress_pa"] > 0


def test_cfd_wall_pressure_transfer_uses_gauge_and_preserves_suction():
    from rocket_workbench.solvers.structure import _transfer_cfd_pressure
    vertices, tetrahedra = box_tetrahedra()
    faces = _boundary_faces(vertices, tetrahedra)
    rows, expected = [], []
    for face in faces:
        a, b, c = vertices[face]
        normal = np.cross(b - a, c - a)
        normal /= np.linalg.norm(normal)
        gauge = 1000 if normal[0] > 0.9 else (-250 if normal[0] < -0.9 else 0)
        rows.append({"position": vertices[face].mean(axis=0).tolist(),
                     "normal": normal.tolist(), "pressure_pa": 100000 + gauge})
        expected.append(gauge)
    options = {"cfd_surface": rows, "cfd_converged": True, "cfd_freestream_pressure_pa": 100000,
               "cfd_cell_spacing_m": [0.01, 0.01, 0.01]}
    pressure, transfer = _transfer_cfd_pressure(vertices, faces, options)
    assert pressure == pytest.approx(expected)
    assert pressure.min() == -250
    assert transfer["mapped_surface_area_fraction"] == pytest.approx(1)
    assert transfer["max_transfer_distance_m"] == pytest.approx(0)
    with pytest.raises(ValueError, match="convergence"):
        _transfer_cfd_pressure(vertices, faces, {**options, "cfd_converged": False})
    with pytest.raises(ValueError, match="No CFD wall samples"):
        far_rows = [{**r, "position": [p + 100 for p in r["position"]]} for r in rows]
        _transfer_cfd_pressure(vertices, faces, {**options, "cfd_surface": far_rows})


def test_native_mesher_cancellation_stops_worker():
    import trimesh
    from rocket_workbench.solvers.structure import _volume_mesh
    with pytest.raises(RuntimeError, match="cancelled"):
        _volume_mesh(trimesh.creation.box(extents=[0.1, 0.1, 0.1]), 0.01, 10000,
                     None, lambda: True)


def test_static_fea_aero_pressure_uses_shared_crosswind_freestream():
    import trimesh
    from rocket_workbench.models import Component, Conditions, GeometryAsset, Material, Project
    from rocket_workbench.solvers.aero import atmosphere
    from rocket_workbench.solvers.structure import solve_fea

    mesh = trimesh.creation.box(extents=[0.1, 0.1, 0.1])
    asset = GeometryAsset(id="cube", name="Wind box", format="stl", vertices=mesh.vertices.tolist(),
                          faces=mesh.faces.tolist(), watertight=True, volume=mesh.volume)
    component = Component(id="cube", kind="masscomponent", asset_id="cube", geometry_mode="replacement")
    model = Project(components=[component], assets=[asset], materials=[Material()])
    conditions = Conditions(speed=0, wind_speed=20, wind_direction=0)
    result = solve_fea(model, component.id, conditions,
                       {"mesh_size": 0.03, "load_mode": "aero_pressure", "backend": "cpu"})
    q = 0.5 * atmosphere(0)["density_kg_m3"] * 20**2
    assert result["summary"]["dynamic_pressure_pa"] == pytest.approx(q)
    assert result["summary"]["freestream_velocity_m_s"] == pytest.approx([0, 20, 0])
    # A cube face perpendicular to the crosswind gets the declared Cp=2.
    assert result["summary"]["applied_force_n"] == pytest.approx([0, 2 * q * 0.01, 0], abs=1e-8)


def test_radial_fin_root_clamp_covers_thickness_edges_and_cant():
    from rocket_workbench.models import Component, Conditions, Project
    from rocket_workbench.solvers.structure import solve_fea

    part = Component(id="fins", kind="trapezoidfinset", x=0.1, length=0.03, radius=0.02,
                     span=0.03, root_chord=0.03, tip_chord=0.015, sweep=0.005,
                     thickness=0.01, fin_count=3, metadata={"cant": 15, "angleoffset": 20})
    model = Project(components=[part])
    result = solve_fea(model, part.id, Conditions(speed=100, wind_speed=0),
                       {"mesh_size": 0.004, "clamp_type": "radial_root", "backend": "cpu"})
    vertices = np.asarray(result["vertices"])
    displacement = np.asarray(result["displacements"])
    directions = np.array([[math.cos(math.radians(20 + i * 120)),
                            math.sin(math.radians(20 + i * 120))] for i in range(3)])
    root_mask = np.any(np.abs(vertices[:, 1:] @ directions.T - part.radius) < 1e-9, axis=1)
    assert root_mask.sum() >= 12
    assert np.linalg.norm(displacement[root_mask], axis=1).max() == 0
    # Confirm this includes finite-thickness root points outside the body's
    # radial circle, the exact case the old radius-only selection missed.
    assert np.any(np.linalg.norm(vertices[root_mask, 1:], axis=1) > part.radius + 0.0005)
    assert np.linalg.norm(displacement[~root_mask], axis=1).max() > 0


def test_cfd_pressure_transfer_rejects_opposite_outer_wall_across_bore():
    from rocket_workbench.solvers.structure import _transfer_cfd_pressure
    # Inner bore's +Y-side wall normal points -Y, like the opposite outer wall.
    # Coarse axial spacing must not permit that pressure to cross 117 mm in Y.
    vertices = np.array([[0, 0.057, 0], [0.01, 0.057, 0], [0, 0.057, 0.01]])
    rows = [{"position": [1 / 300, -0.060, 1 / 300], "normal": [0, -1, 0],
             "pressure_pa": 102000}]
    with pytest.raises(ValueError, match="No CFD wall samples"):
        _transfer_cfd_pressure(vertices, [[0, 1, 2]], {
            "cfd_surface": rows, "cfd_converged": True, "cfd_freestream_pressure_pa": 101325,
            "cfd_cell_spacing_m": [0.086, 0.015, 0.017]})


def test_zero_thickness_reference_parts_are_unsupported_without_blocking_other_parts():
    from rocket_workbench.models import Component, Conditions, Project
    from rocket_workbench.solvers.structure import analyze
    nose = Component(id="nose", kind="nosecone", radius=0.05, length=0.2, thickness=0.002)
    phantom = Component(id="phantom", kind="bodytube", radius=0.05, x=0.2, length=0.3, thickness=0)
    tube = Component(id="tube", kind="bodytube", radius=0.05, x=0.5, length=0.5, thickness=0.002)
    result = analyze(Project(components=[nose, phantom, tube]), Conditions())
    rows = {p["component_id"]: p for p in result["components"]}
    assert not rows["phantom"]["supported"]
    assert "Zero-thickness" in rows["phantom"]["warnings"][0]
    assert rows["tube"]["supported"]
