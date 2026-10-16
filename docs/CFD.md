# Experimental compressible CFD

Rocket Workbench includes a real numerical solver for three-dimensional,
compressible flow. **Euler** is the default inviscid model; optional
**Laminar Navier–Stokes** adds molecular viscosity and heat conduction. Both
advance density, three components of momentum,
and total energy. Pressure and velocity visualization come from this solved
state; pressure colors are not synthetic gradients. The solver is experimental
and is not a validated production CFD package.

This capability supports studying how a detailed CAD replacement changes the
discretized external flow, including pressure waves and shock formation up to an
actual incoming Mach number of 2. Euler does **not** predict viscous drag, boundary
layers, transition, turbulent fluctuations, viscous separation, heating, or
wall shear. Laminar returns resolved numerical wall traction, but has no
turbulence, transition or wall-function model. On practical high-power rocket
grids, first-order numerical diffusion can overwhelm molecular viscosity and
the physical boundary layer can be much thinner than one cell. Selecting
Laminar does not establish accurate skin friction or high-Reynolds-number drag.
Airflow arrows and continuous streamlines use the local solved
velocity. Streamlines trace the stored instantaneous numerical field; they are
not particle trajectories or a turbulence model. Fluid pressure and fluid-wall
traction are distinct from material/structural stress.

## Equations and discretization

The calorically perfect ideal-air equations use a fixed specific-heat ratio
`gamma = 1.4` and conservative state

```text
U = [rho, rho*u, rho*v, rho*w, E]
p = (gamma - 1) * (E - rho*(u² + v² + w²)/2)
dU/dt + dFx/dx + dFy/dy + dFz/dz = 0
```

The flux in direction `i` is `U*velocity_i`, with `p` added to normal momentum
flux and energy flux replaced by `(E+p)*velocity_i`. At each shared fluid/fluid face, the
baseline first-order Rusanov (local Lax-Friedrichs) numerical flux is

```text
Fface = (Fleft + Fright)/2 - amax*(Uright-Uleft)/2
amax = max(abs(normal velocity) + sound speed) on the two sides
```

Forward Euler advances the unsplit sum of the three flux divergences. The
time step uses the full multidimensional bound
`dt = CFL / max(sum_i((abs(velocity_i)+sound speed)/spacing_i))`.
Nonpositive density/pressure states are rejected and the step is retried with
half the time step. The solver raises an error after repeated failures rather
than accepting, clipping or displaying a nonphysical fluid state.

Laminar uses the same conservative convective flux and adds the divergence of
the Newtonian viscous/thermal flux:

```text
dU/dt + div(F_Euler) = div(F_viscous)
tau = mu * (grad(u) + transpose(grad(u)) - (2/3)*div(u)*I)
F_viscous_i = [0, tau[:,i], dot(u,tau[:,i]) + k*dT/dx_i]
T = p/(rho*R_air), R_air = 287.05287 J/(kg K)
mu(T) = 1.716e-5 * (T/273.15)^1.5 * (273.15+110.4)/(T+110.4) Pa s
k(T) = mu(T)*cp/Pr, cp = gamma*R_air/(gamma-1), Pr = 0.72
```

Interior normal gradients use the two adjacent cell values; transverse velocity
gradients average their centered cell gradients. The same face flux is shared
by both cells, conserving mass, momentum and total energy. The explicit laminar
time step divides CFL by the **sum** of acoustic and viscous/thermal rates,
rather than taking separately stable time steps. The diffusion rate uses
`4*max((4/3)*mu_max/rho_min, gamma*mu_max/(Pr*rho_min))*sum_i(1/h_i²)`.
Global transport/density extrema also include the prescribed farfield;
this bounds shared-face coefficients even across changing density or temperature.
The factor four covers the half-cell wall distance and tensor diffusion stencil.
Strong temperature/density gradients or fine cells can require much smaller
steps than Euler. Density and pressure positivity checks still apply.

First-order dissipation smears contacts and shocks. It also makes force values
grid-dependent. Adaptive refinement is not implemented. An explicit experimental
higher-order interior option is described below. The solver advances a transient initial-value problem initialized with a
uniform free stream, so the early steps show genuine numerical startup effects.

## Experimental MUSCL–MC reconstruction

