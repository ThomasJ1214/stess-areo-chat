"""Independent laminar transport references; no drag-accuracy claims."""
import json

import numpy as np
import pytest
import trimesh

from rocket_workbench.models import Conditions, Project
from rocket_workbench.solvers import cfd, cfd_viscous as viscous


def _state(velocity, temperature=300.0, density=1.2):
    return cfd.conserved(density, velocity, np.asarray(density) * viscous.AIR_GAS_CONSTANT * np.asarray(temperature))


def test_sutherland_air_and_fourier_conductivity_reference():
    assert viscous.air_viscosity(273.15) == pytest.approx(1.716e-5, rel=1e-14)
    # Published dry-air values near room temperature: mu~=18.46 microPa s,
    # k~=0.026 W/(m K); conductivity here uses explicitly fixed Pr=0.72.
    assert viscous.air_viscosity(300.0) == pytest.approx(1.846e-5, rel=0.002)
    assert viscous.thermal_conductivity(300.0) == pytest.approx(0.026, rel=0.015)


@pytest.mark.parametrize("temperature", [0.0, -1.0, np.nan, np.inf])
def test_transport_rejects_nonphysical_temperature(temperature):
    with pytest.raises(ValueError, match="temperature"):
        viscous.air_viscosity(temperature)


@pytest.mark.parametrize("boundary", ["periodic", "farfield", "outflow"])
def test_uniform_oblique_flow_has_exactly_zero_viscous_transport(boundary):
    farfield = _state([150.0, -20.0, 4.0])
    state = np.broadcast_to(farfield, (5, 4, 3, 5)).copy()
    solid = np.zeros(state.shape[:-1], dtype=bool)
    rhs = viscous.viscous_rhs(state, solid, [0.03, 0.02, 0.01], farfield, boundary)
    np.testing.assert_array_equal(rhs, 0.0)
    step = cfd.stable_timestep(state, solid, [0.03, 0.02, 0.01], physics_model="laminar")
    result = cfd.finite_volume_step(state, solid, [0.03, 0.02, 0.01], step, farfield,
                                    boundary=boundary, physics_model="laminar")
    np.testing.assert_array_equal(result, state)


def test_periodic_sine_shear_matches_independent_discrete_diffusion_rate():
    n, spacing, amplitude = 48, 0.01, 2.0
    coordinate = (np.arange(n) + 0.5) * spacing
    wave_number = 2 * np.pi / (n * spacing)
    velocity = np.zeros((3, n, 2, 3))
    velocity[..., 0] = amplitude * np.sin(wave_number * coordinate)[None, :, None]
    state = _state(velocity)
    solid = np.zeros(state.shape[:-1], dtype=bool)
    rhs = viscous.viscous_rhs(state, solid, [0.1, spacing, 0.1], state[0, 0, 0], "periodic")
    eigenvalue = (2 * np.cos(wave_number * spacing) - 2) / spacing**2
    expected = viscous.air_viscosity(300.0) * eigenvalue * velocity[..., 0]
    np.testing.assert_allclose(rhs[..., 1], expected, rtol=5e-12, atol=2e-16)
    np.testing.assert_allclose(rhs[..., 2:4], 0.0, atol=1e-16)
    np.testing.assert_allclose(rhs.sum(axis=(0, 1, 2)), 0.0, atol=2e-15)


def test_sine_shear_decay_matches_independent_physical_exponential():
    n, spacing = 48, 0.01
    coordinate = (np.arange(n) + 0.5) * spacing
    wave_number = 2 * np.pi / (n * spacing)
    mode = np.sin(wave_number * coordinate)
    velocity = np.zeros((2, n, 2, 3))
    velocity[..., 0] = 1e-3 * mode[None, :, None]
    state = _state(velocity)
    solid = np.zeros(state.shape[:-1], dtype=bool)
    density = 1.2
    rate = viscous.air_viscosity(300.0) / density * (2 - 2 * np.cos(wave_number * spacing)) / spacing**2
    duration, count = 0.02 / rate, 80
    dt = duration / count
    for _ in range(count):
        state += dt * viscous.viscous_rhs(state, solid, [0.1, spacing, 0.1], state[0, 0, 0], "periodic")
    final_velocity = cfd.primitives(state)[1][0, :, 0, 0]
    np.testing.assert_allclose(final_velocity, 1e-3 * mode * np.exp(-rate * duration), rtol=3e-6, atol=2e-12)
    assert cfd._physical(state, solid)


