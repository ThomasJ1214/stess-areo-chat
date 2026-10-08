# Experimental compressible Euler solver

Rocket Workbench includes a real numerical solver for three-dimensional,
compressible **inviscid** flow. It advances density, three components of momentum,
and total energy. Pressure and velocity visualization come from this solved
state; pressure colors are not synthetic gradients. The solver is experimental
and is not a validated production CFD package.

This capability supports studying how a detailed CAD replacement changes the
discretized external flow, including pressure waves and shock formation up to an
actual incoming Mach number of 2. It does **not** predict viscous drag, boundary
layers, transition, turbulent fluctuations, viscous separation, heating, or
wall shear. Airflow arrows show the local solved velocity. There is no fabricated
streamline/turbulence animation. Euler pressure is not a structural stress field.

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
first-order Rusanov (local Lax-Friedrichs) numerical flux is

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

First-order dissipation smears contacts and shocks. It also makes force values
grid-dependent. This release has neither adaptive refinement nor a higher-order
reconstruction. It solves a transient initial-value problem initialized with a
uniform free stream, so the early steps show genuine numerical startup effects.

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

At a fluid/solid face, the ghost state mirrors normal momentum while preserving
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
| `grid_resolution` | 32 | Cells across geometry's axial extent, 12–256 |
| `transverse_resolution` | min(24, axial resolution) | Cells across each transverse geometry extent, 12–128 |
| `domain_padding` | 0.5 | Padding in multiples of corresponding geometry extent; downstream padding is at least 0.65 |
| `max_cells` | 300,000 | Explicit allocation budget, maximum 2,000,000; excess grids are rejected |
| `max_steps` | 5,000 | Maximum accepted conservative steps, 1–10,000 |
| `cfl` | 0.35 | CFL multiplier, 0.01–0.8 |
| `max_wall_seconds` | 1,200 | Wall-clock integration budget, 1–3,600 seconds |
| `flow_through_times` | 2 | Target simulated time in domain-crossing times |
| `max_physical_time` | derived | Optional explicit physical integration time in seconds |
| `convergence_tolerance` | 0.00001 | Tolerance for conserved-state, wall-pressure, force and moment rate changes per crossing time |
| `sample_limit` | 4,000 | Maximum fluid field samples returned to the viewer |
| `surface_limit` | 5,000 | Maximum exposed-wall pressure samples returned |
| `backend` | `auto` | `auto`, `cpu`, or `gpu` |
| `original` | false | Use original OpenRocket geometry instead of attached replacements |

The default grid is a quick experimental run, especially for thin fins; it
is not sufficient merely because the solver finishes. Compare progressively
refined grids and enlarged domains. Memory and runtime grow rapidly with
resolution. Cell and time budgets prevent an unattended job from exhausting
the workstation. A wall-clock budget is checked between steps and excludes
final extraction time; it is not a precise process timeout.

The history reports accepted step, physical time, actual step size, normalized
RMS conserved-state rate of change, raw normalized step change, minimum fluid
pressure and maximum local Mach. Independently, `wall_pressure_residual` measures
area-weighted RMS wall-pressure change, `force_residual` measures resultant
change, and `moment_residual` measures moment change about the geometry bounding
box center. Pressure rates use incoming dynamic pressure (with a small static
pressure floor at zero speed); force uses dynamic pressure times projected voxel
area, and moment additionally uses maximum geometry extent. All four changes
are divided by `dt` and multiplied by domain-crossing time: reducing the time
step alone cannot improve them. Whole-domain RMS alone could hide changing loads
among many undisturbed farfield cells. Steady convergence therefore requires
**all four** rates below tolerance for 20 successive steps after at least half
a domain crossing time. This criterion does not establish grid convergence or
physical validation. Percentage and ETA refer to the configured work budget,
not a promise that the underlying flow reaches steady state by that time.

The `summary.status` value distinguishes `converged`, `step_budget`,
`physical_time_budget`, `wall_clock_budget`, and `cancelled`. A budget-limited
run still returns its actual partial fields and loads, with an explicit warning;
it is never labeled converged. Cancellation is cooperative between steps.

`samples` contain position, absolute pressure, density, solved velocity and
local Mach. `surface` contains exposed face position, numerical absolute wall
pressure, outward normal and pressure coefficient (null at zero airspeed or
when incoming dynamic pressure is smaller than 64 floating-point ulps of
atmospheric pressure). Absolute solved pressure is always retained.
`summary` includes pressure force in body axes, pressure drag projected along
the free stream, moment about project coordinate origin, resource usage and
the stopping reason. Surface force signs use pressure acting inward onto the
solid; skin-friction force is absent. JSON exports include fidelity and warnings.

Pressure forces remain visible during transient or budget-limited runs as
actual numerical outputs; `pressure_force_steady` explicitly distinguishes a
converged result and `pressure_force_validated` is false in this release.
Only a converged result with appreciable lateral force receives `cp_m`, the
least-squares position on the project X axis satisfying its lateral moment:
`x_cp = (Fy*Mz - Fz*My)/(Fy²+Fz²)`. It is a **condition-specific pressure-resultant
centerline fit**, not the small-angle derivative CP used by Barrowman stability
analysis. Its moment-fit residual is reported because torsion and forces off
the centerline cannot always be represented by one point. No CP is inferred
from pure drag, unconverged startup fields, or negligible lateral force.

## CPU and GPU execution

NumPy runs the actual numerical calculation on CPU. CuPy runs the same
conservative kernels on a supported NVIDIA CUDA GPU when the bundled CuPy CUDA
runtime and a compatible installed NVIDIA driver are usable. Rendering uses
the desktop GPU independently of numerical execution. Geometry voxelization
and final JSON extraction run on CPU in either case.

`auto` falls back to CPU and reports `backend = numpy-cpu` plus a warning.
An explicit `gpu` selection raises an error if CUDA is unavailable; it never
pretends CPU work ran on a GPU. AMD/Intel rendering support does not imply CUDA
solver support. The CUDA runtime can be bundled, but a hardware-specific GPU
driver remains a prerequisite installed on the Windows computer.

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
- Cancellation, JSON finiteness and explicit unavailable-GPU handling.
- Rejection of apparent whole-domain convergence while wall pressure/loads
  continue to change, and an explicit low-Mach dissipation warning.

These verify kernel behavior and bounded execution. They do not validate
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
- [CuPy installation and CUDA compatibility](https://docs.cupy.dev/en/stable/install.html).

The books specify the underlying numerical methods. The implementation is a
small independent solver; it does not claim to incorporate the complete
algorithms or validation suites of those references.
