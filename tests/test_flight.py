import json
import math

import pytest

from rocket_workbench.models import Component, Conditions, FlightConfiguration, Motor, Project
from rocket_workbench.solvers import aero, flight


def rocket(deployment="dual"):
    p = Project(components=[
        Component(id="nose", kind="nosecone", length=.3, radius=.05, mass_override=.4),
        Component(id="body", x=.3, length=1.2, radius=.05, mass_override=1.5),
        Component(id="fins", kind="trapezoidfinset", x=1.18, root_chord=.25, tip_chord=.12,
                  span=.12, sweep=.12, radius=.05, mass_override=.3),
        Component(id="payload", kind="masscomponent", x=.5, mass_override=.5),
    ], motors=[Motor(id="motor", dry_mass=.4, propellant_mass=.4,
                     curve=[[0, 0], [.1, 200], [2, 200], [2.1, 0]], source="Synthetic validation motor, not flight hardware")])
    p.configurations[0].motor_id = "motor"
    p.configurations[0].deployment = deployment
    return p


def conditions(**kwargs):
    values = dict(dt=.05, max_time=180, wind_speed=0, launch_angle=0)
    values.update(kwargs)
    return Conditions(**values)


def event(result, name):
    return next(e for e in result["events"] if e["name"] == name)


def test_dual_deployment_timeline_mass_and_complete_recovery():
    result = flight.simulate(rocket(), conditions())
    rows = result["trajectory"]
    names = {e["name"] for e in result["events"]}
    assert {"ignition", "rail_exit", "burnout", "apogee", "drogue_deployment", "main_deployment", "recovery", "max_q", "max_acceleration"} <= names
    assert result["summary"]["complete"] is True
    assert rows[-1]["altitude"] == 0
    assert all(b["time"] > a["time"] for a, b in zip(rows, rows[1:]))
    assert event(result, "rail_exit")["time"] < event(result, "burnout")["time"] < event(result, "apogee")["time"]
    assert event(result, "drogue_deployment")["time"] - event(result, "apogee")["time"] == pytest.approx(.5, abs=1e-8)
    main = rows[event(result, "main_deployment")["index"]]
    assert main["altitude"] == pytest.approx(250, abs=1e-6)
    assert main["phase"] == "main"
    assert rows[0]["mass"] == pytest.approx(3.5)
    assert rows[event(result, "burnout")["index"]]["mass"] == pytest.approx(3.1)
    assert abs(rows[event(result, "apogee")["index"]]["vertical_velocity"]) < 1e-7
    assert max(abs(row["east"]) + abs(row["north"]) for row in rows) == 0
    assert any("no attitude" in warning for warning in result["warnings"])
    json.dumps(result, allow_nan=False)


def test_single_deployment_and_ignition_delay():
    p = rocket("single")
    p.configurations[0].ignition_delay = .7
    result = flight.simulate(p, conditions())
    names = {e["name"] for e in result["events"]}
    assert "drogue_deployment" not in names
    assert event(result, "ignition")["time"] == pytest.approx(.7)
    assert event(result, "burnout")["time"] == pytest.approx(2.8)
    assert event(result, "main_deployment")["time"] - event(result, "apogee")["time"] == pytest.approx(.5)
    assert all(row["altitude"] == 0 for row in result["trajectory"] if row["time"] < .7)


def test_zero_delay_deploys_at_apogee_and_low_apogee_main_rule():
    p = rocket()
    p.configurations[0].apogee_delay = 0
    p.configurations[0].main_deploy_altitude = 1000
    result = flight.simulate(p, conditions())
    assert event(result, "drogue_deployment")["time"] == event(result, "apogee")["time"]
    assert event(result, "main_deployment")["time"] == event(result, "apogee")["time"]
    assert result["summary"]["complete"]


def test_motor_ejection_trigger_has_actual_delay_and_can_deploy_ascending():
    p = rocket("single")
    p.configurations[0].primary_deploy_event = "motor_ejection"
    p.configurations[0].motor_ejection_delay = 1.0
    p.configurations[0].apogee_delay = .2
    result = flight.simulate(p, conditions())
    assert event(result, "motor_ejection")["time"] == pytest.approx(3.3, abs=1e-8)
    assert event(result, "main_deployment")["time"] == pytest.approx(3.3, abs=1e-8)
    row = result["trajectory"][event(result, "main_deployment")["index"]]
    assert row["vertical_velocity"] > 0
    assert event(result, "apogee")["time"] > 3.3
    assert result["summary"]["complete"]
    p.configurations[0].motor_ejection_delay = None
    with pytest.raises(ValueError, match="actual ejection delay"):
        flight.simulate(p, conditions())


def test_ejection_after_ground_contact_reports_an_undeployed_impact():
    p = rocket("single")
    p.configurations[0].primary_deploy_event = "motor_ejection"
    p.configurations[0].motor_ejection_delay = 100
    result = flight.simulate(p, conditions(max_time=60))
    assert result["summary"]["complete"] is True
    assert result["summary"]["recovery_deployed"] is False
    assert result["summary"]["landing_velocity_m_s"] > 20
    assert not any(item["name"] == "main_deployment" for item in result["events"])
    assert any("undeployed ground impact" in warning for warning in result["warnings"])


