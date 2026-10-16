"""Independent plate references and actual-fin adapter conservation/placement."""

import copy
import numpy as np
import pytest
from rocket_workbench.demo import demo_project
from rocket_workbench.models import Conditions
from rocket_workbench.solvers import plate_elements as element
from rocket_workbench.solvers.plate_fea import solve, preflight
from rocket_workbench.solvers.structure import solve_fea
from rocket_workbench.solvers.aero import analyze
from research.validate_plate_draft import navier_center, geometric_references


def setup():
    p = demo_project()
    f = next(c for c in p.components if c.id == "fins")
    m = next(m for m in p.materials if m.id == f.material_id)
    m.name = "Verified homogeneous aluminum"
    m.description = ""
    m.youngs_modulus = 70e9
    m.poisson_ratio = 0.0
    m.density = 2700
    f.fin_count = 1
    f.span = 0.5
    f.root_chord = 0.1
    f.tip_chord = 0.1
    f.sweep = 0
    f.thickness = 0.005
    f.metadata = {}
    f.radius = 0.05
    return (
        p,
        f,
        dict(
            element_model="plate",
            mesh_size=0.025,
            max_elements=20000,
            plate_pressure_pa=1.0,
            backend="cpu",
        ),
    )


def test_production_kernel_distorted_patches_and_mesh_geometry():
    checks = geometric_references(vars(element), 70e9, 0.3)
    assert checks["invalid_quadrilaterals_rejected"] == 3


@pytest.mark.parametrize("thickness", [0.1, 0.01, 0.001])
def test_production_square_plate_matches_independent_navier_and_refines(thickness):
    E, nu = 70e9, 0.3
    pressure = 1000 * (thickness / 0.1) ** 3
    reference = navier_center(E, nu, thickness, pressure)
    errors = []
    for size in [0.125, 0.0625]:
        xy, quads = element.polygon_quad_mesh([[0, 0], [1, 0], [1, 1], [0, 1]], size)
        xe = np.isclose(xy[:, 0], 0) | np.isclose(xy[:, 0], 1)
        ye = np.isclose(xy[:, 1], 0) | np.isclose(xy[:, 1], 1)
        fixed = np.unique(
            np.concatenate(
                [
                    3 * np.flatnonzero(xe | ye),
                    3 * np.flatnonzero(xe) + 2,
                    3 * np.flatnonzero(ye) + 1,
                ]
            )
        )
        r = element.solve_plate(xy, quads, E, nu, thickness, pressure, fixed)
        center = np.argmin(np.linalg.norm(xy - [0.5, 0.5], axis=1))
        errors.append(abs(r["dofs"][center, 0] / reference - 1))
        assert r["force_balance_relative_error"] < 1e-7
        assert r["external_work_j"] == pytest.approx(2 * r["strain_energy_j"], rel=1e-7)
    assert errors[1] < errors[0] and errors[1] < 0.002


