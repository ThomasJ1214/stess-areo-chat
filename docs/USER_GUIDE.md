# Rocket Workbench: step-by-step user guide

You do not need Python, Node.js, a separate CAD program, Gmsh, or a CUDA Toolkit
to use the Windows installer. Start with [Windows installation](WINDOWS_INSTALL.md),
then follow the first workflow below. Engineering calculations and saved projects
work offline. The optional **Find motor online** search needs an internet
connection and contacts ThrustCurve.org only when you request it.

## 1. Open the app and learn the layout

1. Open **Rocket Workbench** from the Windows Start menu.
2. The app starts with a demonstration rocket. Its motor and example coefficients
   are synthetic tutorial data; use your actual data for your rocket.
3. Click **Getting started** for a guided introduction to the entire app. Choose
   any page and click **Tutorial** for its step-by-step walkthrough. These guides
   are bundled with the app; you can repeat them without internet access. Use
   **Next step**/**Previous**, or **Open [page] & try this step** to return to the
   workspace and practice. Reopen **Tutorial** to continue where you left off.
   **Restart topic** starts a topic again. Completion marks record reading
   progress, not whether a rocket design has been validated.
4. The top tabs are **Design**, **Aerodynamics**, **Flight**, **Structures**,
   **CFD**, and **Studies**. The left assembly selects parts, the centre shows the
   rocket/results, and the right setup panel edits the selected part or simulation.
   Drag the dividers to resize the panels. **Hide assembly** and **Hide setup**
   make room for the view; the matching **Show** buttons bring them back.
   **Focus 3D view** gives the rocket more room; **Reset layout** restores the
   default arrangement. You can adjust a focused divider with the arrow keys.
5. Drag in the 3D view to orbit, use the mouse wheel to zoom, and use the viewport
   camera controls to fit/reset the view. Click a visible part or its assembly row
   to inspect it.
6. Click the small **?** beside an unfamiliar term to read its definition. These
   explanations cover both its meaning and how the app uses it. The **User guide**
   button opens the full offline instructions at any time. Click the question
   mark again, click elsewhere, or press `Escape` to close a definition.
7. Choose metric or US units from the top unit selector. Values convert for
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
   curve, or use **Find motor online** as described below. Select the curve and
   check its mass, diameter, length and mount placement.
5. Choose **Single deployment** or **Dual deployment**. Enter the main chute's
   effective **Cd × area**; dual deployment also needs drogue Cd × area and main
   deployment height above launch level (AGL). This input is not chute diameter:
   for a circular chute, area is `π × diameter² / 4`, multiplied by its justified
   drag coefficient.
6. Select the primary deployment event and delay. Motor ejection requires the
   actual delay after burnout. If recovery was absent/unusable in the ORK file,
   enter the real settings and enable **Recovery settings confirmed**.
7. Click **Apply flight setup**, then **Save project**.

The supported target is passive single-stage, single-motor high-power rockets
through Mach 2. Point-mass flight retains a prescribed gravity-turn axis.
Optional rigid-body 6DOF integrates attitude and angular rates using small-angle
engineering forces and moments. It can respond to wind but does not supply
validated large-angle, tumbling, active-guidance or recovery-opening physics.
Read the supported-domain warnings before using either trajectory.

### Find and review a motor curve online

1. Click **Find motor online**. Enter **Motor designation** (for example,
   `J350W`), optionally enter **Manufacturer**, and click **Search catalog**. This is
   an explicit search of ThrustCurve.org's motor database, not an automated web
   scraper or an AI-generated thrust curve.
2. Click **Review curves** for the intended motor. Compare its manufacturer,
   designation, diameter, length, total mass and propellant mass with your
   physical motor. Similar names
   can identify different motors or versions; do not choose by name alone.
3. Click **Preview curve** for an available file. Inspect the plotted thrust,
   source information, units and warnings. A database entry can contain
   contributed or simulated data;
   downloaded data is not automatically a certification record or an independent
   validation of your motor.
   The review records provider-reported source type, license, fetch time and a
   SHA-256 digest. Keep those records and respect the curve's stated license;
   the app's source license does not replace a data file's own terms.
4. Review the curve before clicking **Import reviewed motor**. Import adds the
   reviewed curve to the project. It does not silently replace the motor in every
   flight configuration.
5. In **Design → Flight setup**, choose the imported **Motor curve**, verify the
   motor mount and ignition/recovery settings, then click **Apply flight setup**.
   **Save project** embeds the curve so later simulations can run offline.

If the service is unavailable or you have no internet connection, import a local
`.eng` or `.rse` file instead. Motor searches do not upload your rocket's CAD or
project. Retain the downloaded source/provenance with your engineering records.

## 3. Replace exactly one part with detailed CAD

For example, replace an OpenRocket payload body tube with the actual payload CAD:

1. In **Design**, select the payload component in the assembly.
2. Open its **Geometry** inspector tab and import `.step`/`.stp` or `.stl`.
   STEP's embedded units are honored. STL/OBJ/PLY lack dependable units: set
   **Mesh file units** to the units used when exporting the source file.
3. Choose the imported **Geometry asset** and leave **Automatic alignment** on.
   Click **Preview automatic alignment**. The app proposes a nose-to-tail axis,
   centers the part across the rocket, and places its front at the selected part's
   front. It preserves actual imported dimensions by default.
4. Inspect the preview and enable **Original geometry** to compare. If the wrong
   end points toward the nose, select **Reverse direction**. If the proposed axis
   is wrong, choose the source X/Y/Z under **Source axis**. **Placement anchor**
   chooses front or centre alignment. Preview again after changing these options.
   Review dimensions and any reported gaps/overlaps with neighboring parts.
5. Leave **Fit selected length** off for actual hardware. Enable it only when you
   deliberately want to resize the CAD to the reference part's length. It scales
   every dimension uniformly; computed material volume/mass change by scale cubed.
   It does not reshape only the diameter. A 100 mm part should appear as 0.1 m
   internally; a factor-of-1,000 error usually means incorrect mesh file units.
6. Click **Attach & use detailed geometry**. Only the selected component changes;
   neighboring parts keep their shapes and positions. Repeated non-fin components
   retain their repeated placement. Check nose tips, shoulders, roll and joints;
   automatic placement is a starting guess, not a confirmed assembly fit.
7. For fine adjustments, turn off **Automatic alignment** and edit translation,
   rotation or **Uniform scale**, then click **Apply alignment / mode**. Rocket X
   runs from nose to tail; Y/Z are transverse. Translation is relative to the
   selected component's axial position; rotations are XYZ Euler degrees.
8. Use **Analysis
   geometry → Original** and reapply when you want the reference shape again.
   Retain your saved pre-edit file for an explicit backup.
9. In **Component**, check **External surface**. Enable it for parts exposed to
   airflow; disable it for enclosed electronics, ballast and internal hardware.
   **Enabled** controls the whole part/subtree; it is different from excluding
   an internal part from aerodynamic surfaces. Apply component changes.
10. Verify material and mass treatment, then save the project.

The replacement joins the displayed assembly and participates in the assembled
exterior-flow grid. Alignment does not create a material Boolean union, adhesive
bond, fastener or structural contact. FEA still uses the selected part's real
geometry and your declared support. Prepare any required physically unioned CAD
in your CAD program; do not assume touching parts became one structural solid.

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
   from vertical**, launch azimuth, time step and duration limit. The rocket
   starts on a launch rail above a flat ground plane. Check that the setup matches
   your intended rail and configuration. Under **Flight dynamics model**, choose
   **Rigid body · 6DOF** to calculate orientation and angular rates, or retain
   **Point mass** for the previous gravity-turn model. Rigid-body inertia comes
   from supported geometry and declared approximations; Flight setup accepts a
   measured complete dry-rocket inertia tensor and source. A supplied Cmq adds
   pitch/yaw damping; missing coefficients do not invent damping.
   Choose **Wind model** deliberately. Dryden stochastic gusts use a fixed
   transport speed and user-assumed correlation length. Smooth gusts retain the
   earlier seeded sine-wave model. Both use the random seed and turbulence
   intensity; neither supplies measured weather or resolved turbulent CFD.
2. Click the large red **Launch** button. The app first calculates the complete
   flight. Progress shows percent, elapsed time and ETA;
   ETA is an estimate. Use **Cancel** to stop a long job. Setup controls are
   locked while a job runs so displayed geometry and inputs remain consistent.
   When calculation finishes, playback starts and the camera pulls back to follow
   the rocket. This animation plays computed results; it is not real-time flight
   integration.
3. Use play/pause, playback speed and **Flight timeline** to scrub. Click events
   to inspect rail exit, burnout, max acceleration, max Q, apogee and recovery.
   The trail follows the computed trajectory and wind indicators show the model's
   wind. Rigid-body playback uses saved quaternion attitude and interpolates it
   smoothly for viewing; point-mass orientation remains prescribed. Smooth
   camera motion and display interpolation do not change the calculated physics.
4. Drag to orbit, right-drag to pan, or scroll to zoom at any time. In **Follow**,
   automatic tracking resumes five seconds after your camera interaction ends;
   **Resume follow** restores it immediately. **Overview** fits the flight path;
   **Inspect** returns to local rocket geometry. A distant rocket may be enlarged
   for visibility; the view labels that display scale and the underlying geometry
   and flight calculations retain their real dimensions.
5. Use the top-down map to compare the rocket, launch pad, flight path and landing
   position. The map is north-up and uses local east/north distances from the
   launch pad. Click a numbered event point of interest or its list entry to
   inspect that flight moment. Drag to pan, use **Zoom in**/**Zoom out**, or
   **Fit whole flight** to restore the full path. With the map focused, arrow keys
   pan, `+`/`−` zoom, and `Home` fits the flight. Wind arrows point toward the
   modeled wind direction. It is a schematic local map, not satellite imagery,
   GPS or a terrain/weather service. A trajectory that stops before ground
   contact has a last recorded position,
   not a predicted completed landing; the map explicitly reports no landing
   point when ground contact was not reached.