**Numerical reconstruction** selects `spatial_scheme:first_order` (the default,
including older projects) or `muscl_mc`. This is separate from Euler versus
Laminar physics and steady versus transient stopping policy.

MUSCL reconstructs primitive `[rho,u,v,w,p]` face states with monotonized-central
slopes: minmod of twice each one-sided difference and the centered difference.
Both adjacent cells share one Rusanov flux. Slopes are zero in a solid and in
cells touching a solid in any face direction. At each prescribed/extrapolated
exterior, the first/last cell has zero slope in that direction. Periodic faces
share the same reconstructed pair on both ends. Directional exterior treatment
retains genuine one-dimensional reconstruction on a singleton transverse grid.
Positive face density/pressure are protected by common slope rescaling relative
to the positive cell value; evolved states are never clipped.

Two-stage SSPRK2 applies `U1=U+dt L(U)` and
`Unew=(U+U1+dt L(U1))/2`. Each stage includes the selected conservative Euler and
optional molecular viscous/thermal fluxes. Solid-cell state remains unchanged.
A nonphysical intermediate stage rejects the entire attempt before further
primitive recovery; the production driver retries from the original state with
half `dt`, retaining its finite retry guard and actual rejection count.

Smooth-interior convergence is second order in the tested periodic entropy-wave
case. The limiter reduces order at extrema/discontinuities; walls and farfield
reconstruction remain first order. Stair-step geometry, low-Mach acoustic
dissipation, unresolved boundary layers and lack of turbulence closure remain.
The method takes two flux evaluations per step and additional stage/face memory.
This is not a guarantee of more accurate rocket drag or pressure on a given grid.

For fixed boundary data the semi-discrete SSPRK2 update is second order in time.
**Launch/time-varying profiles remain start-of-step boundary sampling with a
separately split translational frame source. Their overall temporal order remains
first order.** Output retains `spatial_scheme`, `time_integrator`, reconstruction
and temporal scope, immutable input options and method-specific fidelity text.
Flow display quality is independent of numerical reconstruction.

References: van Leer, *Towards the ultimate conservative difference scheme. II.
Monotonicity and conservation combined in a second-order scheme*, Journal of
Computational Physics 14 (1974), 361–370; Gottlieb, Shu and Tadmor, *Strong
Stability-Preserving High-Order Time Discretization Methods*, SIAM Review 43
(2001), 89–112. These identify underlying methods, not rocket-flow validation.

## Geometry and boundary conditions

The selected OpenRocket configuration is assembled by `geometry.project_mesh`.
CAD replacements use the same transformed geometry as the 3D viewer. The
optional `original` flag instead solves the unreplaced OpenRocket geometry.

The mesh is copied, scaled into anisotropic Cartesian cell coordinates, and
subdivided into surface voxels using trimesh. A six-neighbor flood fill from all
six farfield faces identifies air connected to the outside; all remaining space
is nonflow. This uses the same face connectivity as the finite-volume fluxes.
Separate
axial and transverse spacings preserve resolution of slender rockets. The
surface is consequently a **staircase** of whole solid cells: there are no
body-fitted cells or subcell intersection fractions.

Only exterior-connected air generates a pressure boundary. A sealed hollow CAD
part therefore has the same flow mask, pressure surfaces and solved loads as a
solid part with the identical outside shape. Its hidden cavity or internal
electronics cannot add pressure faces or alter the external flow. This is a
separate aerodynamic grid: **the original CAD triangles, material/void volume,
mass/CG, alignment, viewer geometry and FEA geometry are preserved**. There is no
convex-hull operation or edit to the saved asset.

Open bores and leaks remain exterior-connected flow passages, including their
physically exposed inner walls. Cap an opening in the source CAD only when the
real vehicle is sealed. Overlapping separate components are combined by their
occupied voxels; they are not first Boolean-unioned as CAD solids. Watertightness, narrow
gaps, thin fins, and assembly sealing need inspection. Refining the grid can
materially change whether a small feature is resolved. The result reports its
grid dimensions, three spacings, solid-cell count and warnings. Its
`aerodynamic_voxel_sha256` identifies the flow mask including origin and spacing;
`mesh_sha256` separately identifies the unchanged source triangles for CFD-to-FEA
binding. `surface_voxel_cells`, `enclosed_nonflow_cells` and
`exterior_fluid_cells` describe grid occupancy, **not material mass or physical
cavity volume**. `aerodynamic_geometry_policy` records this policy and
`source_material_mesh_modified` is false.

