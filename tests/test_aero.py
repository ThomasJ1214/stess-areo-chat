"""Analytic physics and geometry-invalidation checks, not UI snapshots."""
import json
import math

import numpy as np
import pytest
import trimesh

from rocket_workbench.models import Component, Conditions, GeometryAsset, Material, Motor, Project, Transform
from rocket_workbench.solvers import aero


def rocket():
    return Project(components=[
        Component(id="nose", kind="nosecone", length=.3, radius=.05, mass_override=.4),
        Component(id="body", x=.3, length=1.2, radius=.05, mass_override=1.5),
        Component(id="fins", kind="trapezoidfinset", x=1.18, root_chord=.25, tip_chord=.12,
                  span=.12, sweep=.12, radius=.05, mass_override=.3),
    ])


def test_1976_standard_sea_level_reference_values():
    atm = aero.atmosphere(0)
    assert atm["temperature_k"] == pytest.approx(288.15)
    assert atm["pressure_pa"] == pytest.approx(101325)
    assert atm["density_kg_m3"] == pytest.approx(1.225000, rel=2e-6)
    assert atm["speed_of_sound_m_s"] == pytest.approx(340.294, rel=2e-6)
    assert atm["dynamic_viscosity_pa_s"] == pytest.approx(1.7894e-5, rel=1e-4)


@pytest.mark.parametrize("height,temperature,pressure,density", [
    (11000, 216.65, 22632.06, .363918),
    (20000, 216.65, 5474.889, .0880349),
    (32000, 228.65, 868.0187, .0132250),
    (47000, 270.65, 110.9063, .00142753),
])
def test_standard_layer_reference_table(height, temperature, pressure, density):
    # The standard table uses geopotential height; the API accepts geometric.
    altitude = aero.EARTH_RADIUS * height / (aero.EARTH_RADIUS - height)
    atm = aero.atmosphere(altitude)
    assert atm["temperature_k"] == pytest.approx(temperature, abs=1e-8)
    # Published tables round the gas constant/base pressures differently; the
    # tolerance is 0.001%, well below a design-tool atmospheric uncertainty.
    assert atm["pressure_pa"] == pytest.approx(pressure, rel=1e-5)
    assert atm["density_kg_m3"] == pytest.approx(density, rel=5e-6)


def test_temperature_offset_changes_density_not_pressure():
    cold, warm = aero.atmosphere(1000), aero.atmosphere(1000, 20)
    assert warm["pressure_pa"] == cold["pressure_pa"]
    assert warm["density_kg_m3"] < cold["density_kg_m3"]
    assert warm["speed_of_sound_m_s"] > cold["speed_of_sound_m_s"]
    with pytest.raises(ValueError):
        aero.atmosphere(60000)


def test_conical_slender_body_cp_and_normal_slope():
    p = Project(components=[Component(kind="nosecone", length=.6, radius=.05, mass_override=1)])
    result = aero.analyze(p, Conditions(speed=0, wind_speed=0))
    assert result["cp_m"] == pytest.approx(.4, abs=1e-10)
    assert result["cna_per_rad"] == pytest.approx(2)
    assert result["drag_n"] == result["normal_force_n"] == 0


def test_hand_calculated_trapezoid_barrowman_reference():
    # Independent classic Barrowman calculation recorded in PHYSICS.md:
    # D=.1, s=.12, Cr=.25, Ct=.12, sweep=.12, N=3, r=.05.
    result = aero.analyze(rocket(), Conditions(speed=0, wind_speed=0))
    fin = next(row for row in result["components"] if row["component_id"] == "fins")
    assert fin["cna_per_rad"] == pytest.approx(10.034860129071134, rel=1e-12)
    assert fin["cp_m"] == pytest.approx(1.281126126126126, rel=1e-12)
    assert result["cp_m"] == pytest.approx(1.1014603693942164, rel=1e-12)


def test_tube_without_lift_preserves_mass_and_drag_but_not_cp():
    p = Project(components=[Component(kind="bodytube", length=1, radius=.05, mass_override=2)])
    result = aero.analyze(p, Conditions(wind_speed=0))
    assert result["mass_kg"] == 2
    assert result["drag_n"] > 0
    assert result["cp_m"] is result["stability_calibers"] is None
    assert result["cp_valid"] is False
    json.dumps(result, allow_nan=False)