def test_rectangular_fin_matches_cantilever_mindlin_beam_reference_and_reactions():
    p, f, o = setup()
    original = p.model_dump()
    errors = []
    stress_errors = []
    E = 70e9
    t = f.thickness
    L = f.span
    G = E / 2
    reference = 1.5 * L**4 / (E * t**3) + L**2 / (2 * (5 / 6) * G * t)
    for size in [0.05, 0.025, 0.0125]:
        r = solve_fea(p, f.id, Conditions(), {**o, "mesh_size": size})
        errors.append(abs(r["summary"]["max_displacement_m"] / reference - 1))
        stress_errors.append(
            abs(r["summary"]["max_von_mises_pa"] / (3 * L**2 / t**2) - 1)
        )
        np.testing.assert_allclose(
            r["summary"]["applied_force_n"], [0, 0, 0.05], atol=1e-12
        )
        np.testing.assert_allclose(
            np.cross(
                r["fins"][0]["load_centroid_world_m"], r["fins"][0]["applied_force_n"]
            ),
            r["summary"]["applied_moment_nm"],
            atol=1e-12,
        )
        expected = [0.05 * (f.radius + L / 2), -0.05 * (f.x + f.root_chord / 2), 0]
        np.testing.assert_allclose(
            r["summary"]["applied_moment_nm"], expected, atol=1e-12
        )
        np.testing.assert_allclose(
            np.add(r["summary"]["reaction_moment_nm"], expected), 0, atol=1e-9
        )
        assert r["summary"]["force_balance_relative_error"] < 1e-6
        assert r["summary"]["external_work_j"] == pytest.approx(
            2 * r["summary"]["strain_energy_j"], rel=1e-7
        )
        assert not r["tetrahedra"] and r["plate_quads"] and r["surface_faces"]
    # Tip nodal response is exact in this manufactured cylindrical case to
    # floating-point conditioning; do not demand monotonic roundoff noise.
    assert max(errors) < 1e-6
    assert stress_errors[-1] < 0.03 and all(
        b < a for a, b in zip(stress_errors, stress_errors[1:])
    )
    assert p.model_dump() == original


def test_pressure_reversal_and_actual_canted_radial_geometry_are_objective():
    from scipy.spatial.transform import Rotation

    p, f, o = setup()
    o["mesh_size"] = 0.05
    baseline = solve(p, f.id, Conditions(), o)
    reverse = solve(p, f.id, Conditions(), {**o, "plate_pressure_pa": -1})
    np.testing.assert_allclose(
        reverse["displacements"], -np.asarray(baseline["displacements"]), atol=1e-12
    )
    np.testing.assert_allclose(
        reverse["von_mises_pa"], baseline["von_mises_pa"], rtol=1e-10
    )
    f.metadata = dict(cant=17, angleoffset=43, radialposition=0.13, radialdirection=20)
    moved = solve(p, f.id, Conditions(), o)
    R = Rotation.from_euler("x", 43, degrees=True) * Rotation.from_euler(
        "y", 17, degrees=True
    )
    np.testing.assert_allclose(
        moved["displacements"],
        R.apply(baseline["displacements"]),
        rtol=1e-10,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        moved["von_mises_pa"], baseline["von_mises_pa"], rtol=1e-10
    )
    np.testing.assert_allclose(
        np.add(
            moved["summary"]["applied_moment_nm"],
            moved["summary"]["reaction_moment_nm"],
        ),
        0,
        atol=1e-9,
    )
    from rocket_workbench.geometry import component_mesh

    # Midsurface stays within the real original material surface bounds.
    bounds = component_mesh(p, f).bounds
    xyz = np.asarray(moved["vertices"])
    assert np.all(xyz >= bounds[0] - 1e-10) and np.all(xyz <= bounds[1] + 1e-10)


def test_aerodynamic_per_fin_partition_reconstructs_shared_actual_resultant():
    p, f, o = setup()
    f.fin_count = 4
    f.metadata = {"angleoffset": 27}
    o.update(plate_load_mode="aero_resultant", mesh_size=0.05)
    conditions = Conditions(speed=100, angle_of_attack=2, sideslip=1, wind_speed=0)
    a = analyze(p, conditions)
    load = next(row for row in a["components"] if row["component_id"] == f.id)
    r = solve(p, f.id, conditions, o)
    np.testing.assert_allclose(
        r["summary"]["applied_force_n"],
        [0, load["normal_force_n"], load["side_force_n"]],
        rtol=1e-10,
        atol=1e-10,
    )
    assert (
        len(r["fins"]) == 4
        and len({round(row["surface_pressure_pa"], 6) for row in r["fins"]}) > 1
    )


