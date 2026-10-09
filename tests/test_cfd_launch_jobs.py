"""Real launch-to-Euler job integration and immutable source validation."""
import bisect
import json
import time

import numpy as np
import pytest

from rocket_workbench.demo import demo_project
from rocket_workbench.jobs import JobManager
from rocket_workbench.models import Conditions
from rocket_workbench.solvers.flight_profile import build_flight_profile


def finished(manager, identity):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = manager.get(identity)
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(.01)
    raise AssertionError("The real integration reference job did not finish")


@pytest.fixture(scope="module")
def actual_launch():
    manager = JobManager()
    project = demo_project()
    conditions = Conditions(dt=.1, wind_speed=3, turbulence=.1, seed=19)
    submitted = manager.submit(project, "flight", conditions)
    flight = finished(manager, submitted["id"])
    assert flight["status"] == "completed", flight["error"]
    yield manager, project, conditions, flight
    manager.shutdown()


def options(flight_id=None):
    return {"mode": "transient", "transient_source": "launch",
            "flight_start_s": 1., "flight_end_s": 1.0001,
            **({"flight_job_id": flight_id} if flight_id else {}),
            "backend": "cpu", "grid_resolution": 12, "transverse_resolution": 12,
            "max_cells": 50000, "sample_limit": 30, "surface_limit": 30, "snapshot_count": 4}


def actual_relative_velocity(rows, time):
    """Independent linear interpolation of saved physical vehicle/wind vectors."""
    times = [row["time"] for row in rows]
    index = min(len(rows) - 2, max(0, bisect.bisect_right(times, time) - 1))
    fraction = (time - times[index]) / (times[index + 1] - times[index])
    vectors = [np.asarray(rows[i]["velocity_vector"]) - np.asarray(rows[i]["wind_vector"])
               for i in (index, index + 1)]
    return vectors[0] + fraction * (vectors[1] - vectors[0])


def test_actual_saved_launch_drives_cfd_physical_time_and_each_frame(actual_launch):
    manager, project, conditions, flight = actual_launch
    submitted = manager.submit(project, "cfd", conditions, options=options(flight["id"]))
    job = finished(manager, submitted["id"])
    assert job["status"] == "completed", job["error"]
    assert job["progress_basis"] == "physical_time"
    result = job["result"]
    assert result["summary"]["status"] == "transient_complete"
    assert result["summary"]["physical_time_s"] == pytest.approx(.0001)
    assert not result["summary"]["converged"] and not result["summary"]["pressure_force_steady"]
    frames = result["transient"]["frames"]
    assert frames[0]["flight_time_s"] == 1.
    assert frames[-1]["flight_time_s"] == pytest.approx(1.0001)
    for frame in frames:
        relative = actual_relative_velocity(flight["result"]["trajectory"], frame["flight_time_s"])
        assert np.linalg.norm(frame["freestream_velocity_m_s"]) == pytest.approx(np.linalg.norm(relative), rel=1e-12)
    assert np.linalg.norm(frames[-1]["freestream_velocity_m_s"]) != pytest.approx(
        np.linalg.norm(frames[0]["freestream_velocity_m_s"]), rel=1e-8)
    source = result["inputs"]["flight_source"]
    assert source["job_id"] == flight["id"] and not source["generated_for_cfd"]
    replay = build_flight_profile(source["profile"])
    assert replay.metadata["profile_sha256"] == source["profile_sha256"]
    assert source["inputs"] == flight["result"]["inputs"]
    assert "flight_result" not in job and "flight_source" not in job
    json.dumps(job, allow_nan=False)
    with pytest.raises(ValueError, match="completed, numerically converged CFD"):
        manager.submit(project, "fea", conditions, options={"component_id": "nose",
            "load_mode": "cfd_pressure", "cfd_job_id": job["id"]})


def test_launch_driven_cfd_calculates_a_real_launch_when_none_selected(actual_launch):
    manager, project, conditions, flight = actual_launch
    job = finished(manager, manager.submit(project, "cfd", conditions, options=options())["id"])
    assert job["status"] == "completed", job["error"]
    source = job["result"]["inputs"]["flight_source"]
    assert source["generated_for_cfd"] and source["job_id"] is None
    assert source["profile_sha256"]
    expected = actual_relative_velocity(flight["result"]["trajectory"], 1.)
    assert np.linalg.norm(job["result"]["transient"]["frames"][0]["freestream_velocity_m_s"]) == pytest.approx(np.linalg.norm(expected))


@pytest.mark.parametrize("change", ["motor", "recovery", "material", "geometry", "configuration"])
def test_saved_launch_is_rejected_after_physical_project_changes(actual_launch, change):
    manager, original, conditions, flight = actual_launch
    project = original.model_copy(deep=True)
    if change == "motor":
        project.motors[0].propellant_mass += .1
    elif change == "recovery":
        project.configurations[0].drogue_cd_area += .1
    elif change == "material":
        project.materials[0].density += 100
    elif change == "configuration":
        project.active_configuration_id = "single"
    else:
        project.components[1].radius += .01
    with pytest.raises(ValueError, match="changed after this launch"):
        manager.submit(project, "cfd", conditions, options=options(flight["id"]))


def test_saved_launch_is_rejected_after_wind_changes_but_allows_display_settings(actual_launch):
    manager, original, conditions, flight = actual_launch
    with pytest.raises(ValueError, match="Launch conditions changed"):
        manager.submit(original, "cfd", conditions.model_copy(update={"wind_speed": 4}), options=options(flight["id"]))
    project = original.model_copy(deep=True)
    project.analysis_settings.cfd_options = {"backend": "cpu", "mode": "transient"}
    project.unit_system = "us"
    project.name = "The same rocket with another display title"
    # Panel changes do not change the rocket source. The job still runs against
    # the immutable earlier flight, as the source hash check demonstrates.
    submitted = manager.submit(project, "cfd", conditions, options=options(flight["id"]))
    job = finished(manager, submitted["id"])
    assert job["status"] == "completed", job["error"]


def test_comparison_cannot_silently_treat_launch_transient_as_steady(actual_launch):
    manager, project, conditions, _ = actual_launch
    with pytest.raises(ValueError, match="comparisons require steady"):
        manager.submit(project, "comparison", conditions, options={"mode": "transient", "use_cfd": True})
