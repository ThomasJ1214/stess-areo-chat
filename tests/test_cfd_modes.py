"""Independent physical-time, limiting-state and bounded playback checks."""
import json

import numpy as np
import pytest
import trimesh

from rocket_workbench.models import Conditions, Project
from rocket_workbench.solvers import cfd


@pytest.fixture
def small_closed_domain(monkeypatch):
    """A small stationary closed cube gives an exact quiescent-air reference."""
    import rocket_workbench.geometry as geometry

    monkeypatch.setattr(geometry, "project_mesh", lambda *args, **kwargs: trimesh.creation.box())
    solid = np.zeros((6, 6, 6), dtype=bool)
    solid[2:4, 2:4, 2:4] = True
    spacing = np.ones(3)
    origin = np.full(3, -2.5)
    monkeypatch.setattr(cfd, "_voxel_domain", lambda *args, **kwargs:
                        (solid.copy(), spacing.copy(), origin.copy(), []))
    return solid, spacing, origin


def _static_conditions():
    return Conditions(speed=0, mach=None, wind_speed=0, angle_of_attack=0, sideslip=0)


def test_quiescent_transient_reaches_requested_time_despite_zero_residual(small_closed_domain):
    events = []
    result = cfd.solve(Project(), _static_conditions(), options={
        "mode": "transient", "duration_s": 0.15, "snapshot_count": 12,
        "backend": "cpu", "sample_limit": 1000, "surface_limit": 2000,
    }, telemetry=events.append)
    summary = result["summary"]
    assert summary["physical_time_s"] == 0.15
    assert summary["status"] == "transient_complete" and summary["completed"]
    assert summary["progress_basis"] == "physical_time"
    assert not summary["converged"] and not summary["pressure_force_steady"]
    assert summary["physical_time_s"] > summary["minimum_convergence_time_s"]
    # This duration passes the 20-step steady criterion; transient must continue.
    assert events[-1]["stable_streak"] > 20
    assert all(row["residual"] == 0 for row in result["history"])
    assert all(row["dt_s"] > 0 for row in result["history"])
    air_pressure = summary["freestream_pressure_pa"]
    for sample in result["samples"]:
        assert sample["pressure_pa"] == pytest.approx(air_pressure, rel=2e-15)
        np.testing.assert_array_equal(sample["velocity"], [0, 0, 0])
    np.testing.assert_allclose(summary["force_n"], 0, atol=1e-12)
    np.testing.assert_allclose(summary["moment_about_origin_nm"], 0, atol=1e-12)
    assert events[0]["phase"] == "voxelization"
    assert events[-1]["phase"] == "complete" and events[-1]["done"]
    assert events[-1]["physical_time_s"] == 0.15
    assert events[-1]["target_physical_time_s"] == 0.15
    json.dumps(result, allow_nan=False)


def test_steady_static_state_converges_without_any_legacy_deadline(small_closed_domain):
    result = cfd.solve(Project(), _static_conditions(), options={
        "mode": "steady", "max_steps": 0, "max_wall_seconds": -10,
        "max_physical_time": 1e-30, "flow_through_times": 0,
        "run_until_converged": False, "backend": "cpu",
    })
    summary = result["summary"]
    assert summary["status"] == "converged" and summary["completed"]
    assert summary["pressure_force_steady"]
    assert summary["physical_time_s"] >= summary["minimum_convergence_time_s"]
    assert summary["steps"] > 20
    assert summary["target_physical_time_s"] is None
    assert summary["estimated_seconds_to_target_flow_time"] is None
    assert summary["max_wall_seconds"] == 0 and summary["max_steps"] is None
    assert len(summary["legacy_stop_options_ignored"]) == 5
    assert "transient" not in result


@pytest.mark.parametrize("duration", [None, 0, -1, True, "bad", float("inf"), float("nan")])
def test_transient_requires_a_positive_finite_duration(duration):
    with pytest.raises(ValueError, match="duration_s"):
        cfd.solve(Project(), _static_conditions(), options={
            "mode": "transient", "duration_s": duration, "backend": "cpu"})