6. Read flight graphs and the selected time's velocity, acceleration, Mach,
   dynamic pressure and supported beam-stress estimate. **Attitude & recovery**
   shows solved incidence, angular rates and forces when available; missing
   point-mass attitude data are unavailable, not zero angular motion.
7. Check whether recovery was deployed and ground contact was reached. A duration
   limit can yield an incomplete flight; an undeployed impact is explicitly
   different from parachute recovery. Extend the duration if necessary.
8. Export **Flight data CSV**, **Engineering report**, and **Run input project**.
   The last file preserves the actual configuration/conditions used for that run,
   even after later edits. Reports show the source hash, method and warnings.

Wind direction is a *toward* direction. Flight uses north=0°, east=90°; static
rocket wind uses +Y=0°, +Z=90°. **Wind shear exponent** optionally applies a
user-assumed power law versus height above the flat launch plane. Zero retains
height-independent wind. Dryden's **Gust sample interval** is independent of the
flight integrator; smaller values retain faster gust changes but cost memory.
Compare justified scales, sample intervals and seeds for sensitivity.

Rigid-body forces still rely on small-angle coefficients and reference CP.
Significant unsupported high incidence stops the un-recovered free-flight
calculation rather than inventing tumbling physics; check completion and validity.
Initial roll can evolve without a supplied aerodynamic roll/cant model.
Main/drogue **inflation time** grows lumped Cd × area linearly; zero preserves
instant deployment. This does not solve line shock, suspension motion or canopy
shape. Flight stress estimates remain distinct from dynamic fin FEA and neither
resolves full-vehicle recovery opening loads.

