"""Independent beam, oscillator and flight-load references for real fin dynamics."""
import copy
import json
import math

import numpy as np
import pytest
from scipy.integrate import quad

from rocket_workbench.demo import demo_project
from rocket_workbench.solvers.flight_structure import (
    _fin_load, analyze_flight_structure, beam_eigenmodes, beam_matrices, newmark_step,
)


def uniform_beam(elements=8):
    return beam_matrices(.3, .12, .12, .003, 70e9, 2700., elements)


def test_consistent_mass_and_static_tip_load_match_exact_cantilever():
    model = uniform_beam()
    length, width, thickness, modulus, density, force = .3, .12, .003, 70e9, 2700., 7.
    inertia = width * thickness**3 / 12
    load = np.zeros(len(model["mass"]))
    load[-2] = force
    displacement = np.zeros_like(load)
    displacement[2:] = np.linalg.solve(model["stiffness"][2:, 2:], load[2:])
    assert displacement[-2] == pytest.approx(force * length**3 / (3 * modulus * inertia), rel=2e-11)
    reaction = model["stiffness"] @ displacement - load
    assert reaction[0] == pytest.approx(-force, rel=2e-11)
    assert reaction[1] == pytest.approx(-force * length, rel=2e-11)
    rigid_translation = np.zeros(len(load))
    rigid_translation[::2] = 1
    assert rigid_translation @ model["mass"] @ rigid_translation == pytest.approx(density * width * thickness * length, rel=2e-14)


def test_fundamental_frequency_matches_independent_cantilever_eigenvalue():
    model = uniform_beam()
    omega, modes = beam_eigenmodes(model)
    # First positive root of cos(beta)*cosh(beta)=-1; tabulated beta=1.8751040687.
    reference = 1.875104068711961**2 / .3**2 * math.sqrt(70e9 * .003**2 / (12 * 2700))
    assert omega[0] == pytest.approx(reference, rel=2.1e-6)
    np.testing.assert_allclose(modes.T @ model["mass"] @ modes, np.eye(len(omega)), atol=2e-13)
    assert np.all(modes[:2] == 0)
    # Complete-basis static response equals the independently assembled solve.
    direct = np.linalg.solve(model["stiffness"][2:, 2:], model["unit_force"][2:])
    modal = modes @ ((modes.T @ model["unit_force"]) / omega**2)
    np.testing.assert_allclose(modal[2:], direct, rtol=2e-9, atol=1e-14)


def test_tapered_span_load_matches_independent_virtual_work_integral():
    length, root, tip, thickness, modulus, force = .4, .2, .08, .004, 30e9, 12.
    area = length * (root + tip) / 2
    chord = lambda station: root + (tip - root) * station / length
    moment = lambda station: quad(lambda outward: force * chord(outward) / area * (outward - station), station, length, epsabs=1e-12)[0]
    # Unit virtual tip force has moment L-s; integrate M*Mv/(EI) in the continuum.
    reference = quad(lambda station: moment(station) * (length - station) / (modulus * chord(station) * thickness**3 / 12), 0, length, epsabs=1e-12)[0]
    errors = []
    for elements in (4, 8, 16):
        model = beam_matrices(length, root, tip, thickness, modulus, 1800., elements)
        response = np.linalg.solve(model["stiffness"][2:, 2:], force * model["unit_force"][2:])
        errors.append(abs(response[-2] - reference))
    assert errors[2] < errors[1] < errors[0]
    assert errors[2] < abs(reference) * 1e-5


def oscillator(dt, damping=0, duration=1., forcing=None):
    mass, omega, displacement, velocity = 2., 8., .03, -.04
    stiffness = mass * omega**2
    viscous = 2 * damping * mass * omega
    initial_force = forcing(0) if forcing else 0
    acceleration = (initial_force - viscous*velocity - stiffness*displacement) / mass
    times = np.arange(0, duration + dt/2, dt)
    energies, states = [], []
    for stamp in times:
        states.append(displacement)
        energies.append(.5*mass*velocity**2 + .5*stiffness*displacement**2)
        if stamp < times[-1]:
            displacement, velocity, acceleration = newmark_step(displacement, velocity, acceleration,
                forcing(stamp + dt) if forcing else 0, mass, viscous, stiffness, dt)
    return times, np.asarray(states), np.asarray(energies)


