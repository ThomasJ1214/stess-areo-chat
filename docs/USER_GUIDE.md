# Rocket Workbench: step-by-step user guide

You do not need Python, Node.js, a separate CAD program, Gmsh, or a CUDA Toolkit
to use the Windows installer. Start with [Windows installation](WINDOWS_INSTALL.md),
then follow the first workflow below. Everything runs locally after installation.

## 1. Open the app and learn the layout

1. Open **Rocket Workbench** from the Windows Start menu.
2. The app starts with a demonstration rocket. Its motor and example coefficients
   are synthetic tutorial data; use your actual data for your rocket.
3. The top tabs are **Design**, **Aerodynamics**, **Flight**, **Structures**,
   **CFD**, and **Studies**. The left assembly selects parts, the centre shows the
   rocket/results, and the right panel edits the selected part or simulation setup.
4. Drag in the 3D view to orbit, use the mouse wheel to zoom, and use the viewport
   camera controls to fit/reset the view. Click a visible part or its assembly row
   to inspect it.
5. Choose metric or US units from the top unit selector. Values convert for
   display; calculations and exported scientific data remain SI.

Changes in component, material and flight-configuration editors require their
**Apply**/**Save** button. Simulation conditions and numerical solver controls
autosave; the bottom status tells you if a save is pending or failed. **Save
project** writes a portable `.rocket.json` file. Keep an explicit saved copy;
the local last-session file is a convenience, not a backup.

## 2. Import an OpenRocket project and configure flight

1. Use **Import → OpenRocket** and choose your `.ork` file.
2. Read the import warnings before running anything. Unsupported pods, clusters,
   staging, event definitions or absent data remain warnings/errors; the app does
   not silently simulate their omitted physics.
3. Select the intended **Flight configuration** near the assembly. Inspect the
   dimensions, enabled parts, materials and measured mass/CG overrides.
4. In **Design → Flight setup**, check **Motor curve**. An OpenRocket motor name
   or digest alone is insufficient. Import your actual `.eng` or `.rse` thrust
   curve, select it, and check its mass, diameter, length and mount placement.
5. Choose **Single deployment** or **Dual deployment**. Enter the main chute's
   effective **Cd × area**; dual deployment also needs drogue Cd × area and main
   deployment height above launch level (AGL). This input is not chute diameter:
   for a circular chute, area is `π × diameter² / 4`, multiplied by its justified
   drag coefficient.
6. Select the primary deployment event and delay. Motor ejection requires the
   actual delay after burnout. If recovery was absent/unusable in the ORK file,
   enter the real settings and enable **Recovery settings confirmed**.
7. Click **Apply flight setup**, then **Save project**.

The first release supports passive single-stage, single-motor high-power rockets
through Mach 2. Flight is a point-mass model; it does not solve attitude,
weathercocking, tumbling, active guidance or recovery opening shock.

## 3. Replace exactly one part with detailed CAD

For example, replace an OpenRocket payload body tube with the actual payload CAD:

1. In **Design**, select the payload component in the assembly.
2. Open its **Geometry** inspector tab and import `.step`/`.stp` or `.stl`.
   STEP's embedded units are honored. STL/OBJ/PLY lack dependable units: set
   **Mesh file units** to the units used when exporting the source file.
3. Choose the imported **Geometry asset**. Rocket X runs from nose to tail.
   Y/Z are transverse. An offset is relative to the selected component's axial
   position, not the whole rocket origin. Rotations are XYZ Euler degrees;
   **Uniform scale** multiplies all three dimensions.
4. Click **Attach & use detailed geometry** to display the imported part. This replaces only the selected
   component. Other components, their transforms and original shapes stay as
   they were. Repeated non-fin components retain their repeated placement.
5. Inspect its dimensions and alignment, adjust translation, rotation or scale,
   and click **Apply alignment / mode** to display each change. A 100 mm part
   should appear as 0.1 m internally; a factor-of-1,000 error usually means
   incorrect STL units.
6. Turn on **Original geometry** in the viewport to compare. Use **Analysis
   geometry → Original** and reapply when you want the reference shape again.
   Retain your saved pre-edit file for an explicit backup.
7. In **Component**, check **External surface**. Enable it for parts exposed to
   airflow; disable it for enclosed electronics, ballast and internal hardware.
   **Enabled** controls the whole part/subtree; it is different from excluding
   an internal part from aerodynamic surfaces. Apply component changes.
8. Verify material and mass treatment, then save the project.

**Airflow and material geometry are separate.** CFD builds a copied exterior-flow
grid from enabled external components. Only air connected to the outer domain
is solved. Sealed interior cavities produce no internal aerodynamic pressure
faces. Open bores remain airflow passages when the grid resolves their openings.
The process does not close holes in your saved CAD, rewrite neighboring parts,
or use the blocked flow volume as material volume. Mass and solid FEA retain
the CAD's actual cavity/material geometry. Small gaps can close at coarse grid
resolution: inspect the cell spacing and refine before interpreting loads.

A watertight CAD mesh is not automatically a homogeneous solid assembly.
Assign actual density and inspect the material volume. Overlapping shells,
unverified topology, open meshes and mixed materials may require measured mass
and CG, a CAD union, or separate components. FEA rejects unverified solid volume.
Projects embed triangulated geometry, not the editable STEP boundary model;
keep the original CAD files too.

## 4. Run a quick aerodynamic check

1. Open **Aerodynamics** and set speed or **Mach override**, altitude, incidence,
   lateral wind, wind direction and temperature deviation.
2. Click **Run aerodynamic analysis**. Inspect drag, dynamic pressure, CG/CP,
   static margin, the component breakdown, method and warnings.
3. Enable **CG / CP** and **Forces** to inspect their locations/directions.

These are fast engineering estimates. Replacing arbitrary CAD does not silently
create new validated fast drag/CP coefficients: the default estimate retains the
original OpenRocket reference shape and flags that limitation. Use CFD for a
mesh-resolved exterior pressure calculation, or import a justified geometry-bound
coefficient CSV for fast current-shape aerodynamics/flight. The required columns
are `mach,cd,cna,cp_m`; CP is metres from the nose and coefficients use the shown
reference area. Geometry edits invalidate that table. See [PHYSICS.md](PHYSICS.md).

## 5. Simulate and inspect a complete launch

1. Open **Flight**. Set launch altitude, wind, **Launch rail length**, **Angle
   from vertical**, launch azimuth, time step and duration limit.
2. Click **Simulate full flight**. Progress shows percent, elapsed time and ETA;
   ETA is an estimate. Use **Cancel** to stop a long job. Setup controls are
   locked while a job runs so displayed geometry and inputs remain consistent.
3. After completion, use play/pause, playback speed and **Flight timeline** to
   scrub. Click events to inspect rail exit, burnout, max acceleration, max Q,
   apogee and recovery. **Follow** moves the camera along the trajectory;
   **Inspect** shows the rocket locally.
4. Read flight graphs and the selected time's velocity, acceleration, Mach,
   dynamic pressure and supported beam-stress estimate.
5. Check whether recovery was deployed and ground contact was reached. A duration
   limit can yield an incomplete flight; an undeployed impact is explicitly
   different from parachute recovery. Extend the duration if necessary.
6. Export **Flight data CSV**, **Engineering report**, and **Run input project**.
   The last file preserves the actual configuration/conditions used for that run,
   even after later edits. Reports show the source hash, method and warnings.

Wind direction is a *toward* direction. Flight uses north=0°, east=90°; static
rocket wind uses +Y=0°, +Z=90°. Turbulence is a reproducible gust estimate, not
resolved turbulent CFD. Flight stress is quasi-static beam/fin estimation,
not transient FEA or a resolved parachute-opening load.

## 6. Solve exterior flow with CFD

1. Open **CFD** and confirm actual exterior geometry and operating conditions.
2. Start with a modest grid/cell budget. Lengthwise and transverse resolution
   are separate so slender rockets still resolve their diameter and fins.
3. Select CPU, automatic, or GPU. Numerical GPU mode needs a compatible NVIDIA
   device/driver. Automatic mode may use CPU; the result reports what ran.
4. Click **Solve flow field**. Pressure/velocity fields are actual numerical
   outputs. Check stopping reason, convergence history, wall/force convergence,
   grid spacing and geometry/flow diagnostics before using loads.
5. Refine the grid and increase **Farfield padding**, then compare loads. Padding
   is a fraction of each geometry extent; it is not a distance in metres. A numerically
   steady answer alone does not establish resolution independence or physical
   accuracy. Export the full **Flow solution JSON** to preserve fields.

This solver is experimental compressible inviscid Euler, with staircase walls.
It omits viscosity, skin friction, boundary layers and turbulence. Low-Mach
pressure forces are particularly sensitive to numerical dissipation. Its
pressure drag is not a validated total drag coefficient. An iteration/time
budget stopping reason is not convergence. See [CFD.md](CFD.md).

## 7. Estimate loads or run component FEA

1. In **Structures**, inspect beam/fin estimates for quick screening.
2. Select the component for solid FEA. Confirm its isotropic material properties,
   actual mesh and whether its support represents the real load path.
3. Set target mesh size and element limit. Choose **Clamp type**, axis and side.
   Choose **Surface load**: an explicitly labeled aerodynamic pressure surrogate,
   uniform pressure, prescribed end traction, or a converged CFD pressure field.
   Body acceleration is an additional declared load, not inferred recovery shock.
4. Click **Run finite element analysis**. Inspect peak element stress, nodal
   heatmap, displacement, energy and equilibrium diagnostics.
5. Turn on **Stress**/**Deformation**. The deformation scale exaggerates the
   displayed displacement; it does not multiply the solved physical result.