### Change wind or air during playback

1. Pause or scrub the flight timeline to the desired timestamp.
2. If **Setup changed since this flight** appears, click **Recalculate flight**
   first. The old playback and geometry retain their original run inputs.
3. Open **Live environment · recalculate from a selected moment**. Enter the
   new lateral wind, toward-bearing direction, gust intensity and transition
   time. An optional temperature deviation changes the standard-atmosphere
   offset; blank preserves the preceding temperature schedule.
4. Click **Apply from selected time**. The app recalculates the actual launch
   with this scheduled input and resumes playback at that moment. The
   prescribed wind history before the timestamp stays unchanged; numerical
   trajectory samples may differ slightly because the new event partitions
   the adaptive integration.
5. Inspect the schedule, wind/attitude/load graphs and landing response.
   Transition windows cannot overlap. **Clear schedule for next launch** removes
   events from the next run; recalculate to obtain its new results.

This control changes atmospheric inputs. It does not steer the rocket or edit
stored solution fields, and it requires a new actual simulation.

### Add time-dependent fin bending

Before launch, select **Dynamic fin bending · 1D beam FEA** under **Flight
structural model**. Set a justified **Fin modal damping ratio**. In its advanced
controls, refine **Fin beam elements** for spatial sensitivity. Keep **Fin time
integrator → Exact modal** for the default complete-basis response to linearly
interpolated recorded loads. Refine flight sampling to check load bandwidth and
sampled stress peaks; exact modal propagation cannot recreate unrecorded loads.
For a legacy comparison, select **Newmark** and refine **Steps per fundamental
beam period** too; that setting alone does not resolve every higher mode.
Fiberglass/carbon require an explicit **Allow isotropic composite approximation**
acknowledgement; a scalar stiffness cannot represent
laminate directions or composite failure criteria.

