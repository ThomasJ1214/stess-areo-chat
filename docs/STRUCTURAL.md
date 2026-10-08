# Structural calculations and their limits

All values are SI internally. Rocket X runs from nose to tail. Positive Y is
the pitch-normal direction in the aerodynamic model; Z is its side direction.
The solver's reported material, support, loads, mesh size, execution backend,
and warnings are part of a result. A colour map alone is not validation.

## Fast tube and fin estimates

`structure.analyze` calls the same aerodynamic analysis used by the aero panel
and uses its component force resultants, not a decorative stress field.

For a tube with outer radius R and inner radius r = R − thickness:

* Area A = π(R² − r²).
* Diametral second moment I = π(R⁴ − r⁴)/4.
* The aerodynamic load path is a **tail-supported cantilever**. At each tube's
  aft section, noseward component forces contribute moment F × axial lever arm.
  Pitch and side moments combine by their Euclidean magnitude.
* Maximum axial surface stress estimate is |M|R/I + |axial aerodynamic force|/A.
* The displayed displacement estimate is ML²/(2EI) for that local tube segment
  under equivalent constant moment. It is not an assembled whole-rocket tip
  deflection, and sections/joints are not coupled by a stiffness matrix.

For a finset, the aerodynamic resultant is shared equally between fins. Each
fin becomes a constant-chord strip with width (root chord + tip chord)/2,
span L, and thickness t. I = width × t³/12. The span load is uniform:

* Root moment M = F L/2 per fin.
* Root bending stress = M(t/2)/I.
* Root strip shear estimate = 1.5 F/(width × t).
* Equivalent isotropic von Mises estimate = √(bending² + 3 shear²).
* Tip displacement = F L³/(8 EI).

These are Euler–Bernoulli idealizations, not a laminate, plate, attachment,
flutter, buckling, or structural dynamics analysis. Sweep and taper are reduced
to an equivalent strip. Individual fins do not receive independent wind loads.
The front-end distinguishes unsupported parts with `supported:false`; a zero
value on such a row does not mean the part is safe. Detailed CAD replacements
are not reduced to a bounding-box beam. Use actual solid FEA for those parts.
Zero-thickness or invalid annular wall dimensions are reported on the affected
part without hiding structural estimates for the other physical components.

The strength ratio is supplied material strength divided by predicted stress.
For fiberglass/carbon, the material is an **isotropic engineering surrogate**;
von Mises and a single strength value do not establish laminate failure margin.
Use tested material/laminate allowables and an appropriate composite solver.

## Flight stress playback

`flight_stress_model` precomputes stress/displacement sensitivities at the
launch conditions' reference Mach and incidence. `evaluate_flight_stress`
scales these with the current flight dynamic pressure, then adds longitudinal
tube inertial stress |specific acceleration| × forward component mass/A.

Specific acceleration is the non-gravitational acceleration magnitude. A body
in ideal free fall does not acquire fictitious gravity-induced structural stress.
The coefficient model uses component masses; it does not reconstruct the motor
thrust path or its changing propellant distribution. The recorded stresses are
**quasi-static pressure-scaled beam/fin estimates**, not a new FEA solve at each
frame. Reference incidence/Mach coefficients are held constant even when flight
Mach changes. Flight playback therefore does not establish transient structural
strength through transonic flight or recovery opening shock.

## Actual solid finite element analysis

`structure.solve_fea` runs linear static 3D elasticity on the selected component
mesh, after CAD scaling/alignment and OpenRocket component placement.

1. Check that every actual triangle solid is watertight, consistently outward
   oriented, and has positive volume. Open STL surfaces, intersecting/self-invalid
   geometry, zero-thickness shells, and independent inner cavity shells are not
   a supported solid model. A closed annular tube with joined end rims is supported.
2. Transfer actual triangle coordinates to Gmsh discrete surfaces, classify and
   parametrize them, and mesh their enclosed volumes. The solver never substitutes
   a bounding box or convex hull. Curved imported CAD has already been tessellated;
   volume meshing retains that surface approximation, not the original CAD B-rep.