For Euler at a fluid/solid face, the ghost state mirrors normal momentum while preserving
density, energy and tangential momentum. The symmetric reflected Euler Riemann
problem is solved analytically at the wall: compression uses the normal-shock
Rankine–Hugoniot curve, and expansion uses the isentropic rarefaction curve.
The exact slip-wall flux has zero mass, tangential momentum, and energy transport
across the stationary wall; its pressure is the normal momentum flux. Fluid/fluid
faces retain first-order Rusanov flux. This avoids the negative wall pressures
that a dissipative Rusanov reflection can produce during strong expansions.
Pressure resultant and
moment are integrated over **all** exposed solid faces using gauge pressure
relative to the incoming atmospheric pressure and the correct face area for
each grid direction. Returned surface samples are a subset; force integration
does not subsample the faces. A receding wall-normal flow faster than
`2*c/(gamma-1)` yields genuine vacuum in the reflected Riemann solution. Such
zero-pressure faces are counted, warned about, and blocked from FEA transfer.

Laminar preserves that impermeable convective pressure flux and adds a
**stationary no-slip, adiabatic** viscous wall condition. The wall is half a
cell from the adjacent fluid center. Its velocity gradient is the reflected
velocity stencil, with all three wall velocity components zero; tangential
derivatives of the stationary wall velocity are zero. Normal temperature
gradient is zero. Wall mechanical work and heat flux are therefore exactly
zero: kinetic dissipation becomes internal energy without adding or removing
total energy at the stationary wall. This is not an imposed-temperature wall,
conjugate heat-transfer solver or rocket-material heating calculation.

The normal points from solid to fluid. Viscous traction on the solid is `tau*n`,
tangential wall shear removes its normal projection, and full total traction is
`-(p-p_inf)*n + tau*n`. Normal viscous stress is retained in full viscous traction,
not silently counted as tangential shear. Pressure and viscous force/moment
integrals both use every exterior-connected face and its actual area.
Sealed interiors remain blocked in the separate flow mask in either model;
adding laminar transport changes no CAD asset, mass or FEA geometry.

The acoustic-speed Rusanov dissipation is not corrected for the incompressible
limit. At low Mach it can overwhelm the physical pressure differences and cause
large artificial pressure drag on coarse meshes. Runs below Mach 0.3 receive an
explicit warning. There is no all-speed preconditioning, and a converged residual
does not make those loads accurate. The same grid study requirement applies
above that warning threshold.

All six external faces prescribe undisturbed free stream. This simple farfield
condition can reflect outgoing disturbances, particularly for subsonic flow.
The grid must be enlarged and checked for domain-size sensitivity. It is a
known limitation, not a nonreflecting characteristic boundary condition.

Rocket coordinates run from nose to tail in positive X. Angle of attack lies
in XY and sideslip in XZ. Body-frame lateral wind direction is the direction
**toward** which air moves: 0 degrees is +Y and 90 degrees is +Z. An explicit
Mach value first sets incoming axial airspeed from the atmospheric sound speed;
lateral wind is then added. The resulting total incoming Mach must be at most
2.05, allowing small rounding around the nominal Mach 2 design limit. Nonzero
turbulence input receives an explicit unsupported-input warning.

## Controls, progress and results

Options passed to `cfd.solve`:

| Option | Default | Meaning |
| --- | ---: | --- |
| `physics_model` | `euler` | `euler` inviscid pressure flow or experimental `laminar` molecular-viscosity Navier–Stokes; neither models turbulence |
| `grid_resolution` | 32 | Cells across geometry's axial extent, 12–256 |
| `transverse_resolution` | min(24, axial resolution) | Cells across each transverse geometry extent, 12–128 |
| `domain_padding` | 0.5 | Padding in multiples of corresponding geometry extent; downstream padding is at least 0.65 |
| `max_cells` | 300,000 | Explicit allocation budget, maximum 2,000,000; excess grids are rejected |
| `mode` | `steady` | `steady` attempts numerical convergence; `transient` integrates a defined physical interval |
| `duration_s` | required for transient | Actual physical flow duration in seconds; this is not a computer runtime limit |
| `snapshot_count` | 24 | Maximum saved instantaneous display frames, 2–32 |
| `cfl` | 0.35 | CFL multiplier, 0.01–0.8 |
| `convergence_tolerance` | 0.00001 | Tolerance for conserved-state, wall-pressure, force and moment rate changes per crossing time; Laminar additionally requires wall-viscous-traction steadiness |
| `sample_limit` | 4,000 | Maximum fluid field samples returned to the viewer |
| `surface_limit` | 5,000 | Maximum exposed-wall samples; Laminar additionally returns actual viscous/shear/total traction |
| `backend` | `auto` | `auto`, `cpu`, or `gpu` |
| `original` | false | Use original OpenRocket geometry instead of attached replacements |