After calculation, inspect **Dynamic fin FEA** graphs and the structural coverage
panel. Dynamic stress/deflection come from a time-integrated Euler–Bernoulli beam
model of original trapezoidal fins under saved aerodynamic and translational
inertial loads. CAD replacement fins are unsupported. These results are separate
from the quasi-static stress estimate. Choose the desired stress source in the
viewer: dynamic colors show each supported fin component's peak beam stress,
while exported nodal values retain the span distribution. They are not a 3D
solid heatmap. Unsupported fins, recovery and unavailable load intervals leave
gaps or gray parts; they do not imply zero stress. Check structural coverage even
when the flight job finished. This solver excludes rotational base inertia,
bonded joints, full-vehicle shell/solid dynamics, flutter and fluid–structure
coupling.

## 6. Solve exterior flow with CFD

1. Open **CFD** and confirm actual exterior geometry and operating conditions.
   Choose **CFD physics model**. **Euler** computes inviscid pressure flow with
   slip walls. **Experimental laminar Navier–Stokes** adds molecular Newtonian
   viscosity, Fourier heat conduction and stationary no-slip adiabatic walls.
   It does not add turbulence, transition or a wall function; neither option
   establishes accurate whole-rocket drag on a coarse grid.
2. Start with a modest grid/cell budget. Lengthwise and transverse resolution
   are separate so slender rockets still resolve their diameter and fins.
3. Select CPU, automatic, or GPU and open **GPU diagnostics** if GPU execution is
   unavailable. Numerical CUDA needs a compatible NVIDIA device/driver; AMD/Intel
   graphics can render the scene but cannot run this CUDA solver. Automatic mode
   may use CPU; the result reports what ran. Restart the app after a driver change.
4. Choose **Steady-state** for fixed-condition numerical convergence, or
   **Transient** for a physical flow interval. Neither mode has a computer-time
   or step-count cutoff. A steady run may continue indefinitely; use **Cancel**
   when needed. Its progress shows measured steps, elapsed time and residuals;
   a tentative ETA requires a consistent residual trend, and otherwise remains
   unknown. Transient percentage follows actual integrated physical time; its
   ETA estimates the remaining integration from measured throughput.
   Initialization and field extraction are separate phases outside that ETA.
   For transient launch flow, use **Launch history** and choose the whole flight
   or a short interval. The app uses calculated air-relative velocity, wind and
   atmosphere. Rigid-body histories also use saved quaternion attitude and roll
   to express that boundary velocity in the original CAD axes; point-mass
   histories use their prescribed body-axis convention. A fixed-condition
   transient test is also available.
   **Each selected interval starts with uniform freestream at its first launch
   timestamp, rather than resuming an earlier CFD state.** Start before the
   event you want to inspect and compare earlier start times to assess startup
   effects; a short window around max Q omits the fluid history before its start.
5. Click **Solve flow field**. Pressure/velocity fields are actual numerical
   outputs. Check stopping reason, convergence history, wall/force convergence,
   grid spacing and geometry/flow diagnostics before using loads. Laminar
   convergence independently includes viscous-wall traction changes, and its
   force/moment criteria include both pressure and full viscous traction.
   **Computed viscous force component**, **Pressure + viscous drag** and
   **Fluid wall shear stress** are separate from pressure-only force and solid
   material stress. Transient playback reports the selected actual state's
   loads; a finished interval does not make them steady or validated.
