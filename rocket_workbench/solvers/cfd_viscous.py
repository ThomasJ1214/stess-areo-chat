"""Experimental resolved laminar Newtonian transport on the CFD Cartesian grid.

The conservative viscous flux is [0, tau[:, axis], u.tau[:, axis]+k*dT/daxis].
It enters the conserved update with +div(flux). No eddy viscosity, transition,
wall function, turbulence closure or reconstructed boundary layer is used.
All array operations support the NumPy/CuPy namespace supplied by the caller.
"""
from __future__ import annotations

import math

import numpy as np

AIR_GAS_CONSTANT = 287.05287
PRANDTL = 0.72
GAMMA = 1.4
FIDELITY = "Experimental 3D compressible laminar Navier–Stokes CFD; first-order Cartesian finite volume"


def air_viscosity(temperature_k, xp=np):
    """Sutherland dry-air dynamic viscosity, Pa s (273.15 K reference)."""
    temperature = xp.asarray(temperature_k, dtype=xp.float64)
    if bool(xp.any(~xp.isfinite(temperature) | (temperature <= 0))):
        raise ValueError("Laminar CFD transport requires positive finite temperature.")
    return 1.716e-5 * (temperature / 273.15)**1.5 * (273.15 + 110.4) / (temperature + 110.4)


def thermal_conductivity(temperature_k, gamma=GAMMA, xp=np):
    """Fourier conductivity, W/(m K), with constant air Prandtl number 0.72."""
    cp = gamma * AIR_GAS_CONSTANT / (gamma - 1)
    return air_viscosity(temperature_k, xp) * cp / PRANDTL


def _primitive(state, gamma=GAMMA, xp=np):
    density = state[..., 0]
    velocity = state[..., 1:4] / density[..., None]
    pressure = (gamma - 1) * (state[..., 4] - 0.5 * density * xp.sum(velocity**2, axis=-1))
    return density, velocity, pressure / (density * AIR_GAS_CONSTANT)


def _face_pairs(values, solid, axis, boundary, farfield_value, xp=np):
    """Adjacent face values and solid flags, including exterior ghost centers."""
    first, last = xp.take(values, [0], axis=axis), xp.take(values, [-1], axis=axis)
    empty = xp.zeros(xp.take(solid, [0], axis=axis).shape, dtype=bool)
    if boundary == "periodic":
        left_ghost, right_ghost = last, first
        left_solid, right_solid = xp.take(solid, [-1], axis=axis), xp.take(solid, [0], axis=axis)
    elif boundary == "outflow":
        left_ghost, right_ghost = first, last
        left_solid = right_solid = empty
    elif boundary == "farfield":
        left_ghost = xp.broadcast_to(farfield_value, first.shape)
        right_ghost = xp.broadcast_to(farfield_value, last.shape)
        left_solid = right_solid = empty
    else:
        raise ValueError("Unknown boundary policy.")
    return (xp.concatenate((left_ghost, values), axis=axis),
            xp.concatenate((values, right_ghost), axis=axis),
            xp.concatenate((left_solid, solid), axis=axis),
            xp.concatenate((solid, right_solid), axis=axis))


def _cell_gradients(values, solid, spacing, boundary, farfield_value, reflected, xp=np):
    gradients = []
    trailing = values.ndim - solid.ndim
    for axis in range(3):
        left, right, sl, sr = _face_pairs(values, solid, axis, boundary, farfield_value, xp)
        take_left = [slice(None)] * values.ndim
        take_right = [slice(None)] * values.ndim
        take_left[axis], take_right[axis] = slice(None, -1), slice(1, None)
        mask_left = [slice(None)] * solid.ndim
        mask_right = [slice(None)] * solid.ndim
        mask_left[axis], mask_right[axis] = slice(None, -1), slice(1, None)
        left_neighbor, right_neighbor = left[tuple(take_left)], right[tuple(take_right)]
        left_mask, right_mask = sl[tuple(mask_left)], sr[tuple(mask_right)]
        suffix = (None,) * trailing
        left_neighbor = xp.where(left_mask[(...,) + suffix], reflected * values, left_neighbor)
        right_neighbor = xp.where(right_mask[(...,) + suffix], reflected * values, right_neighbor)
        gradient = (right_neighbor - left_neighbor) / (2 * spacing[axis])
        gradients.append(xp.where(solid[(...,) + suffix], 0.0, gradient))
    return xp.stack(gradients, axis=-1)


def _newtonian_stress(velocity_gradient, viscosity, xp=np):
    divergence = xp.trace(velocity_gradient, axis1=-2, axis2=-1)
    return viscosity[..., None, None] * (
        velocity_gradient + xp.swapaxes(velocity_gradient, -1, -2)
        - (2 / 3) * divergence[..., None, None] * xp.eye(3))


