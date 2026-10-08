"""Reference/physics tests of the actual Euler finite-volume implementation."""
import json

import numpy as np
import pytest
import trimesh

from rocket_workbench.models import Component, Conditions, GeometryAsset, Material, Project
from rocket_workbench.solvers import cfd


def test_uniform_oblique_supersonic_freestream_is_preserved():
    farfield = cfd.conserved(1.2, [650.0, 30.0, -15.0], 101325.0)
    state = np.broadcast_to(farfield, (10, 7, 6, 5)).copy()
    solid = np.zeros(state.shape[:-1], dtype=bool)
    for _ in range(12):
        dt = cfd.stable_timestep(state, solid, [0.05] * 3)
        state = cfd.finite_volume_step(state, solid, [0.05] * 3, dt, farfield)
    np.testing.assert_array_equal(state, np.broadcast_to(farfield, state.shape))


def test_periodic_update_conserves_all_five_integrated_quantities():
    shape = (15, 6, 5)
    x, y, z = np.indices(shape)
    rho = 1.2 + 0.15 * np.sin(2 * np.pi * x / shape[0])
    pressure = 101325 + 1000 * np.cos(2 * np.pi * y / shape[1])
    velocity = np.stack((40 + 4 * np.sin(2 * np.pi * z / shape[2]),
                         3 * np.sin(2 * np.pi * x / shape[0]),
                         2 * np.cos(2 * np.pi * y / shape[1])), axis=-1)
    state = cfd.conserved(rho, velocity, pressure)
    solid = np.zeros(shape, dtype=bool)
    initial = state.sum(axis=(0, 1, 2))
    for _ in range(20):
        dt = cfd.stable_timestep(state, solid, [0.1, 0.05, 0.03])
        state = cfd.finite_volume_step(state, solid, [0.1, 0.05, 0.03], dt, state[0, 0, 0], boundary="periodic")
    np.testing.assert_allclose(state.sum(axis=(0, 1, 2)), initial, rtol=2e-14, atol=1e-9)
    assert cfd._physical(state, solid)


def _sod_exact_density(x, time):
    """Canonical Sod ideal-gas solution: gamma=1.4, left (1,0,1), right (.125,0,.1).

    Star-state constants are the independently tabulated exact Riemann solution;
    the rarefaction fan is evaluated analytically (Toro, chapter 4).
    """
    xi = (x - 0.5) / time
    sound_left = np.sqrt(1.4)
    density = np.full_like(x, 0.125)
    density[xi < 1.752155732] = 0.265573712
    density[xi < 0.927452620] = 0.426319428
    fan = (xi >= -sound_left) & (xi < -0.070272812)
    density[fan] = (2 / 2.4 - 0.4 / 2.4 * xi[fan] / sound_left) ** (2 / 0.4)
    density[xi < -sound_left] = 1.0
    return density


def test_sod_shock_tube_matches_exact_density_and_conservation():
    n = 250
    dx = 1 / n
    x = (np.arange(n) + 0.5) * dx
    rho = np.where(x < 0.5, 1.0, 0.125)
    pressure = np.where(x < 0.5, 1.0, 0.1)
    state = cfd.conserved(rho, np.zeros((n, 3)), pressure)[:, None, None, :]
    solid = np.zeros((n, 1, 1), dtype=bool)
    initial = state.sum(axis=(0, 1, 2)) * dx
    elapsed = 0.0
    while elapsed < 0.2:
        dt = min(cfd.stable_timestep(state, solid, [dx, 1e6, 1e6], cfl=0.45), 0.2 - elapsed)
        state = cfd.finite_volume_step(state, solid, [dx, 1e6, 1e6], dt, state[0, 0, 0], boundary="outflow")
        elapsed += dt
    actual_rho, _, actual_pressure, _ = cfd.primitives(state)
    reference = _sod_exact_density(x, elapsed)
    assert np.mean(np.abs(actual_rho[:, 0, 0] - reference)) < 0.027
    assert np.min(actual_pressure) > 0
    final = state.sum(axis=(0, 1, 2)) * dx
    # Transmissive ends are undisturbed at t=.2: mass and energy stay fixed.
    # Momentum increases by integrated boundary pressure imbalance (1-.1)*t.
    np.testing.assert_allclose(final[[0, 4]], initial[[0, 4]], rtol=2e-8, atol=2e-8)
    assert final[1] == pytest.approx(0.9 * elapsed, rel=2e-8, abs=2e-8)


