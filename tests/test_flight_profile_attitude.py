"""Independent SciPy rotation references for rigid-flight CFD boundaries."""
import copy
import json

import numpy as np
import pytest
from scipy.spatial.transform import Rotation, Slerp

from rocket_workbench.solvers import aero
from rocket_workbench.solvers.flight_profile import build_flight_profile


def _state(time, rotation, velocity=(100., 8., 13.), wind=(4., -2., 1.), altitude=100.):
    xyzw = rotation.as_quat()
    atmosphere = aero.atmosphere(altitude)
    return {
        "time": time, "altitude_msl": altitude,
        "velocity_vector": list(velocity), "wind_vector": list(wind),
        "body_axis_world": rotation.as_matrix()[:, 0].tolist(),
        "body_quaternion_world": [float(xyzw[3]), *xyzw[:3].tolist()],
        "density_kg_m3": atmosphere["density_kg_m3"],
        "pressure_pa": atmosphere["pressure_pa"],
        "temperature_k": atmosphere["temperature_k"], "phase": "powered",
    }


def _rotation(boundary):
    wxyz = np.asarray(boundary["body_quaternion_world"])
    return Rotation.from_quat(np.r_[wxyz[1:], wxyz[0]])


def _expected_velocity(rotation, relative_world):
    # Original CAD uses tailward X, original Y, original Z. The solved
    # Hamilton quaternion maps noseward X, original Y, negative Z into ENU.
    nose_body_to_cad = np.diag([-1., 1., -1.])
    return nose_body_to_cad @ rotation.as_matrix().T @ -np.asarray(relative_world)


def test_arbitrary_rigid_orientation_uses_original_cad_axes_and_preserves_speed():
    rotation = Rotation.from_euler("zyx", [41., -27., 63.], degrees=True)
    source = {"trajectory": [_state(0., rotation), _state(2., rotation)]}
    original = copy.deepcopy(source)
    profile = build_flight_profile(source)
    relative = np.array([96., 10., 12.])
    for time in [0., .31, 1.7, 2.]:
        boundary = profile(time)
        np.testing.assert_allclose(boundary["velocity_m_s"], _expected_velocity(rotation, relative), atol=2e-12)
        np.testing.assert_allclose(boundary["body_axis_world"], rotation.as_matrix()[:, 0], atol=2e-15)
        assert np.linalg.norm(boundary["velocity_m_s"]) == pytest.approx(np.linalg.norm(relative), abs=2e-12)
    assert profile.metadata["resolved_attitude"] is True
    assert "original CAD Y" in profile.metadata["coordinate_frame"]
    assert source == original


def test_actual_roll_changes_lateral_flow_without_changing_nose_axis():
    rotations = Rotation.from_euler("x", [[0.], [90.]], degrees=True)
    source = {"trajectory": [_state(0., rotations[0], velocity=[120., 0., 0.], wind=[0., 20., 0.]),
                              _state(1., rotations[1], velocity=[120., 0., 0.], wind=[0., 20., 0.])]}
    profile = build_flight_profile(source)
    np.testing.assert_allclose(profile(0.)["body_axis_world"], profile(1.)["body_axis_world"], atol=1e-15)
    np.testing.assert_allclose(profile(0.)["velocity_m_s"], [120., 20., 0.], atol=1e-12)
    np.testing.assert_allclose(profile(1.)["velocity_m_s"], [120., 0., 20.], atol=1e-12)
    np.testing.assert_allclose(profile(.5)["velocity_m_s"], [120., np.sqrt(200.), np.sqrt(200.)], atol=1e-12)


@pytest.mark.parametrize("rotvec", [[.025, .015, -.02], [.7, -.8, .5]])
def test_interpolated_attitude_matches_exact_scipy_slerp_even_near_parallel(rotvec):
    rotations = Rotation.from_rotvec([[0., 0., 0.], rotvec])
    profile = build_flight_profile({"trajectory": [_state(0., rotations[0]), _state(2., rotations[1])]})
    independent = Slerp([0., 2.], rotations)
    for time in [0., .17, .37, .8, 1.31, 1.83, 2.]:
        expected = independent(time)
        boundary = profile(time)
        np.testing.assert_allclose(_rotation(boundary).as_matrix(), expected.as_matrix(), atol=3e-13, rtol=0)
        np.testing.assert_allclose(boundary["velocity_m_s"], _expected_velocity(expected, [96., 10., 12.]), atol=3e-11, rtol=0)