3. Generate four-node, first-order tetrahedra. Each element uses affine shape
   functions, constant strain, B from their physical-coordinate derivatives
   evaluated relative to an element vertex (to avoid a distant CAD origin
   degrading matrix precision),
   and Ke = volume × Bᵀ D B. D is the 3D isotropic elastic tensor with
   λ = Eν/((1+ν)(1−2ν)) and μ = E/(2(1+ν)). Assemble a sparse global stiffness
   matrix and impose zero displacement at the selected root nodes.
4. Integrate each face's pressure/traction as its resultant divided equally
   between its three nodes; integrate constant body acceleration as density ×
   volume × acceleration/4 per tetrahedral node. Solve Kff uf = ff.
5. Recover constant element stress D B ue and von Mises stress. The visualized
   **nodal** values are adjacent-element volume-weighted stress averages.
   Raw element von Mises values are also returned.
6. Report free-DOF residual, force balance, moment balance, clamp reactions,
   material, element count, actual mesh volume/mass, and displacements. Results
   with free-DOF residual above 10⁻⁵ are withheld.

The summary also reports elastic `strain_energy_j` = ½uᵀKu and
`external_work_j` = uᵀf. They satisfy 2U = uᵀf for these zero-displacement
supports and linear static loads. Here `external_work_j` is the force/displacement
dot product at full load; the work of a quasistatically ramped load is U.
Surface and body force resultants are listed separately. Returned applied and
reaction moments are about the project origin; the moment balance error is
evaluated about the reported mesh-centroid `moment_balance_reference_m` to
avoid cancellation for off-origin CAD. The original triangle-surface volume and
tetrahedral material volume are compared, with a warning above 1% difference;
this diagnostic is not an automated convergence study.

Multiple disconnected solids are allowed only if each has at least three
noncollinear fully fixed root nodes. Contact, adhesion, fillets, fasteners, and
assembly connections are not inferred from touching surfaces. A finset can use
its procedural radial roots to give each fin a real support.
An imported asset flagged as open or as having ambiguous overlapping material
volume is rejected before meshing, even if all of its separate shells are
topologically closed. Repair or union the actual CAD solids first.

### Supported options

| Option | Meaning and default |
| --- | --- |
| `component_id` | Required selected component identifier in the job options. |
| `mesh_size` | Nominal maximum tetrahedral edge size in metres. Default component scale/12, additionally capped at thickness/2 for procedural components. |
| `max_elements` | Default 100,000; accepted 20–300,000. An estimate rejects an excessive job before meshing, and actual count is checked afterward. |
| `mesh_timeout_seconds` | Native mesh-process deadline, default 120 s; range 5–900 s. |
| `backend` | `auto`, `cpu`, or `cuda`; default `auto`. |
| `clamp_type` | `plane` (default), or `radial_root` for original procedural finsets. |
| `clamp_axis` | `x` (default), `y`, or `z`, for a plane clamp. |
| `clamp_side` | `min` (default) or `max` coordinate extent. |
| `clamp_tolerance` | Root selection distance in metres; default max(scale × 10⁻⁷, mesh size × 0.08). Verify it selects a genuine support region. |
| `load_mode` | `aero_pressure` (default), `uniform_pressure`, `traction`, or `cfd_pressure`. |
| `load_pressure_pa` | Nonnegative pressure scale; default q = ρV²/2 at the chosen atmosphere and speed/Mach. |
| `traction_pa` | Finite [X,Y,Z] surface traction in Pa, applied to the opposite end plane in `traction` mode. Default [pressure scale,0,0]. |
| `acceleration_m_s2` | Signed [X,Y,Z] body-force acceleration, default [0,0,0]. To approximate D'Alembert inertial loading, enter the negative of the actual component acceleration; gravity must also be considered according to the chosen frame. |

The default support is the **min-X surface, all displacement DOFs fixed**. It
is a visible modeling choice, not an automatically discovered physical mount.
For swept fins, min-X can select an edge rather than the fin root; use
`clamp_type:"radial_root"`. This selects each fin's actual tangent root plane
by its procedural azimuth, including finite-thickness edges and canted root
points. Interior tabs are fixed as embedded supports. For arbitrary CAD,
choose a justified plane/tolerance.
The GUI's displacement scale changes display only; physical results stay in metres.