def test_slip_wall_has_zero_mass_energy_and_tangential_momentum_flux():
    state = np.broadcast_to(cfd.conserved(1.2, [80, 20, -10], 101325), (3, 2, 2, 5)).copy()
    solid = np.zeros((3, 2, 2), dtype=bool)
    solid[1] = True
    flux, left, right = cfd._axis_flux(state, solid, 0, state[0, 0, 0])
    wall = left ^ right
    np.testing.assert_allclose(flux[wall][:, [0, 2, 3, 4]], 0.0, atol=1e-10)


def test_reflected_wall_pressure_matches_normal_shock_and_isentropic_expansion():
    rho, pressure = 1.2, 101325.0
    sound = np.sqrt(1.4 * pressure / rho)
    # Independent normal-shock benchmark: shock Mach 2 has rho2/rho1=8/3
    # and p2/p1=4.5. Its piston speed is 2*c1*(1-3/8)=1.25*c1.
    actual = cfd.wall_riemann_pressure(rho, pressure, 1.25 * sound)
    assert actual == pytest.approx(4.5 * pressure, rel=2e-14)
    # An isentropic rarefaction toward a receding wall has c*/c1=.8 at u=-c1;
    # p*/p1=(c*/c1)^(2*gamma/(gamma-1))=.8^7=.2097152.
    actual = cfd.wall_riemann_pressure(rho, pressure, -sound)
    assert actual == pytest.approx(0.2097152 * pressure, rel=2e-14)
    assert cfd.wall_riemann_pressure(rho, pressure, -6 * sound) == 0
    assert cfd.wall_riemann_pressure(rho, pressure, 0) == pressure


def test_wall_load_is_equal_and_opposite_to_fluid_momentum_change():
    spacing = np.array([0.025, 0.013, 0.009])
    farfield = cfd.conserved(1.2, [160, 30, -20], 101325)
    state = np.broadcast_to(farfield, (10, 9, 8, 5)).copy()
    solid = np.zeros(state.shape[:-1], dtype=bool)
    solid[3:7, 3:6, 2:6] = True
    _, force, _, _, _ = cfd._surface(
        state, solid, spacing, np.zeros(3), farfield, 101325, 164, 1.2, 1)
    dt = cfd.stable_timestep(state, solid, spacing)
    updated = cfd.finite_volume_step(state, solid, spacing, dt, farfield)
    integrated_change = ((updated - state)[~solid].sum(axis=0) * np.prod(spacing))
    # Outer uniform fluxes cancel; stationary walls do no work. Every fluid
    # momentum impulse must be the reaction to the exported full wall force.
    np.testing.assert_allclose(integrated_change[1:4], -force * dt, rtol=2e-13, atol=1e-13)
    np.testing.assert_allclose(integrated_change[[0, 4]], 0, atol=1e-12)


def test_uniform_tangential_flow_is_preserved_between_slip_walls():
    farfield = cfd.conserved(1.2, [320, 0, 0], 101325)
    state = np.broadcast_to(farfield, (8, 8, 8, 5)).copy()
    solid = np.zeros(state.shape[:-1], dtype=bool)
    solid[:, :2, :] = True
    solid[:, -2:, :] = True
    for _ in range(5):
        dt = cfd.stable_timestep(state, solid, [0.02, 0.01, 0.03])
        state = cfd.finite_volume_step(state, solid, [0.02, 0.01, 0.03], dt, farfield, boundary="periodic")
    np.testing.assert_array_equal(state, np.broadcast_to(farfield, state.shape))


def test_uniform_static_pressure_integrates_to_zero_force_on_closed_body():
    state = np.broadcast_to(cfd.conserved(1.2, [0, 0, 0], 101325), (8, 7, 6, 5)).copy()
    solid = np.zeros((8, 7, 6), dtype=bool)
    solid[2:5, 2:5, 1:4] = True
    _, force, moment, count, negatives = cfd._surface(
        state, solid, np.array([0.02] * 3), np.zeros(3), state[0, 0, 0], 101325, 0, 1.2, 100)
    np.testing.assert_allclose(force, 0, atol=1e-10)
    np.testing.assert_allclose(moment, 0, atol=1e-10)
    assert count == 54
    assert negatives == 0


