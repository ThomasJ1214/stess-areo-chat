"""Independent rotation/restoring benchmarks and real flight contracts."""
import json
import math

import numpy as np
import pytest

from rocket_workbench.models import Component, Conditions, FlightConfiguration, GeometryAsset, Motor, Project, WindEvent
from rocket_workbench.solvers import aero, attitude, flight
from rocket_workbench.solvers.flight_dynamics import InertiaModel


def rocket():
    p = Project(components=[
        Component(id="nose", kind="nosecone", length=.3, radius=.05, mass_override=.4),
        Component(id="body", x=.3, length=1.2, radius=.05, mass_override=1.5),
        Component(id="fins", kind="trapezoidfinset", x=1.18, root_chord=.25, tip_chord=.12,
                  span=.12, sweep=.12, radius=.05, mass_override=.3),
        Component(id="payload", kind="masscomponent", x=.5, mass_override=.5),
    ], motors=[Motor(id="motor", dry_mass=.4, propellant_mass=.4,
        curve=[[0, 0], [.1, 200], [2, 200], [2.1, 0]], source="Synthetic validation motor")])
    p.configurations[0].motor_id = "motor"
    return p


def integrate_rotation(derivative, q, omega, duration, dt=.002):
    state = np.r_[q, omega].astype(float)
    for i in range(round(duration/dt)):
        t = i*dt
        k1 = derivative(t, state)
        k2 = derivative(t+dt/2, state+dt*k1/2)
        k3 = derivative(t+dt/2, state+dt*k2/2)
        k4 = derivative(t+dt, state+dt*k3)
        state += dt*(k1+2*k2+2*k3+k4)/6
        state[:4] = attitude.normalize(state[:4])
    return state


def test_torque_free_quaternion_and_conservation_of_world_angular_momentum():
    inertia = np.diag([1.0, 2.0, 3.0])
    q0, omega0 = np.array([1.0, 0, 0, 0]), np.array([.2, .3, .4])
    def derivative(_t, state):
        dq, domega = attitude.derivatives(state[:4], state[4:], np.zeros(3), inertia)
        return np.r_[dq, domega]
    end = integrate_rotation(derivative, q0, omega0, 2)
    energy0 = .5*omega0@inertia@omega0
    energy_end = .5*end[4:]@inertia@end[4:]
    angular_world_end = attitude.rotation_matrix(end[:4]) @ (inertia@end[4:])
    assert energy_end == pytest.approx(energy0, rel=1e-10)
    assert angular_world_end == pytest.approx(inertia@omega0, rel=1e-9, abs=1e-10)
    assert np.linalg.norm(end[:4]) == pytest.approx(1, abs=1e-14)


def test_constant_axis_moment_matches_closed_form_angle_and_rate():
    inertia = np.diag([2.0, 3.0, 4.0])
    def derivative(_t, state):
        dq, domega = attitude.derivatives(state[:4], state[4:], [2, 0, 0], inertia)
        return np.r_[dq, domega]
    end = integrate_rotation(derivative, [1, 0, 0, 0], [0, 0, 0], 2)
    # alpha=M/I=1 rad/s²; omega=2, rotation=alpha*t²/2=2 radians.
    assert end[4:] == pytest.approx([2, 0, 0], abs=1e-10)
    assert end[:4] == pytest.approx([math.cos(1), math.sin(1), 0, 0], abs=1e-10)


def test_angular_kernel_rejects_nonsymmetric_tensor_and_nonfinite_vectors():
    with pytest.raises(ValueError, match="symmetric"):
        attitude.derivatives([1, 0, 0, 0], [0, 0, 0], [0, 0, 0], [[1, .1, 0], [0, 2, 0], [0, 0, 3]])
    with pytest.raises(ValueError, match="finite three-vectors"):
        attitude.derivatives([1, 0, 0, 0], [0, math.nan, 0], [0, 0, 0], np.eye(3))