def test_vacuum_triangular_motor_matches_closed_form_ballistics(monkeypatch):
    original = aero.atmosphere
    def vacuum(altitude, temperature_delta=0):
        result = original(0)
        result.update(density_kg_m3=0.0, gravity_m_s2=aero.G0)
        return result
    monkeypatch.setattr(aero, "atmosphere", vacuum)
    p = rocket("single")
    p.motors[0].propellant_mass = 0
    p.motors[0].curve = [[0, 0], [1, 200], [2, 0]]
    p.configurations[0].apogee_delay = 0
    # Constant mass; triangular F(t), constrained on pad until F > m*g.
    mass, peak, g = 3.1, 200.0, aero.G0
    liftoff = mass*g/peak
    burnout_velocity = peak/mass - 2*g + .5*g*liftoff
    burnout_height = peak/mass - 2*g + g*liftoff - g*liftoff**2/6
    expected_apogee = burnout_height + burnout_velocity**2/(2*g)
    result = flight.simulate(p, conditions(dt=.005, rail_length=.2, max_time=30))
    row = result["trajectory"][event(result, "burnout")["index"]]
    assert row["vertical_velocity"] == pytest.approx(burnout_velocity, abs=.002)
    assert row["altitude"] == pytest.approx(burnout_height, abs=.004)
    assert result["summary"]["apogee_m"] == pytest.approx(expected_apogee, abs=.02)
    assert result["summary"]["total_impulse_ns"] == pytest.approx(200)


def test_step_halving_converges_and_canopy_large_step_stays_stable():
    coarse = flight.simulate(rocket(), conditions(dt=.1))
    fine = flight.simulate(rocket(), conditions(dt=.05))
    assert coarse["summary"]["apogee_m"] == pytest.approx(fine["summary"]["apogee_m"], rel=.001)
    assert coarse["summary"]["flight_time_s"] == pytest.approx(fine["summary"]["flight_time_s"], rel=.001)
    p = rocket()
    p.configurations[0].main_cd_area = 30
    large = flight.simulate(p, conditions(dt=.2, max_time=300))
    assert all(math.isfinite(row["velocity"]) for row in large["trajectory"])
    assert max(row["vertical_velocity"] for row in large["trajectory"] if row["phase"] == "main") <= 0


def test_wind_drift_turbulence_seed_and_progress():
    updates = []
    c = conditions(wind_speed=6, wind_direction=90, turbulence=.1, seed=6, max_time=25, dt=.1)
    a = flight.simulate(rocket(), c, progress=lambda fraction, message: updates.append((fraction, message)))
    b = flight.simulate(rocket(), c)
    assert a["trajectory"] == b["trajectory"]
    assert a["trajectory"][-1]["east"] > 0
    assert updates[0][0] == 0 and updates[-1][0] == 1
    assert all(y[0] >= x[0] for x, y in zip(updates, updates[1:]))
    assert a["summary"]["complete"] is False
    assert any("incomplete" in warning for warning in a["warnings"])


@pytest.mark.parametrize("feature", ["multistage", "cluster", "active_guidance", "deployment_event"])
def test_unsupported_configuration_fails_explicitly(feature):
    p = rocket()
    p.metadata["unsupported_features"] = [feature]
    with pytest.raises(ValueError, match=feature):
        flight.simulate(p, conditions())


def test_missing_motor_invalid_curve_no_liftoff_and_cancel():
    p = rocket()
    p.configurations[0].motor_id = None
    with pytest.raises(ValueError, match="real thrust curve"):
        flight.simulate(p, conditions())
    p = rocket()
    with pytest.raises(ValueError, match="increase strictly"):
        p.motors[0].curve = [[0, 1], [1, 1], [1, 0]]
    p = rocket()
    p.motors[0].curve = []
    with pytest.raises(ValueError, match="at least two"):
        flight.simulate(p, conditions())
    p.motors[0].curve = [[0, 0], [.1, 1], [1, 0]]
    with pytest.raises(ValueError, match="cannot lift"):
        flight.simulate(p, conditions())
    with pytest.raises(RuntimeError, match="cancelled"):
        flight.simulate(rocket(), conditions(), cancelled=lambda: True)


def test_supplied_polar_changes_trajectory_and_invalidates_on_geometry_change():
    p = rocket()
    original = flight.simulate(p, conditions(max_time=20))
    signature = aero.geometry_signature(p)
    p.metadata["aerodynamic_polars"] = [
        {"mach": 0, "cd": 2, "cna": 10, "cp_m": 1.2, "source": "synthetic sensitivity test", "geometry_signature": signature},
        {"mach": 2, "cd": 2, "cna": 10, "cp_m": 1.2, "source": "synthetic sensitivity test", "geometry_signature": signature},
    ]
    draggy = flight.simulate(p, conditions(max_time=20))
    assert draggy["summary"]["apogee_m"] < original["summary"]["apogee_m"]
    assert all(row["polar_applied"] for row in draggy["trajectory"])
    assert draggy["validity"]["polar_covers_full_flight"] is True
    p.components[2].span *= 1.01
    stale = flight.simulate(p, conditions(max_time=20))
    assert all(not row["polar_applied"] for row in stale["trajectory"])
    assert any("stale" in warning for warning in stale["warnings"])