def test_pressure_coefficients_remain_undefined_at_unresolvable_dynamic_pressure():
    state = np.broadcast_to(cfd.conserved(1.2, [0, 0, 0], 101325), (6, 6, 6, 5)).copy()
    solid = np.zeros(state.shape[:-1], dtype=bool)
    solid[2:4, 2:4, 2:4] = True
    surface, _, _, _, _ = cfd._surface(
        state, solid, np.array([0.02] * 3), np.zeros(3), state[0, 0, 0], 101325, 1e-160, 1.2, 100)
    assert all(row["pressure_coefficient"] is None for row in surface)
    json.dumps(surface, allow_nan=False)


def test_voxel_grid_preserves_actual_closed_geometry_and_enforces_cell_budget():
    mesh = trimesh.creation.box(extents=[0.5, 0.12, 0.12])
    solid, spacing, origin, warnings = cfd._voxel_domain(mesh, {"grid_resolution": 16})
    assert solid.any() and not solid[0].any() and not solid[-1].any()
    assert spacing[0] == pytest.approx(0.5 / 16)
    centers = origin + np.argwhere(solid) * spacing
    assert np.max(np.abs(centers[:, 0])) <= 0.25 + spacing[0]
    assert warnings  # underresolved cross-section is explicitly disclosed
    with pytest.raises(ValueError, match="exceeding the explicit max_cells budget"):
        cfd._voxel_domain(mesh, {"grid_resolution": 128, "max_cells": 1000})


def test_sealed_cad_cavity_has_identical_exterior_flow_without_changing_material_geometry():
    """A sealed cavity changes material/mass, never the exterior pressure boundary."""
    from rocket_workbench.geometry import component_mesh, project_mesh
    from rocket_workbench.solvers.aero import mass_properties

    outer = trimesh.creation.box(extents=[0.3, 0.2, 0.16])
    inner = trimesh.creation.box(extents=[0.22, 0.12, 0.08])
    inner.invert()
    hollow = trimesh.util.concatenate([outer, inner])
    material_volume = 0.3 * 0.2 * 0.16 - 0.22 * 0.12 * 0.08
    asset = GeometryAsset(id="sealed-cad", name="Sealed hollow box", format="stl",
                          vertices=hollow.vertices.tolist(),
                          faces=hollow.faces.tolist(), volume=material_volume,
                          watertight=True)
    component = Component(id="payload", asset_id=asset.id, geometry_mode="replacement",
                          material_id="test-material")
    project = Project(components=[component], assets=[asset],
                      materials=[Material(id="test-material", density=1500)])
    before_project = project.model_dump(mode="json")
    before_material_mesh = component_mesh(project, component)
    before_mass = mass_properties(project)
    assert before_mass["mass_kg"] == pytest.approx(material_volume * 1500)

    options = {"grid_resolution": 16, "transverse_resolution": 16, "max_steps": 4,
               "backend": "cpu", "sample_limit": 200, "surface_limit": 30000}
    outer_diagnostics, hollow_diagnostics = {}, {}
    solid, spacing, origin, _ = cfd._voxel_domain(outer, options, diagnostics=outer_diagnostics)
    shell, shell_spacing, shell_origin, _ = cfd._voxel_domain(
        project_mesh(project), options, diagnostics=hollow_diagnostics)
    np.testing.assert_array_equal(shell, solid)
    np.testing.assert_array_equal(shell_spacing, spacing)
    np.testing.assert_array_equal(shell_origin, origin)
    assert hollow_diagnostics["aerodynamic_voxel_sha256"] == outer_diagnostics["aerodynamic_voxel_sha256"]
    assert hollow_diagnostics["enclosed_nonflow_cells"] > 0
    assert not hollow_diagnostics["source_material_mesh_modified"]

    # Evolve both domains independently. The identical exterior should give
    # identical solved pressures/loads, irrespective of concealed triangles.
    farfield = cfd.conserved(1.2, [180, 20, 0], 101325)
    states = [np.broadcast_to(farfield, mask.shape + (5,)).copy() for mask in (solid, shell)]
    for _ in range(4):
        for i, mask in enumerate((solid, shell)):
            dt = cfd.stable_timestep(states[i], mask, spacing)
            states[i] = cfd.finite_volume_step(states[i], mask, spacing, dt, farfield)
    results = [cfd._surface(state, mask, spacing, origin, farfield,
                            101325, np.linalg.norm([180, 20, 0]), 1.2, 30000)
               for state, mask in zip(states, (solid, shell))]
    assert results[0][0] == results[1][0]
    np.testing.assert_array_equal(results[0][1], results[1][1])
    np.testing.assert_array_equal(results[0][2], results[1][2])
    # Every pressure face is on the outer box, including staircase tolerance;
    # the sealed inner box contributes neither samples nor force.
    positions = np.asarray([row["position"] for row in results[1][0]])
    assert np.all(np.max(np.abs(positions) / (np.array([0.3, 0.2, 0.16]) / 2), axis=1) >= 1)

    solved = cfd.solve(project, Conditions(mach=0.3, wind_speed=0), options=options)
    assert solved["summary"]["aerodynamic_voxel_sha256"] == hollow_diagnostics["aerodynamic_voxel_sha256"]
    assert solved["summary"]["source_material_mesh_modified"] is False
    assert project.model_dump(mode="json") == before_project
    assert mass_properties(project) == before_mass
    after_material_mesh = component_mesh(project, component)
    np.testing.assert_array_equal(after_material_mesh.vertices, before_material_mesh.vertices)
    np.testing.assert_array_equal(after_material_mesh.faces, before_material_mesh.faces)
    assert after_material_mesh.volume == pytest.approx(material_volume)