def test_aft_cp_restores_small_attitude_error_and_fore_cp_destabilizes():
    theta = .02
    q = [math.cos(theta/2), 0, 0, math.sin(theta/2)]
    rotation = attitude.rotation_matrix(q)
    normal, incidence = attitude.aerodynamic_normal(rotation[:, 0], [100, 0, 0], 1000, .01, 10)
    aft = attitude.cp_moment(normal, rotation, 1, [.5, 0, 0])
    fore = attitude.cp_moment(normal, rotation, 0, [.5, 0, 0])
    assert incidence == pytest.approx(theta, abs=1e-12)
    assert np.linalg.norm(normal) == pytest.approx(2)
    assert aft[2] == pytest.approx(-1)
    assert fore[2] == pytest.approx(1)


def test_small_angle_restoring_oscillator_has_reference_quarter_period():
    qbar, area, slope, arm, inertia_z = 1000, .01, 10, .5, 2
    natural_frequency = math.sqrt(qbar*area*slope*arm/inertia_z)
    duration = math.pi/(2*natural_frequency)
    theta0 = .02
    def derivative(_t, state):
        rotation = attitude.rotation_matrix(state[:4])
        force, _ = attitude.aerodynamic_normal(rotation[:, 0], [100, 0, 0], qbar, area, slope)
        moment = attitude.cp_moment(force, rotation, 1, [.5, 0, 0])
        dq, domega = attitude.derivatives(state[:4], state[4:], moment, np.diag([1, 2, inertia_z]))
        return np.r_[dq, domega]
    steps = 1000
    end = integrate_rotation(derivative, [math.cos(theta0/2), 0, 0, math.sin(theta0/2)], [0, 0, 0], duration, duration/steps)
    angle_end = 2*math.atan2(end[3], end[0])
    assert angle_end == pytest.approx(0, abs=1e-10)
    assert end[6] == pytest.approx(-theta0*natural_frequency, rel=1e-9)


def test_inertia_override_requires_physical_shape_source_and_is_dry_reference():
    with pytest.raises(ValueError, match="symmetric"):
        FlightConfiguration(inertia_override_kg_m2=[[1, .2, 0], [0, 2, 0], [0, 0, 2]], inertia_override_source="measured")
    with pytest.raises(ValueError, match="positive definite"):
        FlightConfiguration(inertia_override_kg_m2=[[-1, 0, 0], [0, 2, 0], [0, 0, 2]], inertia_override_source="measured")
    with pytest.raises(ValueError, match="source"):
        FlightConfiguration(inertia_override_kg_m2=[[.1, 0, 0], [0, 2, 0], [0, 0, 2]])
    p = rocket()
    p.configurations[0].inertia_override_source = "Synthetic dry-tensor reference"
    p.configurations[0].inertia_override_kg_m2 = [[.1, 0, 0], [0, 2, 0], [0, 0, 2]]
    model = InertiaModel(p, None, p.motors[0], aero.mass_properties(p))
    dry_mass, _, dry_tensor = model.at(0)
    wet_mass, _, wet_tensor = model.at(.4)
    assert dry_tensor == pytest.approx(np.diag([.1, 2, 2]))
    assert wet_mass-dry_mass == pytest.approx(.4)
    assert np.min(np.linalg.eigvalsh(wet_tensor-dry_tensor)) > 0
    assert "Synthetic dry-tensor" in model.basis


def test_inertia_override_rejects_impossible_spd_tensor_but_accepts_physical_rotated_tensor():
    from scipy.spatial.transform import Rotation
    with pytest.raises(ValueError, match="triangle inequality"):
        FlightConfiguration(inertia_override_kg_m2=np.diag([1., 1., 100.]).tolist(),
                            inertia_override_source="Impossible synthetic measurement")
    rotation = Rotation.from_euler("xyz", [23., 41., -18.], degrees=True).as_matrix()
    # The principal-moment condition is invariant under a change of axes.
    physical = rotation @ np.diag([1., 2., 2.5]) @ rotation.T
    cfg = FlightConfiguration(inertia_override_kg_m2=physical.tolist(),
                              inertia_override_source="Rotated physical reference")
    np.testing.assert_allclose(cfg.inertia_override_kg_m2, physical)
    planar = rotation @ np.diag([1., 2., 3.]) @ rotation.T
    FlightConfiguration(inertia_override_kg_m2=planar.tolist(),
                        inertia_override_source="Planar positive-mass distribution")
    impossible = rotation @ np.diag([1., 1., 100.]) @ rotation.T
    with pytest.raises(ValueError, match="triangle inequality"):
        FlightConfiguration(inertia_override_kg_m2=impossible.tolist(),
                            inertia_override_source="Rotated impossible reference")


