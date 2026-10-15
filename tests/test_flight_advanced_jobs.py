"""Actual advanced flight jobs and immutable source-history admission."""
import json
import time

import pytest

from rocket_workbench.demo import demo_project
from rocket_workbench.jobs import JobManager
from rocket_workbench.models import Conditions, WindEvent


def finish(manager, identity):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = manager.get(identity)
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(.01)
    raise AssertionError("Actual advanced flight job did not finish within its test timeout.")


def test_dynamic_fin_job_preserves_estimates_and_exposes_real_aligned_states():
    manager = JobManager()
    try:
        project = demo_project()
        conditions = Conditions(wind_speed=0, turbulence=0, max_time=2, dt=.05)
        options = {"structural_mode": "dynamic_fins", "allow_isotropic_surrogate": True,
                   "elements": 4, "steps_per_period": 20}
        job = finish(manager, manager.submit(project, "flight", conditions, options=options)["id"])
        assert job["status"] == "completed", job["error"]
        result = job["result"]
        assert result["dynamic_structural_analysis"]["summary"]["substeps"] > 0
        assert result["dynamic_structural_analysis"]["summary"]["supported_components"] > 0
        assert all("stress" in row and "dynamic_stress" in row for row in result["trajectory"])
        assert any(row["dynamic_structural_components"] for row in result["trajectory"])
        assert result["inputs"]["options"] == options
        assert manager.input_project(job["id"]).analysis_settings.flight_options == options
        assert "max_dynamic_fin_stress_pa" in result["summary"]
        assert any(event["name"] == "max_dynamic_fin_stress" for event in result["events"])
        json.dumps(result, allow_nan=False)
    finally:
        manager.shutdown()


@pytest.mark.parametrize("update", [
    {"flight_model": "rigid_body"},
    {"wind_model": "dryden"},
    {"wind_shear_exponent": .15},
    {"initial_angular_velocity_body_rad_s": [0, .1, 0]},
    {"wind_events": [WindEvent(time_s=.5, wind_speed=12, wind_direction=180, turbulence=.1)]},
])
def test_old_launch_cannot_drive_cfd_after_new_physical_inputs_change(update):
    manager = JobManager()
    try:
        project = demo_project()
        conditions = Conditions(wind_speed=0, max_time=2, dt=.1)
        launch = finish(manager, manager.submit(project, "flight", conditions)["id"])
        assert launch["status"] == "completed", launch["error"]
        changed = conditions.model_copy(update=update)
        with pytest.raises(ValueError, match="Launch conditions changed"):
            manager.submit(project, "cfd", changed, options={"mode": "transient",
                "transient_source": "launch", "flight_job_id": launch["id"]})
    finally:
        manager.shutdown()


def test_unknown_flight_structural_mode_cannot_be_silently_ignored():
    manager = JobManager()
    try:
        with pytest.raises(ValueError, match="structural mode"):
            manager.submit(demo_project(), "flight", Conditions(), options={"structural_mode": "fake_solid_transient"})
    finally:
        manager.shutdown()