6. Enable **Streamlines** and **Pressure** in the 3D overlays. In **Flow display**,
   adjust **Streamline density**, **Streamline length** and **Streamline color**.
   The speed legend comes from the solved field. **Direction tracers** use visual
   timing on the frozen field, not unsteady particle histories. Lines stop at the
   exported domain and conservative wall mask; they do not enter sealed cavities.
   Older saved results show sparse solved vectors until rerun. Display settings
   do not change forces, geometry or the solution. Streamline quality improves
   display integration and smoothness; it does not refine the CFD grid.
   **X-ray rocket** makes the rocket translucent. **Cutaway** clips the displayed
   model/field to inspect inner layers; it never cuts saved CAD or opens sealed
   flow space.
   Choose **Cutaway axis**, drag **Cutaway position**, or enable **Reverse cutaway**
   to inspect the other side. Hidden sealed interiors still contain no solved air.
   For transient results, use **Play CFD playback**/**Pause CFD playback**, the
   previous/next snapshot buttons, or the **CFD snapshot timeline**. Each
   timestamp identifies an actual computed state, with no manufactured
   intermediate flow fields. **Replay → Slow/Normal/Fast** changes visual timing;
   Normal replays the saved interval in about eight seconds, independently of
   its physical duration. Read the CFD and launch timestamps to inspect time.
7. Refine the grid and increase **Farfield padding**, then compare loads. Padding
   is a fraction of each geometry extent; it is not a distance in metres. A numerically
   steady answer alone does not establish resolution independence or physical
   accuracy. Export the full **Flow solution JSON** to preserve fields.

Both solvers use an experimental first-order compressible Cartesian scheme with
staircase walls. Euler omits viscosity. Laminar transport computes real molecular
stress and heat conduction, but rocket boundary layers can be far thinner than
the mesh, and numerical diffusion can overwhelm those physical terms. Neither
mode supplies transition or turbulent flow physics. Low-Mach pressure forces
remain particularly sensitive to acoustic numerical dissipation.

Laminar **Run diagnostics**, warnings and exported `summary.transport` describe
the **initial freestream reference**: Reynolds number, viscosity/conductivity and
a characteristic numerical-to-molecular diffusivity ratio. They are not updated
to match every playback timestamp. A large ratio warns that adding physical
viscosity has not resolved the boundary layer; the ratio is a diagnostic scale,
not a measured error bound. Compare grid/domain refinement and trusted data.
Sutherland viscosity and a fixed Prandtl number set transport properties.
Adiabatic walls have zero imposed heat flux; the model does not predict wall
heating with an external thermal boundary condition.

Surface exports distinguish gauge-pressure loading, tangential fluid shear,
full viscous traction and their sum. These loads integrate every exposed voxel
face; display sampling does not reduce the integration. **CFD pressure transfer
to FEA remains pressure-only**, excluding viscous normal and tangential traction.
The computed total pressure-plus-viscous drag is not a validated rocket drag
coefficient. Completed transient fields are instantaneous loads, not steady drag.

Launch-driven CFD prescribes one-way airflow on fixed geometry. It uses saved
rigid-body orientation when available to rotate the boundary inputs, but does
not implement moving meshes, rotating-frame forces, canopy shape changes or
CFD force feedback into the trajectory.
Whole-flight CFD can require millions of acoustic CFL steps. Begin with a short
interval. See [CFD.md](CFD.md).

### If CFD says “Not reached” or an older result says “wall clock budget”

The reported force and colored fields are the actual **partial solution** at
the time the solver stopped. Do not use that force as settled drag or transfer
it to FEA. Current steady runs have no runtime limit. Old budget-limited results
remain partial after upgrading; rerun them to obtain a new solution. Transient
100% means its physical interval was integrated, not that steady convergence
was reached.

For the reported example, `7.83e-3 s` is simulated physical flow time, whereas
`1200 s` is the computer's allowed running time. The two are different clocks.
`numpy-cpu` means this run used CPU numerical calculations even if the graphics
card rendered the rocket. More time may let residuals settle, but does not
remove the method's accuracy limits. At 100 m/s near sea level, Mach is around
0.29; this scheme's low-Mach warning is particularly relevant, and its pressure
drag remains unreliable even if a later run reaches numerical convergence.

Before increasing the grid, inspect the stopping reason, residual history and
actual backend. A finer grid needs more memory and computation and may take
longer to reach comparable physical flow time. First establish a stable run,
then compare finer grids and larger domains. Fast aerodynamic estimates provide
a separate quick reference; they do not validate the CFD field.

## 7. Estimate loads or run component FEA

1. In **Structures**, inspect beam/fin estimates for quick screening.
2. Select the component for solid FEA. Confirm its isotropic material properties,
   actual mesh and whether its support represents the real load path.
3. Leave **Automatic mesh sizing** on initially and read **Mesh readiness**.
   It checks the actual solid and proposes a starting mesh before native meshing.
   Automatic sizing applies the recommendation only when it fits the current
   element budget. **Use recommended mesh** can also raise that budget to the
   suggested permitted value, up to 300,000 elements. Read any remaining error
   before starting. For manual refinement, turn automatic sizing off and set
   target mesh size and element limit yourself. CAD thin features still need
   measurement; the suggestion cannot infer their wall thickness.
4. Choose **Clamp type**, axis and side.
   Choose **Surface load**: an explicitly labeled aerodynamic pressure surrogate,
   uniform pressure, prescribed end traction, or a converged CFD pressure field.
   Body acceleration is an additional declared load, not inferred recovery shock.
5. Click **Run finite element analysis**. Inspect peak element stress, nodal
   heatmap, displacement, energy and equilibrium diagnostics.
6. Turn on **Stress**/**Deformation**. The deformation scale exaggerates the
   displayed displacement; it does not multiply the solved physical result.