def test_inertial_transverse_load_uses_material_mass_and_no_automatic_gravity():
    p, f, o = setup()
    o.update(plate_pressure_pa=0, acceleration_m_s2=[0, 0, 10], mesh_size=0.05)
    r = solve(p, f.id, Conditions(), o)
    np.testing.assert_allclose(
        r["summary"]["applied_force_n"],
        [0, 0, -r["summary"]["mass_kg"] * 10],
        atol=1e-10,
    )
    zero = solve(p, f.id, Conditions(), {**o, "acceleration_m_s2": [0, 0, 0]})
    assert zero["summary"]["max_displacement_m"] == 0
    assert zero["summary"]["max_von_mises_pa"] == 0


@pytest.mark.parametrize(
    "change,options",
    [
        ({"geometry_mode": "replacement"}, {}),
        ({"thickness": 0.03}, {}),
        ({}, {"max_elements": 20}),
        ({}, {"backend": "cuda"}),
        ({}, {"mesh_size": 1e-200}),
        ({"fin_count": 2}, {"plate_load_mode": "aero_resultant"}),
    ],
)
def test_unsupported_or_excessive_models_fail_before_solve(change, options):
    p, f, o = setup()
    for k, v in change.items():
        setattr(f, k, v)
    ready = preflight(p, f.id, {**o, **options})
    assert not ready["can_run"] and ready["errors"]
    with pytest.raises(ValueError):
        solve(p, f.id, Conditions(), {**o, **options})


def test_composite_acknowledgement_and_unavailable_strength_margin():
    p = demo_project()
    o = dict(
        mesh_size=0.05, max_elements=20000, plate_allow_isotropic_surrogate="false"
    )
    assert not preflight(p, "fins", o)["can_run"]
    r = solve(p, "fins", Conditions(), {**o, "plate_allow_isotropic_surrogate": True})
    assert r["summary"]["safety_factor"] is None


def test_cancellation_never_returns_a_completed_fake_field():
    p, f, o = setup()
    with pytest.raises(RuntimeError, match="cancelled"):
        solve(p, f.id, Conditions(), o, cancelled=lambda: True)


@pytest.mark.parametrize(
    "options",
    [
        {"load_mode": "cfd_pressure"},
        {"plate_pressure_pa": float("nan")},
        {"acceleration_m_s2": [1, 2]},
        {"max_elements": False},
    ],
)
def test_invalid_or_unimplemented_load_requests_are_explicit(options):
    p, f, o = setup()
    assert not preflight(p, f.id, {**o, **options})["can_run"]


@pytest.mark.parametrize(
    "conditions", [Conditions(angle_of_attack=12), Conditions(speed=1000)]
)
def test_aero_loading_rejects_outside_declared_model_limits(conditions):
    p, f, o = setup()
    f.fin_count = 3
    with pytest.raises(ValueError, match="unavailable"):
        solve(p, f.id, conditions, {**o, "plate_load_mode": "aero_resultant"})


def test_actual_triangular_fin_force_centroid_and_refinement():
    p, f, options = setup()
    f.root_chord = 0.2
    f.tip_chord = 0
    f.sweep = 0.1
    f.span = 0.3
    options["plate_pressure_pa"] = 7
    values = []
    force = 7 * f.root_chord * f.span / 2
    expected_moment = [
        force * (f.radius + f.span / 3),
        -force * (f.x + (f.root_chord + f.sweep) / 3),
        0,
    ]
    for size in [0.05, 0.025, 0.0125]:
        answer = solve(p, f.id, Conditions(), {**options, "mesh_size": size})
        np.testing.assert_allclose(
            answer["summary"]["applied_force_n"], [0, 0, force], atol=1e-12
        )
        np.testing.assert_allclose(
            answer["summary"]["applied_moment_nm"], expected_moment, atol=1e-12
        )
        assert answer["summary"]["moment_balance_relative_error"] < 1e-6
        values.append(answer["summary"]["max_displacement_m"])
    assert abs(values[-1] / values[-2] - 1) < 0.05
    assert abs(values[-1] - values[-2]) < abs(values[-2] - values[-3])
