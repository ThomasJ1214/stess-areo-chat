"""Reference/physics tests of the actual Euler finite-volume implementation."""
import json

import numpy as np
import pytest
import trimesh

from rocket_workbench.models import Conditions, Project
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
    assert np.linalg.norm(summary["force_n"]) > 0
    assert abs(summary["cp_m"]) < 0.02  # expected near box center; grid/domain error is permitted
    assert "not Barrowman" in summary["cp_kind"]
    assert summary["min_pressure_pa"] > 0


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
