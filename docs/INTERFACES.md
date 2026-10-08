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
* `aero.atmosphere(altitude: float, temperature_delta: float = 0) -> dict`
* `aero.mass_properties(project: Project, configuration_id: str | None = None, time: float = 0) -> dict`
* `aero.analyze(project: Project, conditions: Conditions, configuration_id: str | None = None) -> dict`
* `flight.simulate(project: Project, conditions: Conditions, configuration_id: str | None = None, progress=None, cancelled=None) -> dict`
* `structure.analyze(project: Project, conditions: Conditions, configuration_id: str | None = None) -> dict` (beam/fin estimates)
* `structure.solve_fea(project: Project, component_id: str, conditions: Conditions, options: dict, progress=None, cancelled=None) -> dict`
* `cfd.solve(project: Project, conditions: Conditions, configuration_id: str | None = None, options: dict | None = None, progress=None, cancelled=None) -> dict`

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
CFD: samples [{position:[x,y,z],pressure_pa,velocity:[x,y,z]}],
surface [{position:[x,y,z],pressure_pa}], history, summary, fidelity,warnings,backend.

## HTTP interface (local session, single project)

* GET /api/health -> {status,version,capabilities}
* GET /api/project -> Project; PUT /api/project (Project JSON) -> Project
* POST /api/project/demo -> Project
* POST /api/import/ork (multipart file) -> Project
* POST /api/import/geometry (multipart file, units) -> GeometryAsset, also stores it
* POST /api/import/motor (multipart file) -> list[Motor], also stores them
* POST /api/import/polar (UTF-8 CSV multipart file: mach,cd,cna,cp_m, optional source) -> Project with table bound to selected configuration/geometry
* GET /api/project/download -> complete project JSON attachment
* POST /api/project/load (multipart file) -> Project
* POST /api/geometry/attach -> {component_id,asset_id,transform,geometry_mode}; returns Project
* POST /api/geometry/standalone -> {asset_id}; returns a new CAD-only Project using actual mesh
* GET /api/geometry/properties/{component_id} -> {original,replacement} geometric diagnostics
* GET /api/mesh?original=false -> {components:[{id,name,vertices,faces}]}
* POST /api/analyze -> {conditions,configuration_id?} -> {aero,structure}
* POST /api/jobs -> {kind:flight|cfd|fea|sweep|monte_carlo|comparison,conditions,configuration_id?,options:{}} -> {id,...}
* GET /api/jobs/{id} -> {id,status,progress,message,elapsed_seconds,eta_seconds,result,error}
* POST /api/jobs/{id}/cancel -> job
* GET /api/jobs/{id}/export?format=csv|json|html -> attachment
* POST /api/compare -> {conditions,configuration_id?} -> fast original/replacement comparison

Long comparisons use a `comparison` job with `options.use_flight` and/or
`options.use_cfd`. They retain per-configuration errors and per-basis convergence
status. A supplied polar matching only the replacement geometry is not applied
to the original basis. CFD-to-FEA transfer requires the completed CFD job ID,
numerical convergence and both project and actual mesh signature matches.

FEA options include explicit support axis/side/tolerance, tetrahedron/mesh budgets,
body acceleration and pressure or prescribed traction loading. CFD options
include lengthwise/transverse grid dimensions, cell budget, CFL, flow-through
time, residual tolerance, iteration and elapsed-time budgets. See method docs
and solver argument validation for bounds; a job budget is not a claimed
physical convergence criterion.

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

Current scientific scope: Barrowman small-angle stability and documented Mach
corrections up to 2; passive point-mass trajectory with rail/apogee/main events;
beam/fin calculations and tetrahedral linear static FEA with defined root clamp;
experimental compressible inviscid Cartesian Euler CFD. Euler is NOT RANS or
viscous CFD and does NOT predict skin friction or validated transonic drag.
Explicit unsupported component and solver limitations must be visible.