def test_antipodal_quaternions_follow_same_shortest_physical_rotation():
    rotations = Rotation.from_euler("xyz", [[12., 28., -37.], [48., -31., 62.]], degrees=True)
    source = {"trajectory": [_state(0., rotations[0]), _state(2., rotations[1])]}
    antipodal = copy.deepcopy(source)
    antipodal["trajectory"][1]["body_quaternion_world"] = [-q for q in source["trajectory"][1]["body_quaternion_world"]]
    profiles = [build_flight_profile(source), build_flight_profile(antipodal)]
    independent = Slerp([0., 2.], rotations)
    for time in [0., .3, .75, 1.1, 2.]:
        expected = independent(time)
        for profile in profiles:
            np.testing.assert_allclose(_rotation(profile(time)).as_matrix(), expected.as_matrix(), atol=2e-14, rtol=0)
            np.testing.assert_allclose(profile(time)["velocity_m_s"], _expected_velocity(expected, [96., 10., 12.]), atol=3e-12, rtol=0)


@pytest.mark.parametrize("near_parallel", [False, True])
def test_selected_interval_and_export_preserve_orientation_at_common_times(near_parallel):
    rotations = (Rotation.from_rotvec([[0., 0., 0.], [.025, .015, -.02], [.04, -.01, .03]])
                 if near_parallel else Rotation.from_euler("xyz", [[12., 28., -37.], [48., -31., 62.], [-20., 17., 93.]], degrees=True))
    source = {"trajectory": [_state(0., rotations[0], velocity=[100., 8., 13.]),
                              _state(2., rotations[1], velocity=[160., -4., 20.], altitude=1000.),
                              _state(5., rotations[2], velocity=[80., 13., -3.], altitude=1800.)]}
    original = copy.deepcopy(source)
    whole = build_flight_profile(source)
    interval = build_flight_profile(source, start_s=.37, end_s=3.31)
    saved = interval.to_dict()
    replay = build_flight_profile(saved)
    assert saved["trajectory"][0]["time"] == .37
    assert saved["trajectory"][-1]["time"] == 3.31
    assert replay.metadata["profile_sha256"] == interval.metadata["profile_sha256"]
    for time in [.37, .5, .8, 1.31, 2., 2.7, 3.31]:
        expected = whole(time)
        for profile in [interval, replay]:
            actual = profile(time - .37)
            np.testing.assert_allclose(actual["velocity_m_s"], expected["velocity_m_s"], atol=5e-11, rtol=0)
            np.testing.assert_allclose(_rotation(actual).as_matrix(), _rotation(expected).as_matrix(), atol=4e-13, rtol=0)
            assert actual["flight_time_s"] == pytest.approx(time, abs=5e-16)
            assert actual["dynamic_pressure_pa"] == pytest.approx(expected["dynamic_pressure_pa"], rel=2e-15)
    assert source == original
    retained = interval(.43)
    source["trajectory"][0]["body_quaternion_world"][0] = 500.
    saved["trajectory"][0]["body_quaternion_world"][0] = 500.
    assert interval(.43) == retained
    json.dumps(interval.to_dict(), allow_nan=False)


@pytest.mark.parametrize("invalid", [[1., 0., 0.], [2., 0., 0., 0.], [0., 0., 0., 0.], [float("nan"), 0., 0., 0.]])
def test_profile_rejects_nonunit_or_invalid_saved_quaternion(invalid):
    source = {"trajectory": [_state(0., Rotation.identity()), _state(1., Rotation.identity())]}
    source["trajectory"][1]["body_quaternion_world"] = invalid
    with pytest.raises(ValueError, match="unit"):
        build_flight_profile(source)


def test_profile_rejects_incomplete_attitude_or_quaternion_axis_disagreement():
    source = {"trajectory": [_state(0., Rotation.identity()), _state(1., Rotation.identity())]}
    inconsistent = copy.deepcopy(source)
    inconsistent["trajectory"][1]["body_axis_world"] = [0., 0., 1.]
    with pytest.raises(ValueError, match="disagrees"):
        build_flight_profile(inconsistent)
    del source["trajectory"][1]["body_quaternion_world"]
    with pytest.raises(ValueError, match="incomplete"):
        build_flight_profile(source)