def test_terminal_step_uses_exact_remainder_without_time_interpolation(small_closed_domain, monkeypatch):
    accepted_steps = []
    original_step = cfd.finite_volume_step

    def observe(*args, **kwargs):
        accepted_steps.append(args[3])
        return original_step(*args, **kwargs)

    monkeypatch.setattr(cfd, "finite_volume_step", observe)
    duration = 0.00123456789
    result = cfd.solve(Project(), _static_conditions(), options={
        "mode": "transient", "duration_s": duration, "snapshot_count": 32,
        "backend": "cpu",
    })
    frames = result["transient"]["frames"]
    assert result["summary"]["physical_time_s"] == duration
    assert sum(accepted_steps) == duration
    assert accepted_steps[-1] < accepted_steps[0]
    assert frames[0]["time_s"] == 0 and frames[0]["step"] == 0
    assert frames[-1]["time_s"] == duration
    assert len(frames) <= len(accepted_steps) + 1
    times = [frame["time_s"] for frame in frames]
    assert np.all(np.diff(times) > 0)
    assert all(frame["time_s"] == sum(accepted_steps[:frame["step"]]) for frame in frames)


@pytest.mark.parametrize("cancel_steps", [0, 3])
def test_cancelled_transient_retains_actual_initial_and_latest_fields(small_closed_domain, cancel_steps):
    calls = 0
    def cancelled():
        nonlocal calls
        calls += 1
        return calls > cancel_steps

    result = cfd.solve(Project(), Conditions(mach=0.3, wind_speed=0), options={
        "mode": "transient", "duration_s": 1, "snapshot_count": 2,
        "backend": "cpu", "sample_limit": 1000, "surface_limit": 2000,
    }, cancelled=cancelled)
    summary, transient = result["summary"], result["transient"]
    assert summary["status"] == "cancelled" and not summary["completed"]
    assert not transient["completed"] and not summary["pressure_force_steady"]
    assert summary["steps"] == cancel_steps
    assert transient["frames"][0]["time_s"] == 0
    last = transient["frames"][-1]
    assert last["time_s"] == summary["physical_time_s"] and last["step"] == cancel_steps
    assert len(transient["frames"]) == (1 if cancel_steps == 0 else 2)
    np.testing.assert_array_equal(last["force_n"], summary["force_n"])
    np.testing.assert_array_equal(last["moment_about_origin_nm"], summary["moment_about_origin_nm"])
    assert last["pressure_drag_n"] == summary["pressure_drag_n"]
    for sample, pressure, velocity in zip(result["samples"], last["sample_pressure_pa"], last["sample_velocity_m_s"]):
        assert sample["pressure_pa"] == pressure
        np.testing.assert_array_equal(sample["velocity"], velocity)
    for surface, pressure in zip(result["surface"], last["surface_pressure_pa"]):
        assert surface["pressure_pa"] == pressure


def test_time_varying_prescribed_boundary_is_used_at_real_physical_time(small_closed_domain):
    requested_times = []
    events = []
    def provider(time_s):
        requested_times.append(time_s)
        return dict(density_kg_m3=1.2, pressure_pa=101325,
                    velocity_m_s=[100 + 1000 * time_s, 10, -5],
                    altitude_msl_m=123 + time_s,
                    flight_time_s=10 + time_s)

    result = cfd.solve(Project(), _static_conditions(), options={
        "mode": "transient", "duration_s": 0.006,
        "snapshot_count": 8, "backend": "cpu",
    }, freestream_provider=provider, telemetry=events.append)
    frames = result["transient"]["frames"]
    assert result["summary"]["status"] == "transient_complete"
    assert np.all(np.diff(requested_times) >= 0)
    assert requested_times[-1] == 0.006
    for frame in frames:
        time_s = frame["time_s"]
        assert frame["flight_time_s"] == 10 + time_s
        assert frame["altitude_msl_m"] == 123 + time_s
        np.testing.assert_array_equal(frame["freestream_velocity_m_s"], [100 + 1000 * time_s, 10, -5])
        expected_q = 0.5 * 1.2 * ((100 + 1000 * time_s)**2 + 10**2 + (-5)**2)
        assert frame["dynamic_pressure_pa"] == pytest.approx(expected_q, rel=1e-14)
    assert result["summary"]["flight_time_s"] == 10.006
    assert result["summary"]["freestream_kind"] == "time_varying_prescribed"
    assert not result["summary"]["pressure_force_steady"]
    assert any("one-way" in warning for warning in result["warnings"])
    for event in events:
        if event.get("phase") != "integration":
            continue
        time_s = event["physical_time_s"]
        expected_speed = np.linalg.norm([100 + 1000 * time_s, 10, -5])
        assert event["freestream_mach"] == pytest.approx(expected_speed / np.sqrt(1.4 * 101325 / 1.2))


