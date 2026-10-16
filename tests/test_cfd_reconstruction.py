"""Independent smooth-wave, shock, conservation and boundary checks for MUSCL."""

import numpy as np
import pytest

from rocket_workbench.solvers import cfd
from rocket_workbench.solvers.cfd_reconstruction import primitive_slopes
from test_cfd import _sod_exact_density


def _advance(state, solid, spacing, end, boundary="periodic", scheme="muscl_mc"):
    time = 0.0
    while time < end:
        dt = min(cfd.stable_timestep(state, solid, spacing, cfl=0.3), end - time)
        state = cfd.finite_volume_step(
            state,
            solid,
            spacing,
            dt,
            state[0, 0, 0],
            boundary=boundary,
            spatial_scheme=scheme,
        )
        assert cfd._physical(state, solid)
        time += dt
    return state


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_advected_entropy_cell_averages_show_second_order_l1_convergence(
    axis, record_property
):
    errors = []
    for n in (24, 48, 96):
        shape = [2, 2, 2]
        shape[axis] = n
        dx = 1 / n
        centers = (np.arange(n) + 0.5) * dx
        # Exact FV cell average of a smooth periodic entropy wave.
        average = lambda t: 1 + 0.15 * np.sinc(dx) * np.sin(2 * np.pi * (centers - t))
        reshape = [1, 1, 1]
        reshape[axis] = n
        rho = np.broadcast_to(average(0).reshape(reshape), shape)
        velocity = np.zeros(shape + [3])
        velocity[..., axis] = 1
        initial = cfd.conserved(rho, velocity, np.ones(shape))
        spacing = [1e4] * 3
        spacing[axis] = dx
        state = _advance(initial, np.zeros(shape, bool), spacing, 0.2)
        exact = np.broadcast_to(average(0.2).reshape(reshape), shape)
        errors.append(np.mean(np.abs(state[..., 0] - exact)))
        np.testing.assert_allclose(
            state.sum((0, 1, 2)), initial.sum((0, 1, 2)), rtol=2e-14, atol=1e-11
        )
        _, vel, pressure, _ = cfd.primitives(state)
        np.testing.assert_allclose(pressure, 1, atol=1e-13)
        np.testing.assert_allclose(vel, velocity, atol=1e-13)
    orders = np.log2(np.array(errors[:-1]) / errors[1:])
    record_property("density_l1_errors", [float(value) for value in errors])
    record_property("observed_orders", orders.tolist())
    assert np.min(orders) > 1.7, (errors, orders)


def test_sod_shock_improves_density_error_without_nonphysical_states(record_property):
    n = 180
    dx = 1 / n
    x = (np.arange(n) + 0.5) * dx
    state = cfd.conserved(
        np.where(x < 0.5, 1.0, 0.125), np.zeros((n, 3)), np.where(x < 0.5, 1.0, 0.1)
    )[:, None, None, :]
    solid = np.zeros((n, 1, 1), bool)
    initial = state.sum((0, 1, 2)) * dx
    reference = _sod_exact_density(x, 0.2)
    errors = []
    for scheme in ("first_order", "muscl_mc"):
        result = _advance(state.copy(), solid, [dx, 1e6, 1e6], 0.2, "outflow", scheme)
        errors.append(np.mean(np.abs(result[:, 0, 0, 0] - reference)))
        integral = result.sum((0, 1, 2)) * dx
        np.testing.assert_allclose(integral[[0, 4]], initial[[0, 4]], atol=2e-8)
        assert integral[1] == pytest.approx(0.18, abs=2e-8)
    record_property(
        "density_l1_errors_first_order_muscl", [float(value) for value in errors]
    )
    assert errors[1] < 0.65 * errors[0], errors
    assert errors[1] < 0.015


def test_multidimensional_periodic_conservation_and_uniform_preservation():
    shape = (9, 8, 7)
    x, y, z = np.indices(shape)
    rho = 1 + 0.1 * np.sin(2 * np.pi * x / 9)
    vel = np.stack(
        (
            0.3 + 0.1 * np.sin(2 * np.pi * y / 8),
            0.2 * np.cos(2 * np.pi * z / 7),
            0.1 * np.sin(2 * np.pi * x / 9),
        ),
        axis=-1,
    )
    initial = cfd.conserved(rho, vel, 1 + 0.1 * np.cos(2 * np.pi * y / 8))
    result = _advance(initial.copy(), np.zeros(shape, bool), [0.1, 0.08, 0.05], 0.05)
    np.testing.assert_allclose(
        result.sum((0, 1, 2)), initial.sum((0, 1, 2)), rtol=2e-14, atol=1e-10
    )
    uniform = np.broadcast_to(
        cfd.conserved(1.2, [650, 30, -15], 101325), shape + (5,)
    ).copy()
    result = _advance(
        uniform.copy(), np.zeros(shape, bool), [0.1, 0.08, 0.05], 1e-5, "farfield"
    )
    np.testing.assert_allclose(result, uniform, rtol=3e-16, atol=1e-10)