6. Repeat with a finer mesh and inspect load/support sensitivity. Export full
   solver JSON and the FEA report.

For CFD pressure transfer, solve CFD first on the same current geometry and select
that source. Transfer requires numerical convergence and matching geometry.
Inspect mapped area and distances; the mapper is one-way and not force-conservative.
The source job is session-local: export its JSON and recorded inputs before
closing. A downloaded FEA input project alone does not include that solved field;
rerun its source CFD before pressure transfer in a new session.

FEA is linear isotropic static elasticity. It does not model laminate failure,
yielding/plasticity, buckling, joints/contact, flutter or transient opening shock.
See [STRUCTURAL.md](STRUCTURAL.md).

## 8. Compare, sweep and save your work

- **Studies → Compare** compares original/current geometry and configurations;
  **Compare flight performance** runs both flight bases. Fast CAD comparisons
  retain the stated reference-geometry aerodynamic limits.
- A parameter/wind sweep changes one input with a common gust realization.
  Flight speed and Mach are outputs; use wind, launch altitude/angle, rail length
  or other supported flight inputs. An angle-of-attack flight sweep changes
  the structural reference angle rather than integrating attitude.
- Monte Carlo uses the displayed seed and records failed samples. Statistics
  exclude failed inputs; examine warnings and validity in the individual rows.
