# Shared implementation contracts

Python 3.12 backend: FastAPI, Pydantic, NumPy, SciPy, trimesh, cadquery-ocp,
gmsh; desktop shell: PySide6 QtWebEngine. Frontend: React/TypeScript/Vite,
Three.js/react-three-fiber and Recharts. PyInstaller and Inno Setup create a
Windows x64 single-download offline installer. GPU renders the scene. NVIDIA
CuPy can accelerate supported numerical solvers; CPU fallback remains available
and actual execution backend must be displayed. Never promise GPU acceleration
for every solver or certified results.

All internal lengths are metres, masses kg, times seconds, pressures Pa;
angles are degrees. Rocket X axis runs from nose to tail; cross-section is YZ.
Materials use isotropic linear elasticity. UI performs display conversion only.
`rocket_workbench/models.py` defines shared schemas. Coordinate schema changes
across file readers, solvers, API persistence and frontend types.

## Python interfaces

* `imports.import_ork(data: bytes, filename: str = '') -> Project`
* `imports.import_motor(data: bytes, filename: str) -> list[Motor]` (.eng, .rse)
* `geometry.import_geometry(data: bytes, filename: str, units: str = 'mm') -> GeometryAsset`
* `geometry.component_mesh(project: Project, component: Component, original: bool = False) -> trimesh.Trimesh`
* `geometry.project_mesh(project: Project, configuration_id: str | None = None, original: bool = False) -> trimesh.Trimesh`
* `alignment.propose_alignment(project: Project, component: Component, asset: GeometryAsset, options: AlignmentOptions | None = None) -> dict`
* `fea_setup.preflight(project: Project, component_id: str, options: dict | None = None) -> dict`
* `backenddiagnostics.cuda_diagnostics() -> dict`
* `motor_catalog.MotorCatalog` provides `search`, `curves`, `preview` and `reviewed_motor`; only requested lookup/preview performs network I/O
* `aero.atmosphere(altitude: float, temperature_delta: float = 0) -> dict`
* `aero.mass_properties(project: Project, configuration_id: str | None = None, time: float = 0) -> dict`
* `aero.analyze(project: Project, conditions: Conditions, configuration_id: str | None = None) -> dict`
* `flight.simulate(project: Project, conditions: Conditions, configuration_id: str | None = None, progress=None, cancelled=None) -> dict`
  Dispatches `Conditions.flight_model` between legacy `point_mass` and experimental
  `rigid_body`. Both use `WindField`, configured inflation and causal `wind_events`.
* `flight_structure.analyze_flight_structure(project, trajectory, configuration_id=None, options=None, progress=None, cancelled=None) -> dict`
  Independent original-fin transient beam pass; immutable input, aligned nullable
  rows, full FEM/modal metadata, coverage, reactions, bending stresses and energy.
* `structure.analyze(project: Project, conditions: Conditions, configuration_id: str | None = None) -> dict` (beam/fin estimates)
* `structure.solve_fea(project: Project, component_id: str, conditions: Conditions, options: dict, progress=None, cancelled=None) -> dict`
* `cfd.solve(project: Project, conditions: Conditions, configuration_id: str | None = None, options: dict | None = None, progress=None, cancelled=None, telemetry=None, freestream_provider=None) -> dict`

Callbacks: `progress(fraction: float, message: str)`; `cancelled() -> bool`.
Raise ValueError for invalid physical inputs and RuntimeError for unavailable
capabilities. Return JSON-serializable dicts, including `fidelity`, `warnings`,
and numerical `backend` where relevant. No fabricated pressure/stress fields.