`aero_pressure` uses the shared body-frame mean freestream (including lateral
wind) and q = ρ|relative flow|²/2. Wind direction is a toward angle: 0° is +Y,
90° is +Z. Specified Mach sets the main stream speed before lateral wind is
added. Turbulent time-varying loads are not resolved by this static model.
It uses Cp = 2 max(0, −n·flow)² and p = q Cp on windward faces,
with force −p n. This is an explicitly labeled **projected Newtonian-style load
surrogate**, not the aerodynamic component-force calculation, CFD coupling, or
a validated Mach-2 surface-pressure prediction. Modified Newtonian/stagnation
pressure, shock fitting, viscous skin forces, and suction are absent. This
convenient load illustration is especially limited in subsonic/transonic flow.
Use prescribed, benchmarked loading for an engineering structural decision.

`uniform_pressure` loads every closed face, including hollow-tube interior
faces. It is not a differential internal/external pressure-vessel model.
`traction` is useful for analytical bar benchmarks and known end loads.
Nonzero prescribed traction requires actual boundary faces at the selected
opposite end; selecting a curved endpoint or only an edge fails explicitly.
Loads and support options are validated before native meshing. An explicit zero
pressure is preserved and an unloaded solution is labeled as such; zero stress
is not a strength demonstration. FEA body loads use the chosen density and
tetrahedral volume, rather than distributing a project component mass override.

`cfd_pressure` connects a completed, pressure-force-converged CFD job to the
selected actual component geometry. The job manager checks project/configuration
consistency before forwarding its samples. This is **one-way Euler pressure
loading**, not fluid-structure interaction or validated viscous CFD. The nearest
normal-compatible wall sample (outward normal dot product ≥ 0.25) is selected
within a cell-scaled ellipsoid: √Σ(Δcoordinate/cell spacing)² ≤ 1.5.
This keeps fine radial resolution separate from coarse axial resolution,
preventing transfer from the opposite outside wall onto a hollow tube's inside
wall. If the initial 16 nearby samples all face the wrong way, the transfer
searches the full permitted neighborhood for a compatible normal before marking
the face as unmapped. This does not enlarge the transfer cutoff. Its gauge pressure
is absolute wall pressure minus freestream pressure; negative suction is kept.
Unmatched faces get zero gauge pressure, and the result reports mapped area
fraction and mean/max transfer distances. Enclosed inner surfaces should not
receive the outside pressure accidentally, hence normals are required.

The API passes `cfd_surface` rows with `position`, `pressure_pa`, and `normal`,
`cfd_converged:true`, `cfd_freestream_pressure_pa`, `cfd_cell_spacing_m:[dx,dy,dz]`,
`cfd_fidelity`, and `cfd_warnings`. `cfd_max_transfer_distance_m` can override the
distance cutoff with an explicit justified Euclidean value; a large override
can cross opposite walls and must be inspected carefully. The summary includes
`cfd_pressure_transfer` with coverage and distance metrics. Nearest transfer is
not force-conservative: check the mapped force resultant and refine the CFD
grid and structural mesh. Pressure-force steadiness alone does not establish
physical/grid validation or correct stagnation/shock resolution.

### Mesh quality, cancellation, and numerical backend

First-order solid tetrahedra need refinement to represent bending. Procedural
thin components require mesh size ≤ thickness/2. Whole 12 ft thin rocket bodies
will often exceed the safe volume-element budget; the solver reports this
rather than showing a coarse misleading stress image. A dedicated shell solver
would be the appropriate future extension. Imported CAD wall thickness cannot
be inferred reliably from an arbitrary triangle surface: the user must choose
an adequate mesh and demonstrate convergence, particularly for hollow parts.

Gmsh runs in an isolated spawned worker process. The job checks cancellation
while that worker runs and terminates it at its deadline, including native
mesher failures. Assembly, surface-load integration, stress recovery and extended
pressure-transfer searches also check cancellation regularly. Sparse assembly
buffers are released before solving to reduce peak memory use.
The CPU direct sparse solve is a bounded monolithic operation; cancellation
during it takes effect after the solve returns. Packaged Windows entrypoints
call `multiprocessing.freeze_support()` to support this worker.

CPU execution uses NumPy/SciPy sparse direct solution. If a working NVIDIA
CUDA/CuPy installation is available, `auto` uses float64 CuPy sparse conjugate
gradient with Jacobi preconditioning. It checks the same equilibrium residual.
CUDA assembly and element stress recovery remain on CPU; only the linear solve
is accelerated. An explicit `cuda` request fails if unavailable instead of
silently claiming GPU execution. The result records the executed backend.