def viscous_fluxes(state, solid, spacing, farfield, boundary="farfield", gamma=GAMMA, xp=np):
    """One shared viscous flux per face; stationary no-slip, adiabatic walls.

    Interior transverse derivatives average neighboring centered gradients.
    At a material/nonflow face the fluid center is half a cell from the wall:
    all velocity components vanish at that wall and normal dT is zero. Wall
    mechanical work and heat flux are exactly zero, so kinetic dissipation
    becomes internal energy without injecting/removing total energy.
    """
    _, velocity, temperature = _primitive(state, gamma, xp)
    _, far_velocity, far_temperature = _primitive(xp.asarray(farfield), gamma, xp)
    gradients = _cell_gradients(velocity, solid, spacing, boundary, far_velocity, -1, xp)
    fluxes = []
    for axis in range(3):
        vl, vr, sl, sr = _face_pairs(velocity, solid, axis, boundary, far_velocity, xp)
        tl, tr, _, _ = _face_pairs(temperature, solid, axis, boundary, far_temperature, xp)
        gl, gr, _, _ = _face_pairs(gradients, solid, axis, boundary, xp.zeros((3, 3)), xp)
        face_gradient = 0.5 * (gl + gr)
        face_gradient[..., :, axis] = (vr - vl) / spacing[axis]
        wall = sl ^ sr
        fluid_velocity = xp.where(sl[..., None], vr, vl)
        wall_gradient = xp.zeros_like(face_gradient)
        wall_gradient[..., :, axis] = (2 / spacing[axis]) * fluid_velocity * xp.where(sl, 1.0, -1.0)[..., None]
        face_gradient = xp.where(wall[..., None, None], wall_gradient, face_gradient)
        face_temperature = xp.where(wall, xp.where(sl, tr, tl), 0.5 * (tl + tr))
        viscosity = air_viscosity(face_temperature, xp)
        stress = _newtonian_stress(face_gradient, viscosity, xp)
        traction = stress[..., :, axis]
        flux = xp.zeros(traction.shape[:-1] + (5,), dtype=state.dtype)
        flux[..., 1:4] = traction
        heat_transport = thermal_conductivity(face_temperature, gamma, xp) * (tr - tl) / spacing[axis]
        flux[..., 4] = xp.sum(0.5 * (vl + vr) * traction, axis=-1) + heat_transport
        # No slip means u_wall=0, and adiabatic means k*dT/dn=0.
        flux[..., 4] = xp.where(wall, 0.0, flux[..., 4])
        fluxes.append(xp.where((sl & sr)[..., None], 0.0, flux))
    return fluxes


def viscous_rhs(state, solid, spacing, farfield, boundary="farfield", gamma=GAMMA, xp=np):
    """Conservative resolved viscous/thermal contribution dU/dt=+div(Fv)."""
    derivative = xp.zeros_like(state)
    for axis, flux in enumerate(viscous_fluxes(state, solid, spacing, farfield, boundary, gamma, xp)):
        derivative += xp.diff(flux, axis=axis) / spacing[axis]
    return xp.where(solid[..., None], 0.0, derivative)


def diffusive_inverse_time(state, solid, spacing, gamma=GAMMA, xp=np, farfield=None):
    """Conservative global explicit diffusion rate, including half-cell walls.

    Global mu_max/rho_min bounds transport at shared faces even when density
    and temperature differ strongly. The factor four covers no-slip half-cell
    wall distances and tensor cross derivatives. Add this rate to the acoustic
    rate, rather than taking independently stable hyperbolic/parabolic steps.
    """
    density, _, temperature = _primitive(state, gamma, xp)
    fluid = ~solid
    if not bool(xp.any(fluid)):
        raise ValueError("Laminar CFD requires exterior fluid cells.")
    density_min = float(xp.min(xp.where(fluid, density, xp.inf)))
    viscosity_max = float(xp.max(xp.where(fluid, air_viscosity(temperature, xp), 0.0)))
    if farfield is not None:
        far_density, _, far_temperature = _primitive(xp.asarray(farfield), gamma, xp)
        density_min = min(density_min, float(far_density))
        viscosity_max = max(viscosity_max, float(air_viscosity(far_temperature, xp)))
    if not math.isfinite(density_min) or density_min <= 0:
        raise ValueError("Laminar CFD diffusion requires positive finite fluid density.")
    diffusivity = viscosity_max / density_min * max(4 / 3, gamma / PRANDTL)
    return float(4 * diffusivity * np.sum(1 / np.asarray(spacing, dtype=float)**2))


def wall_tractions(state, wall, spacing, gamma=GAMMA, xp=np):
    """Viscous traction on solid, tangential shear and wall-fluid temperature.

    Uses precisely the half-cell stationary-wall stencil in ``viscous_fluxes``.
    Normals point from solid to fluid. Thus traction on the solid is tau*n;
    pressure is separately -p*n. Normal viscous stress is retained distinctly
    from tangential wall shear, and neither is a material/structural stress.
    """
    indices = wall["fluid_indices"]
    fluid = state[indices[:, 0], indices[:, 1], indices[:, 2]]
    _, velocity, temperature = _primitive(fluid, gamma, xp)
    normals = wall["normals"]
    axis_spacing = xp.sum(xp.abs(normals) * xp.asarray(spacing), axis=-1)
    gradient = (2 / axis_spacing)[..., None, None] * velocity[..., :, None] * normals[..., None, :]
    stress = _newtonian_stress(gradient, air_viscosity(temperature, xp), xp)
    traction = xp.einsum("...ij,...j->...i", stress, normals)
    normal_traction = xp.sum(traction * normals, axis=-1)[..., None] * normals
    return traction, traction - normal_traction, temperature