7. Repeat with a finer mesh and inspect load/support sensitivity. Export full
   solver JSON and the FEA report.

For CFD pressure transfer, solve CFD first on the same current geometry and select
that source. Transfer requires a completed, numerically converged **steady-state**
result and matching geometry; completed transient snapshots remain ineligible.
Inspect mapped area and distances; the mapper is one-way and not force-conservative.
The source job is session-local: export its JSON and recorded inputs before
closing. A downloaded FEA input project alone does not include that solved field;
rerun its source CFD before pressure transfer in a new session.

Component solid FEA in **Structures** is linear isotropic static elasticity.
It does not model laminate failure, yielding/plasticity, buckling, joints/contact,
flutter or transient opening shock. The separate dynamic fin beam option in
**Flight** retains its own limited geometry, load coverage and damping assumptions.
See [STRUCTURAL.md](STRUCTURAL.md).

### Use flat-fin plate FEA

1. Select an original trapezoidal or triangular finset, then open **Structures**.
2. Set **FEA element model → Original fins · MITC4 plates**. The external root
   is fully clamped at the body surface; tabs, adhesive and body flexibility are
   excluded. CAD midsurfaces and curved body tubes are not supported here.
3. Choose **Plate loading**: prescribed differential pressure, or estimated
   directional aerodynamic loads from the current static conditions. The latter
   requires at least three uncanted fins and uses a uniform pressure equivalent
   of an engineering force estimate, not CFD pressure.
4. Enter **Signed fin pressure** for prescribed loading. Negative values reverse
   bending. Support-specific acceleration contributes the opposite transverse
   inertial load using material density; in-plane forces are excluded.
5. Check material properties. For composites, explicitly acknowledge the
   isotropic surrogate; no laminate safety factor is reported.
6. Review **Mesh readiness**. Plate sizing controls in-plane resolution rather
   than volume layers. The limit is 20,000 quadrilaterals across all fins. Run
   the analysis, enable stress/deformation and **Forces**, and inspect
   **Per-fin plate loads and equilibrium**. Symmetry can cancel a net force without making each fin unloaded.
7. Refine the surface mesh and compare displacement, energy and stress away from
   the clamp. Export CSV/JSON and the engineering report. Midsurface colors are
   recovered stress averages; deformation scale changes display only.

This is static flat-plate FEA. It does not add transient plate analysis during
flight, CAD shell extraction, laminate failure, joints, buckling or flutter.

### If FEA asks for mesh size ≤ thickness/2

