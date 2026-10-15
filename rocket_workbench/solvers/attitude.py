"""Rigid-body quaternion and Euler equations, independent of rocket force models.

Hamilton quaternion [w,x,y,z] maps right-handed NOSE-body coordinates into ENU
world coordinates. Body +X points toward the nose, +Y is original geometry Y,
and +Z is minus original geometry Z. Angular velocity is expressed in body axes.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation


def normalize(quaternion) -> np.ndarray:
    q = np.asarray(quaternion, dtype=float)
    norm = float(np.linalg.norm(q))
    if q.shape != (4,) or not np.all(np.isfinite(q)) or norm < 1e-12:
        raise ValueError("Attitude requires a finite nonzero quaternion [w,x,y,z].")
    return q / norm


def multiply(left, right) -> np.ndarray:
    w, xyz = float(left[0]), np.asarray(left[1:], dtype=float)
    v, uvw = float(right[0]), np.asarray(right[1:], dtype=float)
    return np.r_[w*v - np.dot(xyz, uvw), w*uvw + v*xyz + np.cross(xyz, uvw)]


def rotation_matrix(quaternion) -> np.ndarray:
    w, x, y, z = normalize(quaternion)
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
    ])


def quaternion_from_axis(nose_axis) -> np.ndarray:
    nose = np.asarray(nose_axis, dtype=float)
    nose /= np.linalg.norm(nose)
    transverse = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(transverse, nose))) > .9:
        transverse = np.array([0.0, 1.0, 0.0])
    transverse -= np.dot(transverse, nose)*nose
    transverse /= np.linalg.norm(transverse)
    third = np.cross(nose, transverse)
    xyzw = Rotation.from_matrix(np.column_stack((nose, transverse, third))).as_quat()
    return np.r_[xyzw[3], xyzw[:3]]


def derivatives(quaternion, angular_velocity_body, moment_body, inertia, inertia_rate=None) -> tuple[np.ndarray, np.ndarray]:
    """Euler angular momentum balance for a prescribed changing rigid tensor.

    Symmetric on-axis propellant outflow carries away its local angular momentum;
    callers must explicitly choose their model for this flux rather than hiding it
    as damping. With inertia_rate=None, Euler's constant-inertia equation applies.
    """
    omega = np.asarray(angular_velocity_body, dtype=float)
    tensor = np.asarray(inertia, dtype=float)
    moment = np.asarray(moment_body, dtype=float)
    if (tensor.shape != (3, 3) or not np.all(np.isfinite(tensor))
            or not np.allclose(tensor, tensor.T, rtol=1e-10, atol=1e-12)
            or np.min(np.linalg.eigvalsh(tensor)) <= 0):
        raise ValueError("Rigid-body inertia must be finite, symmetric positive definite.")
    if omega.shape != (3,) or moment.shape != (3,) or not np.all(np.isfinite(omega)) or not np.all(np.isfinite(moment)):
        raise ValueError("Rigid-body rates and applied moment must be finite three-vectors.")
    momentum = tensor @ omega
    rhs = moment - np.cross(omega, momentum)
    if inertia_rate is not None:
        rhs -= np.asarray(inertia_rate) @ omega
    dq = .5 * multiply(np.asarray(quaternion), np.r_[0.0, omega])
    return dq, np.linalg.solve(tensor, rhs)


def aerodynamic_normal(nose_axis, air_relative_velocity, dynamic_pressure: float, reference_area: float, cna: float) -> tuple[np.ndarray, float]:
    """Small-angle normal force opposite relative velocity transverse to nose.

    This helper reports the geometric angle and does not decide a domain cutoff;
    the flight integrator must enforce its documented small-angle policy.
    """
    nose = np.asarray(nose_axis, dtype=float)
    relative = np.asarray(air_relative_velocity, dtype=float)
    speed = float(np.linalg.norm(relative))
    if speed < 1e-8:
        return np.zeros(3), 0.0
    axial = float(np.dot(relative, nose))
    perpendicular = relative - axial*nose
    transverse_speed = float(np.linalg.norm(perpendicular))
    angle = float(np.arctan2(transverse_speed, axial))
    force = -dynamic_pressure*reference_area*cna*angle*perpendicular/transverse_speed if transverse_speed > 1e-10 else np.zeros(3)
    return force, angle


def cp_moment(normal_force_world, body_to_world, cp_m: float, cg_geometry) -> np.ndarray:
    """Return body moment from CP on original geometry axis and actual 3D CG."""
    geometry_to_body = np.diag([-1.0, 1.0, -1.0])
    arm_body = geometry_to_body @ (np.array([cp_m, 0.0, 0.0]) - np.asarray(cg_geometry))
    return np.cross(arm_body, np.asarray(body_to_world).T @ normal_force_world)