The default grid is a coarse experimental starting point, especially for thin
fins; it is not sufficient merely because the solver finishes. Compare progressively
refined grids and enlarged domains. Memory and runtime grow rapidly with
resolution. Cell budgets always limit grid allocations. There is no wall-clock,
step-count or domain-crossing timeout in either mode. Old project options
`max_steps`, `max_wall_seconds`, `flow_through_times`, `max_physical_time` and
`run_until_converged` no longer impose stopping limits; direct solver calls retain
an explicit migration warning when those keys are supplied.

In the CFD page, choose **CFD physics model** before starting a run. Euler is
appropriate for experiments that intentionally omit molecular transport.
Laminar exposes pressure, viscous and total numerical loads separately. Inspect
its Reynolds number and numerical-to-molecular diffusivity diagnostic before
interpreting those loads; adding a solver term does not resolve a missing
boundary layer. Saved project options retain the chosen model.

Choose **Steady-state** to run until the numerical convergence test succeeds or
you cancel. A flow that does not settle can run indefinitely. Choose **Transient**
to resolve the requested physical duration, even if the state becomes steady
earlier. **Cancel** stops between accepted steps and preserves actual partial
fields. Diagnostic history is thinned to at most 4,000 samples,
retaining the first and latest sample, so long runs do not accumulate unlimited
history memory. This temporal sampling does not alter the numerical state.

The history reports accepted step, physical time, actual step size, normalized
RMS conserved-state rate of change, raw normalized step change, minimum fluid
pressure and maximum local Mach. Independently, `wall_pressure_residual` measures
area-weighted RMS wall-pressure change, `force_residual` measures resultant
change, and `moment_residual` measures moment change about the geometry bounding
box center. Pressure rates use the initial incoming dynamic pressure (with a
small static pressure floor at zero speed); force uses dynamic pressure times projected voxel
area, and moment additionally uses maximum geometry extent. All four changes
are divided by `dt` and multiplied by domain-crossing time: reducing the time
step alone cannot improve them. These reference scales remain fixed during a
changing transient profile; those diagnostic rates do not turn the experiment
into a steady result. Whole-domain RMS alone could hide changing loads
among many undisturbed farfield cells. Steady convergence therefore requires
**all four** rates below tolerance for 20 successive steps after at least half
a domain crossing time. For Laminar, a fifth `wall_viscous_residual` measures
area-weighted RMS full viscous-traction change. Its independent reference scale
is `max(2*mu_inf*speed_inf/minimum_spacing, p_inf*epsilon*64)`, using the initial
freestream. It is reported as `viscous_convergence_scale_pa`; dynamic pressure
would hide a changing viscous load much smaller than pressure loads. Laminar
force/moment residuals include **both** pressure and full viscous traction.
All five rates must meet the same tolerance/streak/minimum-time criterion.
This criterion does not establish grid convergence or
physical validation. Steady-state has no meaningful completion percentage.
Its progress text reports accepted steps, physical
domain crossings, all residuals, and whether the half-crossing minimum time has
been reached. `progress_basis = convergence_unknown` distinguishes that mode.
The job layer may show a tentative convergence ETA range only when measured
residuals consistently decline; insufficient data, stalls or oscillations leave
the ETA unknown. All active residuals participate, including viscous traction
for Laminar; a stalled or unavailable viscous rate prevents a convergence ETA.
This prediction is not a convergence guarantee. Transient
percentage is integrated physical time divided by the requested duration; its
ETA uses recent measured physical-time throughput. Initialization and extraction
are separate phases, and changing CFL steps or hardware load change the estimate.

