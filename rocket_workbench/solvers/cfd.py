"""Experimental compressible Euler CFD on a uniform, Cartesian cut-free grid.

This is a conservative first-order finite-volume solver, not a viscous CFD or
turbulence model. Solid faces use the analytic reflected slip-wall Riemann flux.
The staircase surface and coarse-grid numerical dissipation are significant.
Every field returned by ``solve`` comes from the evolving conserved state.
"""
from __future__ import annotations

import math
import hashlib
import time
from typing import Any

import numpy as np

GAMMA = 1.4
FIDELITY = "Experimental 3D compressible inviscid Euler CFD; first-order Cartesian finite volume"


def conserved(density, velocity, pressure, gamma: float = GAMMA, xp=np):
    """Convert physical primitive states to [rho, rho*u, rho*v, rho*w, E]."""
    velocity = xp.asarray(velocity, dtype=xp.float64)
    density = xp.asarray(density, dtype=xp.float64)
    pressure = xp.asarray(pressure, dtype=xp.float64)
    shape = xp.broadcast_shapes(density.shape, pressure.shape, velocity.shape[:-1])
    rho = xp.broadcast_to(density, shape)
    vel = xp.broadcast_to(velocity, shape + (3,))
    energy = pressure / (gamma - 1) + 0.5 * rho * xp.sum(vel * vel, axis=-1)
    return xp.concatenate((rho[..., None], rho[..., None] * vel, energy[..., None]), axis=-1)


def primitives(state, gamma: float = GAMMA, xp=np):
    """Return density, velocity, pressure and sound speed without modifying state."""
    rho = state[..., 0]
    velocity = state[..., 1:4] / rho[..., None]
    pressure = (gamma - 1) * (state[..., 4] - 0.5 * rho * xp.sum(velocity**2, axis=-1))
    # Small negative values are NOT silently clipped: callers reject invalid states.
    sound = xp.sqrt(gamma * pressure / rho)
    return rho, velocity, pressure, sound


def euler_flux(state, axis: int, gamma: float = GAMMA, xp=np):
    _, velocity, pressure, _ = primitives(state, gamma, xp)
    return _primitive_flux(state, axis, velocity, pressure)


def _primitive_flux(state, axis, velocity, pressure):
    """Euler flux from already recovered primitives; avoids duplicate grid work."""
    normal_velocity = velocity[..., axis]
    flux = state * normal_velocity[..., None]
    flux[..., axis + 1] += pressure
    flux[..., 4] = (state[..., 4] + pressure) * normal_velocity
    return flux


def rusanov_flux(left, right, axis: int, gamma: float = GAMMA, xp=np):
    """Local Lax-Friedrichs/Rusanov numerical flux, shared by adjacent cells."""
    _, vl, pl, cl = primitives(left, gamma, xp)
    _, vr, pr, cr = primitives(right, gamma, xp)
    speed = xp.maximum(xp.abs(vl[..., axis]) + cl, xp.abs(vr[..., axis]) + cr)
    return 0.5 * (_primitive_flux(left, axis, vl, pl) + _primitive_flux(right, axis, vr, pr)) - 0.5 * speed[..., None] * (right - left)


def wall_riemann_pressure(density, pressure, velocity_toward_wall, gamma=GAMMA, xp=np):
    """Exact symmetric Euler Riemann pressure at an impermeable stationary wall.

    The mirror problem has zero contact velocity. Compression follows the
    Rankine-Hugoniot shock curve; expansion follows the isentropic rarefaction
    curve. A sufficiently strong expansion creates genuine vacuum at the wall.
    Unlike a Rusanov reflection, an expansion cannot give negative pressure.
    """
    density = xp.asarray(density)
    pressure = xp.asarray(pressure)
    toward = xp.asarray(velocity_toward_wall)
    sound = xp.sqrt(gamma * pressure / density)
    # f(p*)=(p*-p)*sqrt(2/((gamma+1)*rho)/(p*+B))=u_toward.
    compression_speed = xp.maximum(toward, 0)
    d = compression_speed**2 * (gamma + 1) * density / 2
    b = (gamma - 1) * pressure / (gamma + 1)
    shock = pressure + d / 2 + xp.sqrt(d * (d + 4 * (pressure + b))) / 2
    rarefaction = pressure * xp.maximum(0, 1 + (gamma - 1) * toward / (2 * sound)) ** (2 * gamma / (gamma - 1))
    return xp.where(toward >= 0, shock, rarefaction)


def _axis_flux(state, solid, axis, farfield, boundary="farfield", gamma=GAMMA, xp=np):
    first = xp.take(state, [0], axis=axis)
    last = xp.take(state, [-1], axis=axis)
    first_solid = xp.zeros(first.shape[:-1], dtype=bool)
    last_solid = xp.zeros(last.shape[:-1], dtype=bool)
    if boundary == "periodic":
        left_ghost, right_ghost = last, first
        first_solid = xp.take(solid, [-1], axis=axis)
        last_solid = xp.take(solid, [0], axis=axis)
    elif boundary == "outflow":
        left_ghost, right_ghost = first, last
    elif boundary == "farfield":
        # Prescribed undisturbed far field on all six faces. Keep them far enough
        # from the object and inspect domain-size sensitivity before interpreting forces.
        left_ghost = xp.broadcast_to(farfield, first.shape)
        right_ghost = xp.broadcast_to(farfield, last.shape)
    else:
        raise ValueError("Unknown boundary policy.")
    left = xp.concatenate((left_ghost, state), axis=axis)
    right = xp.concatenate((state, right_ghost), axis=axis)
    solid_left = xp.concatenate((first_solid, solid), axis=axis)
    solid_right = xp.concatenate((solid, last_solid), axis=axis)
    # Rusanov is used only on fluid/fluid faces. Solid-face entries below are
    # overwritten by the analytic reflected Riemann flux, avoiding full-grid
    # mirror-state copies and their additional CPU/GPU memory allocations.
    flux = rusanov_flux(left, right, axis, gamma, xp)
    flux = xp.where((solid_left & solid_right)[..., None], 0.0, flux)
    wall = solid_left ^ solid_right
    fluid = xp.where(solid_left[wall][..., None], right[wall], left[wall])
    rho, velocity, pressure, _ = primitives(fluid, gamma, xp)
    toward = xp.where(solid_left[wall], -velocity[..., axis], velocity[..., axis])
    # The exact reflected Riemann solution transports neither mass nor energy
    # through the stationary wall. The normal pressure impulse is the only flux.
    wall_flux = xp.zeros_like(fluid)
    wall_flux[..., axis + 1] = wall_riemann_pressure(rho, pressure, toward, gamma, xp)
    flux[wall] = wall_flux
    return flux, solid_left, solid_right


def stable_timestep(state, solid, spacing, cfl=0.35, gamma=GAMMA, xp=np) -> float:
    """Unsplit positive-state CFL bound including all three characteristic speeds."""
    _, velocity, _, sound = primitives(state, gamma, xp)
    inverse_time = xp.sum((xp.abs(velocity) + sound[..., None]) / xp.asarray(spacing), axis=-1)
    rate = float(xp.max(xp.where(solid, 0.0, inverse_time)))
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("The Euler state is nonphysical or has no fluid cells.")
    return float(cfl / rate)