def test_resolved_cad_bore_remains_connected_to_exterior_air():
    """A genuine through-hole must remain a flow passage rather than a convex hull."""
    mesh = trimesh.creation.annulus(r_min=0.035, r_max=0.06, height=0.3, sections=32)
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    before_vertices, before_faces = mesh.vertices.copy(), mesh.faces.copy()
    solid, spacing, origin, _ = cfd._voxel_domain(mesh, {
        "grid_resolution": 16, "transverse_resolution": 24,
    })
    center = np.rint(-origin / spacing).astype(int)
    assert not solid[tuple(center)]
    assert not solid[:, center[1], center[2]].any()  # continuous passage to both X farfields
    wall = cfd._wall_geometry(solid, spacing, origin)
    radii = np.linalg.norm(wall["positions"][:, 1:], axis=1)
    assert np.any((radii < 0.045) & (np.abs(wall["positions"][:, 0]) < 0.1))
    np.testing.assert_array_equal(mesh.vertices, before_vertices)
    np.testing.assert_array_equal(mesh.faces, before_faces)


def test_exterior_connectivity_follows_flux_faces_and_never_modifies_input():
    surface = np.ones((7, 7, 7), dtype=bool)
    surface[[0, -1], :, :] = False
    surface[:, [0, -1], :] = False
    surface[:, :, [0, -1]] = False
    surface[3, 3, 3] = False  # sealed cavity
    surface[1, 1, 1] = False  # face-connected to the exterior at (0, 1, 1)
    surface[2, 2, 2] = False  # diagonal contact alone transports no solver flux
    surface[0, 0, 0] = False
    before = surface.copy()
    blocked = cfd._exterior_flow_mask(surface)
    assert blocked[3, 3, 3] and blocked[2, 2, 2]
    assert not blocked[1, 1, 1]
    np.testing.assert_array_equal(surface, before)
    # A face-connected opening admits physical flow, preserving the cavity.
    opened = surface.copy()
    opened[:4, 3, 3] = False
    assert not cfd._exterior_flow_mask(opened)[3, 3, 3]


@pytest.mark.parametrize("mach", [0.2, 2.0])
def test_real_geometry_solve_produces_positive_pressure_and_real_loads(monkeypatch, mach):
    import rocket_workbench.geometry as geometry
    mesh = trimesh.creation.box(extents=[0.4, 0.1, 0.1])
    monkeypatch.setattr(geometry, "project_mesh", lambda *args, **kwargs: mesh)
    messages = []
    result = cfd.solve(Project(), Conditions(mach=mach, wind_speed=0, angle_of_attack=0),
                       options={"grid_resolution": 12, "max_steps": 12, "backend": "cpu"},
                       progress=lambda fraction, message: messages.append((fraction, message)))
    assert result["backend"] == "numpy-cpu"
    assert result["summary"]["steps"] == 12
    assert result["summary"]["min_pressure_pa"] > 0
    assert result["summary"]["force_n"][0] > 0
    assert result["summary"]["status"] == "step_budget"
    assert result["summary"]["cp_m"] is None
    assert not result["summary"]["pressure_force_steady"]
    assert not result["summary"]["pressure_force_validated"]
    assert len(result["samples"]) > 10 and len(result["surface"]) > 10
    assert np.ptp([point["pressure_pa"] for point in result["samples"]]) > 0.1
    assert messages[-1][0] == 1.0
    json.dumps(result, allow_nan=False)