Aerodynamics required output: mass_kg, cg_m, cp_m, stability_calibers,
reference_area_m2, cd, drag_n, normal_force_n, dynamic_pressure_pa, mach,
speed_m_s, density_kg_m3, components (per-component coefficient/force/mass).
Flight output: trajectory (rows: time, altitude, east, north, velocity,
acceleration, mach, dynamic_pressure, mass, cg, cp, stability, drag, thrust,
stress, phase), events (name,time,index), summary, fidelity, warnings.
Structure estimates: components [{component_id,name,stress_pa,deflection_m,
safety_factor, ...}], warnings, fidelity. FEA: vertices, tetrahedra,
displacements, von_mises_pa, summary, fidelity, warnings, backend.
CFD: samples [{position:[x,y,z],pressure_pa,velocity:[x,y,z],density_kg_m3,mach}],
surface [{position:[x,y,z],pressure_pa,pressure_coefficient,normal:[x,y,z]}],
flow_grid, history, summary, fidelity,warnings,backend; optional transient
topology/frames. Euler is default; experimental Laminar returns additional
actual viscous/shear/total traction fields described below.

## HTTP interface (local session, single project)

* GET /api/health -> {status,version,capabilities}; capabilities includes gpu_compute, gpu_backend and cached gpu_diagnostics
* GET /api/project -> Project; PUT /api/project (Project JSON) -> Project
* PUT /api/project/settings -> {project_id,settings:AnalysisSettings}; atomically patches current settings, rejects a stale project ID
* POST /api/project/demo -> Project
* POST /api/import/ork (multipart file) -> Project
* POST /api/import/geometry (multipart file, units) -> GeometryAsset, also stores it
* POST /api/import/motor (multipart file) -> list[Motor], also stores them
* POST /api/motors/search -> {query,manufacturer?,limit?}; bounded ThrustCurve.org search results
* GET /api/motors/{motor_id}/curves -> available curve/source records
* POST /api/motors/preview -> {motor_id,simfile_id}; parsed curve, source/provenance and review_token, without changing the project
* POST /api/motors/import -> {project_id,review_token}; returns Project containing the reviewed motor, without assigning it to a configuration
* POST /api/import/polar (UTF-8 CSV multipart file: mach,cd,cna,cp_m, optional source) -> Project with table bound to selected configuration/geometry
* GET /api/project/download -> complete project JSON attachment
* POST /api/project/load (multipart file) -> Project
* POST /api/geometry/alignment -> {component_id,asset_id,axis?,reverse?,fit_length?,anchor?}; read-only placement proposal and SI bounds/interface diagnostics
* POST /api/geometry/attach -> {component_id,asset_id,transform?,geometry_mode?,auto_align?,alignment_options?}; returns Project
* POST /api/geometry/standalone -> {asset_id}; returns a new CAD-only Project using actual mesh
* GET /api/geometry/properties/{component_id} -> {original,replacement} geometric diagnostics
* GET /api/mesh?original=false -> {components:[{id,name,vertices,faces}]}
* POST /api/analyze -> {conditions,configuration_id?} -> {aero,structure}
* POST /api/fea/preflight -> {component_id,options:{mesh_size?,max_elements?}}; actual-solid validity, placed bounds/material, sizing recommendations and resource errors without volume meshing
* POST /api/jobs -> {kind:flight|cfd|fea|sweep|monte_carlo|comparison,conditions,configuration_id?,options:{}} -> {id,...}
* GET /api/jobs/{id} -> {id,status,progress,progress_basis,message,elapsed_seconds,eta_seconds,result,error}; lifecycle completion does not imply CFD convergence
* GET /api/jobs/{id}/project -> immutable input-project JSON attachment with selected configuration, conditions and solver options
* POST /api/jobs/{id}/cancel -> job
* GET /api/jobs/{id}/export?format=csv|json|html -> attachment
* POST /api/compare -> {conditions,configuration_id?} -> fast original/replacement comparison

Long comparisons use a `comparison` job with `options.use_flight` and/or
`options.use_cfd`. They retain per-configuration errors and per-basis convergence
status. A supplied polar matching only the replacement geometry is not applied
to the original basis. CFD-to-FEA transfer requires the completed CFD job ID,
numerical convergence and both project and actual mesh signature matches.
Cancelled CFD jobs can retain actual partial fields and export them as JSON,
CSV or HTML. Their lifecycle status remains `cancelled`; retained partial data
does not make them an eligible FEA pressure source. Transfer still requires a
completed, numerically converged CFD job with matching geometry.