def finite_volume_step(state, solid, spacing, dt, farfield, boundary="farfield", gamma=GAMMA, xp=np):
    """One unsplit conservative forward-Euler step; useful independently for tests."""
    derivative = xp.zeros_like(state)
    for axis in range(3):
        flux, _, _ = _axis_flux(state, solid, axis, farfield, boundary, gamma, xp)
        derivative -= xp.diff(flux, axis=axis) / spacing[axis]
    updated = state + dt * derivative
    return xp.where(solid[..., None], state, updated)


def _physical(state, solid, xp=np) -> bool:
    rho = state[..., 0]
    pressure = (GAMMA - 1) * (state[..., 4] - 0.5 * xp.sum(state[..., 1:4] ** 2, axis=-1) / rho)
    invalid = (~xp.isfinite(state).all(axis=-1)) | (rho <= 0) | (pressure <= 0)
    return not bool(xp.any(invalid & ~solid))


def _backend(requested: str):
    if requested not in {"auto", "cpu", "gpu"}:
        raise ValueError("CFD backend must be auto, cpu or gpu.")
    if requested != "cpu":
        from ..backenddiagnostics import cuda_diagnostics
        diagnostics = cuda_diagnostics()
        if diagnostics["available"]:
            import cupy as cp
            return cp, "cupy-cuda", []
        if requested == "gpu":
            raise RuntimeError(f"GPU CFD requires a supported NVIDIA GPU, driver and bundled CuPy CUDA runtime. CUDA check failed at {diagnostics['probe_stage']}: {diagnostics['reason']} Select CPU or automatic backend.")
        return np, "numpy-cpu", [f"CUDA execution unavailable; the actual CFD calculation used the CPU. CUDA check failed at {diagnostics['probe_stage']}: {diagnostics['reason']}"]
    return np, "numpy-cpu", []


def _number(options, name, default, low, high, integer=False):
    raw = options.get(name, default)
    if isinstance(raw, bool):
        raise ValueError(f"{name} must be a number.")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if not math.isfinite(value) or not low <= value <= high or (integer and int(value) != value):
        raise ValueError(f"{name} must be {'an integer' if integer else 'a number'} between {low} and {high}.")
    return int(value) if integer else value


def _exterior_flow_mask(surface_solid):
    """Block enclosed space in a copied flow grid, preserving boundary-connected air.

    Six-neighbor Cartesian connectivity matches the solver's six face fluxes.
    Material and sealed air cavities are both nonflow; this operation changes no
    CAD triangles, signed material volume, asset, or FEA geometry.
    """
    from scipy.ndimage import binary_fill_holes, generate_binary_structure
    return binary_fill_holes(surface_solid, structure=generate_binary_structure(3, 1))


def _voxel_domain(mesh, options, *, diagnostics=None):
    """Voxelize exterior-flow boundaries on a separate immutable-source flow grid."""
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError("CFD needs external rocket geometry.")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError("The imported geometry contains nonfinite vertices.")
    bounds = np.asarray(mesh.bounds, dtype=float)
    extent = bounds[1] - bounds[0]
    longest = float(np.max(extent))
    if longest <= 0:
        raise ValueError("The geometry has no physical extent.")
    resolution = _number(options, "grid_resolution", 32, 12, 256, True)
    transverse = _number(options, "transverse_resolution", min(24, resolution), 12, 128, True)
    max_cells = _number(options, "max_cells", 300000, 1000, 2000000, True)
    pad = _number(options, "domain_padding", 0.50, 0.15, 3.0)
    if np.any(extent <= 0):
        raise ValueError("CFD needs geometry with nonzero extent in all three dimensions.")
    # Slender rockets require independent transverse spacing: a cube whose pitch
    # is based on rocket length would fail to resolve body diameter. Preserve
    # genuine Cartesian anisotropy in the flux/CFL/face-area calculations.
    spacing = extent / np.array([resolution, transverse, transverse])
    lower = bounds[0] - extent * np.array([max(pad, 0.35), pad, pad])
    upper = bounds[1] + extent * np.array([max(pad, 0.65), pad, pad])
    lower = np.floor(lower / spacing) * spacing
    shape = np.ceil((upper - lower) / spacing).astype(int)
    cells = math.prod(shape.tolist())
    if cells > max_cells:
        raise ValueError(f"The requested grid has {cells:,} cells, exceeding the explicit max_cells budget {max_cells:,}. Reduce grid_resolution or increase max_cells (maximum 2,000,000).")
    # Voxelize in dimensionless anisotropic cell coordinates. This retains the
    # imported triangles exactly before discretization and avoids ray/rtree deps.
    grid_mesh = mesh.copy()
    grid_mesh.vertices /= spacing
    voxel = grid_mesh.voxelized(pitch=1.0, method="subdivide")
    points = np.asarray(voxel.points)
    origin = lower
    indices = np.rint(points - origin / spacing).astype(int)
    inside = np.all((indices >= 0) & (indices < shape), axis=1)
    indices = indices[inside]
    solid = np.zeros(tuple(shape), dtype=bool)
    if len(indices):
        solid[tuple(indices.T)] = True
    if not solid.any():
        raise ValueError("The voxel grid does not resolve any solid geometry.")
    if solid[0].any() or solid[-1].any() or solid[:, 0].any() or solid[:, -1].any() or solid[:, :, 0].any() or solid[:, :, -1].any():
        raise ValueError("Geometry intersects the farfield boundary; increase domain_padding.")
    surface_cells = int(solid.sum())
    solid = _exterior_flow_mask(solid)
    # These counts deliberately distinguish surface voxels from all enclosed
    # nonflow volume, not material from air: boundary tessellation alone cannot
    # establish a trustworthy volumetric material/void decomposition.
    if diagnostics is not None:
        digest = hashlib.sha256()
        digest.update(np.asarray(solid.shape, dtype="<i8").tobytes())
        digest.update(np.asarray(spacing, dtype="<f8").tobytes())
        digest.update(np.asarray(origin, dtype="<f8").tobytes())
        digest.update(np.packbits(solid, bitorder="little").tobytes())
        diagnostics.update(surface_voxel_cells=surface_cells,
                           enclosed_nonflow_cells=int(solid.sum()) - surface_cells,
                           exterior_fluid_cells=int((~solid).sum()),
                           aerodynamic_voxel_sha256=digest.hexdigest(),
                           aerodynamic_geometry_policy="Only air connected to the six farfield faces is solved; sealed interiors are nonflow",
                           source_material_mesh_modified=False)
    warnings = []
    if not mesh.is_watertight:
        warnings.append("The combined mesh is not watertight. Surface voxels were filled where enclosed; leaks and overlaps may change the solid mask. Inspect the voxel counts and use closed CAD parts.")
    widths = []
    for x_slice in solid:
        occupied = np.argwhere(x_slice)
        if len(occupied):
            widths.append(np.ptp(occupied, axis=0) + 1)
    median_widths = np.median(widths, axis=0)
    diameter_cells = float(np.min(median_widths))
    if diagnostics is not None:
        diagnostics.update(geometry_extent_m=extent.tolist(),
                           geometry_extent_cells=(extent / spacing).tolist(),
                           median_solid_cross_section_cells=median_widths.tolist(),
                           cross_section_axes=["Y", "Z"])
    if diameter_cells < 8:
        warnings.append(f"The median solid cross-section spans only {diameter_cells:.1f} transverse cells. Refine substantially before interpreting pressure forces.")
    warnings.append("Fins or gaps thinner than one cell are stair-stepped or merged; mesh refinement and domain-size studies are required.")
    warnings.append("Aerodynamics uses only exterior-connected air: sealed interior space is blocked in a separate flow grid and generates no internal pressure faces. Source CAD cavities, component mass and FEA geometry are unchanged. Open bores and leaks remain flow passages; cap an opening only if the physical vehicle is sealed.")
    return solid, spacing, origin, warnings