The summary reports `domain_crossings_completed`,
`minimum_convergence_time_s`, `minimum_convergence_time_reached`, measured
integration steps per wall second, and simulated seconds per wall second.
`estimated_seconds_to_minimum_flow_time` and
`estimated_seconds_to_target_flow_time` extrapolate **current measured integration
throughput**, excluding voxelization and extraction. These are estimates of time
to a given physical flow time, never convergence estimates; changing waves,
retries and GPU/CPU load can change them. A domain crossing is axial domain
length divided by the initial resultant freestream speed, with a 0.1-sound-speed
floor at near-zero inflow. Reaching the minimum only permits the convergence test; all
active residuals must still stay below tolerance for 20 successive steps.

The `summary.status` value distinguishes `converged`, `transient_complete` and
`cancelled`. A completed transient experiment is not a converged steady result.
A cancelled run retains its actual partial fields and loads with an explicit
warning. Cancellation is cooperative between steps.

### Flight-driven transient experiments

Transient CFD can use the current launch simulation, or a geometry-matched saved
flight job. Select the whole flight or a shorter interval around rail exit,
burnout or max Q. The boundary history uses calculated **air-relative** velocity,
wind and local atmosphere, rather than ground speed or one fixed entered Mach.
The CFD clock advances with its real acoustic CFL time step; a longer launch
interval is not accelerated by skipping fluid integration. A whole flight can
require millions of steps and substantial runtime. Begin with a short interval.

Every selected interval initializes the fluid to uniform freestream at its
first launch timestamp. It does not resume the CFD state from an earlier part
of the launch or a previous run. Start sufficiently before the event you want
to inspect, then compare earlier start times to assess numerical startup
effects. Selecting a tight window around max Q does not supply the flow history
that developed before that window.

This is one-way prescribed airflow around fixed rigid geometry. The CFD solver
does not integrate vehicle attitude, rotating-frame flow, a moving mesh, canopy
deployment geometry or feedback of CFD loads into the trajectory. The saved
profile records its frame assumption and interpolation policy. The source
flight model's declared attitude and aerodynamic-coefficient limitations remain
applicable. For rigid-body flight rows with a saved unit quaternion, the profile
SLERPs the calculated attitude/roll and rotates air-relative velocity into the
original CAD frame. `resolved_attitude` records that choice. Older point-mass
rows retain their declared rail/gravity-turn axis assumption with a warning.
Using resolved flight attitude to prescribe the boundary does not add moving
walls, surface rotational velocity, Coriolis/centrifugal terms or a rotating
CFD mesh. Actual
transient fields are available at bounded saved timestamps, with frame-specific
freestream pressure, dynamic pressure, Mach, altitude and flight time. Playback
selects those computed states; it does not manufacture intermediate flow fields.
The snapshot timeline steps through saved accepted states. Its replay speed is
visual: the default full pass takes about eight seconds regardless of physical
duration. This timing changes neither the solver clock nor the saved fields.
Only completed, converged **steady** results qualify for the existing CFD-to-FEA
pressure-transfer workflow.
This remains **pressure-only**, including when the source run used Laminar.
Computed shear/full viscous traction is not mapped into the current FEA load
transfer; its saved result and transfer warning state that omission.

`samples` contain position, absolute pressure, density, solved velocity and
local Mach. `surface` contains exposed face position, numerical absolute wall
pressure, outward normal and pressure coefficient (null at zero airspeed or
when incoming dynamic pressure is smaller than 64 floating-point ulps of
atmospheric pressure). Absolute solved pressure is always retained.
`summary` includes pressure force in body axes, pressure drag projected along
the free stream, moment about project coordinate origin, resource usage and
the stopping reason. Surface force signs use pressure acting inward onto the
solid; Euler has no skin-friction force. JSON exports include fidelity and warnings.

Laminar retains `force_n`, `pressure_drag_n` and `moment_about_origin_nm` as
pressure-only compatibility fields. It adds `viscous_force_n`,
`viscous_drag_n`, `viscous_moment_about_origin_nm`, `total_force_n`,
`total_drag_n` and `total_moment_about_origin_nm`; total values add pressure and
full viscous traction. Surface samples additionally contain
`viscous_traction_pa`, tangential `shear_traction_pa`, scalar `shear_stress_pa`,
`total_traction_pa` and `wall_fluid_temperature_k`. Stored transient frames
contain the corresponding actual force/moment values and `surface_*` arrays,
aligned to their shared surface topology. Playback uses the selected frame's
loads, not the final snapshot's loads. `viscous_force_validated` is false.