FEA options include explicit support axis/side/tolerance, tetrahedron/mesh budgets,
body acceleration and pressure or prescribed traction loading. CFD options
include lengthwise/transverse grid dimensions, allocation budget, physics model,
CFL, residual tolerance, steady/transient mode and requested transient physical
duration. Wall-clock, iteration and domain-crossing stopping budgets are no
longer enforced. See [CFD.md](CFD.md) and solver validation for bounds;
numerical convergence does not establish physical accuracy.

CAD alignment options are `axis:"auto"|"x"|"y"|"z"` (default `auto`),
`reverse:false`, `fit_length:false`, and `anchor:"start"|"center"` (default
`start`). Alignment uses one selected reference part; repeated component placement
is applied afterward by the geometry layer. The response includes the proposed
component-local `transform`, actual `aligned_bounds_m`, source/target dimensions,
axis/direction method, scale, warnings and adjacent axial separation diagnostics.
Default rigid placement preserves source dimensions. Explicit fit applies one
uniform scale; no source mesh edit, material union or structural joint is inferred.
With `auto_align:true`, attachment derives this transform from `alignment_options`
rather than using a supplied manual transform.

CFD `physics_model` is `euler` (default) or `laminar`. Euler uses inviscid slip
walls. Experimental Laminar adds conservative Newtonian viscous momentum/energy
flux, Sutherland air viscosity and Fourier conduction with Prandtl number 0.72.
Its stationary no-slip wall is adiabatic: wall mass/energy flux is zero and
kinetic dissipation becomes internal energy. Neither model includes transition,
turbulence closure or wall functions. Acoustic plus viscous/thermal rates set
the Laminar explicit CFL step; a separate diffusion-only bound is insufficient.

CFD `mode` is `steady` (default) or `transient`. Steady runs stop only at
numerical convergence or cancellation. Transient runs integrate positive
`duration_s` or stop on cancellation. Neither mode enforces old wall-clock,
step-count or domain-crossing budgets. Cell-allocation limits, cancellation and
numerical validity checks remain. Transient job options can select
`transient_source:launch` or `fixed`; launch uses a matching `flight_job_id` or
calculates a current launch, with optional `flight_start_s`/`flight_end_s`.
`snapshot_count` bounds saved real display states independently of integration.
Steady job progress uses `convergence_unknown`, always without a finite percentage;
transient progress measures integrated physical time. Structured telemetry
supports measured-throughput ETA or a qualified tentative convergence range.
`summary.status`, `converged`, force-result validity and warnings distinguish an
actual partial field, completed transient experiment and converged steady field.
Convergence remains numerical steadiness, not mesh/domain or physical validation.
Job polling exposes the same mode distinction; ordinary jobs use
`completion_fraction`. Transient output adds shared `transient.topology` and
bounded actual-time `transient.frames` with field arrays and frame-specific
freestream pressure/velocity, altitude and flight time. No intermediate flow
states are inferred by the frontend.

Laminar steady convergence additionally requires area-weighted full wall-viscous
traction steadiness (`wall_viscous_residual`) using its reported independent
`viscous_convergence_scale_pa`. Total pressure-plus-viscous force/moment rates
also participate. All five rates must remain below tolerance for 20 steps after
the minimum flow time; the convergence ETA requires decline in every active
rate, including viscous traction.

Compatibility fields `summary.force_n`, `pressure_drag_n` and
`moment_about_origin_nm` remain **pressure-only**. Laminar adds
`viscous_force_n`, `viscous_drag_n`, `viscous_moment_about_origin_nm`,
`total_force_n`, `total_drag_n`, `total_moment_about_origin_nm`,
`max_wall_shear_stress_pa`, `wall_heat_flux_w_m2:0`,
`viscous_force_steady` and `viscous_force_validated:false`.
Each Laminar surface row additionally contains `viscous_traction_pa:[x,y,z]`,
tangential `shear_traction_pa:[x,y,z]`, `shear_stress_pa`,
`total_traction_pa:[x,y,z]` and `wall_fluid_temperature_k`.
Normals point from solid to fluid: total traction is
`-(pressure_pa-freestream_pressure_pa)*normal + viscous_traction_pa`.
This fluid-wall traction is not material/structural stress.