def test_body_annulus_and_solid_cone_mass_centers():
    material = Material(id="known", density=1000)
    tube = Component(id="tube", length=1, radius=.05, thickness=.005, material_id="known")
    p = Project(components=[tube], materials=[material])
    result = aero.mass_properties(p)
    assert result["mass_kg"] == pytest.approx(math.pi * (.05**2 - .045**2) * 1000)
    assert result["cg_m"] == pytest.approx(.5)
    cone = Component(kind="nosecone", x=.1, length=.6, radius=.05, material_id="known", metadata={"filled": True})
    p.components = [cone]
    result = aero.mass_properties(p)
    assert result["mass_kg"] == pytest.approx(math.pi * .05**2 * .6 / 3 * 1000)
    assert result["cg_m"] == pytest.approx(.1 + .6 * .75)


def test_secant_ogive_parameter_zero_is_the_visible_cone():
    p = Project(materials=[Material(id="known", density=1000)], components=[
        Component(kind="nosecone", length=.6, radius=.05, material_id="known",
                  metadata={"nose_shape": "ogive", "shape_parameter": 0, "filled": True})])
    cone = aero.analyze(p, Conditions(speed=0, wind_speed=0))
    assert cone["cp_m"] == pytest.approx(.4, abs=1e-10)
    assert cone["mass_kg"] == pytest.approx(math.pi * .05**2*.6/3*1000)
    p.components[0].metadata["shape_parameter"] = 1
    tangent = aero.analyze(p, Conditions(speed=0, wind_speed=0))
    assert tangent["mass_kg"] > cone["mass_kg"]
    assert tangent["cp_m"] < cone["cp_m"]


def test_shaped_transition_mass_and_cp_use_elliptic_profile():
    a, b, length = .03, .05, .4
    p = Project(materials=[Material(id="known", density=1000)], components=[
        Component(kind="transition", length=length, radius=a, radius_end=b, material_id="known",
                  metadata={"nose_shape": "ellipsoid", "filled": True})])
    integral_radius_squared = a*a + 2*a*(b-a)*math.pi/4 + (b-a)**2*2/3
    volume = math.pi * length * integral_radius_squared
    result = aero.analyze(p, Conditions(speed=0, wind_speed=0))
    assert result["mass_kg"] == pytest.approx(volume*1000, rel=1e-9)
    assert result["cp_m"] == pytest.approx((length*b*b - volume/math.pi)/(b*b-a*a), rel=1e-9)


def test_zero_thickness_body_is_massless_without_invented_wall():
    p = rocket()
    p.components[1].mass_override = None
    p.components[1].thickness = 0
    body = next(row for row in aero.mass_properties(p)["components"] if row["component_id"] == "body")
    assert body["mass_kg"] == 0


def test_watertight_cad_mass_scale_rotation_and_center():
    mesh = trimesh.creation.box(extents=[.1, .2, .3])
    mesh.apply_translation([.1, .2, .3])
    asset = GeometryAsset(id="cad", name="box", format="stl", vertices=mesh.vertices.tolist(),
                          faces=mesh.faces.tolist(), watertight=True, volume=float(mesh.volume))
    p = Project(materials=[Material(id="known", density=1000)], assets=[asset], components=[
        Component(kind="bodytube", x=1, material_id="known", asset_id="cad", geometry_mode="replacement",
                  transform=Transform(scale=2, rotation=[0, 0, 90], translation=[.7, 0, 0]))])
    result = aero.mass_properties(p)
    assert result["mass_kg"] == pytest.approx(48, rel=1e-12)
    # Local (.1,.2,.3)*2 rotates to (-.4,.2,.6), then x +1+.7.
    assert result["cg_m"] == pytest.approx(1.3, abs=1e-12)
    p.components[0].mass_override = 5
    measured = aero.mass_properties(p)
    assert measured["mass_kg"] == 5
    assert measured["cg_m"] == pytest.approx(1.3)


def test_mass_subtree_override_does_not_double_count_descendants():
    parent = Component(id="assembly", kind="stage", external=False, mass_override=2, cg_override=.8,
                       metadata={"mass_subcomponents_overridden": True, "cg_subcomponents_overridden": True})
    child = Component(id="child", parent_id="assembly", mass_override=100, x=.2)
    p = Project(components=[parent, child])
    result = aero.mass_properties(p)
    assert result["mass_kg"] == 2
    assert result["cg_m"] == .8
    assert result["components"][1]["mass_kg"] == 0


