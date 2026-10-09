"""Independent flight-to-CFD input checks, separate from solved flow fields."""
import copy
import json
import math

import numpy as np
import pytest

from rocket_workbench.models import Component, Conditions, Motor, Project
from rocket_workbench.solvers import aero, flight
from rocket_workbench.solvers.flight_profile import build_flight_profile, _segment_peak_mach


def state(time, velocity, wind=(0, 0, 0), altitude=0, axis=(0, 0, 1), **kwargs):
    atmosphere = aero.atmosphere(altitude, kwargs.pop("temperature_delta", 0))
    row = {
        "time": time, "altitude_msl": altitude, "velocity_vector": list(velocity),
        "wind_vector": list(wind), "body_axis_world": list(axis), "phase": "powered",
        "density_kg_m3": atmosphere["density_kg_m3"], "pressure_pa": atmosphere["pressure_pa"],
        "temperature_k": atmosphere["temperature_k"],
    }
    row.update(kwargs)
    return row


def test_vertical_rocket_uses_air_relative_speed_and_actual_wind_not_ground_speed():
    source = {"trajectory": [state(0, [0, 0, 100], [10, 0, 0]), state(2, [0, 0, 200], [20, 0, 0], altitude=1000)]}
    profile = build_flight_profile(source)
    at_start = profile(0)
    # Tailward X = -world Up, Y = world East, Z = -world North.
    assert at_start["velocity_m_s"] == pytest.approx([100, 10, 0])
    assert at_start["air_relative_speed_m_s"] == pytest.approx(math.sqrt(100**2 + 10**2))
    at_middle = profile(1)
    assert at_middle["velocity_m_s"] == pytest.approx([150, 15, 0])
    assert at_middle["flight_time_s"] == 1
    assert at_middle["altitude_msl_m"] == 500
    expected_rho = sum(row["density_kg_m3"] for row in source["trajectory"]) / 2
    assert at_middle["dynamic_pressure_pa"] == pytest.approx(.5 * expected_rho * (150**2 + 15**2))
    assert "frame_acceleration_m_s2" not in at_middle
    assert any("one-way" in warning for warning in profile.warnings)
    assert any("CFL-limited" in warning for warning in profile.warnings)


def test_arbitrary_body_basis_is_right_handed_and_preserves_velocity_magnitude():
    axis = np.array([1, 2, 3]) / math.sqrt(14)
    velocity = axis * 200
    wind = np.array([3, -4, 5])
    profile = build_flight_profile({"trajectory": [state(0, velocity, wind, axis=axis), state(1, velocity, wind, axis=axis)]})
    result = profile(.4)
    actual = np.array(result["velocity_m_s"])
    assert np.linalg.norm(actual) == pytest.approx(np.linalg.norm(velocity - wind), abs=1e-10)
    assert actual[0] == pytest.approx(np.dot(velocity - wind, axis), abs=1e-10)
    # Vertical rocket east+north input produces -Y,+Z incoming lateral flow.
    vertical = build_flight_profile({"trajectory": [state(0, [3, 4, 100]), state(1, [3, 4, 100])]})
    assert vertical(0)["velocity_m_s"] == pytest.approx([100, -3, 4])
    # A nose pointing east exercises the declared north-reference fallback.
    east = build_flight_profile({"trajectory": [state(0, [100, 4, 3], axis=[1, 0, 0]), state(1, [100, 4, 3], axis=[1, 0, 0])]})
    assert east(0)["velocity_m_s"] == pytest.approx([100, -4, 3])