def test_importer_ambiguous_closed_cad_cannot_supply_volume_inertia_with_measured_mass():
    import trimesh
    from rocket_workbench.geometry import component_mesh
    p = rocket()
    mesh = trimesh.creation.box([.4, .2, .2])
    mesh.apply_translation([.2, .07, -.03])
    asset = GeometryAsset(id="ambiguous", name="Importer-rejected material volume", format="stl",
                          vertices=mesh.vertices.tolist(), faces=mesh.faces.tolist(), watertight=False)
    p.assets.append(asset)
    body = p.components[1]
    body.asset_id, body.geometry_mode, body.cg_override = asset.id, "replacement", .5
    imported = component_mesh(p, body)
    assert imported.is_watertight and imported.metadata.get("volume_ambiguous")
    model = InertiaModel(p, None, p.motors[0], aero.mass_properties(p))
    provenance = next(row for row in model.provenance if row["component_id"] == body.id)
    assert provenance["mass_kg"] == body.mass_override
    assert "cylinder" in provenance["basis"] and "ambiguous" in provenance["basis"]
    assert "volume moments" not in provenance["basis"]
    assert any("mesh-derived inertia and lateral CG are unavailable" in warning for warning in model.warnings)
    # The untrusted CAD's artificial lateral center cannot move the rocket CG.
    np.testing.assert_allclose(model.at(0)[1][1:], [0., 0.], atol=1e-14)
    p.configurations[0].inertia_override_source = "Complete measured dry reference"
    p.configurations[0].inertia_override_kg_m2 = np.diag([.1, 2., 2.]).tolist()
    measured = InertiaModel(p, None, p.motors[0], aero.mass_properties(p))
    np.testing.assert_allclose(measured.at(0)[2], np.diag([.1, 2., 2.]), atol=1e-14)
    assert any("supplied complete dry-rocket tensor replaces" in warning for warning in measured.warnings)


def test_rigid_body_rows_close_force_balance_and_preserve_rail_axis():
    result = flight.simulate(rocket(), Conditions(flight_model="rigid_body", wind_speed=1, launch_angle=0, max_time=2, dt=.05))
    rail = next(event for event in result["events"] if event["name"] == "rail_exit")
    assert result["validity"]["six_dof"] is True
    assert all(row["body_axis_world"] == pytest.approx([0, 0, 1], abs=1e-10) for row in result["trajectory"] if row["time"] < rail["time"])
    normal_nonzero = False
    for row in result["trajectory"]:
        q = row["body_quaternion_world"]
        assert np.linalg.norm(q) == pytest.approx(1, abs=1e-12)
        assert attitude.rotation_matrix(q)[:, 0] == pytest.approx(row["body_axis_world"], abs=1e-12)
        forces = row["force_vectors_n"]
        total = sum((np.array(forces[key]) for key in ["body_aerodynamic_drag", "aerodynamic_normal", "recovery_drag", "thrust", "gravity", "rail_reaction"]), start=np.zeros(3))
        assert total == pytest.approx(row["mass"]*np.array(row["acceleration_vector"]), abs=1e-9)
        normal_nonzero |= np.linalg.norm(forces["aerodynamic_normal"]) > 1e-5
    assert normal_nonzero
    assert any("No measured/supplied" in warning for warning in result["warnings"])
    json.dumps(result, allow_nan=False)


def test_high_incidence_returns_honest_partial_result_at_model_limit():
    result = flight.simulate(rocket(), Conditions(flight_model="rigid_body", wind_speed=30, launch_angle=0, max_time=10, dt=.05))
    assert result["summary"]["complete"] is False
    assert result["summary"]["termination_reason"] == "aerodynamic_angle_limit"
    assert any(event["name"] == "aerodynamic_model_limit" for event in result["events"])
    assert result["summary"]["flight_time_s"] < 10
    assert any("partial trajectory" in warning for warning in result["warnings"])