def _fin_resolution(project, configuration_id, spacing, original):
    """Declared original-fin thickness versus Cartesian support along its normal.

    This is a grid-resolution indicator, not a claim that voxels reproduce the
    true thickness. Arbitrary replacement CAD has no reliable thickness field.
    """
    from ..geometry import FINS
    from ..models import active_components
    rows = []
    for component in active_components(project, configuration_id):
        if not component.external or component.kind not in FINS:
            continue
        row = dict(component_id=component.id, component_name=component.name)
        if not original and component.geometry_mode == "replacement":
            rows.append(row | {"thickness_m": None, "cells_across_thickness_min": None,
                               "cells_across_thickness_max": None,
                               "source": "CAD replacement; thickness is not inferred from original ORK dimensions"})
            continue
        thickness = 0.0 if component.metadata.get("zero_thickness") else component.thickness
        cant = math.radians(float(component.metadata.get("cant", 0)))
        rotation = float(component.metadata.get("angleoffset", component.metadata.get("rotation", 0)))
        cells = []
        for index in range(component.fin_count):
            angle = math.radians(rotation + 360 * index / component.fin_count)
            normal = np.array([math.sin(cant), -math.cos(cant) * math.sin(angle), math.cos(cant) * math.cos(angle)])
            cells.append(thickness / float(np.dot(np.abs(normal), spacing)))
        rows.append(row | {"thickness_m": float(thickness),
                           "cells_across_thickness_min": min(cells),
                           "cells_across_thickness_max": max(cells),
                           "source": "Declared original ORK fin thickness / Cartesian cell support along fin normal"})
    return rows


def _record_history(history, row):
    """Keep diagnostic history bounded even during an unlimited solve."""
    history.append(row)
    if len(history) > 4000:
        # Preserve first and latest samples while thinning older samples.
        history[:] = history[::2]


def _wall_geometry(solid, spacing, origin):
    """Positions, solid-outward normals, areas and adjacent fluid-cell indices."""
    positions, normals, areas, fluid_indices = [], [], [], []
    for axis in range(3):
        area = float(np.prod(np.delete(spacing, axis)))
        end_shape = list(solid.shape)
        end_shape[axis] = 1
        empty = np.zeros(end_shape, dtype=bool)
        left_solid = np.concatenate((empty, solid), axis=axis)
        right_solid = np.concatenate((solid, empty), axis=axis)
        boundary = left_solid ^ right_solid
        indices = np.argwhere(boundary)
        if not len(indices):
            continue
        # Face k separates centers k-1 and k. Outward normal points from solid to fluid.
        position = origin + indices * spacing
        position[:, axis] -= spacing[axis] / 2
        normal = np.zeros_like(position)
        normal[:, axis] = np.where(left_solid[boundary], 1.0, -1.0)
        fluid = indices.copy()
        fluid[:, axis] -= right_solid[boundary].astype(int)
        if np.any(fluid < 0) or np.any(fluid >= np.asarray(solid.shape)):
            raise ValueError("Solid geometry touches the external fluid boundary.")
        positions.append(position)
        normals.append(normal)
        areas.append(np.full(len(indices), area))
        fluid_indices.append(fluid)
    if not positions:
        raise RuntimeError("No exposed wall faces were found in the solid grid.")
    return dict(positions=np.concatenate(positions), normals=np.concatenate(normals),
                areas=np.concatenate(areas), fluid_indices=np.concatenate(fluid_indices))


def _wall_pressure(state, wall, xp=np):
    indices = wall["fluid_indices"]
    fluid = state[indices[:, 0], indices[:, 1], indices[:, 2]]
    rho, velocity, pressure, _ = primitives(fluid, xp=xp)
    toward = -xp.sum(velocity * wall["normals"], axis=-1)
    return wall_riemann_pressure(rho, pressure, toward, xp=xp)


def _surface(state, solid, spacing, origin, farfield, pressure_inf, speed, rho_inf, limit):
    """Integrate the same exact wall Riemann flux used by the conservative update."""
    wall = _wall_geometry(solid, spacing, origin)
    positions, normals = wall["positions"], wall["normals"]
    pressures = _wall_pressure(state, wall)
    force = -(pressures - pressure_inf)[:, None] * normals * wall["areas"][:, None]
    total_force = force.sum(axis=0)
    total_moment = np.cross(positions, force).sum(axis=0)
    count = len(pressures)
    take = np.linspace(0, count - 1, min(count, limit), dtype=int)
    q = 0.5 * rho_inf * speed**2
    coefficient_defined = q > pressure_inf * np.finfo(float).eps * 64
    rows = [dict(position=positions[i].tolist(), pressure_pa=float(pressures[i]),
                 pressure_coefficient=float((pressures[i] - pressure_inf) / q) if coefficient_defined else None,
                 normal=normals[i].tolist()) for i in take]
    return rows, total_force, total_moment, count, int(np.sum(pressures <= 0))