def test_average_acceleration_conserves_undamped_energy_and_converges_to_oscillator():
    errors = []
    for dt in (.01, .005, .0025):
        times, displacement, energy = oscillator(dt)
        reference = .03 * np.cos(8*times) - .04/8 * np.sin(8*times)
        errors.append(np.max(np.abs(displacement - reference)))
        np.testing.assert_allclose(energy, np.full(len(times), energy[0]), rtol=4e-14)
    assert 3.8 < errors[0] / errors[1] < 4.2
    assert 3.8 < errors[1] / errors[2] < 4.2


def test_damped_oscillator_matches_exact_decay_and_dissipates_energy():
    damping = .04
    times, displacement, energy = oscillator(.0005, damping)
    damped = 8 * math.sqrt(1 - damping**2)
    reference = np.exp(-damping*8*times) * (.03*np.cos(damped*times) + (-.04 + damping*8*.03)/damped*np.sin(damped*times))
    np.testing.assert_allclose(displacement, reference, atol=3e-7)
    assert np.all(np.diff(energy) <= 1e-14)
    assert energy[-1] < energy[0]


def reference_rows():
    return [{"time": stamp, "phase": "powered", "dynamic_pressure": 1000., "mach": .3,
             "body_quaternion_world": [1., 0., 0., 0.], "body_axis_world": [1., 0., 0.],
             "air_relative_velocity_vector": [100., 0., 1.],
             "aerodynamic_components": [{"component_id": "fins", "normal_force_vector_n": [0., 0., -30.],
                 "force_fidelity": "Recorded original-reference fin force estimate"}]}
            for stamp in (0., .05, .13)]


def isotropic_project():
    project = demo_project()
    project.components[3].material_id = "aluminum"
    return project


def test_recorded_quaternion_resolves_individual_fin_loads_with_correct_force_signs():
    project, rows = isotropic_project(), reference_rows()
    fin = project.components[3]
    load, fidelity, incidence, resolved = _fin_load(rows[0], fin, .06, 10)
    assert resolved and incidence == pytest.approx(math.degrees(math.atan(.01)))
    assert "Recorded" in fidelity
    np.testing.assert_allclose(load, [20., -10., -10.], atol=2e-14)
    result = analyze_flight_structure(project, rows)
    assert result["summary"]["complete"] and result["summary"]["substeps"] > 0
    first = result["trajectory"][0]["components"][0]
    assert first["supported"] and first["resolved_attitude"]
    assert not first["translational_base_inertia_included"]
    assert first["fins"][0]["base_inertial_force_n"] is None
    for index, applied in enumerate((20, -10, -10)):
        row = first["fins"][index]
        center_span = fin.span * (fin.root_chord + 2*fin.tip_chord) / (3*(fin.root_chord + fin.tip_chord))
        assert row["root_reaction_force_n"] == pytest.approx(-applied, rel=1e-7)
        assert row["root_reaction_moment_nm"] == pytest.approx(-applied * center_span, rel=1e-7)
        assert math.copysign(1., row["tip_deflection_m"]) == math.copysign(1., applied)
    assert first["fins"][0]["root_reaction_vector_n"] == pytest.approx([0., 0., 20.], abs=1e-7)
    assert first["fins"][0]["root_reaction_moment_vector_nm"] == pytest.approx([20*center_span, 0., 0.], abs=1e-7)
    # A constant prescribed load started at declared static equilibrium stays
    # static even though genuine dynamic steps are taken between irregular rows.
    for frame in result["trajectory"]:
        assert frame["components"][0]["deflection_m"] == pytest.approx(first["deflection_m"], rel=2e-10)
        assert frame["components"][0]["relative_dynamic_equilibrium_residual"] < 1e-7
    json.dumps(result, allow_nan=False)