`summary.transport` reports Sutherland viscosity, molecular kinematic viscosity,
thermal conductivity, Prandtl number and a Reynolds number based on maximum
rocket extent. These reference values explicitly identify **initial** freestream
time zero; a launch profile can later change the boundary conditions. Its
`estimated_numerical_to_molecular_diffusivity_ratio` uses the characteristic
first-order estimate `0.5*(sound_speed+speed)*maximum_spacing / (mu/rho)`.
Large ratios, commonly orders of magnitude above one on coarse rocket grids,
warn that numerical diffusion can swamp the added physical transport. This is
a scaling diagnostic, not a measured error bound, turbulence prediction or
proof of boundary-layer resolution. Neither numerical convergence nor a smooth
shear field makes high-Reynolds-number drag physically validated.

### Structured velocity field for visualization

`flow_grid` contains a bounded, regular sampling of the actual final numerical
velocity state, including a partial state when a run stops before convergence.
It supplements the existing scattered `samples`; it does not change force
integration or numerical discretization. Its fields are:

| Field | Meaning |
| --- | --- |
| `shape` | Exported node counts `[nx, ny, nz]` |
| `origin_m` | Physical position of the first exported **cell center**, in body axes |
| `spacing_m` | Three spacings between exported centers, in metres |
| `velocity_m_s` | Flat numeric array: node `(i*ny+j)*nz+k`, velocity component `node*3+axis` |
| `fluid_mask` | Flat C-order array with 1 for permitted flow support and 0 for blocked display support |
| `solver_shape`, `solver_origin_m`, `solver_spacing_m` | Original numerical-grid resolution and coordinates |
| `stride`, `node_count` | Integer sampling stride and actual display node count, at most 100,000 |
| `visualization_only`, `sampling_policy`, `interpolation` | Explicit display sampling and reconstruction limits |

Stride 1 preserves each solver fluid node. Larger grids use an equal integer
stride in all axes, retaining the original spacing anisotropy. Every original
nonflow cell conservatively blocks the sampled interpolation cube containing it.
This may terminate lines outside a physical wall, but cannot invent a passage
through an unsampled thin wall or sealed interior. A viewer must use trilinear
interpolation only when every nonzero-weight support node is fluid and stop at
the exported center bounds. The unsampled remainder near a farfield edge is
omitted; extrapolating through it would fabricate velocity data. Masked entries
store zero and are not physical zero-speed measurements.

Display coarsening can lose narrow resolved flow passages and near-wall detail.
It is reported separately from solver resolution, has no effect on saved CAD,
pressure loads or FEA, and is not a substitute for numerical grid refinement.

Pressure forces remain visible during completed transient or cancelled runs as
actual numerical outputs; `pressure_force_steady` explicitly distinguishes a
converged result and `pressure_force_validated` is false in this release.
`pressure_output_kind` explicitly calls an unfinished load a partial transient
numerical pressure resultant, rather than a steady drag prediction. For example,
a 100 m/s sea-level run with modest lateral wind is approximately Mach 0.294:
its pressure drag is in the scheme's low-Mach dissipation region. A large force
in an early or cancelled numerical snapshot cannot be interpreted as the rocket's
real drag.
Longer runtime alone does not remove that numerical-method limitation.
Only a converged result with appreciable lateral force receives `cp_m`, the
least-squares position on the project X axis satisfying its lateral moment:
`x_cp = (Fy*Mz - Fz*My)/(Fy²+Fz²)`. It is a **condition-specific pressure-resultant
centerline fit**, not the small-angle derivative CP used by Barrowman stability
analysis. Its moment-fit residual is reported because torsion and forces off
the centerline cannot always be represented by one point. No CP is inferred
from pure drag, unconverged startup fields, or negligible lateral force.

**Flow display** controls change visualization only. **Streamline quality**
changes display integration, not the numerical grid or solver order. **X-ray
rocket** makes the displayed rocket translucent. **Cutaway** clips the displayed
rocket and field along the chosen axis and position; **Reverse cutaway** changes
the visible side. These controls preserve saved CAD, material mass, FEA geometry,
the exterior-connected flow mask and integrated loads. Sealed interiors remain
nonflow even when the viewer exposes them.