def test_finite_inflation_has_continuous_zero_initial_load_and_actual_eta_progress():
    p = rocket()
    p.configurations[0].deployment = "single"
    p.configurations[0].primary_deploy_event = "motor_ejection"
    p.configurations[0].motor_ejection_delay = .5
    p.configurations[0].apogee_delay = 0
    p.configurations[0].main_inflation_time = 1
    updates = []
    result = flight.simulate(p, Conditions(flight_model="rigid_body", wind_speed=0, launch_angle=0, max_time=6, dt=.05), progress=lambda fraction, message: updates.append(fraction))
    event = next(e for e in result["events"] if e["name"] == "main_deployment")
    row = result["trajectory"][event["index"]]
    assert row["recovery_inflation_fraction"] == 0
    assert row["canopy_load_n"] == 0
    inflation = [sample for sample in result["trajectory"] if 0 < sample["recovery_inflation_fraction"] < 1]
    assert inflation and all(sample["canopy_load_n"] > 0 for sample in inflation)
    assert updates[0] == 0 and updates[-1] == 1
    assert all(y >= x for x, y in zip(updates, updates[1:]))


def test_full_rigid_body_dual_recovery_tracks_mass_inertia_and_inflation():
    p = rocket()
    cfg = p.configurations[0]
    cfg.drogue_inflation_time, cfg.main_inflation_time = .4, .7
    result = flight.simulate(p, Conditions(flight_model="rigid_body", wind_speed=0, launch_angle=0,
                                          max_time=180, dt=.1))
    rows = result["trajectory"]
    events = {event["name"]: event for event in result["events"]}
    assert result["summary"]["complete"] and rows[-1]["altitude"] == 0
    assert events["rail_exit"]["time"] < events["burnout"]["time"] < events["apogee"]["time"]
    assert events["drogue_deployment"]["time"]-events["apogee"]["time"] == pytest.approx(.5, abs=1e-8)
    assert rows[events["apogee"]["index"]]["vertical_velocity"] == pytest.approx(0, abs=1e-7)
    main = rows[events["main_deployment"]["index"]]
    assert main["altitude"] == pytest.approx(cfg.main_deploy_altitude, abs=1e-6)
    assert main["recovery_inflation_fraction"] == 0
    assert main["recovery_cd_area_m2"] == pytest.approx(cfg.drogue_cd_area)
    assert rows[-1]["recovery_cd_area_m2"] == pytest.approx(cfg.main_cd_area)
    assert rows[0]["mass"] == pytest.approx(3.5)
    assert rows[events["burnout"]["index"]]["mass"] == pytest.approx(3.1)
    wet_tensor = np.asarray(rows[0]["inertia_tensor_body_kg_m2"])
    dry_tensor = np.asarray(rows[events["burnout"]["index"]]["inertia_tensor_body_kg_m2"])
    assert np.min(np.linalg.eigvalsh(wet_tensor-dry_tensor)) > 0
    assert max(abs(row["east"])+abs(row["north"]) for row in rows) < 1e-9
    assert all(np.linalg.norm(row["body_quaternion_world"]) == pytest.approx(1, abs=1e-12) for row in rows)
    assert any("Unsupported high-incidence" in warning for warning in result["warnings"])
    json.dumps(result, allow_nan=False)


def test_rigid_body_step_halving_converges_position_attitude_and_rates():
    coarse = flight.simulate(rocket(), Conditions(flight_model="rigid_body", wind_speed=1,
                              launch_angle=0, max_time=2, dt=.1))
    fine = flight.simulate(rocket(), Conditions(flight_model="rigid_body", wind_speed=1,
                            launch_angle=0, max_time=2, dt=.05))
    a, b = coarse["trajectory"][-1], fine["trajectory"][-1]
    assert a["time"] == b["time"] == 2
    assert a["altitude"] == pytest.approx(b["altitude"], abs=1e-4)
    assert a["velocity_vector"] == pytest.approx(b["velocity_vector"], abs=1e-4)
    assert a["body_axis_world"] == pytest.approx(b["body_axis_world"], abs=1e-5)
    assert a["angular_velocity_body_rad_s"] == pytest.approx(b["angular_velocity_body_rad_s"], abs=1e-4)
    assert coarse["numerical_integration"]["maximum_accepted_error_norm"] <= 1
    assert fine["numerical_integration"]["maximum_accepted_error_norm"] <= 1