def test_nontrivial_oblique_box_run_converges_and_pressure_cp_is_condition_specific(monkeypatch):
    import rocket_workbench.geometry as geometry
    monkeypatch.setattr(geometry, "project_mesh", lambda *args, **kwargs: trimesh.creation.box(extents=[0.1] * 3))
    result = cfd.solve(Project(), Conditions(mach=0.3, angle_of_attack=5, wind_speed=0), options={
        "grid_resolution": 12, "max_steps": 1000, "max_wall_seconds": 60,
        "flow_through_times": 8, "convergence_tolerance": 1e-3, "cfl": 0.7,
        "backend": "cpu", "sample_limit": 50, "surface_limit": 50,
    })
    summary = result["summary"]
    assert summary["status"] == "converged" and summary["pressure_force_steady"]
    assert not summary["pressure_force_validated"]
    assert summary["physical_time_s"] >= 0.5 * summary["flow_through_time_s"]
    assert result["history"][-1]["step"] == summary["steps"]
    assert summary["residual"] < 1e-3
    assert summary["wall_pressure_residual"] < 1e-3
    assert summary["force_residual"] < 1e-3
    assert summary["moment_residual"] < 1e-3
    assert np.linalg.norm(summary["force_n"]) > 0
    assert abs(summary["cp_m"]) < 0.02  # expected near box center; grid/domain error is permitted
    assert "not Barrowman" in summary["cp_kind"]
    assert summary["min_pressure_pa"] > 0


def test_farfield_rms_does_not_hide_unsettled_pressure_loads(monkeypatch):
    import rocket_workbench.geometry as geometry
    monkeypatch.setattr(geometry, "project_mesh", lambda *args, **kwargs: trimesh.creation.box(extents=[0.1] * 3))
    result = cfd.solve(Project(), Conditions(mach=0.3, angle_of_attack=5, wind_speed=0), options={
        "grid_resolution": 12, "max_steps": 200, "max_wall_seconds": 60,
        "flow_through_times": 8, "convergence_tolerance": 0.01, "cfl": 0.7,
        "backend": "cpu", "sample_limit": 1, "surface_limit": 1,
    })
    summary = result["summary"]
    assert summary["residual"] < 0.01
    assert max(summary["wall_pressure_residual"], summary["force_residual"], summary["moment_residual"]) > 0.01
    assert not summary["converged"] and not summary["pressure_force_steady"]


def test_low_mach_dissipation_limitation_is_explicit(monkeypatch):
    import rocket_workbench.geometry as geometry
    monkeypatch.setattr(geometry, "project_mesh", lambda *args, **kwargs: trimesh.creation.box(extents=[0.1] * 3))
    result = cfd.solve(Project(), Conditions(mach=0.05, wind_speed=0), options={
        "grid_resolution": 12, "max_steps": 1, "backend": "cpu", "sample_limit": 1, "surface_limit": 1,
    })
    assert any("Low-Mach" in warning and "dissipation" in warning for warning in result["warnings"])


def test_cancellation_and_invalid_input_are_explicit(monkeypatch):
    import rocket_workbench.geometry as geometry
    monkeypatch.setattr(geometry, "project_mesh", lambda *args, **kwargs: trimesh.creation.box(extents=[0.4, 0.1, 0.1]))
    result = cfd.solve(Project(), Conditions(wind_speed=0),
                       options={"grid_resolution": 12, "backend": "cpu"}, cancelled=lambda: True)
    assert result["summary"]["status"] == "cancelled"
    assert result["summary"]["steps"] == 0
    assert not result["summary"]["converged"]
    with pytest.raises(ValueError, match="max_steps"):
        cfd.solve(Project(), Conditions(), options={"max_steps": 0})


def test_explicit_gpu_request_does_not_silently_fall_back(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "cupy", None)
    with pytest.raises(RuntimeError, match="GPU CFD requires"):
        cfd._backend("gpu")