def test_affine_couette_shear_has_exact_newtonian_stress_and_dissipation():
    shape, spacing, shear_rate = (7, 6, 5), np.array([0.01, 0.02, 0.03]), 15.0
    coordinate = np.indices(shape).transpose(1, 2, 3, 0) * spacing
    velocity = np.zeros(shape + (3,))
    velocity[..., 0] = shear_rate * coordinate[..., 1]
    state = _state(velocity)
    solid = np.zeros(shape, dtype=bool)
    fluxes = viscous.viscous_fluxes(state, solid, spacing, state[0, 0, 0], "outflow")
    mu = viscous.air_viscosity(300.0)
    np.testing.assert_allclose(fluxes[1][2:-2, 2:-2, 2:-2, 1], mu * shear_rate, rtol=2e-14)
    rhs = viscous.viscous_rhs(state, solid, spacing, state[0, 0, 0], "outflow")
    np.testing.assert_allclose(rhs[2:-2, 2:-2, 2:-2, 1:4], 0.0, atol=1e-16)
    np.testing.assert_allclose(rhs[2:-2, 2:-2, 2:-2, 4], mu * shear_rate**2, rtol=2e-14)


@pytest.mark.parametrize("flow", ["rotation", "isotropic_expansion"])
def test_rigid_rotation_and_stokes_isotropic_expansion_have_zero_viscous_stress(flow):
    shape, spacing, rate = (7, 7, 7), np.array([0.01, 0.02, 0.03]), 10.0
    position = np.indices(shape).transpose(1, 2, 3, 0) * spacing
    velocity = rate * position
    if flow == "rotation":
        velocity = np.stack((-rate * position[..., 1], rate * position[..., 0], np.zeros(shape)), axis=-1)
    state = _state(velocity)
    solid = np.zeros(shape, dtype=bool)
    fluxes = viscous.viscous_fluxes(state, solid, spacing, state[0, 0, 0], "outflow")
    for flux in fluxes:
        np.testing.assert_allclose(flux[2:-2, 2:-2, 2:-2], 0.0, atol=5e-17)


def test_fourier_heat_flux_matches_linear_temperature_gradient():
    shape, spacing, gradient = (7, 3, 3), [0.01, 0.1, 0.1], 100.0
    temperatures = np.broadcast_to(300 + gradient * (np.arange(shape[0]) - 3)[:, None, None] * spacing[0], shape)
    state = _state(np.zeros(shape + (3,)), temperatures)
    solid = np.zeros(shape, dtype=bool)
    flux = viscous.viscous_fluxes(state, solid, spacing, state[0, 0, 0], "outflow")[0]
    # Face between the 299 K and 300 K centers: T_face=299.5 K.
    expected = viscous.thermal_conductivity(299.5) * gradient
    assert flux[3, 1, 1, 4] == pytest.approx(expected, rel=1e-13)
    np.testing.assert_array_equal(flux[..., :4], 0.0)


def test_half_cell_couette_wall_shear_and_normal_viscous_stress_are_distinct():
    h, shear_rate = 0.02, 15.0
    state = np.broadcast_to(_state([0.0, shear_rate * h / 2, 0.0]), (3, 3, 3, 5)).copy()
    wall = dict(fluid_indices=np.array([[1, 1, 1]]), normals=np.array([[1.0, 0.0, 0.0]]))
    traction, shear, _ = viscous.wall_tractions(state, wall, [h, h, h])
    np.testing.assert_allclose(traction, [[0.0, viscous.air_viscosity(300.0) * shear_rate, 0.0]], rtol=1e-14)
    np.testing.assert_array_equal(shear, traction)
    state = np.broadcast_to(_state([2.0, 0.0, 0.0]), state.shape).copy()
    traction, shear, _ = viscous.wall_tractions(state, wall, [h, h, h])
    assert traction[0, 0] == pytest.approx((4 / 3) * viscous.air_viscosity(300.0) * (2 * 2.0 / h), rel=1e-14)
    np.testing.assert_array_equal(shear, 0.0)