## CPU and GPU execution

NumPy runs the actual numerical calculation on CPU. CuPy runs the same
conservative kernels on a supported NVIDIA CUDA GPU when the bundled CuPy CUDA
runtime and a compatible installed NVIDIA driver are usable. Rendering uses
the desktop GPU independently of numerical execution. Geometry voxelization
and final JSON extraction run on CPU in either case.

The application checks import, driver/runtime versions, device discovery, then
a tiny **actual float64 allocation, compiled multiplication and reduction**.
`gpu_diagnostics` in health capabilities and `cuda_diagnostics` in automatic/GPU
CFD results report the selected device, compute capability, VRAM, CuPy version,
CUDA driver/runtime versions, failed check stage and the actual exception reason.
The concise reason uses the original chained error, rather than the beginning of
CuPy's DLL inventory. `root_cause` and bounded `error_details` retain the cause
and traceback, while `bundled_runtime` records the registered library directories
and packaged DLL files. Long details retain both their beginning and final cause.
Import/runtime-library failures are distinguished from driver, device-discovery,
memory-allocation and compiled-kernel failures. `CUDA_PATH` being unset is normal
for the bundled split CUDA wheels and does not itself indicate a failure.
The check is cached until application restart to keep health polling inexpensive;
restart after changing a driver. Enumeration alone is not counted as working
numerical execution.

`auto` falls back to CPU and reports `backend = numpy-cpu` plus the specific
failed CUDA check and reason in its warning.
An explicit `gpu` selection raises an error if CUDA is unavailable; it never
pretends CPU work ran on a GPU. AMD/Intel rendering support does not imply CUDA
solver support. The CUDA runtime can be bundled, but a hardware-specific GPU
driver remains a prerequisite installed on the Windows computer.

Frozen Windows startup loads the bundled, version-matched
`nvrtc-builtins64_129.dll` by absolute path before its NVRTC compiler and retains
both library handles. This handles NVRTC's later name-based builtins load without
changing global `PATH` or requiring a CUDA Toolkit installation. Packaging tests
exercise CuPy's ordinary compiler-preprocessing path before any test-only native
library loads, then compile real uncached PTX for `compute_75` and `compute_89`
(the RTX 4070 family). Offline compilation validates the shipped compiler path;
the application's allocation/kernel probe still requires the actual GPU/driver.

The finite-volume CPU/GPU kernels reuse already recovered primitive states for
the Rusanov Euler fluxes. This removes redundant full-grid work without changing
the conservative flux, reflected-wall pressure or positivity checks.
Laminar transport uses the same NumPy/CuPy array namespace and backend selection.
Physical GPU execution of the new laminar path still requires a hardware test;
CPU reference tests and offline CUDA compiler checks do not establish it.

## Why thin features need refinement

`geometry_extent_cells` gives three-axis bounding-box resolution;
`median_solid_cross_section_cells` gives the measured median occupied Y/Z spans
of axial slices. Neither is a grid-accuracy guarantee. `fin_resolution` compares
each active original fin's declared thickness against Cartesian cell support
along the fin normal (including angular placement and cant). A thickness below
two cells receives a specific refinement warning. Replacement CAD fin thickness
is **unknown**, rather than inferred from obsolete OpenRocket dimensions. A
zero-width or merged voxel fin can still produce plausible-looking pressure
colors; inspect progressively refined grids before interpreting its loading.

## Verification and interpretation

`tests/test_cfd.py` verifies:

- Exactly preserved uniform oblique supersonic free stream.
- Conservation of all five integrated variables with periodic boundaries.
- The canonical Sod shock tube against independent exact Riemann star states
  and analytic rarefaction density, with mass/energy conservation and the
  correct boundary-pressure momentum impulse.
- Impermeable slip-wall mass/energy flux and zero tangential momentum transfer.
- Exact reflected wall pressure against independent Mach-2 normal-shock jump
  conditions and an isentropic rarefaction benchmark; uniform tangential flow
  between slip walls; equal/opposite exported wall force and fluid momentum impulse.