This is a bending-resolution check, not an installation error. For a 3 mm
original fin, the initial solid mesh must be no larger than 1.5 mm. A coarse
solid mesh across a thin wall can appear too stiff and give misleading stress
and deformation, so the app deliberately rejects it.

Use **Mesh readiness** and choose **Use recommended mesh** when the permitted
budget can fit it. If the
whole thin body needs too many elements even at the maximum budget, use the
separate **Use beam/fin estimates** option for supported original tubes/fins, or prepare a
smaller physical CAD part in your CAD program and import that part for a local
study. Recreate justified support and loading for the local part; cutting out
a piece does not preserve its full-rocket load path automatically. The app has
no region-cutting tool or curved-shell FEA solver. Original flat fins have the
separate plate option above. Do not increase mesh size past the
thickness limit merely to obtain a heatmap.

The OpenRocket thickness is not imposed on a CAD replacement. Imported CAD may
contain thinner features than the automatic scale-based suggestion resolves;
measure those features and check mesh refinement yourself. A passing preflight
does not establish that the clamps, materials or loads match the real rocket.

## 8. Compare, sweep and save your work

- **Studies → Compare** compares original/current geometry and configurations;
  **Compare flight performance** runs both flight bases. Fast CAD comparisons
  retain the stated reference-geometry aerodynamic limits.
- A parameter/wind sweep changes one input with a common gust realization.
  Flight speed and Mach are outputs; use wind, launch altitude/angle, rail length
  or other supported flight inputs. An angle-of-attack flight sweep changes
  the static structural reference angle; rigid-body incidence comes from solved
  attitude and wind, rather than that entered static-test angle.
- Monte Carlo uses the displayed seed and records failed samples. Statistics
  exclude failed, incomplete and explicitly out-of-domain flight runs. Inspect
  **Eligible samples**, **Excluded samples** and the exclusion reasons. A partial
  ascent is not a completed apogee or landing. CSV/JSON retain its computed
  partial history under `observed_` names; comparisons label partial values
  as observations. Extend the flight duration or correct the model inputs, then
  rerun before comparing completed-flight performance.
- **Save project** preserves geometry, materials, motors, configuration, units
  and simulation setup. Solved jobs are not restored on restart. Export their
  CSV/JSON/reports and **Run input project** before closing.
- CSV `_result_*` columns in the first data row carry method/provenance/warnings.
  Keep that row and those columns with the table. HTML reports are offline and
  can be opened in a browser and printed; JSON retains full numerical fields.

## When something looks wrong

| Symptom | What to check |
| --- | --- |
| CAD is huge, tiny or misplaced | Source units first; preview automatic placement, inspect nose/tail and neighboring gaps, then reverse/change source axis or apply manual alignment. Preserve actual scale unless resizing is intended |
| An internal object receives aerodynamic loads | Its **External surface** flag and whether an opening actually connects it to exterior air; refine small gaps |
| No flight can run | Real assigned motor curve, enabled mount, supported configuration and confirmed recovery |
| CP is unavailable | Unsupported/reference placeholder geometry, nonpositive normal slope or missing/stale supplied polar |
| CFD loads are not steady | Check the mode and stopping reason: a completed transient field is instantaneous; a cancelled run is partial. Inspect actual backend, wall/load residuals and low-Mach warnings. Run steady-state separately when settled numerical loads are needed, then compare grids/domains |
| FEA rejects a thin part's mesh | Keep mesh ≤ thickness/2 for original parts; use the recommended mesh if its budget permits. Otherwise use supported beam/fin estimates or a smaller externally prepared CAD part |
| Zero FEA stress | Declared load, load direction, selected loaded faces and unloaded-result warning |
| Extremely high local stress | Clamp idealization, corner singularities, material/units, mesh refinement and reported element versus averaged nodal values |
| GPU calculation cannot start | NVIDIA driver/device and available VRAM; choose automatic/CPU to inspect the actual fallback |
| Black or failed viewport | Update the graphics driver; inspect `%LOCALAPPDATA%\RocketWorkbench\application.log` |
| Setup did not save | Bottom save status/error banner; correct invalid values and save again |

The [validation record](VALIDATION.md) describes reference and integration checks.
Those checks verify calculations and workflows; they do not establish flight-test
or wind-tunnel agreement for your particular rocket.