def _flow_grid(velocity, solid, spacing, origin, max_nodes=100_000):
    """Bounded, regular samples of actual solved velocity for streamlines.

    Values lie on solver cell centers, not cell faces. Every source nonflow cell
    blocks all corners of the output interpolation cube containing it. Therefore
    a trilinear renderer accepting only all-fluid support cannot reconstruct a
    fictitious passage through a thin wall or an enclosed cavity after striding.
    This conservative display mask never changes the solver or source geometry.
    """
    solver_shape = np.asarray(solid.shape, dtype=int)
    stride = max(1, math.ceil((int(solid.size) / max_nodes) ** (1 / 3)))
    while math.prod(((solver_shape - 1) // stride + 1).tolist()) > max_nodes:
        stride += 1
    sampled = np.array(velocity[::stride, ::stride, ::stride], copy=True, order="C")
    shape = np.asarray(sampled.shape[:-1], dtype=int)
    fluid = np.ones(tuple(shape), dtype=bool)
    if stride == 1:
        fluid[:] = ~solid
    else:
        # A solid may fall between sampled nodes. Mark both bounding nodes in
        # each direction, including original occupied nodes themselves. Clipping
        # only affects the unsampled remainder beyond the final output node.
        blocked = np.argwhere(solid) // stride
        for i in (0, 1):
            for j in (0, 1):
                for k in (0, 1):
                    corners = np.minimum(blocked + [i, j, k], shape - 1)
                    fluid[tuple(corners.T)] = False
    sampled[~fluid] = 0.0
    return dict(
        shape=shape.tolist(), origin_m=np.asarray(origin).tolist(),
        spacing_m=(np.asarray(spacing) * stride).tolist(),
        velocity_m_s=sampled.reshape(-1).tolist(),
        fluid_mask=fluid.reshape(-1).astype(np.uint8).tolist(),
        layout="C order: node=(i*ny+j)*nz+k; velocity[node*3+axis]",
        solver_shape=solver_shape.tolist(),
        solver_origin_m=np.asarray(origin).tolist(),
        solver_spacing_m=np.asarray(spacing).tolist(),
        stride=stride, node_count=int(fluid.size), visualization_only=True,
        interpolation="Trilinear only where every nonzero-weight support node is fluid; terminate at nonflow or the exported center bounds",
        sampling_policy="Actual solver cell-center velocities at a regular integer stride; every nonflow source cell blocks its enclosing output interpolation cube. Unsampled domain-edge remainder is omitted. No reconstructed boundary layer or turbulence.",
    )


class _TransientRecorder:
    """Bounded actual-time snapshots with one immutable display topology.

    Snapshot scheduling never changes the CFL step or interpolates a fluid state.
    A scheduled time is represented by the first accepted state at/after it;
    the initial state and exact final/cancelled state are always retained.
    """

    def __init__(self, state, solid, spacing, origin, wall, pressure_inf,
                 density_inf, velocity_inf, duration, frame_limit,
                 sample_limit, surface_limit):
        self.solid = solid
        self.wall = wall
        self.duration = duration
        self.frame_limit = frame_limit
        self.pressure_inf = pressure_inf
        self.density_inf = density_inf
        self.speed = float(np.linalg.norm(velocity_inf))
        self.velocity_inf = velocity_inf
        self.dynamic_pressure = 0.5 * density_inf * self.speed**2
        fluid_indices = np.argwhere(~solid)
        take = np.linspace(0, len(fluid_indices) - 1,
                           min(sample_limit, 1000, len(fluid_indices)), dtype=int)
        self.sample_indices = fluid_indices[take]
        self.surface_indices = np.linspace(
            0, len(wall["areas"]) - 1,
            min(surface_limit, 2000, len(wall["areas"])), dtype=int)
        _, initial_velocity, _, _ = primitives(state)
        flow = _flow_grid(initial_velocity, solid, spacing, origin, max_nodes=12_000)
        self.mask = np.asarray(flow["fluid_mask"], dtype=bool).reshape(flow["shape"])
        self.stride = flow["stride"]
        flow.pop("velocity_m_s")
        self.topology = dict(
            flow_grid=flow,
            sample_positions_m=(origin + self.sample_indices * spacing).tolist(),
            surface_positions_m=wall["positions"][self.surface_indices].tolist(),
            surface_normals=wall["normals"][self.surface_indices].tolist(),
        )
        self.frames = []
        self.next_schedule = 1
        self.capture(state, 0.0, 0)

    def due(self, physical_time):
        # Reserve a slot for the exact final/cancelled numerical state.
        return (self.next_schedule < self.frame_limit - 1 and
                physical_time >= self.duration * self.next_schedule / (self.frame_limit - 1))

    def capture(self, state, physical_time, step, environment=None):
        environment = environment or dict(
            pressure_pa=self.pressure_inf, density_kg_m3=self.density_inf,
            velocity_m_s=self.velocity_inf.tolist())
        pressure_inf = float(environment["pressure_pa"])
        incoming_velocity = np.asarray(environment["velocity_m_s"], dtype=float)
        speed = float(np.linalg.norm(incoming_velocity))
        dynamic_pressure = 0.5 * float(environment["density_kg_m3"]) * speed**2
        rho, velocity, pressure, sound = primitives(state)
        index = tuple(self.sample_indices.T)
        sampled_velocity = velocity[index]
        wall_pressure = _wall_pressure(state, self.wall)
        face_force = -(wall_pressure - pressure_inf)[:, None] * self.wall["normals"] * self.wall["areas"][:, None]
        force = face_force.sum(axis=0)
        moment = np.cross(self.wall["positions"], face_force).sum(axis=0)
        flow_velocity = np.array(velocity[::self.stride, ::self.stride, ::self.stride], copy=True)
        flow_velocity[~self.mask] = 0.0
        frame = dict(
            time_s=float(physical_time), step=int(step),
            flow_velocity_m_s=flow_velocity.reshape(-1).tolist(),
            sample_pressure_pa=pressure[index].tolist(),
            sample_velocity_m_s=sampled_velocity.tolist(),
            sample_density_kg_m3=rho[index].tolist(),
            sample_mach=(np.linalg.norm(sampled_velocity, axis=-1) / sound[index]).tolist(),
            surface_pressure_pa=wall_pressure[self.surface_indices].tolist(),
            force_n=force.tolist(), moment_about_origin_nm=moment.tolist(),
            pressure_drag_n=float(np.dot(force, incoming_velocity / speed)) if speed else 0.0,
            freestream_pressure_pa=pressure_inf,
            dynamic_pressure_pa=dynamic_pressure,
            freestream_velocity_m_s=incoming_velocity.tolist(),
            freestream_mach=speed / math.sqrt(GAMMA * pressure_inf / float(environment["density_kg_m3"])) if speed else 0.0,
            pressure_coefficient_defined=bool(dynamic_pressure > pressure_inf * np.finfo(float).eps * 64),
            altitude_msl_m=environment.get("altitude_msl_m"),
            flight_time_s=environment.get("flight_time_s"),
        )
        if self.frames and self.frames[-1]["step"] == step:
            self.frames[-1] = frame
        elif len(self.frames) < self.frame_limit:
            self.frames.append(frame)
        else:
            self.frames[-1] = frame
        while (self.next_schedule < self.frame_limit - 1 and
               physical_time >= self.duration * self.next_schedule / (self.frame_limit - 1)):
            self.next_schedule += 1

    def result(self, completed):
        return dict(
            duration_s=self.duration, completed=completed, topology=self.topology,
            frames=self.frames, frame_limit=self.frame_limit,
            max_display_nodes=12_000,
            temporal_sampling="Actual accepted Euler states at their physical timestamps; scheduled capture times snap forward to an accepted step. Initial and final/cancelled states retained. No temporal field interpolation.",
            scope="Fixed rocket geometry, uniform initial freestream and constant prescribed farfield; inviscid numerical startup/evolution, without moving geometry or modeled turbulence.",
        )


def _freestream_environment(provider, physical_time):
    """Validate prescribed boundary data without modifying provider output."""
    environment = dict(provider(physical_time))
    for key in ("density_kg_m3", "pressure_pa"):
        if isinstance(environment[key], bool):
            raise ValueError(f"Transient freestream {key} must be positive and finite.")
        value = float(environment[key])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Transient freestream {key} must be positive and finite.")
        environment[key] = value
    velocity = np.asarray(environment["velocity_m_s"], dtype=float)
    if velocity.shape != (3,) or not np.isfinite(velocity).all():
        raise ValueError("Transient freestream velocity_m_s must be a finite 3D vector.")
    mach = float(np.linalg.norm(velocity)) / math.sqrt(GAMMA * environment["pressure_pa"] / environment["density_kg_m3"])
    if mach > 2.05 + 1e-12:
        raise ValueError("The prescribed transient freestream exceeds the supported Mach 2 range.")
    environment["velocity_m_s"] = velocity.tolist()
    environment["freestream_mach"] = mach
    for key in ("altitude_msl_m", "flight_time_s"):
        if environment.get(key) is not None:
            value = float(environment[key])
            if not math.isfinite(value):
                raise ValueError(f"Transient freestream {key} must be finite.")
            environment[key] = value
    acceleration = np.asarray(environment.get("frame_acceleration_m_s2", [0, 0, 0]), dtype=float)
    if acceleration.shape != (3,) or not np.isfinite(acceleration).all():
        raise ValueError("Transient frame_acceleration_m_s2 must be a finite 3D vector.")
    environment["frame_acceleration_m_s2"] = acceleration.tolist()
    return environment


def _accelerating_frame_update(state, solid, acceleration, dt, xp=np):
    """Translation-only inertial source, preserving internal energy exactly.

    Constant frame acceleration over an explicit split step gives momentum
    impulse -rho*a*dt and corresponding kinetic-energy work. It does not imply
    a rotating coordinate frame, moving walls, or a full vehicle-attitude model.
    """
    impulse_velocity = xp.asarray(acceleration) * dt
    updated = state.copy()
    momentum = state[..., 1:4]
    updated[..., 1:4] = momentum - state[..., 0, None] * impulse_velocity
    updated[..., 4] = state[..., 4] - xp.sum(momentum * impulse_velocity, axis=-1) + 0.5 * state[..., 0] * xp.sum(impulse_velocity**2)
    return xp.where(solid[..., None], state, updated)


def solve(project, conditions, configuration_id: str | None = None,
          options: dict | None = None, progress=None, cancelled=None,
          telemetry=None, freestream_provider=None) -> dict[str, Any]:
    """Run real Euler flow on current/original combined project geometry.

    Steady mode has no wall-clock, step or physical-time stopping budget. It
    stops only at numerical convergence or cancellation. Transient mode solves
    the requested physical duration, independently of the steady residual.
    Cell allocation limits remain enforced; cancellation retains actual fields.
    The optional telemetry callback receives structured measured progress while
    the existing two-argument progress callback remains compatible.
    """
    from ..geometry import project_mesh
    from .aero import atmosphere, freestream

    options = dict(options or {})
    mode = options.get("mode", "steady")
    if not isinstance(mode, str) or mode not in {"steady", "transient"}:
        raise ValueError("CFD mode must be steady or transient.")
    if freestream_provider is not None and mode != "transient":
        raise ValueError("A time-varying freestream provider requires transient CFD mode.")
    duration = None
    if mode == "transient":
        raw_duration = options.get("duration_s")
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError) as exc:
            raise ValueError("Transient duration_s must be a positive finite physical time in seconds.") from exc
        if isinstance(raw_duration, bool) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("Transient duration_s must be a positive finite physical time in seconds.")
    frame_limit = _number(options, "snapshot_count", 24, 2, 32, True)
    legacy_stop_options = sorted(set(options) & {
        "max_steps", "max_wall_seconds", "max_physical_time", "flow_through_times", "run_until_converged",
    })
    cfl = _number(options, "cfl", 0.35, 0.01, 0.8)
    tolerance = _number(options, "convergence_tolerance", 1e-5, 1e-10, 0.01)
    sample_limit = _number(options, "sample_limit", 4000, 1, 20000, True)
    surface_limit = _number(options, "surface_limit", 5000, 1, 30000, True)
    original = options.get("original", False)
    if not isinstance(original, bool):
        raise ValueError("original must be a boolean geometry selection.")
    xp, backend, warnings = _backend(str(options.get("backend", "auto")))
    if legacy_stop_options:
        warnings.append("Legacy CFD stopping options are ignored: " + ", ".join(legacy_stop_options) + ". Steady mode stops only at convergence/cancellation; transient mode completes duration_s or is cancelled. No wall-clock or step timeout is enforced.")
    start = time.perf_counter()
    if telemetry:
        telemetry(dict(mode=mode, phase="voxelization", integration_steps=0,
                       physical_time_s=0.0, target_physical_time_s=duration,
                       elapsed_seconds=0.0, integration_elapsed_seconds=0.0,
                       done=False, status="running"))
    if progress:
        progress(0.0, "Voxelizing the external rocket geometry for the Euler grid")
    mesh = project_mesh(project, configuration_id, original=original)
    mesh_digest = hashlib.sha256()
    mesh_digest.update(np.asarray(mesh.vertices, dtype="<f8").tobytes())
    mesh_digest.update(np.asarray(mesh.faces, dtype="<i8").tobytes())
    geometry_diagnostics = {}
    solid_cpu, spacing, origin, voxel_warnings = _voxel_domain(mesh, options, diagnostics=geometry_diagnostics)
    warnings.extend(voxel_warnings)
    geometry_diagnostics["fin_resolution"] = _fin_resolution(project, configuration_id, spacing, original)
    for fin in geometry_diagnostics["fin_resolution"]:
        cells = fin["cells_across_thickness_min"]
        if cells is not None and cells < 2:
            warnings.append(f"{fin['component_name']}: declared fin thickness spans only {cells:.2f} Cartesian cells along its normal. The grid cannot resolve the thickness reliably; refine the transverse grid and inspect sensitivity.")
    air = atmosphere(conditions.altitude, conditions.temperature_delta)
    # The shared aerodynamic convention includes wind and treats optional Mach
    # as the axial speed input before adding the lateral wind vector.
    flow = freestream(conditions)
    if isinstance(flow, dict):
        velocity = np.asarray(flow.get("velocity", flow.get("velocity_m_s", flow.get("vector"))), dtype=float)
    else:
        velocity = np.asarray(flow, dtype=float)
    if velocity.shape != (3,) or not np.isfinite(velocity).all():
        raise ValueError("Freestream must contain a finite 3D velocity vector.")
    rho_inf = float(air.get("density", air.get("density_kg_m3")))
    pressure_inf = float(air.get("pressure", air.get("pressure_pa")))
    environment = dict(density_kg_m3=rho_inf, pressure_pa=pressure_inf,
                       velocity_m_s=velocity.tolist(), altitude_msl_m=conditions.altitude,
                       flight_time_s=None, frame_acceleration_m_s2=[0, 0, 0])
    if freestream_provider is not None:
        environment = _freestream_environment(freestream_provider, 0.0)
        rho_inf = environment["density_kg_m3"]
        pressure_inf = environment["pressure_pa"]
        velocity = np.asarray(environment["velocity_m_s"], dtype=float)
        warnings.append("Time-varying transient CFD is one-way prescribed boundary forcing of fixed geometry. A launch profile supplies body-equivalent air-relative flow, not a solved moving/rotating vehicle. Translation-only frame acceleration is included only when explicitly supplied; rotating-frame forces, changing attitude, moving boundaries and CFD feedback into the flight are not modeled.")
        warnings.append("A time-varying profile may pass through low Mach below 0.3. This Euler scheme has no all-speed preconditioning: acoustic numerical dissipation can dominate physical pressure differences, and low-Mach pressure drag is especially unreliable.")
    sound_inf = math.sqrt(GAMMA * pressure_inf / rho_inf)
    speed = float(np.linalg.norm(velocity))
    actual_mach = speed / sound_inf
    if actual_mach > 2.05 + 1e-12:
        raise ValueError("The actual freestream including lateral wind exceeds the supported Mach 2 range.")
    if conditions.turbulence:
        warnings.append("The turbulence input is not modeled by inviscid Euler; no turbulent or viscous fluctuations are synthesized.")
    if 0 < actual_mach < 0.3:
        warnings.append("Low-Mach flow below 0.3: this acoustic-speed Rusanov scheme has no all-speed preconditioning. Numerical dissipation can dominate the small physical pressure differences; pressure drag is especially unreliable even if the residual converges.")
    warnings.extend([
        "Experimental inviscid Euler: no skin friction, boundary layers, transition, viscous separation, heat transfer, turbulence or wall/shear stress.",
        "Unvalidated first-order stair-step grid. Supersonic shocks can be represented, but transonic/drag predictions need grid/domain convergence and comparison to trusted measurements or a validated viscous solver.",
        "Prescribed freestream on all six domain faces can reflect disturbances, especially for subsonic flow; enlarge the domain and inspect sensitivity.",
        "Surface pressure uses the exact reflected Euler slip-wall Riemann momentum flux; absolute pressure and gauge pressure forces are available, but these are not structural stress results.",
    ])
    farfield_cpu = conserved(rho_inf, velocity, pressure_inf)
    farfield = xp.asarray(farfield_cpu)
    solid = xp.asarray(solid_cpu)
    state = xp.broadcast_to(farfield, solid_cpu.shape + (5,)).copy()
    fluid_count = int(np.sum(~solid_cpu))
    wall_cpu = _wall_geometry(solid_cpu, spacing, origin)
    wall = {key: xp.asarray(value) for key, value in wall_cpu.items()}
    previous_wall_pressure = _wall_pressure(state, wall, xp)
    # A whole-domain RMS can be diluted by many nearly undisturbed farfield
    # cells. Independently require surface pressure, force and moment rates to
    # settle on dynamic-pressure scales before accepting pressure-transfer FEA.
    dynamic_pressure = 0.5 * rho_inf * speed**2
    if dynamic_pressure <= pressure_inf * np.finfo(float).eps * 64:
        warnings.append("Pressure coefficient is undefined: incoming dynamic pressure is zero or too small relative to atmospheric-pressure floating-point precision. Absolute solved pressure is retained.")
    pressure_scale = max(dynamic_pressure, pressure_inf * 1e-6)
    projected_area = float(np.sum(wall_cpu["areas"] * np.abs(wall_cpu["normals"] @ (velocity / speed)))) / 2 if speed else float(np.sum(wall_cpu["areas"])) / 2
    force_scale = max(pressure_scale * projected_area, 1e-18)
    geometry_extent = np.ptp(np.asarray(mesh.vertices), axis=0)
    moment_scale = force_scale * float(np.max(geometry_extent))
    relative_wall_positions = wall["positions"] - xp.asarray(np.mean(mesh.bounds, axis=0))
    # Reference scales normalize change in each conserved quantity separately.
    momentum_scale = rho_inf * max(speed, sound_inf)
    scales = xp.asarray([rho_inf, momentum_scale, momentum_scale, momentum_scale, float(farfield_cpu[4])])
    crossing_speed = max(speed, sound_inf * 0.1)
    flow_time = float(solid_cpu.shape[0] * spacing[0] / crossing_speed)
    minimum_convergence_time = 0.5 * flow_time
    target_time = duration
    physical_time = 0.0
    history = []
    status = "running"
    steps = 0
    stable_streak = 0
    rejected_steps = 0
    residual = wall_pressure_residual = force_residual = moment_residual = None
    recorder = None
    if mode == "transient":
        initial_state = xp.asnumpy(state) if backend == "cupy-cuda" else np.asarray(state)
        recorder = _TransientRecorder(initial_state, solid_cpu, spacing, origin, wall_cpu,
                                      pressure_inf, rho_inf, velocity, duration,
                                      frame_limit, sample_limit, surface_limit)
        recorder.capture(initial_state, 0.0, 0, environment)
    integration_start = time.perf_counter()

    def emit_telemetry(phase="integration", done=False):
        if telemetry:
            telemetry(dict(
                mode=mode, phase=phase, integration_steps=steps,
                physical_time_s=physical_time, target_physical_time_s=target_time,
                domain_crossings_completed=physical_time / flow_time,
                minimum_convergence_time_s=minimum_convergence_time,
                residual=residual, wall_pressure_residual=wall_pressure_residual,
                force_residual=force_residual, moment_residual=moment_residual,
                convergence_tolerance=tolerance, stable_streak=stable_streak,
                required_stable_steps=20, rejected_steps=rejected_steps,
                elapsed_seconds=max(0.0, time.perf_counter() - start),
                integration_elapsed_seconds=max(0.0, time.perf_counter() - integration_start),
                flight_time_s=environment.get("flight_time_s"),
                freestream_mach=environment.get("freestream_mach", actual_mach),
                altitude_msl_m=environment.get("altitude_msl_m"),
                done=done, status=status,
            ))

    emit_telemetry()
    while True:
        if cancelled and cancelled():
            status = "cancelled"
            break
        if mode == "transient" and physical_time >= target_time:
            status = "transient_complete"
            break
        if freestream_provider is not None:
            environment = _freestream_environment(freestream_provider, physical_time)
            rho_inf, pressure_inf = environment["density_kg_m3"], environment["pressure_pa"]
            velocity = np.asarray(environment["velocity_m_s"], dtype=float)
            sound_inf = math.sqrt(GAMMA * pressure_inf / rho_inf)
            speed = float(np.linalg.norm(velocity))
            actual_mach = speed / sound_inf
            farfield_cpu = conserved(rho_inf, velocity, pressure_inf)
            farfield = xp.asarray(farfield_cpu)
        step = steps + 1
        dt = stable_timestep(state, solid, spacing, cfl, xp=xp)
        # A changing prescribed boundary may be faster than the current domain.
        # Include its characteristic speeds in the same multidimensional CFL.
        incoming_dt = cfl / float(np.sum((np.abs(velocity) + sound_inf) / spacing))
        dt = min(dt, incoming_dt)
        if mode == "transient":
            dt = min(dt, target_time - physical_time)
        if not math.isfinite(dt) or dt <= 0 or physical_time + dt <= physical_time:
            raise RuntimeError("The CFD physical timestep cannot advance finite time. No duplicate-time or nonphysical state was accepted.")
        accepted = False
        for _ in range(9):
            candidate = finite_volume_step(state, solid, spacing, dt, farfield, xp=xp)
            acceleration = environment.get("frame_acceleration_m_s2", [0, 0, 0])
            if any(acceleration):
                candidate = _accelerating_frame_update(candidate, solid, acceleration, dt, xp)
            if _physical(candidate, solid, xp):
                accepted = True
                break
            rejected_steps += 1
            dt *= 0.5
        if not accepted:
            raise RuntimeError("Euler update lost positive density/pressure even after CFL reduction. No nonphysical pressure field was accepted; refine the geometry or lower CFL.")
        relative_delta = (candidate - state) / scales
        state_change = float(xp.sqrt(xp.sum(xp.where(solid[..., None], 0.0, relative_delta**2)) / (fluid_count * 5)))
        # Normalize by dt in crossing-time units. A smaller time step must not
        # make an equally unsteady state appear better converged.
        residual = state_change * flow_time / dt
        wall_pressure = _wall_pressure(candidate, wall, xp)
        pressure_change = wall_pressure - previous_wall_pressure
        wall_pressure_residual = float(xp.sqrt(xp.sum(wall["areas"] * (pressure_change / pressure_scale)**2) / xp.sum(wall["areas"]))) * flow_time / dt
        force_change = -pressure_change[..., None] * wall["normals"] * wall["areas"][..., None]
        force_residual = float(xp.linalg.norm(xp.sum(force_change, axis=0))) / force_scale * flow_time / dt
        moment_residual = float(xp.linalg.norm(xp.sum(xp.cross(relative_wall_positions, force_change), axis=0))) / moment_scale * flow_time / dt
        previous_wall_pressure = wall_pressure
        state = candidate
        # Pin the terminal timestamp to the user's actual physical duration;
        # the accepted terminal Euler step uses precisely this remainder.
        physical_time = target_time if mode == "transient" and dt == target_time - physical_time else physical_time + dt
        steps = step
        _, vel, pressure, sound = primitives(state, xp=xp)
        min_pressure = float(xp.min(xp.where(solid, xp.inf, pressure)))
        max_mach = float(xp.max(xp.where(solid, 0, xp.linalg.norm(vel, axis=-1) / sound)))
        if step == 1 or step % 5 == 0 or (mode == "transient" and physical_time >= target_time):
            _record_history(history, dict(step=step, time_s=physical_time, dt_s=dt, residual=residual,
                                wall_pressure_residual=wall_pressure_residual,
                                force_residual=force_residual, moment_residual=moment_residual,
                                normalized_state_change=state_change,
                                min_pressure_pa=min_pressure, max_mach=max_mach))
        # Avoid labeling the initially undisturbed far field converged before a
        # disturbance has had time to traverse the body/domain.
        rates = (residual, wall_pressure_residual, force_residual, moment_residual)
        stable_streak = stable_streak + 1 if max(rates) < tolerance and physical_time >= minimum_convergence_time else 0
        integration_elapsed = max(time.perf_counter() - integration_start, 1e-12)
        physical_rate = physical_time / integration_elapsed
        time_to_minimum = max(0.0, minimum_convergence_time - physical_time) / physical_rate
        if freestream_provider is not None:
            environment = _freestream_environment(freestream_provider, physical_time)
        if recorder and recorder.due(physical_time):
            snapshot_state = xp.asnumpy(state) if backend == "cupy-cuda" else np.asarray(state)
            recorder.capture(snapshot_state, physical_time, steps, environment)
        if progress and (step == 1 or step % 5 == 0):
            timing = f"about {time_to_minimum:.0f} s to minimum flow time" if time_to_minimum > 0 else "minimum flow time reached"
            deadline = ("Completion time unknown; waiting for numerical convergence" if mode == "steady" else
                        f"{physical_time:.6g}/{target_time:.6g} s physical flow time; completion follows the requested duration")
            completion = 0.0 if mode == "steady" else min(0.95, physical_time / target_time * 0.95)
            progress(completion, f"Euler step {step}; {physical_time / flow_time:.3f} domain crossings; fluid residual {residual:.3g}, wall residual {max(rates[1:]):.3g}; {timing}. {deadline}.")
        if step == 1 or step % 5 == 0:
            emit_telemetry()
        if mode == "steady" and stable_streak >= 20:
            status = "converged"
            break
        if mode == "transient" and physical_time >= target_time:
            status = "transient_complete"
            break
    integration_elapsed = max(0.0, time.perf_counter() - integration_start)
    if steps and history[-1]["step"] != steps:
        _record_history(history, dict(step=steps, time_s=physical_time, dt_s=dt, residual=residual,
                            wall_pressure_residual=wall_pressure_residual,
                            force_residual=force_residual, moment_residual=moment_residual,
                            normalized_state_change=state_change,
                            min_pressure_pa=min_pressure, max_mach=max_mach))
    if backend == "cupy-cuda":
        xp.cuda.Stream.null.synchronize()
        state_cpu = xp.asnumpy(state)
    else:
        state_cpu = np.asarray(state)
    if freestream_provider is not None:
        environment = _freestream_environment(freestream_provider, physical_time)
        rho_inf, pressure_inf = environment["density_kg_m3"], environment["pressure_pa"]
        velocity = np.asarray(environment["velocity_m_s"], dtype=float)
        speed = float(np.linalg.norm(velocity))
        actual_mach = speed / math.sqrt(GAMMA * pressure_inf / rho_inf)
    if recorder:
        recorder.capture(state_cpu, physical_time, steps, environment)
    emit_telemetry("extraction")
    if progress:
        progress(0.96, "Extracting solved fluid samples and integrating wall pressure loads")
    rho, vel, pressure, sound = primitives(state_cpu)
    fluid_indices = np.argwhere(~solid_cpu)
    take = np.linspace(0, len(fluid_indices) - 1, min(sample_limit, len(fluid_indices)), dtype=int)
    samples = []
    for i in take:
        index = tuple(fluid_indices[i])
        position = origin + fluid_indices[i] * spacing
        samples.append(dict(position=position.tolist(), pressure_pa=float(pressure[index]),
                            velocity=vel[index].tolist(), density_kg_m3=float(rho[index]),
                            mach=float(np.linalg.norm(vel[index]) / sound[index])))
    flow_grid = _flow_grid(vel, solid_cpu, spacing, origin)
    if flow_grid["stride"] > 1:
        warnings.append(f"Streamline visualization samples the solved velocity at stride {flow_grid['stride']}, capped at 100,000 display nodes. A conservative display mask stops lines near unresolved thin walls; it changes neither the solved field nor integrated pressure loads. Inspect solver-grid refinement separately.")
    surface, force, moment, face_count, negative_wall_faces = _surface(
        state_cpu, solid_cpu, spacing, origin, farfield_cpu, pressure_inf,
        speed, rho_inf, surface_limit)
    if negative_wall_faces:
        warnings.append(f"{negative_wall_faces} wall Riemann expansions reach vacuum (zero pressure). These loads cannot be transferred to FEA; inspect the flow and refine before interpreting them.")
    if status == "transient_complete":
        warnings.append("Completed the requested transient physical duration. Stored fields are instantaneous numerical states, not a converged steady-flow prediction or time-averaged loads.")
    elif status != "converged":
        warnings.append(f"Stopping reason: {status}. The returned fields are the actual partial solution, not a converged steady-flow prediction.")
    lateral_force_squared = float(force[1] ** 2 + force[2] ** 2)
    cp_m = None
    cp_fit_residual = None
    if status == "converged" and lateral_force_squared > max(1e-12, float(np.dot(force, force)) * 1e-10):
        # Best-fitting pressure-resultant application point on the rocket X axis.
        # It is specific to this flow condition, not dCm/dCn (Barrowman CP).
        cp_m = float((force[1] * moment[2] - force[2] * moment[1]) / lateral_force_squared)
        cp_fit_residual = float(np.linalg.norm(moment - np.cross([cp_m, 0, 0], force)))
    elif status == "converged":
        warnings.append("Pressure-resultant CP is undefined at negligible lateral force; no CP is inferred from axial drag.")
    summary = dict(status=status, mode=mode, completed=status in {"converged", "transient_complete"},
                   converged=status == "converged", steps=steps,
                   physical_time_s=physical_time, target_physical_time_s=target_time,
                   elapsed_seconds=time.perf_counter() - start, flow_through_time_s=flow_time,
                   force_n=force.tolist(), moment_about_origin_nm=moment.tolist(),
                   pressure_drag_n=float(np.dot(force, velocity / speed)) if speed else 0.0,
                   pressure_force_steady=status == "converged", pressure_force_validated=False,
                   pressure_output_kind=("Converged numerical pressure resultant; unvalidated" if status == "converged" else
                                         "Completed transient instantaneous pressure resultant; not a steady drag prediction" if status == "transient_complete" else
                                         "Partial transient numerical pressure resultant; not a steady drag prediction"),
                   run_until_converged=mode == "steady",
                   stop_policy="Numerical convergence or cancellation; no wall-clock, step or physical-time timeout" if mode == "steady" else "Requested physical duration or cancellation; no wall-clock or step timeout",
                   progress_basis="convergence_unknown" if mode == "steady" else "physical_time",
                   legacy_stop_options_ignored=legacy_stop_options,
                   domain_crossings_completed=physical_time / flow_time,
                   minimum_convergence_time_s=minimum_convergence_time,
                   minimum_convergence_time_reached=physical_time >= minimum_convergence_time,
                   crossing_reference_speed_m_s=crossing_speed,
                   flow_through_time_basis="Axial domain length / max(resultant freestream speed, 0.1 sound speed)",
                   integration_elapsed_seconds=integration_elapsed,
                   measured_steps_per_second=steps / integration_elapsed if steps and integration_elapsed > 0 else None,
                   simulated_seconds_per_wall_second=physical_time / integration_elapsed if steps and integration_elapsed > 0 else None,
                   estimated_seconds_to_minimum_flow_time=max(0.0, minimum_convergence_time - physical_time) * integration_elapsed / physical_time if physical_time > 0 else None,
                   estimated_seconds_to_target_flow_time=max(0.0, target_time - physical_time) * integration_elapsed / physical_time if target_time is not None and physical_time > 0 else None,
                   timing_estimate_basis="Measured integration throughput; startup/voxelization and extraction excluded. Not an estimate of convergence time.",
                   wall_pressure_residual=wall_pressure_residual,
                   force_residual=force_residual, moment_residual=moment_residual,
                   convergence_tolerance=tolerance,
                   pressure_convergence_scale_pa=pressure_scale,
                   force_convergence_scale_n=force_scale,
                   moment_convergence_scale_nm=moment_scale,
                   wall_flux="Exact symmetric reflected Euler Riemann solution",
                   low_mach_preconditioned=False,
                   convergence_requires="Global conserved-state, wall-pressure, resultant-force and centered-moment rates all below tolerance for 20 steps after half a crossing time",
                   cp_m=cp_m, cp_kind="Condition-specific pressure-resultant centerline fit; not Barrowman derivative CP",
                   cp_fit_moment_residual_nm=cp_fit_residual,
                   cell_count=int(solid_cpu.size), solid_cells=int(solid_cpu.sum()),
                   fluid_cells=fluid_count, grid_shape=list(solid_cpu.shape), spacing_m=float(spacing[0]),
                   flow_visualization_nodes=flow_grid["node_count"],
                   flow_visualization_stride=flow_grid["stride"],
                   cell_spacing_m=spacing.tolist(),
                   grid_origin_m=origin.tolist(), freestream_velocity_m_s=velocity.tolist(),
                   freestream_mach=actual_mach, freestream_pressure_pa=pressure_inf,
                   dynamic_pressure_pa=0.5 * rho_inf * speed**2,
                   freestream_kind="time_varying_prescribed" if freestream_provider is not None else "constant",
                   altitude_msl_m=environment.get("altitude_msl_m"), flight_time_s=environment.get("flight_time_s"),
                   min_pressure_pa=float(np.min(pressure[~solid_cpu])),
                   max_mach=float(np.max(np.linalg.norm(vel[~solid_cpu], axis=-1) / sound[~solid_cpu])),
                   residual=history[-1]["residual"] if history else None,
                   surface_face_count=face_count, positivity_retries=rejected_steps,
                   nonpositive_wall_faces=negative_wall_faces,
                   project_id=project.id,
                   configuration_id=configuration_id or project.active_configuration_id,
                   original_geometry=original, mesh_sha256=mesh_digest.hexdigest(),
                   max_steps=None, max_wall_seconds=0, cfl=cfl)
    if options.get("backend", "auto") != "cpu":
        from ..backenddiagnostics import cuda_diagnostics
        summary["cuda_diagnostics"] = cuda_diagnostics()
    summary.update(geometry_diagnostics)
    if recorder:
        summary["transient_frame_count"] = len(recorder.frames)
        summary["transient_frame_limit"] = frame_limit
    emit_telemetry("complete", done=True)
    if progress:
        progress(1.0, f"Euler solve finished: {status}; {steps} conservative steps")
    result = dict(samples=samples, flow_grid=flow_grid, surface=surface, history=history, summary=summary,
                  fidelity=FIDELITY, warnings=warnings, backend=backend)
    if recorder:
        result["transient"] = recorder.result(status == "transient_complete")
        if freestream_provider is not None:
            result["transient"]["scope"] = "Fixed rocket geometry with an actual-time prescribed freestream profile. Launch data supply body-equivalent air-relative boundary conditions; moving/rotating geometry, solved attitude, recovery geometry and CFD feedback into flight are not modeled. No physical-time compression."
    return result