Laminar transient frames carry corresponding force/drag/moment values and
`surface_viscous_traction_pa`, `surface_shear_traction_pa`,
`surface_shear_stress_pa`, `surface_total_traction_pa` and
`surface_wall_fluid_temperature_k` arrays aligned with shared surface topology.
The renderer selects actual stored frames rather than borrowing final-frame
loads. `summary.transport` contains initial-freestream viscosity, kinematic
viscosity, conductivity, Prandtl number, reference length/Reynolds number and
`estimated_numerical_to_molecular_diffusivity_ratio`. It explicitly identifies
`reference_time_s:0`; changing launch boundaries can subsequently differ.
The ratio is the characteristic first-order Rusanov estimate
`0.5*(sound_speed+speed)*maximum_spacing/(mu/rho)`, not an error bound or
proof of boundary-layer resolution. Numerical diffusion can dominate molecular
transport on typical rocket grids; viscous loads remain unvalidated.

CFD-to-FEA transfer remains pressure-only for either physics model. It omits
computed viscous/shear traction and records that limitation. Both models share
the exterior-connected-air flow mask and preserve source CAD, mass and FEA
geometry. Sealed interiors generate no fluid-wall traction faces.

Preflight `can_run` concerns current solid-validity/thickness/resource checks,
not validated FEA loading/supports. Original thin parts retain mesh size no
greater than thickness/2. Imported CAD thickness is unknown and a scale-based
suggestion does not guarantee bending resolution. Counts are estimates; native
meshing still enforces the actual element cap. The app provides neither curved-shell
FEA nor an in-app region-cutting tool.

Motor service requests use a fixed HTTPS provider and bounded responses, not
arbitrary user URLs. Only designation/manufacturer or selected provider IDs are
sent; project geometry is not uploaded. Preview tokens are session-local and
import rejects a changed project ID. A motor's saved provenance includes provider,
provider IDs, declared source/license, fetch time and raw-curve SHA-256. Provider
labels are attribution, not independent certification or applicability checks.

CSV exports remain rectangular tables. Dedicated `_result_*` columns in the
first data row retain the method, backend, warnings, validity, run inputs and
summary; those columns are blank in later rows. Nested metadata uses JSON. Keep
that row and these columns with the exported dataset when sharing engineering
results. Text beginning with spreadsheet formula characters is prefixed with
an apostrophe; numeric negative quantities remain ordinary numbers. JSON and
HTML exports preserve the complete result structure.

All /api requests require header X-Rocket-Session when desktop token enabled;
localhost development disables token by default. Development API defaults to
127.0.0.1 port 8765; Vite proxies /api. Desktop selects a free loopback port and
serves bundled web/dist using that API server.
Do not create localhost preview links during cloud onboarding.

UI workspaces: design (component tree/properties/CAD alignment/standalone project/
supplied polar), aero (conditions,
force/CG/CP), flight (launch job + playback/timeline/events/graphs), structures
(beam estimates + component FEA), CFD (grid/iterations/fidelity/progress), studies
(parameter/wind sweep, Monte Carlo and comparisons). Persist project incl meshes.

## Portable settings and run provenance

`Project.analysis_settings` stores validated conditions, extensible JSON option
dictionaries for flight/CFD/FEA/studies, and the study mode. Older schema-1 projects
receive defaults; saving with this version includes these fields. The UI restores
and autosaves them, and flushes pending settings before saving a project or
starting a calculation. Display units never change their SI values. Settings
patches operate on the latest project and include its ID, so a delayed save from a
previous project cannot overwrite a newly imported project.

Jobs retain an input project independently of later edits. Progress polling omits
that potentially large snapshot. Download it with `/jobs/{id}/project` while the
job remains among the twelve retained runs. Results include application version,
UTC submission timestamp, actual conditions/options and `project_sha256`. The
digest covers the input project's complete JSON model, UTF-8 encoded with sorted
keys and compact `(',', ':')` separators; whitespace in a downloaded file does
not affect that canonical digest. It includes materials, motor curves, geometry
assets, transforms and settings, while the separate geometry signature binds
only aerodynamic shape. These records support reproducibility, not physical
validation. Jobs/results remain session-local; export them before closing.

