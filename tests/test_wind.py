import math

import numpy as np
import pytest
from scipy.linalg import expm

from rocket_workbench.models import Conditions
from rocket_workbench.solvers.wind import WindField, dryden_transition


def test_exact_dryden_covariance_and_continuous_transition():
    stationary = np.array([[0.5, 0.25], [0.25, 0.25]])
    for rate, interval in [(0.1, 0.02), (2, 0.3), (1e-5, 0.001), (100, 0.2)]:
        f, q = dryden_transition(rate, interval)
        np.testing.assert_allclose(f, expm(rate * np.array([[-1., 0], [1, -1.]]) * interval), atol=1e-15)
        np.testing.assert_allclose(f @ stationary @ f.T + q, stationary, atol=2e-15)
        assert np.linalg.eigvalsh(q).min() > 0
        c = np.array([math.sqrt(3), 1 - math.sqrt(3)])
        assert c @ stationary @ c == pytest.approx(1)
        assert c @ f @ stationary @ c == pytest.approx((1 - 0.5 * rate * interval) * math.exp(-rate * interval))


def test_dryden_extreme_rates_fail_cleanly_or_use_stationary_limit():
    transition, covariance = dryden_transition(1e200, .2)
    np.testing.assert_array_equal(transition, np.zeros((2, 2)))
    np.testing.assert_array_equal(covariance, [[.5, .25], [.25, .25]])
    with pytest.raises(ValueError, match="resolution"):
        dryden_transition(1e-200, .01)


def test_legacy_wind_preserves_previous_realization_exactly():
    conditions = Conditions(wind_speed=8, turbulence=0.3, seed=51)
    field = WindField(conditions)
    phase = np.random.default_rng(51).uniform(0, 2 * math.pi, (3, 3))
    for t in [0, 0.17, 1.3, 29.5]:
        expected = np.array([8., 0., 0.]) + 8 * 0.3 / math.sqrt(3) * np.sin(2 * math.pi * np.array([0.23, 0.71, 1.9])[None, :] * t + phase).sum(axis=1)
        np.testing.assert_allclose(field.velocity(t, 100), expected, atol=2e-15)


def test_dryden_queries_are_seeded_causal_and_independent_of_call_order():
    conditions = Conditions(wind_model="dryden", turbulence=0.2, max_time=4)
    field = WindField(conditions)
    original = {t: field.velocity(t, 10) for t in [0, 0.127, 2.57, 4]}
    for t in [4, 0.127, 2.57, 0]:
        np.testing.assert_array_equal(field.velocity(t, 10), original[t])
    repeated = WindField(conditions)
    shorter = WindField(conditions.model_copy(update={"max_time": 3}))
    for t in [0, 0.127, 2.57]:
        np.testing.assert_array_equal(repeated.velocity(t, 10), original[t])
        np.testing.assert_array_equal(shorter.velocity(t, 10), original[t])


def test_dryden_stationary_variance_and_expected_autocorrelation():
    conditions = Conditions(wind_model="dryden", wind_speed=10, wind_direction=0,
        turbulence=0.1, turbulence_length_scale_m=1, max_time=500,
        turbulence_sample_interval_s=0.02)
    field = WindField(conditions)
    samples = field._samples
    np.testing.assert_allclose(samples.mean(axis=0), 0, atol=0.035)
    np.testing.assert_allclose(np.var(samples, axis=0), 1, atol=0.06)
    for axis in range(3):
        lag = 3
        covariance = np.mean(samples[:-lag, axis] * samples[lag:, axis])
        x = 10 * 0.02 * lag
        expected = math.exp(-x) if axis == 0 else (1 - 0.5 * x) * math.exp(-x)
        assert covariance == pytest.approx(expected, abs=0.04)


def test_scheduled_wind_and_temperature_change_preserve_history():
    base = Conditions(wind_model="dryden", wind_speed=5, turbulence=0.2, max_time=10)
    changed = base.model_copy(update={"wind_events": []})
    from rocket_workbench.models import WindEvent
    changed.wind_events = [WindEvent(time_s=3, wind_speed=9, wind_direction=0,
        turbulence=0.4, transition_s=2, temperature_delta=10)]
    old, new = WindField(base), WindField(changed)
    for t in [0, 0.1, 2.9, 3]:
        np.testing.assert_array_equal(old.velocity(t, 20), new.velocity(t, 20))
        assert new.temperature_delta(t) == 0
    assert new.temperature_delta(4) == 5
    assert new.temperature_delta(5) == 10
    assert new.event_times == [3., 5.]
    assert np.linalg.norm(old.velocity(6, 20) - new.velocity(6, 20)) > 1


def test_shear_power_law_uses_height_above_ground():
    field = WindField(Conditions(wind_speed=10, wind_direction=0, turbulence=0,
        wind_shear_exponent=0.2, wind_reference_height_m=10))
    assert field.velocity(1, 0)[1] == 0
    assert field.velocity(1, 10)[1] == 10
    assert field.velocity(1, 100)[1] == pytest.approx(10 * 10 ** 0.2)


def test_dryden_allocation_and_query_guards():
    with pytest.raises(ValueError, match="samples"):
        WindField(Conditions(wind_model="dryden", turbulence_sample_interval_s=1e-5))
    field = WindField(Conditions(wind_model="dryden", max_time=1))
    for time in [-1, 2, math.nan]:
        with pytest.raises(ValueError, match="query"):
            field.velocity(time, 10)


def test_environment_event_validation_is_strict():
    from rocket_workbench.models import WindEvent
    with pytest.raises(ValueError):
        Conditions(wind_events=[WindEvent(time_s=4, wind_speed=8, wind_direction=0,
            turbulence=0.1, transition_s=3), WindEvent(time_s=5, wind_speed=9,
            wind_direction=20, turbulence=0.2)])