- **Save project** preserves geometry, materials, motors, configuration, units
  and simulation setup. Solved jobs are not restored on restart. Export their
  CSV/JSON/reports and **Run input project** before closing.
- CSV `_result_*` columns in the first data row carry method/provenance/warnings.
  Keep that row and those columns with the table. HTML reports are offline and
  can be opened in a browser and printed; JSON retains full numerical fields.

## When something looks wrong

| Symptom | What to check |
| --- | --- |
| CAD is huge, tiny or misplaced | Source units, X alignment, component-relative offsets and scale |
| An internal object receives aerodynamic loads | Its **External surface** flag and whether an opening actually connects it to exterior air; refine small gaps |
| No flight can run | Real assigned motor curve, enabled mount, supported configuration and confirmed recovery |
| CP is unavailable | Unsupported/reference placeholder geometry, nonpositive normal slope or missing/stale supplied polar |
| CFD finishes without convergence | Stopping reason, work budget, CFL, wall/load residuals, grid and domain sensitivity |
| Zero FEA stress | Declared load, load direction, selected loaded faces and unloaded-result warning |
| Extremely high local stress | Clamp idealization, corner singularities, material/units, mesh refinement and reported element versus averaged nodal values |
| GPU calculation cannot start | NVIDIA driver/device and available VRAM; choose automatic/CPU to inspect the actual fallback |
| Black or failed viewport | Update the graphics driver; inspect `%LOCALAPPDATA%\RocketWorkbench\application.log` |
| Setup did not save | Bottom save status/error banner; correct invalid values and save again |

The [validation record](VALIDATION.md) describes reference and integration checks.
Those checks verify calculations and workflows; they do not establish flight-test
or wind-tunnel agreement for your particular rocket.