def test_adiabatic_no_slip_wall_force_closes_with_fluid_momentum_loss():
    shape, spacing = (7, 6, 5), np.array([0.02, 0.03, 0.04])
    state = np.broadcast_to(_state([3.0, 7.0, -2.0]), shape + (5,)).copy()
    solid = np.zeros(shape, dtype=bool)
    solid[2:5, 2:4, 2] = True
    wall = cfd._wall_geometry(solid, spacing, np.zeros(3))
    rhs = viscous.viscous_rhs(state, solid, spacing, state[0, 0, 0], "periodic")
    traction, _, _ = viscous.wall_tractions(state, wall, spacing)
    wall_force = (traction * wall["areas"][:, None]).sum(axis=0)
    fluid_force = rhs[..., 1:4].sum(axis=(0, 1, 2)) * np.prod(spacing)
    np.testing.assert_allclose(fluid_force, -wall_force, rtol=3e-14, atol=1e-17)
    assert np.linalg.norm(wall_force) > 0
    assert rhs[..., 0].sum() == 0
    assert rhs[..., 4].sum() * np.prod(spacing) == pytest.approx(0.0, abs=2e-17)
    # Full coupled Euler+viscous update must preserve stationary-wall total
    # energy (kinetic loss becomes internal energy) and total fluid mass.
    initial = state[~solid].sum(axis=0)
    for _ in range(8):
        dt = cfd.stable_timestep(state, solid, spacing, physics_model="laminar")
        state = cfd.finite_volume_step(state, solid, spacing, dt, state[0, 0, 0],
                                        boundary="periodic", physics_model="laminar")
    np.testing.assert_allclose(state[~solid].sum(axis=0)[[0, 4]], initial[[0, 4]], rtol=2e-14)
    assert cfd._physical(state, solid)


def test_every_adiabatic_wall_face_has_exactly_zero_mass_and_energy_transport():
    shape, spacing = (5, 5, 5), [0.01, 0.02, 0.03]
    temperature = 300 + 5 * np.indices(shape).sum(axis=0)
    velocity = np.zeros(shape + (3,))
    velocity[..., :] = [5.0, 3.0, -2.0]
    state = _state(velocity, temperature)
    solid = np.zeros(shape, dtype=bool)
    solid[2, 2, 2] = True
    for axis, flux in enumerate(viscous.viscous_fluxes(state, solid, spacing, state[0, 0, 0], "periodic")):
        _, sl, sr = cfd._axis_flux(state, solid, axis, state[0, 0, 0], "periodic")
        wall = sl ^ sr
        assert wall.sum() == 2
        np.testing.assert_array_equal(flux[wall][..., [0, 4]], 0.0)
        assert np.any(np.abs(flux[wall][..., 1:4]) > 0)


def test_full_laminar_periodic_update_conserves_all_five_quantities():
    shape, spacing = (6, 5, 4), [0.005, 0.007, 0.009]
    x, y, z = np.indices(shape)
    density = 1.1 + 0.1 * np.sin(2 * np.pi * x / shape[0])
    temperature = 300 + 20 * np.cos(2 * np.pi * y / shape[1])
    velocity = np.stack((20 + np.sin(2 * np.pi * z / shape[2]),
                         3 * np.cos(2 * np.pi * x / shape[0]),
                         np.sin(2 * np.pi * y / shape[1])), axis=-1)
    state = _state(velocity, temperature, density)
    solid = np.zeros(shape, dtype=bool)
    initial = state.sum(axis=(0, 1, 2))
    for _ in range(12):
        dt = cfd.stable_timestep(state, solid, spacing, physics_model="laminar")
        state = cfd.finite_volume_step(state, solid, spacing, dt, state[0, 0, 0],
                                        boundary="periodic", physics_model="laminar")
    np.testing.assert_allclose(state.sum(axis=(0, 1, 2)), initial, rtol=2e-14, atol=1e-10)
    assert cfd._physical(state, solid)