def test_selected_interval_exact_endpoints_and_self_contained_roundtrip_are_immutable():
    source = {"trajectory": [state(0, [0, 0, 0]), state(2, [0, 0, 100], altitude=200), state(4, [0, 0, 200], altitude=1000)],
              "events": [{"name": "burnout", "time": 2}, {"name": "apogee", "time": 10}]}
    original = copy.deepcopy(source)
    profile = build_flight_profile(source, start_s=.5, end_s=3)
    assert profile.duration_s == 2.5
    assert profile(0)["flight_time_s"] == .5
    assert profile(0)["velocity_m_s"][0] == pytest.approx(25)
    assert profile(2.5)["flight_time_s"] == 3
    assert profile(2.5)["velocity_m_s"][0] == pytest.approx(150)
    assert profile.metadata["events"] == [{"name": "burnout", "time": 2}]
    saved = profile.to_dict()
    assert [row["time"] for row in saved["trajectory"]] == [.5, 2, 3]
    restored = build_flight_profile(saved)
    assert restored.metadata["profile_sha256"] == profile.metadata["profile_sha256"]
    for at_time in (0, .25, 1, 2.5):
        assert restored(at_time) == profile(at_time)
    source["trajectory"][1]["velocity_vector"][2] = 9000
    saved["trajectory"][1]["pressure_pa"] = -1
    assert profile(1.5)["velocity_m_s"][0] == pytest.approx(100)
    assert original["trajectory"][1]["velocity_vector"][2] == 100
    json.dumps(profile.to_dict(), allow_nan=False)
    with pytest.raises(ValueError, match="outside"):
        profile(2.6)
    with pytest.raises(ValueError, match="outside"):
        profile(-.1)


def test_varying_axis_selected_window_preserves_whole_profile_direction_and_roundtrip():
    source = {"trajectory": [
        state(0, [0, 20, 100], [6, 2, 0], axis=[0, 0, 1]),
        state(2, [80, 40, 120], [9, 5, 0], axis=[.8, .2, .6]),
        state(4, [90, 80, 60], [11, 7, 0], axis=[.9, .5, .2]),
    ]}
    whole = build_flight_profile(source)
    window = build_flight_profile(source, start_s=.3, end_s=3.2)
    restored = build_flight_profile(window.to_dict())
    assert restored.metadata["profile_sha256"] == window.metadata["profile_sha256"]
    for at_time in (.3, .6, 1.1, 1.9, 2.7, 3.2):
        expected = whole(at_time)
        for actual in (window(at_time - .3), restored(at_time - .3)):
            assert actual["velocity_m_s"] == pytest.approx(expected["velocity_m_s"], abs=1e-10)
            assert actual["body_axis_world"] == pytest.approx(expected["body_axis_world"], abs=1e-10)
            assert actual["freestream_mach"] == pytest.approx(expected["freestream_mach"], abs=1e-12)


def test_antipodal_apogee_axes_are_finite_without_inventing_rotation():
    source = {"trajectory": [state(0, [0, 0, 10], axis=[0, 0, 1]),
                              state(2, [0, 0, -10], axis=[0, 0, -1])]}
    whole = build_flight_profile(source)
    window = build_flight_profile(source, start_s=1, end_s=2)
    restored = build_flight_profile(window.to_dict())
    assert any("not a resolved physical rotation" in warning for warning in whole.warnings)
    for at_time in (1, 1.001, 1.1, 1.9, 2):
        expected = whole(at_time)
        for actual in (window(at_time - 1), restored(at_time - 1)):
            assert all(math.isfinite(value) for value in actual["velocity_m_s"])
            assert actual["velocity_m_s"] == pytest.approx(expected["velocity_m_s"], abs=1e-10)
            assert actual["body_axis_world"] == pytest.approx(expected["body_axis_world"], abs=1e-10)


def test_old_history_reconstructs_inclined_rail_and_temperature_offset():
    axis = np.array([0, math.sin(math.radians(10)), math.cos(math.radians(10))])
    rows = [state(0, [0, 0, 0], wind=[4, 0, 0]), state(1, axis * 100, wind=[4, 0, 0])]
    for row in rows:
        for field in ("body_axis_world", "density_kg_m3", "pressure_pa", "temperature_k"):
            del row[field]
    profile = build_flight_profile({"trajectory": rows}, temperature_delta=20)
    assert profile(1)["velocity_m_s"][0] == pytest.approx(100)
    assert profile(0)["density_kg_m3"] == pytest.approx(101325 / (287.05287 * 308.15))
    assert any("Older flight" in warning for warning in profile.warnings)


