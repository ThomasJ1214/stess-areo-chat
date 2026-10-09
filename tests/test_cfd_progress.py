"""ETA reference cases independent of finite-volume implementation details."""
import math

import pytest

from rocket_workbench.cfd_progress import CfdProgress


def transient_event(wall, physical, target=20):
    return {"mode": "transient", "phase": "integration",
            "integration_elapsed_seconds": wall, "physical_time_s": physical,
            "integration_steps": wall * 100, "target_physical_time_s": target}


def steady_event(wall, residuals):
    return {"mode": "steady", "phase": "integration",
            "integration_elapsed_seconds": wall, "physical_time_s": wall * .01,
            "integration_steps": wall * 100, "minimum_convergence_time_s": .001,
            "convergence_tolerance": 1e-4, "stable_streak": 0,
            "required_stable_steps": 20,
            **dict(zip(("residual", "wall_pressure_residual", "force_residual", "moment_residual"), residuals))}


def test_transient_eta_uses_measured_physical_rate_and_excludes_startup():
    progress = CfdProgress()
    assert progress.update({"mode": "transient", "phase": "voxelization", "elapsed_seconds": 900})["eta_seconds"] is None
    for wall in range(1, 5):
        answer = progress.update(transient_event(wall, 2 * wall))
    # 20 seconds requested, 8 reached, advancing 2 physical seconds/wall second.
    assert answer["eta_seconds"] == pytest.approx(6)
    assert answer["eta_range_seconds"] == pytest.approx([6, 6])
    assert answer["eta_basis"] == "physical_time_throughput"
    assert answer["eta_confidence"] == "measured"
    assert progress.update({"mode": "transient", "phase": "extraction"})["eta_seconds"] is None


def test_steady_exponential_decay_eta_matches_analytic_threshold_crossing():
    progress = CfdProgress()
    # The initialization callback has no accepted-step residuals. It supplies
    # throughput timing but must not delay valid residual fits until eviction.
    progress.update(steady_event(0, (None, None, None, None)))
    amplitudes = (1., .2, .3, .4)
    decay_rates = (.4, .3, .6, .5)
    for index in range(12):
        wall = (index + 1) * .5
        residuals = [amplitude * math.exp(-rate * wall) for amplitude, rate in zip(amplitudes, decay_rates)]
        answer = progress.update(steady_event(wall, residuals))
    # Every residual must cross 1e-4. Then another 20 steps at 100 steps/s
    # confirms stability; the half-crossing minimum time has already passed.
    remaining = max(math.log(amplitude / 1e-4) / rate - wall
                    for amplitude, rate in zip(amplitudes, decay_rates))
    assert answer["eta_seconds"] == pytest.approx(remaining + .2)
    assert answer["eta_range_seconds"] == pytest.approx([remaining + .2, remaining + .2])
    assert answer["eta_basis"] == "convergence_trend"
    assert answer["eta_confidence"] == "tentative"


@pytest.mark.parametrize("kind", ["plateau", "growing_mode", "stalled_recently", "oscillating"])
def test_steady_eta_is_unknown_without_consistent_decay_in_all_residuals(kind):
    progress = CfdProgress()
    for wall in range(16):
        residual = math.exp(-.2 * wall)
        values = [residual] * 4
        if kind == "plateau":
            values[1] = .1
        elif kind == "growing_mode":
            values[2] = .01 * math.exp(.1 * wall)
        elif kind == "stalled_recently":
            values = [math.exp(-.2 * min(wall, 7))] * 4
        else:
            values[3] *= 4 if wall % 2 else .2
        answer = progress.update(steady_event(wall, values))
    assert answer["eta_seconds"] is None
    assert answer["eta_basis"] is None


def test_eta_requires_observations_and_never_reuses_another_comparison_stage():
    progress = CfdProgress()
    for wall in range(1, 5):
        answer = progress.update(transient_event(wall, wall) | {"comparison_stage": "original"})
    assert answer["eta_seconds"] == 16
    answer = progress.update(transient_event(1, 1) | {"comparison_stage": "replacement"})
    assert answer["eta_seconds"] is None


def test_no_progress_and_invalid_telemetry_have_unknown_eta():
    progress = CfdProgress()
    for wall in range(1, 8):
        assert progress.update(transient_event(wall, 0))["eta_seconds"] is None
    assert progress.update(transient_event(float("nan"), 2))["eta_seconds"] is None
    assert progress.update(transient_event(10, 2) | {"target_physical_time_s": float("inf")})["eta_seconds"] is None
