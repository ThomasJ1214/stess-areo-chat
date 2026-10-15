"""Closed-form and independently integrated modal references, including high modes."""
import numpy as np
import pytest
from scipy.integrate import solve_ivp

from rocket_workbench.solvers.flight_structure import exact_foh_step, _fin_load, analyze_flight_structure
from test_flight_structure import isotropic_project, reference_rows


@pytest.mark.parametrize("omega,dt", [(3., .4), (10000., .023), (40., 1e-9)])
def test_unforced_modes_match_exact_phase_and_conserve_energy(omega, dt):
    q, v, a = exact_foh_step(np.array([[.03]]), np.array([[-.07]]), np.zeros((1, 1)), np.zeros((1, 1)), np.array([omega]), 0, dt)
    phase = omega*dt
    expected_q = .03*np.cos(phase)-.07/omega*np.sin(phase)
    expected_v = -.03*omega*np.sin(phase)-.07*np.cos(phase)
    np.testing.assert_allclose(q, [[expected_q]], rtol=1e-12, atol=1e-14)
    np.testing.assert_allclose(v, [[expected_v]], rtol=1e-12, atol=1e-13)
    assert (.5*(v[0, 0]**2+omega**2*q[0, 0]**2)) == pytest.approx(.5*(.07**2+omega**2*.03**2), rel=1e-12)


def test_damped_ramp_matches_independent_adaptive_ode_and_interval_composition():
    omega, zeta, duration = 73., .07, .13
    initial = [.02, -.03]
    forcing = lambda t: 2+11*t
    reference = solve_ivp(lambda t, y: [y[1], forcing(t)-2*zeta*omega*y[1]-omega**2*y[0]],
                          (0, duration), initial, method="DOP853", rtol=2e-13, atol=2e-14).y[:, -1]
    q, v, _ = exact_foh_step(np.array([[initial[0]]]), np.array([[initial[1]]]), np.array([[forcing(0)]]),
                             np.array([[forcing(duration)]]), np.array([omega]), zeta, duration)
    np.testing.assert_allclose([q[0, 0], v[0, 0]], reference, rtol=1e-10, atol=1e-12)
    split = .037
    a, b, _ = exact_foh_step(np.array([[initial[0]]]), np.array([[initial[1]]]), np.array([[forcing(0)]]), np.array([[forcing(split)]]), np.array([omega]), zeta, split)
    c, d, _ = exact_foh_step(a, b, np.array([[forcing(split)]]), np.array([[forcing(duration)]]), np.array([omega]), zeta, duration-split)
    np.testing.assert_allclose([c[0, 0], d[0, 0]], [q[0, 0], v[0, 0]], atol=1e-12)


@pytest.mark.parametrize("count", [1, 2])
def test_degenerate_fin_basis_is_unavailable_rather_than_doubling_load(count):
    project, rows = isotropic_project(), reference_rows()
    fin = project.components[3]
    fin.fin_count = count
    load, reason, *_ = _fin_load(rows[0], fin, .06, 10)
    assert load is None and "three" in reason
    answer = analyze_flight_structure(project, rows)
    assert answer["summary"]["supported_components"] == 0
    assert all(row["max_stress_pa"] is None for row in answer["trajectory"])


def test_exact_mode_retains_all_fem_modes_and_uses_actual_intervals():
    project, rows = isotropic_project(), reference_rows()
    answer = analyze_flight_structure(project, rows)
    model = answer["components"][0]
    assert model["time_integrator"] == "exact_foh"
    assert model["retained_modes"] == model["free_dofs"]
    assert model["substeps"] == len(rows)-1
    assert model["maximum_internal_step_s"] is None
    limited = analyze_flight_structure(project, rows, options={"max_substeps": 1})
    assert limited["summary"]["status"] == "work_budget"
    assert limited["trajectory"][1]["max_stress_pa"] is not None
    assert all(row["max_stress_pa"] is None for row in limited["trajectory"][2:])