def test_transient_beam_response_matches_independent_harmonic_modal_solution():
    project = isotropic_project()
    fin = project.components[3]
    fin.span, fin.root_chord, fin.tip_chord, fin.thickness = .3, .12, .12, .003
    material = project.materials[1]
    model = beam_matrices(fin.span, fin.root_chord, fin.tip_chord, fin.thickness,
                          material.youngs_modulus, material.density, 8)
    omega, modes = beam_eigenmodes(model)
    drive = omega[0]
    period = 2*math.pi/drive
    times = np.linspace(0, 5*period, 501)
    rows = []
    for stamp in times:
        phase = math.sin(drive*stamp)
        rows.append({"time": float(stamp), "phase": "powered", "dynamic_pressure": 1000., "mach": .3,
                     "body_quaternion_world": [1., 0., 0., 0.], "air_relative_velocity_vector": [100., 0., phase],
                     "aerodynamic_components": [{"component_id": fin.id, "normal_force_vector_n": [0., 0., -.15*phase]}]})
    result = analyze_flight_structure(project, rows, options={"elements": 8, "damping_ratio": .01})
    actual = np.asarray([row["components"][0]["fins"][0]["tip_deflection_m"] for row in result["trajectory"]])
    # Independent continuous-time solution of each damped oscillator under
    # sinusoidal force, including the homogeneous transient enforcing zero IC.
    force_modal = (modes.T @ model["unit_force"]) * .1
    complex_amplitude = force_modal / (omega**2 - drive**2 + 2j*.01*omega*drive)
    damped = omega * math.sqrt(1 - .01**2)
    a = -complex_amplitude.imag
    b = (-drive*complex_amplitude.real + .01*omega*a) / damped
    q = np.imag(complex_amplitude[:, None] * np.exp(1j*drive*times)[None, :])
    q += np.exp(-.01*omega[:, None]*times) * (a[:, None]*np.cos(damped[:, None]*times) + b[:, None]*np.sin(damped[:, None]*times))
    reference = modes[-2] @ q
    assert np.max(np.abs(actual - reference)) < .008 * np.max(np.abs(reference))
    static_tip = np.linalg.solve(model["stiffness"][2:, 2:], .1*model["unit_force"][2:])[-2]
    assert np.max(np.abs(actual)) > 5*abs(static_tip)  # actual resonance, not framewise statics


def test_trajectory_and_material_geometry_are_not_modified():
    project, rows = isotropic_project(), reference_rows()
    original_project, original_rows = copy.deepcopy(project.model_dump()), copy.deepcopy(rows)
    analyze_flight_structure(project, rows)
    assert project.model_dump() == original_project
    assert rows == original_rows


def test_fin_root_inertia_uses_transverse_specific_acceleration_and_excludes_gravity():
    project, rows = isotropic_project(), reference_rows()
    for row in rows:
        row["aerodynamic_components"][0]["normal_force_vector_n"] = [0., 0., 0.]
        row["acceleration_vector"] = [0., 0., -9.81]
        row["specific_acceleration_vector"] = [0., 0., 0.]
    freefall = analyze_flight_structure(project, rows)
    assert freefall["summary"]["max_stress_pa"] == 0
    assert freefall["summary"]["max_deflection_m"] == 0
    # Positive world-up specific acceleration is negative along fin0's actual
    # normal, so its D'Alembert load is +m_fin and attachment reaction is -m_fin.
    for row in rows:
        row["specific_acceleration_vector"] = [0., 0., 1.]
    accelerated = analyze_flight_structure(project, rows)
    mass = accelerated["components"][0]["mass_per_fin_kg"]
    fin = accelerated["trajectory"][0]["components"][0]["fins"][0]
    assert fin["aerodynamic_force_n"] == 0
    assert fin["base_inertial_force_n"] == pytest.approx(mass)
    assert fin["root_reaction_force_n"] == pytest.approx(-mass, rel=1e-7)
    assert accelerated["summary"]["max_stress_pa"] > 0


