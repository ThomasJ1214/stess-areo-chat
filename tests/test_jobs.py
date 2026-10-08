"""Study reproducibility and worker lifecycle checks using actual engineering jobs."""
import threading
import time

import pytest

from rocket_workbench.demo import demo_project
from rocket_workbench.jobs import JobManager, study
from rocket_workbench.models import Conditions


def completed(manager, identity):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = manager.get(identity)
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.01)
    raise AssertionError("Engineering job timed out")


def test_run_snapshot_survives_project_edits_and_is_not_polled():
    manager = JobManager()
    try:
        project = demo_project()
        original_mass = project.components[0].mass_override
        submitted = manager.submit(project, "sweep", Conditions(wind_speed=9), options={
            "parameter": "speed", "start": 10, "stop": 20, "count": 2})
        project.components[0].mass_override = 100
        job = completed(manager, submitted["id"])
        assert job["status"] == "completed", job["error"]
        assert "project_snapshot" not in job
        snapshot = manager.input_project(job["id"])
        assert snapshot.components[0].mass_override == original_mass
        assert snapshot.analysis_settings.conditions.wind_speed == 9
        assert snapshot.analysis_settings.study_options["count"] == 2
        assert job["result"]["inputs"]["project_sha256"] == job["project_sha256"]
        import hashlib
        import json
        canonical = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
        assert hashlib.sha256(canonical.encode()).hexdigest() == job["project_sha256"]
        snapshot.components[0].mass_override = 200
        assert manager.input_project(job["id"]).components[0].mass_override == original_mass
    finally:
        manager.shutdown()


def test_sweep_preserves_gust_realization_and_solver_warnings():
    result = study(demo_project(), Conditions(turbulence=.4, seed=7), None, "sweep",
                   {"parameter": "wind_speed", "start": 5, "stop": 10, "count": 2}, None, lambda: False)
    assert [row["gust_seed"] for row in result["rows"]] == [7, 7]
    assert result["gust_seed_policy"] == "common across sweep"
    assert "gust_seed" not in result["statistics"]
    assert result["warnings"] and all(row["fidelity"] for row in result["rows"])


def test_monte_carlo_reports_actual_random_seed_and_is_repeatable():
    options = {"parameter": "wind_speed", "mean": 8, "std": .2, "count": 3, "seed": 91, "flight": False}
    run = lambda: study(demo_project(), Conditions(seed=7), None, "monte_carlo", options, None, lambda: False)
    first, second = run(), run()
    assert first["seed"] == 91
    assert [row["value"] for row in first["rows"]] == [row["value"] for row in second["rows"]]
    assert [row["gust_seed"] for row in first["rows"]] == [91, 92, 93]
    assert first["rows"][0]["warnings"]


@pytest.mark.parametrize("options, message", [
    ({"count": 2.5}, "count"),
    ({"parameter": "speed", "flight": True}, "integrated outputs"),
    ({"parameter": "mach", "flight": True}, "integrated outputs"),
    ({"parameter": "rail_length", "flight": False}, "require flight mode"),
    ({"seed": 1.5}, "integer"),
    ({"seed": True}, "integer"),
    ({"start": float("nan")}, "finite"),
])
def test_invalid_or_ineffective_study_inputs_are_rejected(options, message):
    with pytest.raises(ValueError, match=message):
        study(demo_project(), Conditions(), None, "sweep", options, None, lambda: False)


def test_launch_angle_sweep_changes_actual_flight_path():
    result = study(demo_project(), Conditions(dt=.1, wind_speed=0), None, "sweep",
        {"parameter": "launch_angle", "start": 0, "stop": 20, "count": 2, "flight": True}, None, lambda: False)
    assert result["rows"][0]["apogee_m"] > result["rows"][1]["apogee_m"]
    assert abs(result["rows"][1]["landing_north_m"]) > 10


def test_cancelled_queued_jobs_can_be_pruned_without_worker_errors():
    manager = JobManager()
    gate = threading.Event()
    # Hold the single worker while cancelled queued jobs exceed retention.
    blocker = manager.executor.submit(gate.wait)
    original_submit = manager.executor.submit
    futures = []

    def record_submit(*args, **kwargs):
        future = original_submit(*args, **kwargs)
        futures.append(future)
        return future

    manager.executor.submit = record_submit
    try:
        identities = []
        for _ in range(15):
            identity = manager.submit(demo_project(), "sweep", Conditions(), options={"count": 2})["id"]
            identities.append(identity)
            manager.cancel(identity)
        with pytest.raises(KeyError):
            manager.get(identities[0])
        gate.set()
        blocker.result(timeout=5)
        # An executor barrier proves all prior callbacks have returned.
        manager.executor.submit(lambda: None).result(timeout=5)
        for future in futures:
            future.result(timeout=5)
        assert manager.get(identities[-1])["status"] == "cancelled"
    finally:
        gate.set()
        manager.shutdown()
    with pytest.raises(RuntimeError, match="shutting down"):
        manager.submit(demo_project(), "sweep", Conditions(), options={"count": 2})