def test_legacy_window_at_zero_velocity_uses_preceding_axis_instead_of_rail():
    rows = [state(0, [0, 0, 10]), state(1, [0, 10, 0]), state(2, [0, 0, 0]), state(3, [0, -10, 0])]
    for row in rows:
        del row["body_axis_world"]
    profile = build_flight_profile({"trajectory": rows}, start_s=2, end_s=3)
    assert profile(0)["body_axis_world"] == pytest.approx([0, 1, 0])


def test_selected_interval_rejects_mach_excess_without_clamping_but_valid_interval_survives():
    source = {"trajectory": [state(0, [0, 0, 100]), state(1, [0, 0, 100]), state(2, [0, 0, 1000])]}
    with pytest.raises(ValueError, match="No speed was clamped"):
        build_flight_profile(source)
    valid = build_flight_profile(source, start_s=0, end_s=.5)
    assert valid(.5)["velocity_m_s"] == pytest.approx([100, 0, 0])


def test_launch_high_to_low_mach_warns_even_when_initial_flow_is_above_point_three():
    source = {"trajectory": [state(0, [0, 0, 400]), state(2, [0, 0, 20])]}
    profile = build_flight_profile(source)
    sound = math.sqrt(1.4 * 287.05287 * 288.15)
    assert profile(0)["freestream_mach"] > .3
    assert profile.metadata["min_incoming_mach"] == pytest.approx(20 / sound, abs=1e-12)
    assert profile.metadata["max_incoming_mach"] == pytest.approx(400 / sound, abs=1e-12)
    assert any("Mach below 0.3" in warning and "pressure drag" in warning for warning in profile.warnings)


def test_interior_relative_velocity_cancellation_detects_zero_mach_despite_fast_endpoints():
    source = {"trajectory": [state(0, [0, 0, 200]), state(2, [0, 0, -200])]}
    profile = build_flight_profile(source)
    assert profile(0)["freestream_mach"] > .3
    assert profile(2)["freestream_mach"] > .3
    assert profile(1)["freestream_mach"] == 0
    assert profile.metadata["min_incoming_mach"] == pytest.approx(0, abs=1e-12)
    assert any("Mach below 0.3" in warning for warning in profile.warnings)
    # Selecting a fast portion must not inherit the warning from excluded flow.
    fast = build_flight_profile(source, start_s=0, end_s=.1)
    assert fast.metadata["min_incoming_mach"] > .3
    assert not any("Mach below 0.3" in warning for warning in fast.warnings)


def test_segment_mach_peak_matches_dense_independent_evaluation():
    # Changing atmospheric primitives can put the maximum inside a segment;
    # validate polynomial stationary points against independent dense sampling.
    rng = np.random.default_rng(214)
    fractions = np.linspace(0, 1, 20001)
    for _ in range(20):
        v0, v1 = rng.normal(0, 100, (2, 3))
        rho0, rho1 = rng.uniform(.1, 1.8, 2)
        p0, p1 = rng.uniform(10000, 110000, 2)
        relative = v0[None, :] + fractions[:, None] * (v1 - v0)[None, :]
        rho = rho0 + fractions * (rho1 - rho0)
        pressure = p0 + fractions * (p1 - p0)
        expected = np.max(np.linalg.norm(relative, axis=1) / np.sqrt(1.4 * pressure / rho))
        assert _segment_peak_mach(v0, v1, rho0, rho1, p0, p1) == pytest.approx(expected, rel=1e-8)