Do not rely on a single mesh. Refine and compare displacement, strain energy,
and stress away from clamps/sharp reentrant corners. The present solver does
not perform an automated convergence study. Stress singularities at ideal
supports/sharp corners can increase with refinement and are not design allowables.
Near-incompressible materials (ν > 0.45) can lock in linear tetrahedra; the solver
warns. Deformation exceeding 5% of component scale and supplied strength
exceedance also produce warnings, not simulated nonlinear failure.

## Validation included in the repository

`tests/test_structure.py` verifies:

* Annular section inertia/area and Euler–Bernoulli tip-load beam formulas.
* A real six-tetrahedron uniaxial patch under exact face traction with minimal
  constraints allowing Poisson contraction: displacement and all element stresses
  match the affine analytical solution, and forces/reactions balance.
* A hydrostatic-pressure patch matches exact isotropic compression, near-zero
  von Mises stress, and analytical elastic energy; force work satisfies 2U = uᵀf.
* A fully clamped elastic solid preserves displacement rotation, von Mises stress
  and energy under a 3D rigid alignment with an off-origin CAD translation.
* Body force proportional to actual tetrahedral volume, not surface area.
* Positive elastic energy, invalid/degenerate mesh rejection, and cancellation.
  Fractional connectivity indices and nonfinite constitutive data are rejected.
* Gmsh tetrahedral volume of a non-cubical tetrahedral surface equals its actual
  solid volume, not its six-times-larger bounding box.
* Full imported-solid FEA with a clamped end and end traction agrees with long-bar
  axial displacement within 6% (the full clamp intentionally constrains local
  Poisson contraction); mesh volume and applied face force are checked.
  A second real mesh/solve verifies CAD scale, 90° rotation, local translation,
  component placement, scaled mass and the applied moment about the project origin.
* Quasi-static flight stress is zero unloaded, scales with pressure, and includes
  longitudinal specific acceleration loading.
* CFD pressure transfer subtracts freestream pressure, preserves negative gauge
  suction, and rejects unconverged or geometrically remote samples.
* Static pressure loading at zero axial speed and nonzero lateral wind matches
  the shared freestream dynamic pressure and declared Cp=2 crosswind-face force.
* A finite-thickness canted finset clamps all procedural root-plane nodes;
  anisotropic CFD transfer rejects opposite-wall samples across a hollow bore.
  A matching normal beyond 16 incompatible nearby samples still transfers pressure.
* A zero-thickness OpenRocket reference part reports unsupported structural
  calculations while other physical parts continue to analyze.
* Invalid support/load options, extremely small mesh requests and unverified
  enclosed material volumes fail before invoking the native mesher. Deliberately
  unloaded solid solves preserve zero pressure and an explicit warning.

These establish implementation consistency for these cases, not validation of
arbitrary rocket structures, CAD topology, aerodynamic pressure predictions,
composite allowables, or every GPU/driver combination.

## References

* S. P. Timoshenko and J. M. Gere, *Mechanics of Materials*: Euler–Bernoulli
  beam, annular section and elementary shear formulas.
* K. J. Bathe, *Finite Element Procedures* (1996), linear elastic continuum
  formulation and displacement-based tetrahedral elements.
* C. Geuzaine and J.-F. Remacle, "Gmsh: A 3-D finite element mesh generator with
  built-in pre- and post-processing facilities," *International Journal for
  Numerical Methods in Engineering* 79 (2009), 1309–1331,
  [doi:10.1002/nme.2579](https://doi.org/10.1002/nme.2579).
* [Gmsh tutorial t13: discrete surface remeshing](https://gmsh.info/doc/texinfo/gmsh.html#t13)
  and [Gmsh Python API](https://gmsh.info/doc/texinfo/).
* J. D. Anderson, *Hypersonic and High-Temperature Gas Dynamics*: Newtonian
  impact theory; cited to identify the surrogate and its limitations, not to
  validate it for the requested Mach-2 rockets.
* [SciPy sparse linear algebra](https://docs.scipy.org/doc/scipy/reference/sparse.linalg.html)
  and [CuPy sparse conjugate gradient](https://docs.cupy.dev/en/stable/reference/generated/cupyx.scipy.sparse.linalg.cg.html).
