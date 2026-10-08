# Development and validation plan

The selected goal is a private-use Windows design tool for passive high-power
rockets up to 12 ft and Mach 2, with single and dual deployment, detailed CAD
replacement, local calculations, GPU graphics and supported numerical GPU paths.
Advanced solvers ship inside one download. The target is transparent engineering
use; no certification, flight-test match or validated arbitrary-CAD transonic
drag claim is implied.

## Implementation sequence

| Phase | Deliverable | Acceptance evidence |
| --- | --- | --- |
| Shared model and imports | SI schemas, OpenRocket hierarchy/configurations, motor curves, STEP/STL, replacement/standalone meshes and supplied coefficient CSV | Import fixtures, malformed input handling, configuration and transform tests; synthetic tutorial readers |
| Fast scientific core | Atmosphere, mass/CG, Barrowman baseline, geometry-bound polar interpolation, scoped drag/loading and beam/fin estimates | Independent atmosphere, geometry/mass and analytical mechanics checks; stale-polar invalidation |
| Flight and studies | Passive rail/coast/recovery trajectory, events, sweeps, seeded Monte Carlo and comparisons | Deterministic runs, recovery/event tests and input limits |
| Numerical solvers | Conservative inviscid flow field; tetrahedral linear elasticity; one-way converged-CFD pressure mapping | Conservation/shock limiting cases; analytical displacement/reaction/residual checks; mapped force/coverage and shape compatibility |
| Local application | Job progress/ETA/cancel, project save/load, data/report export, desktop API | Request/job and project roundtrip tests, integrated smoke check |
| Interface | GPU 3D view, CAD alignment, conditions, numerical field inspection, flight playback and graphs | Type/build checks plus interactive import/simulate/save/playback inspection |
| Windows delivery | Locked native dependencies, frozen app, offline one-download installer | Windows tests, executable smoke, silent install and installed smoke in workflow |

The repository implements these paths with clear method limits. A completed
source implementation is distinct from a validated packaged Windows release.
The release workflow must run on Windows before its artifact is presented as a
working download. Real CUDA execution additionally needs a GPU machine.

## Required release checks

1. Run scientific/reference and importer/API tests on supported Python 3.12.
2. Build the frontend with the committed npm lockfile and fix type errors.
3. Exercise a demonstration and a representative real OpenRocket project,
   checking the import warnings, selected motor curve and recovery configuration.
4. Replace a component with STEP and STL geometry; verify units, alignment,
   mass treatment, project save/reload and original/replacement comparison.
5. Run flight playback, exports, a small CFD job and a component FEA job; inspect
   actual progress, cancellation, method labels and results. Check a supplied
   polar's interpolation and invalidation after shape edits. Exercise a CAD-only
   project with appropriate coefficients and verify CFD-to-FEA mapping coverage.
6. Build the Windows installer, test it on a clean user profile without Python,
   Node.js, Gmsh or the CUDA Toolkit installed, and confirm offline operation.
7. On supported NVIDIA hardware, run the documented numerical cases with CPU and
   GPU backends and compare within meaningful floating-point tolerances.

Automated reference tests are necessary but do not replace physical benchmarks.
The hosted CI's installed smoke test does not prove every viewport feature or
GPU kernel on every driver. Keep those validation gaps explicit.

## Research and accuracy backlog

The first release should not quietly inflate its fidelity. Work requiring
separate engineering validation includes:

- Real-rocket OpenRocket cross-checks and measured flight/wind-tunnel benchmarks
  with complete conditions, motor/recovery data and quantitative error metrics.
- RANS or other validated viscous compressible CFD, boundary layers, turbulence
  closure, improved body-fitted meshing and transonic/shock grid convergence.
- Six-degree-of-freedom flight, attitude and aerodynamic moments, weathercocking,
  damping derivatives, gust spectra and aeroelastic coupling.
- Composite laminates, shell buckling, nonlinear/contact/transient FEA, recovery
  shock and fin flutter with mesh/time-step studies.
- Genuine multistage/cluster/pod event semantics and more complete OpenRocket
  feature parity, tested against real versioned project fixtures.
- Preserved CAD solid topology and richer assembly/material mapping when needed.
- Code signing and longer-lived release delivery when distribution expands.

Solver modules and shared contracts allow these improvements without replacing
the desktop or project/UI model. Add only capabilities backed by implemented
physics, trustworthy input mapping and independent validation evidence.