def test_measured_fin_mass_changes_inertia_and_frequency_without_changing_material():
    project, rows = isotropic_project(), reference_rows()
    original = analyze_flight_structure(project, rows)
    original_mass = original["components"][0]["mass_per_fin_kg"]
    fin = project.components[3]
    fin.mass_override = 2 * fin.fin_count * original_mass
    density_before = project.materials[1].density
    doubled = analyze_flight_structure(project, rows)
    assert doubled["components"][0]["mass_per_fin_kg"] == pytest.approx(2*original_mass)
    assert doubled["components"][0]["natural_frequencies_hz"][0] == pytest.approx(original["components"][0]["natural_frequencies_hz"][0] / math.sqrt(2), rel=1e-8)
    assert project.materials[1].density == density_before
    assert doubled["trajectory"][0]["components"][0]["deflection_m"] == pytest.approx(original["trajectory"][0]["components"][0]["deflection_m"], rel=1e-8)


def test_unsupported_composite_and_cad_fin_results_are_unavailable():
    project, rows = demo_project(), reference_rows()
    result = analyze_flight_structure(project, rows)
    assert result["summary"]["max_stress_pa"] is None
    assert "Composite" in result["components"][0]["reason"]
    assert all(frame["components"][0]["stress_pa"] is None for frame in result["trajectory"])
    acknowledged = analyze_flight_structure(project, rows, options={"allow_isotropic_surrogate": True})
    assert acknowledged["components"][0]["isotropic_surrogate_acknowledged"]
    assert acknowledged["trajectory"][0]["components"][0]["safety_factor"] is None
    project.components[3].asset_id = "actual-cad-fin"
    project.components[3].geometry_mode = "replacement"
    cad = analyze_flight_structure(project, rows, options={"allow_isotropic_surrogate": True})
    assert not cad["components"][0]["supported"] and "CAD" in cad["components"][0]["reason"]


def test_recovery_or_invalid_load_interval_is_never_interpolated():
    project, rows = isotropic_project(), reference_rows()
    rows[1]["air_relative_velocity_vector"] = [10., 30., 0.]
    rows[2]["phase"] = "drogue"
    result = analyze_flight_structure(project, rows)
    assert result["trajectory"][0]["components"][0]["supported"]
    assert not result["trajectory"][1]["components"][0]["supported"]
    assert "exceeds" in result["trajectory"][1]["components"][0]["reason"]
    assert not result["trajectory"][2]["components"][0]["supported"]
    assert result["trajectory"][2]["max_stress_pa"] is None
    assert result["components"][0]["final_time_s"] == 0


def test_work_budget_and_cancellation_return_aligned_partial_unavailable_states():
    project, rows = isotropic_project(), reference_rows()
    partial = analyze_flight_structure(project, rows, options={"max_substeps": 1, "time_integrator": "newmark"})
    assert partial["summary"]["status"] == "work_budget" and not partial["summary"]["complete"]
    assert len(partial["trajectory"]) == len(rows)
    assert partial["trajectory"][0]["components"][0]["supported"]
    assert partial["trajectory"][1]["components"][0]["stress_pa"] is None
    cancelled = analyze_flight_structure(project, rows, cancelled=lambda: True)
    assert cancelled["summary"]["status"] == "cancelled" and not cancelled["summary"]["complete"]
    assert all(row["max_stress_pa"] is None for row in cancelled["trajectory"])


def test_recorded_component_unavailable_marker_is_respected():
    rows = reference_rows()
    rows[0]["aerodynamic_components"][0]["normal_force_vector_n"] = None
    result = analyze_flight_structure(isotropic_project(), rows)
    assert not result["trajectory"][0]["components"][0]["supported"]
    assert "no fin load is invented" in result["trajectory"][0]["components"][0]["reason"]
    assert result["components"][0]["initial_time_s"] == .05


@pytest.mark.parametrize("options", [{"damping_ratio": -.1}, {"elements": 2.5}, {"steps_per_period": True}, {"allow_isotropic_surrogate": "yes"}])
def test_invalid_dynamic_options_are_rejected(options):
    with pytest.raises(ValueError):
        analyze_flight_structure(isotropic_project(), reference_rows(), options=options)