def test_unstable_supplied_cp_is_reported_without_pretending_tumble_dynamics():
    p = rocket()
    signature = aero.geometry_signature(p)
    p.metadata["aerodynamic_polars"] = [
        {"mach": mach, "cd": .3, "cna": 10, "cp_m": .01, "geometry_signature": signature} for mach in [0, 2]
    ]
    result = flight.simulate(p, conditions(max_time=3))
    assert result["validity"]["positive_static_margin_throughout"] is False
    assert any("nonpositive static stability" in warning for warning in result["warnings"])
    assert result["validity"]["cad_resolved_aerodynamics"] is False


def test_tube_only_flight_fails_without_a_valid_aerodynamic_polar():
    p = rocket()
    p.components = [p.components[1]]
    with pytest.raises(ValueError, match="positive normal-force slope"):
        flight.simulate(p, conditions())


def test_immediate_positive_thrust_records_liftoff_at_ignition():
    p = rocket()
    p.motors[0].curve = [[0, 200], [1, 200], [1.1, 0]]
    result = flight.simulate(p, conditions(max_time=2))
    assert event(result, "liftoff")["time"] == 0
    assert event(result, "ignition")["time"] == 0
    assert event(result, "rail_exit")["time"] > 0
    p.configurations[0].ignition_delay = .7
    delayed = flight.simulate(p, conditions(max_time=2))
    assert event(delayed, "liftoff")["time"] == pytest.approx(.7, abs=1e-9)


def test_configuration_limits_do_not_block_a_supported_configuration():
    p = rocket()
    supported = p.configurations[0]
    blocked = FlightConfiguration(id="unsupported", motor_id="motor")
    p.configurations.append(blocked)
    p.metadata["unsupported_features"] = ["deployment_event"]
    p.metadata["unsupported_features_by_configuration"] = {supported.id: [], blocked.id: ["deployment_event"]}
    result = flight.simulate(p, conditions(max_time=2), supported.id)
    assert not any("Unsupported reference-model feature: deployment_event" in warning for warning in result["warnings"])
    with pytest.raises(ValueError, match="deployment_event"):
        flight.simulate(p, conditions(max_time=2), blocked.id)


def test_newly_enabled_unsupported_geometry_is_detected_without_import_metadata():
    p = rocket()
    p.components.append(Component(kind="podset", external=False))
    with pytest.raises(ValueError, match="podset"):
        flight.simulate(p, conditions())
    p.components[-1].enabled = False
    p.components[1].metadata["cluster_configuration"] = "three"
    with pytest.raises(ValueError, match="cluster"):
        flight.simulate(p, conditions())


def test_undefined_imported_recovery_is_not_replaced_with_default_canopies():
    p = rocket()
    p.configurations[0].recovery_defined = False
    with pytest.raises(ValueError, match="Recovery is not defined"):
        flight.simulate(p, conditions())


def test_high_body_drag_matches_closed_form_terminal_approach(monkeypatch):
    # Constant-mass, constant-thrust, vertical quadratic drag has the independent
    # exact solution v(t)=sqrt(a/b)*tanh(sqrt(a*b)*t), a=T/m-g,
    # b=rho*Cd*A/(2m). This deliberately stiff numerical-conditioning case must
    # remain stable even with a 0.2 s user output step and no deployed canopy.
    original = aero.atmosphere
    def constant_atmosphere(altitude, temperature_delta=0):
        return original(0)
    monkeypatch.setattr(aero, "atmosphere", constant_atmosphere)
    p = rocket()
    p.motors[0].propellant_mass = 0
    p.motors[0].curve = [[0, 200], [1, 200], [1.1, 0]]
    p.metadata["aerodynamic_polars"] = [
        {"mach": mach, "cd": 10000, "cna": 10, "cp_m": 1.2, "geometry_signature": aero.geometry_signature(p)}
        for mach in [0, 2]
    ]
    result = flight.simulate(p, conditions(dt=.2, rail_length=.01, max_time=1))
    mass, density, area = 3.1, original(0)["density_kg_m3"], math.pi*.05**2
    acceleration, damping = 200/mass-aero.G0, density*10000*area/(2*mass)
    expected = math.sqrt(acceleration/damping)*math.tanh(math.sqrt(acceleration*damping))
    assert result["trajectory"][-1]["vertical_velocity"] == pytest.approx(expected, rel=2e-5)
    assert all(0 <= row["vertical_velocity"] <= expected*(1+1e-4) for row in result["trajectory"])
    assert result["summary"]["integration_steps"] > 5
