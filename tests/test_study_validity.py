"""Completed-performance statistics must not incorporate partial launch histories."""
import pytest

from rocket_workbench.demo import demo_project
from rocket_workbench.jobs import compare, study
from rocket_workbench.models import Conditions
from rocket_workbench.solvers.flight import simulate


def test_powered_ascent_is_observed_height_not_completed_apogee():
    answer = study(demo_project(), Conditions(max_time=1, wind_speed=0, dt=.05), None,
                   "sweep", {"flight": True, "parameter": "launch_angle", "start": 0, "stop": 2, "count": 2}, None, lambda: False)
    assert answer["statistics"] == {}
    assert answer["sample_counts"]["statistics_eligible"] == 0
    assert answer["sample_counts"]["excluded"] == 2
    for row in answer["rows"]:
        assert row["complete"] is False and row["recovery_reached"] is False
        assert "apogee_m" not in row and 0 < row["observed_apogee_m"] < 100
        assert row["statistics_exclusion_reason"].startswith("Incomplete flight")


def test_mixed_actual_flights_only_aggregate_completed_performance(monkeypatch):
    from rocket_workbench.solvers import flight
    def limited_by_weather(project, conditions, *args, **kwargs):
        return simulate(project, conditions.model_copy(update={"max_time": 1 if conditions.wind_speed > .5 else 300}), *args, **kwargs)
    monkeypatch.setattr(flight, "simulate", limited_by_weather)
    answer = study(demo_project(), Conditions(dt=.1, wind_speed=0), None, "sweep",
                   {"flight": True, "parameter": "wind_speed", "start": 0, "stop": 1, "count": 2}, None, lambda: False)
    full, partial = answer["rows"]
    assert full["complete"] and not partial["complete"]
    assert answer["statistics"]["apogee_m"]["count"] == 1
    assert answer["statistics"]["apogee_m"]["mean"] == pytest.approx(full["apogee_m"])
    assert "observed_apogee_m" not in answer["statistics"]


def test_partial_rigid_body_comparison_does_not_claim_final_flight_deltas():
    answer = compare(demo_project(), Conditions(flight_model="rigid_body", max_time=.2, wind_speed=0),
                     None, {"use_flight": True}, None, lambda: False)
    assert "flight_deltas" not in answer
    assert "observed_flight_deltas" in answer
    assert "6DOF" in answer["fidelity"]
    assert "point-mass flight comparisons" not in answer["fidelity"]