def test_transient_snapshots_are_bounded_and_share_unchanged_topology(small_closed_domain):
    result = cfd.solve(Project(), Conditions(mach=0.3, wind_speed=0), options={
        "mode": "transient", "duration_s": 0.05, "snapshot_count": 32,
        "backend": "cpu", "sample_limit": 20000, "surface_limit": 30000,
    })
    transient = result["transient"]
    topology = transient["topology"]
    assert len(transient["frames"]) <= 32
    assert topology["flow_grid"]["node_count"] <= 12000
    assert len(topology["sample_positions_m"]) <= 1000
    assert len(topology["surface_positions_m"]) <= 2000
    assert "velocity_m_s" not in topology["flow_grid"]
    assert "freestream_pressure_pa" not in topology
    mask = np.asarray(topology["flow_grid"]["fluid_mask"], dtype=bool)
    for frame in transient["frames"]:
        flow = np.asarray(frame["flow_velocity_m_s"]).reshape(-1, 3)
        assert len(flow) == len(mask)
        np.testing.assert_array_equal(flow[~mask], 0)
        assert len(frame["sample_pressure_pa"]) == len(topology["sample_positions_m"])
        assert len(frame["surface_pressure_pa"]) == len(topology["surface_positions_m"])
    assert "No temporal field interpolation" in transient["temporal_sampling"]
    json.dumps(transient, allow_nan=False)


def test_translating_frame_source_preserves_thermodynamics_and_exact_impulse():
    """Independent force-work identity for optional fixed-axis frame forcing."""
    rho, velocity, pressure = 1.2, np.array([100, 20, -5]), 101325
    state = np.broadcast_to(cfd.conserved(rho, velocity, pressure), (5, 4, 3, 5)).copy()
    solid = np.zeros((5, 4, 3), dtype=bool)
    solid[2, 1, 1] = True
    acceleration, dt = np.array([2, -3, 5]), 0.03
    result = cfd._accelerating_frame_update(state, solid, acceleration, dt)
    final_rho, final_velocity, final_pressure, _ = cfd.primitives(result)
    np.testing.assert_array_equal(final_rho, rho)
    np.testing.assert_allclose(final_velocity[~solid], np.broadcast_to(velocity - acceleration * dt, (59, 3)), rtol=0, atol=2e-14)
    np.testing.assert_allclose(final_pressure[~solid], pressure, rtol=2e-15)
    np.testing.assert_array_equal(result[solid], state[solid])


def test_prescribed_mach_boundary_tolerance_only_allows_floating_point_roundoff():
    sound = np.sqrt(1.4 * 101325 / 1.2)
    def provider(mach):
        return lambda time_s: dict(density_kg_m3=1.2, pressure_pa=101325,
                                  velocity_m_s=[mach * sound, 0, 0])
    accepted = cfd._freestream_environment(provider(2.05 + 5e-13), 0)
    assert accepted["velocity_m_s"][0] > 2.05 * sound  # no clamping
    with pytest.raises(ValueError, match="Mach 2"):
        cfd._freestream_environment(provider(2.05 + 1e-9), 0)