`Conditions` adds `flight_model:point_mass|rigid_body`,
`initial_angular_velocity_body_rad_s`, `wind_model:legacy_gust|dryden`,
`turbulence_length_scale_m`, fixed `turbulence_transport_speed_m_s`,
`turbulence_sample_interval_s`, `wind_reference_height_m`,
`wind_shear_exponent` and ordered nonoverlapping `wind_events`.
An event contains `time_s,wind_speed,wind_direction,turbulence,transition_s` and
optional `temperature_delta`; null temperature preserves the preceding offset.
`FlightConfiguration` adds drogue/main inflation durations, optional supplied Cmq
and a symmetric positive-definite complete dry inertia tensor with required
source text. See [PHYSICS.md](PHYSICS.md) for frames and physical assumptions.

Flight job `options.structural_mode` is `quasi_static` or `dynamic_fins`.
Dynamic fin options/limits are in [STRUCTURAL.md](STRUCTURAL.md). The job attaches
aligned `dynamic_stress`/`dynamic_structural_components` without rewriting default
estimates and retains `dynamic_structural_analysis` metadata. Completion of the
flight job is separate from structural coverage or an unfinished work-limited
structural pass; unsupported fields remain null. Quaternion/rate/inertia/moment
fields are present for rigid-body rows only, not fabricated for point-mass runs.

Pressure-transfer FEA also records `inputs.cfd_source`, including the source run's
inputs and mesh/wall-field hashes. A run input project contains the source job ID,
not its complete solved CFD field. That ID expires across sessions: export the
source CFD JSON for traceability and rerun its recorded inputs before pressure
transfer in a new session. CUDA and sparse-mesher results can vary with hardware
and mesh generation; a matching input hash does not promise bitwise equality.

Studies preserve each row's method, warnings and validity rather than dropping
the underlying solver's limits. Sweeps share a gust seed to change one input at
a time; Monte Carlo uses its recorded study seed for sampling and distinct gust
seeds per sample. Flight speed/Mach are integrated outputs and cannot be swept as
independent flight inputs. Static angle-of-attack flight sweeps vary the structural
reference loading angle; rigid-body incidence is an integrated result rather than
an independently prescribed static angle.
Failed samples are reported and excluded from statistics. Flight rows preserve
completion, recovery, termination and statistics-eligibility status. Incomplete
histories use `observed_` metric names and never enter completed-flight statistics.
Flights outside their operating/static-stability limits are also excluded;
`sample_counts` and per-metric counts describe the actual contributing population.
Partial comparison differences are separately labelled `observed_flight_deltas`.
Dynamic fin jobs accept `time_integrator:exact_foh` (default) or legacy `newmark`;
the selected method and full-basis model remain recorded in structural metadata.

Current scientific scope: Barrowman small-angle stability and documented Mach
corrections up to 2; passive point-mass or small-angle quaternion rigid-body
trajectory with rail/apogee/main events, Dryden/shear and causal wind schedules;
beam/fin estimates, original-fin dynamic beam FEA and tetrahedral linear static
FEA with defined root clamp;
experimental compressible Cartesian CFD with default inviscid Euler and optional
resolved laminar Navier–Stokes. Neither CFD model is RANS/LES or predicts
validated transonic/high-Reynolds-number rocket drag. Euler omits skin friction;
Laminar molecular transport does not establish boundary-layer resolution.
Explicit unsupported component and solver limitations must be visible.

Plate FEA uses the existing fea job/preflight endpoints with element_model:plate.
See STRUCTURAL.md for the strict geometry/material/load scope. Results expose
mesh_kind:plate_midsurface, plate_quads and triangulated surface_faces, with empty
tetrahedra, world vertices/displacements and recovered nodal stresses. Per-fin
loads, bases, root nodes, local slope rotations, Gauss stresses, balance and
energy are retained in fins; conventions distinguish these from solid fields.
The renderer uses actual surface_faces for this mesh kind. Plate requests remove
inactive solid clamp/traction/CFD controls and never transfer CFD pressure.