def test_instance_replication_mass_and_cg():
    p = Project(components=[Component(kind="centeringring", x=.2, length=.01, mass_override=.03,
                                     metadata={"instance_count": 3, "instanceseparation": .1})])
    result = aero.mass_properties(p)
    assert result["mass_kg"] == pytest.approx(.09)
    assert result["cg_m"] == pytest.approx(.305)


def test_motor_mass_tracks_integrated_thrust_not_linear_time():
    p = rocket()
    p.motors = [Motor(id="motor", dry_mass=.2, propellant_mass=.8, curve=[[0, 0], [1, 100], [2, 0]])]
    p.configurations[0].motor_id = "motor"
    p.configurations[0].motor_position = 1.3
    assert aero.mass_properties(p, time=.5)["motor"]["mass_kg"] == pytest.approx(.9)
    assert aero.mass_properties(p, time=1)["motor"]["mass_kg"] == pytest.approx(.6)
    assert aero.mass_properties(p, time=2)["motor"]["mass_kg"] == pytest.approx(.2)


def test_wind_is_added_to_stream_and_changes_incidence():
    result = aero.analyze(rocket(), Conditions(speed=100, angle_of_attack=0, wind_speed=10, wind_direction=0))
    assert result["speed_m_s"] == pytest.approx(math.hypot(100, 10))
    assert result["effective_angle_of_attack_deg"] == pytest.approx(math.degrees(math.atan(.1)))
    assert result["normal_force_n"] > 0
    result = aero.analyze(rocket(), Conditions(speed=100, angle_of_attack=-2, wind_speed=0))
    assert result["normal_force_n"] < 0


@pytest.mark.parametrize("mach", [.7, .9, 1, 1.3, 1.5, 2])
def test_mach_extension_is_finite_and_explicitly_limited(mach):
    result = aero.analyze(rocket(), Conditions(mach=mach, angle_of_attack=3, wind_speed=0))
    assert result["mach"] == pytest.approx(mach)
    assert result["validity"]["within_operating_range"] is True
    assert math.isfinite(result["cd"]) and result["cd"] > 0
    assert math.isfinite(result["normal_force_n"])
    assert result["cp_valid"] is False
    assert any("preliminary" in message for message in result["warnings"])
    json.dumps(result, allow_nan=False)


def test_conical_pressure_reference_formula_at_mach_two():
    sine = .05 / math.hypot(.05, .3)
    assert aero._cone_pressure_cd(2, sine) == pytest.approx(2.1*sine*sine + .5*sine/math.sqrt(3))
    assert aero._cone_pressure_cd(0, sine) == pytest.approx(.8*sine*sine)


def test_geometry_matched_polar_overrides_total_not_component_breakdown():
    p = rocket()
    signature = aero.geometry_signature(p)
    p.metadata["aerodynamic_polars"] = [
        {"mach": 0, "cd": .2, "cna": 8, "cp_m": 1, "source": "test reference", "geometry_signature": signature},
        {"mach": 1, "cd": .5, "cna": 12, "cp_m": 1.4, "source": "test reference", "geometry_signature": signature},
    ]
    result = aero.analyze(p, Conditions(mach=.5, wind_speed=0, angle_of_attack=2))
    assert result["cd"] == pytest.approx(.35)
    assert result["cp_m"] == pytest.approx(1.2)
    assert result["cna_per_rad"] == pytest.approx(10)
    assert result["polar_applied"] is True
    assert result["component_breakdown_valid"] is False
    p.components[0].mass_override = 5
    assert aero.geometry_signature(p) == signature
    p.components[0].metadata["aftshoulderlength"] = .1
    assert aero.geometry_signature(p) != signature
    stale = aero.analyze(p, Conditions(mach=.5, wind_speed=0))
    assert stale["polar_applied"] is False
    assert any("stale" in warning for warning in stale["warnings"])


def test_missing_cad_asset_raises_and_does_not_use_fake_mass():
    p = rocket()
    p.components[0].mass_override = None
    p.components[0].asset_id = "missing"
    p.components[0].geometry_mode = "replacement"
    with pytest.raises(ValueError, match="asset.*missing"):
        aero.mass_properties(p)