def test_rigid_body_vacuum_triangular_thrust_matches_analytic_ballistics(monkeypatch):
    original = aero.atmosphere
    def vacuum(_altitude, _temperature_delta=0):
        result = original(0)
        result.update(density_kg_m3=0, gravity_m_s2=aero.G0)
        return result
    monkeypatch.setattr(aero, "atmosphere", vacuum)
    p = rocket()
    p.motors[0].propellant_mass = 0
    p.motors[0].curve = [[0, 0], [1, 200], [2, 0]]
    p.configurations[0].apogee_delay = 0
    mass, peak, g = 3.1, 200.0, aero.G0
    liftoff = mass*g/peak
    expected_velocity = peak/mass-2*g+.5*g*liftoff
    expected_height = peak/mass-2*g+g*liftoff-g*liftoff**2/6
    expected_apogee = expected_height+expected_velocity**2/(2*g)
    result = flight.simulate(p, Conditions(flight_model="rigid_body", wind_speed=0, launch_angle=0,
                                          rail_length=.2, max_time=10, dt=.2))
    events = {event["name"]: event for event in result["events"]}
    burnout = result["trajectory"][events["burnout"]["index"]]
    assert events["liftoff"]["time"] == pytest.approx(liftoff, abs=1e-8)
    assert burnout["vertical_velocity"] == pytest.approx(expected_velocity, abs=1e-6)
    assert burnout["altitude"] == pytest.approx(expected_height, abs=1e-6)
    assert result["summary"]["apogee_m"] == pytest.approx(expected_apogee, abs=1e-6)
    assert all(row["angular_velocity_body_rad_s"] == pytest.approx([0, 0, 0], abs=1e-12)
               for row in result["trajectory"])


@pytest.mark.parametrize("mode", ["point_mass", "rigid_body"])
def test_future_environment_change_keeps_past_trajectory_and_temperature_causal(mode):
    base = Conditions(flight_model=mode, wind_speed=0, launch_angle=0, max_time=4, dt=.05)
    unchanged = flight.simulate(rocket(), base)
    # Projects/configuration IDs differ but identical physical geometry/data.
    changed_conditions = base.model_copy(deep=True)
    changed_conditions.wind_events = [WindEvent(time_s=2, wind_speed=4, wind_direction=90, turbulence=0, transition_s=0, temperature_delta=20)]
    changed = flight.simulate(rocket(), changed_conditions)
    for row in unchanged["trajectory"]:
        if row["time"] >= 1.9:
            break
        counterpart = min(changed["trajectory"], key=lambda other: abs(other["time"]-row["time"]))
        assert counterpart["time"] == pytest.approx(row["time"], abs=1e-10)
        assert counterpart["altitude"] == pytest.approx(row["altitude"], abs=1e-8)
        assert counterpart["velocity"] == pytest.approx(row["velocity"], abs=1e-8)
    event = next(e for e in changed["events"] if e["name"] == "environment_change")
    after = changed["trajectory"][event["index"]]
    before = changed["trajectory"][event["index"]-1]
    assert after["wind_vector"] == pytest.approx([4, 0, 0])
    assert after["temperature_k"] > before["temperature_k"]+19
    assert changed["summary"]["max_dynamic_pressure_pa"] != unchanged["summary"]["max_dynamic_pressure_pa"]


def test_schedule_validation_and_cancellation():
    with pytest.raises(ValueError, match="must not overlap"):
        Conditions(wind_events=[WindEvent(time_s=1, wind_speed=1, wind_direction=0, turbulence=0, transition_s=2),
                                WindEvent(time_s=2, wind_speed=2, wind_direction=90, turbulence=0)])
    with pytest.raises(ValueError, match="maximum simulation time"):
        Conditions(max_time=1, wind_events=[WindEvent(time_s=2, wind_speed=1, wind_direction=0, turbulence=0)])
    with pytest.raises(RuntimeError, match="cancelled"):
        flight.simulate(rocket(), Conditions(flight_model="rigid_body"), cancelled=lambda: True)