def test_variable_transport_cfl_uses_global_face_safe_density_and_viscosity():
    temperatures = np.array([300.0, 1200.0])[:, None, None]
    density = np.array([0.01, 100.0])[:, None, None]
    state = _state(np.zeros((2, 1, 1, 3)), temperatures, density)
    solid = np.zeros(state.shape[:-1], dtype=bool)
    spacing = np.array([0.0001, 0.0002, 0.0003])
    rate = viscous.diffusive_inverse_time(state, solid, spacing)
    expected_diffusivity = viscous.air_viscosity(1200.0) / 0.01 * max(4 / 3, 1.4 / 0.72)
    assert rate == pytest.approx(4 * expected_diffusivity * np.sum(spacing**-2), rel=2e-14)
    acoustic = np.max(np.sum(cfd.primitives(state)[3][..., None] / spacing, axis=-1))
    dt = cfd.stable_timestep(state, solid, spacing, cfl=0.35, physics_model="laminar")
    assert dt == pytest.approx(0.35 / (acoustic + rate), rel=2e-14)
    assert dt < min(0.35 / acoustic, 0.35 / rate)


def test_exterior_mask_does_not_alter_original_material_geometry():
    material = np.zeros((7, 7, 7), dtype=bool)
    material[2:5, 2:5, 2:5] = True
    material[3, 3, 3] = False
    original = material.copy()
    solid = cfd._exterior_flow_mask(material)
    state = np.broadcast_to(_state([20.0, 3.0, 0.0]), solid.shape + (5,)).copy()
    wall = cfd._wall_geometry(solid, np.array([0.02] * 3), np.zeros(3))
    assert solid[3, 3, 3]
    assert not np.any(np.all(wall["fluid_indices"] == [3, 3, 3], axis=1))
    viscous.viscous_rhs(state, solid, [0.02] * 3, state[0, 0, 0])
    np.testing.assert_array_equal(material, original)


def test_real_laminar_transient_exports_actual_distinct_pressure_shear_and_total_loads(monkeypatch):
    import rocket_workbench.geometry as geometry
    monkeypatch.setattr(geometry, "project_mesh", lambda *args, **kwargs: trimesh.creation.box(extents=[0.12, 0.04, 0.04]))
    result = cfd.solve(Project(), Conditions(speed=120.0, wind_speed=0, angle_of_attack=3), options={
        "physics_model": "laminar", "mode": "transient", "duration_s": 1e-5,
        "grid_resolution": 12, "transverse_resolution": 12,
        "backend": "cpu", "snapshot_count": 4, "sample_limit": 30, "surface_limit": 30,
    })
    summary = result["summary"]
    assert summary["physics_model"] == "laminar" and summary["status"] == "transient_complete"
    assert summary["physical_time_s"] == 1e-5
    assert "laminar Navier" in result["fidelity"]
    assert summary["transport"]["estimated_numerical_to_molecular_diffusivity_ratio"] > 1000
    assert summary["viscous_drag_n"] > 0
    np.testing.assert_allclose(summary["total_force_n"], np.array(summary["force_n"]) + summary["viscous_force_n"])
    assert summary["wall_heat_flux_w_m2"] == 0
    assert not summary["viscous_force_validated"] and not summary["pressure_force_steady"]
    assert summary["wall_viscous_residual"] is not None
    for surface in result["surface"]:
        normal = np.array(surface["normal"])
        assert abs(np.dot(surface["shear_traction_pa"], normal)) < 1e-10
        expected = -(surface["pressure_pa"] - summary["freestream_pressure_pa"]) * normal + surface["viscous_traction_pa"]
        np.testing.assert_allclose(surface["total_traction_pa"], expected)
    for frame in result["transient"]["frames"]:
        np.testing.assert_allclose(frame["total_force_n"], np.array(frame["force_n"]) + frame["viscous_force_n"])
        assert len(frame["surface_shear_stress_pa"]) == len(result["surface"])
    assert any("numerical-to-molecular" in message for message in result["warnings"])
    assert any("does not transfer viscous shear" in message for message in result["warnings"])
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("model", ["turbulent", "LES", None, False])
def test_unknown_physics_model_rejected_before_geometry_work(model):
    with pytest.raises(ValueError, match="physics_model"):
        cfd.solve(Project(), Conditions(), options={"physics_model": model, "backend": "cpu"})