@pytest.mark.parametrize("change,match", [
    (lambda rows: rows[1].update(time=0), "strictly increasing"),
    (lambda rows: rows[1].update(velocity_vector=[0, float("nan"), 2]), "finite three"),
    (lambda rows: rows[1].update(pressure_pa=-1), "positive"),
    (lambda rows: rows[1].update(body_axis_world=[0, 0, 0]), "nonzero"),
    (lambda rows: rows[1].update(air_relative_speed=999), "disagrees"),
    (lambda rows: rows[1].update(air_relative_velocity_vector=[0, 0, 999]), "disagrees"),
    (lambda rows: rows[1].update(altitude_msl=50001), "atmospheric"),
])
def test_untrusted_history_invalid_states_are_rejected(change, match):
    rows = [state(0, [0, 0, 20]), state(1, [0, 0, 40])]
    change(rows)
    with pytest.raises(ValueError, match=match):
        build_flight_profile({"trajectory": rows})


@pytest.mark.parametrize("start,end", [(-.1, .5), (0, 2), (.7, .7), (.8, .4), (float("nan"), 1)])
def test_invalid_selected_window_is_rejected(start, end):
    with pytest.raises(ValueError):
        build_flight_profile({"trajectory": [state(0, [0, 0, 20]), state(1, [0, 0, 40])]}, start_s=start, end_s=end)


def test_recovery_and_incomplete_flight_are_declared_and_not_extrapolated():
    source = {"trajectory": [state(0, [0, 0, -10], phase="drogue"), state(1, [0, 0, -5], phase="main")],
              "summary": {"complete": False}}
    profile = build_flight_profile(source)
    assert any("parachutes" in warning for warning in profile.warnings)
    assert any("incomplete" in warning for warning in profile.warnings)
    assert profile.duration_s == 1


def test_real_computed_flight_profile_matches_every_sampled_airspeed_atmosphere_and_mach():
    project = Project(components=[
        Component(id="nose", kind="nosecone", length=.3, radius=.05, mass_override=.4),
        Component(id="body", x=.3, length=1.2, radius=.05, mass_override=1.5),
        Component(id="fins", kind="trapezoidfinset", x=1.18, root_chord=.25, tip_chord=.12,
                  span=.12, sweep=.12, radius=.05, mass_override=.3),
    ], motors=[Motor(id="motor", dry_mass=.4, propellant_mass=.4, curve=[[0, 0], [.1, 200], [2, 200], [2.1, 0]],
                     source="Synthetic reference curve, not real flight hardware")])
    project.configurations[0].motor_id = "motor"
    conditions = Conditions(dt=.05, max_time=15, wind_speed=6, wind_direction=60,
                            launch_angle=7, launch_azimuth=30, turbulence=.15, seed=8, altitude=800, temperature_delta=10)
    result = flight.simulate(project, conditions)
    profile = build_flight_profile(result, end_s=10, temperature_delta=conditions.temperature_delta)
    for row in result["trajectory"][::11]:
        if row["time"] > 10:
            continue
        boundary = profile(row["time"])
        assert boundary["air_relative_speed_m_s"] == pytest.approx(row["air_relative_speed"], abs=1e-8)
        assert np.linalg.norm(boundary["velocity_m_s"]) == pytest.approx(row["air_relative_speed"], abs=1e-8)
        assert boundary["altitude_msl_m"] == pytest.approx(row["altitude_msl"], abs=1e-8)
        assert boundary["freestream_mach"] == pytest.approx(row["mach"], abs=1e-9)
        assert boundary["dynamic_pressure_pa"] == pytest.approx(row["dynamic_pressure"], rel=1e-12, abs=1e-8)
        atmosphere = aero.atmosphere(row["altitude_msl"], conditions.temperature_delta)
        assert boundary["pressure_pa"] == pytest.approx(atmosphere["pressure_pa"], rel=1e-12)
        assert boundary["density_kg_m3"] == pytest.approx(atmosphere["density_kg_m3"], rel=1e-12)
    assert result["trajectory"][0]["velocity"] == 0
    assert profile(0)["air_relative_speed_m_s"] > 0  # actual pad wind, not zero ground speed