- Zero resultant/moment under uniform static pressure on a closed solid.
- Geometry voxelization, cell-budget enforcement, actual geometry solves at
  Mach 0.2 and 2.0, positive fluid pressure, changed solved fields and nonzero
  pressure loads.
- A sealed hollow CAD box and its solid exterior yield bit-identical flow masks,
  pressure samples, force and moment after independent numerical advancement.
  A real project solve preserves its asset, cavity-subtracted mass and the shared
  component geometry used by FEA. A resolved through-bore remains open, while
  diagonal-only cell contact cannot admit flow through a sealed wall.
- A nonzero Mach 0.3, 5-degree oblique-flow box run reaching the configured
  conserved-state **and pressure-load** steady-state criteria, with a condition-specific pressure-resultant
  CP near the symmetric box center and explicit unvalidated-force metadata.
- Cancellation, ignored legacy wall/step/time budgets, bounded history,
  exact transient duration despite zero residual, actual saved timestamps and
  changing boundary metadata, JSON finiteness and explicit unavailable-GPU
  handling. Hardware-discovery tests use controlled fake runtimes to verify error
  stages, failed kernel execution, cache behavior and vendor messages; they do not
  substitute for physical NVIDIA hardware validation.
- Rejection of apparent whole-domain convergence while wall pressure/loads
  continue to change, and an explicit low-Mach dissipation warning.

`tests/test_cfd_field_export.py` additionally checks continuous reconstruction
against uniform Euler flow and an analytic affine velocity field in anisotropic
physical coordinates, safe ray termination at an unsampled one-cell barrier,
blocked sealed interiors, bounded payload size and unchanged source arrays.

`tests/test_cfd_viscous.py` checks molecular transport independently of rocket
drag predictions:

- Sutherland reference viscosity and room-temperature dry-air conductivity,
  invalid-temperature rejection and unchanged uniform oblique flow.
- Periodic sinusoidal shear against the independent discrete diffusion rate
  and exponential decay; full coupled conservation of all five quantities.
- Affine Couette shear and viscous dissipation, rigid-rotation zero stress and
  zero deviatoric stress under isotropic expansion with the Stokes hypothesis.
- Fourier conduction under a known linear temperature gradient; exact half-cell
  Couette traction and distinct normal viscous stress.
- Zero mass/energy transport at every stationary adiabatic wall face under
  nonuniform temperature; opposite integrated wall force and fluid momentum loss.
- A combined acoustic/diffusive CFL bound with changing density/temperature,
  preserved sealed-cavity source geometry, and actual finite transient
  pressure/shear/total-load exports with explicit validity warnings.

The progress tests also require viscous-traction decline for a Laminar steady
ETA and retain unknown ETA when that rate stalls or is missing.

These verify kernel behavior and bounded output storage. They do not validate
rocket drag, transonic shocks, CP or pressure accuracy. This release has no
wind-tunnel rocket force benchmark and no claim of production CFD accuracy.
For consequential design decisions, compare a grid/domain convergence study
against a trusted solver and relevant experiments, and use an appropriate
viscous/turbulence model where those effects matter.

Reference methods and benchmarks:

- E. F. Toro, *Riemann Solvers and Numerical Methods for Fluid Dynamics*, third
  edition, Springer, 2009. [Publisher](https://doi.org/10.1007/b79761).
- R. J. LeVeque, *Finite Volume Methods for Hyperbolic Problems*, Cambridge,
  2002. [Publisher](https://doi.org/10.1017/CBO9780511791253).
- G. A. Sod, “A survey of several finite difference methods for systems of
  nonlinear hyperbolic conservation laws,” *Journal of Computational Physics*
  27, 1–31 (1978). [Paper](https://doi.org/10.1016/0021-9991(78)90023-2).
- R. B. Bird, W. E. Stewart and E. N. Lightfoot, *Transport Phenomena*, second
  edition, Wiley, 2002: Newtonian stress, viscous energy transport and Fourier
  conduction. The implementation's Sutherland air constants and fixed Prandtl
  number are stated above; this citation is not a claim of a validated
  rocket boundary-layer model.
- [CuPy installation and CUDA compatibility](https://docs.cupy.dev/en/stable/install.html).

The books specify the underlying numerical methods. The implementation is a
small independent solver; it does not claim to incorporate the complete
algorithms or validation suites of those references.