@pytest.mark.parametrize("boundary", ["periodic", "outflow", "farfield"])
def test_reconstruction_preserves_positive_faces_and_downgrades_at_walls(boundary):
    rng = np.random.default_rng(73)
    prim = rng.normal(size=(7, 6, 5, 5))
    prim[..., 0] = np.exp(10 * prim[..., 0])
    prim[..., 4] = np.exp(10 * prim[..., 4])
    solid = np.zeros((7, 6, 5), bool)
    solid[3, 2, 2] = True
    from rocket_workbench.solvers.cfd_reconstruction import (
        face_primitives,
        first_order_cells,
    )

    for axis in range(3):
        slopes = primitive_slopes(prim, solid, axis, boundary)
        np.testing.assert_array_equal(
            slopes[first_order_cells(solid, axis, boundary)], 0
        )
        left, right, sl, sr = face_primitives(
            prim, solid, axis, prim[0, 0, 0], boundary
        )
        assert np.all(left[..., [0, 4]] > 0) and np.all(right[..., [0, 4]] > 0)
        assert np.isfinite(left).all() and np.isfinite(right).all()
        state = cfd.conserved(prim[..., 0], prim[..., 1:4], prim[..., 4])
        flux, sl, sr = cfd._axis_flux(
            state, solid, axis, state[0, 0, 0], boundary, spatial_scheme="muscl_mc"
        )
        wall = sl ^ sr
        np.testing.assert_array_equal(flux[wall][:, [0, 4]], 0)


@pytest.mark.parametrize("invalid_stage", [1, 2])
def test_invalid_stage_is_rejected_without_reconstruction_or_clipping(
    monkeypatch, invalid_stage
):
    initial = np.broadcast_to(cfd.conserved(1, [1, 0, 0], 1), (4, 2, 2, 5)).copy()
    calls = []

    def invalid(*args):
        calls.append(True)
        state = args[0].copy()
        if len(calls) == invalid_stage:
            state[..., 0] = -1
        return state

    monkeypatch.setattr(cfd, "_forward_step", invalid)
    result = cfd.finite_volume_step(
        initial,
        np.zeros((4, 2, 2), bool),
        [1] * 3,
        0.1,
        initial[0, 0, 0],
        spatial_scheme="muscl_mc",
    )
    assert len(calls) == invalid_stage and np.all(result[..., 0] == -1)
    assert np.all(initial[..., 0] == 1)


@pytest.mark.parametrize("physics", ["euler", "laminar"])
def test_closed_walls_preserve_mass_energy_and_source_arrays(physics):
    shape = (7, 6, 5)
    coords = np.indices(shape)
    rho = 1.2 + 0.02 * np.sin(coords[0])
    velocity = np.zeros(shape + (3,))
    velocity[:] = [3, 2, -1]
    state = cfd.conserved(rho, velocity, 101325 + 30 * np.cos(coords[1]))
    solid = np.zeros(shape, bool)
    solid[2:5, 2:4, 2] = True
    saved = state.copy()
    saved_solid = solid.copy()
    initial = state[~solid].sum(axis=0)
    for _ in range(5):
        dt = cfd.stable_timestep(
            state, solid, [0.02, 0.03, 0.04], physics_model=physics
        )
        state = cfd.finite_volume_step(
            state,
            solid,
            [0.02, 0.03, 0.04],
            dt,
            saved[0, 0, 0],
            boundary="periodic",
            spatial_scheme="muscl_mc",
            physics_model=physics,
        )
        assert cfd._physical(state, solid)
    np.testing.assert_allclose(
        state[~solid].sum(axis=0)[[0, 4]], initial[[0, 4]], rtol=2e-14
    )
    np.testing.assert_array_equal(solid, saved_solid)
    np.testing.assert_array_equal(state[solid], saved[solid])
    assert not np.array_equal(state[~solid], saved[~solid])


@pytest.mark.parametrize("scheme", [None, False, [], "weno", 2])
def test_invalid_scheme_is_rejected_before_geometry(scheme):
    from rocket_workbench.models import Project, Conditions

    with pytest.raises(ValueError, match="spatial_scheme"):
        cfd.solve(Project(), Conditions(), options={"spatial_scheme": scheme})
