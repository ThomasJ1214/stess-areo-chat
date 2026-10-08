# Validation checkpoint

Recorded 2026-10-08 during the version 0.1.1 review in the Linux cloud workspace.
Version 0.1.1 also passed checks on GitHub's Linux/Windows runners. All checks
use Python 3.12 and the pinned dependency specifications. Passing these
checks establishes tested implementation behavior, not certification or agreement
with a real rocket's flight/wind-tunnel measurements.

| Check | Result at this checkpoint | What it establishes |
| --- | --- | --- |
| Python suite | **227 tests passed** | Reference/limiting cases, importer and geometry handling, flight events, project/API behavior, scientific solvers and integration safeguards |
| Frontend unit suite | **14 tests passed** | Unit/display bounds, editable numbers, settings restoration, FEA load-option filtering, vector direction and geometry fitting |
| Frontend production build | Passed | Type checking and bundled frontend compilation |
| Core executable smoke | Passed on Linux from source | Real Open CASCADE solid construction, Gmsh initialization, original rocket meshing, aerodynamic analysis and complete synthetic flight |
| Solid FEA checks | Passed on Linux/CPU | Actual Gmsh tetrahedral meshing and sparse elasticity, analytical bar mechanics, reactions/residuals and pressure-transfer checks covered by the suite |
| Native desktop smoke | Passed with Qt software WebGL on Linux | Actual desktop window, rendered interface/WebGL, authenticated API health and loaded project through the embedded page; hardware graphics performance is not established |
| Full browser workflow | Passed with Chromium software WebGL on Linux | Actual flight/playback/CSV, three-point sweep, original/current flight comparison, STEP attachment/project roundtrip, CAD-only STL, genuinely converged CFD, pressure-transfer FEA/deformation and upstream ORK configuration selection; no external page requests or JavaScript errors |
| Tutorial assets | Passed through actual readers/API | Saved project, synthetic ENG, STL and STEP dimensions/volume, coefficient CSV import and interpolation |
| Windows installer | Version 0.1.1 passed | Locked dependency installation, tests, frozen executable engineering smoke, Inno Setup installer, silent user-local installation, installed engine and installed native desktop/authenticated API/WebGL checks |
| NVIDIA numerical backend | **Unverified on physical hardware** | CuPy/CUDA packaging and fallback logic do not establish GPU execution, numerical agreement or performance on a user's driver/device |

The Python suite includes independent analytical cases and conservation/positivity
checks; see [PHYSICS.md](PHYSICS.md), [CFD.md](CFD.md) and
[STRUCTURAL.md](STRUCTURAL.md) for their meaning and physical limits. Counts are a
checkpoint, not a promise that future revisions always have the same test count.

The version 0.1.1 [cross-platform test workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37811145726)
and [Windows installer workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37811145867)
passed their engineering, browser, packaging and installed-app checks for source commit
`d5a0131ab612870878f95ed8328f3de7951419ef`. The installer artifact is approximately
1.5 GB and includes an executable checksum and dependency/source manifest.
The Windows hosted runner tested software WebGL and CPU numerical execution;
it did not test a physical NVIDIA GPU or a fresh consumer PC. Documentation-only
commits after this source revision do not imply the binary was rebuilt.

## Reproduce and extend

```powershell
uv run --no-sync pytest
uv run --no-sync rocket-workbench --smoke-test
cd web
npm test
npm run build
cd ..
uv run --no-sync rocket-workbench --desktop-smoke-test
```

The final command requires the `desktop` extra and a usable graphics/display
path. On a headless Linux host, configure Qt's offscreen/software rendering as
appropriate. The native smoke check is intentionally limited; it does not click
every control or validate every native download dialog.

`scripts/browser_smoke.py` performs broader real browser workflows against its
own isolated loopback API: flight/events/timeline/export, studies/comparison,
STEP replacement, save/reload, CAD-only geometry, actual converged CFD,
pressure-transfer solid FEA and a real upstream OpenRocket fixture. It uses
software WebGL and writes a receipt, screenshots, data and logs under
`build/browser-smoke/`. The initial checkpoint run completed successfully and wrote a
passed receipt on 2026-10-08. The expanded version 0.1.1 run passed all ten workflows, including focused/same-value reload and malformed-edit regression checks, at 16:23 UTC on that date. The pressure-transfer check required more than
50% mapped surface coverage, positive stress and force equilibrium error below
1e-7; it did not assert physical or mesh convergence. Mark future runs passed
only after they write a successful `receipt.json`. Setup and invocation are in
[DEVELOPMENT.md](DEVELOPMENT.md).

The **Windows offline installer** workflow must complete Python/frontend tests,
freezing, silent installation, installed engine smoke and installed native
desktop/WebGL smoke before a Windows artifact is accepted. Its hosted VM uses
software WebGL and ordinarily has no NVIDIA GPU. Test physical GPU execution
separately, comparing CPU/GPU outputs with justified numerical tolerances.

## Remaining engineering limits

No real flight-log/wind-tunnel correlation or validated arbitrary-CAD transonic
drag benchmark has been completed. Euler CFD lacks viscosity/boundary layers
and turbulence; its steadiness is separate from grid/domain convergence. FEA is
isotropic linear static elasticity with declared support/load assumptions;
pressure transfer is nearest-sample, one-way and not force-conservative. Flight
is a passive point-mass model without attitude/weathercocking or transient
recovery shock. Supplied coefficient tables retain their source uncertainty.
Those model limits remain even when every automated test passes.


## Version 0.1.1 review coverage

The additional checks cover disabled assembly descendants and inactive motor
mounts, configuration-specific limitations, explicit recovery availability,
combined incidence, nonpositive lift-slope CP, stiff drag integration, shifted
CAD volume, replicated replacements, material-geometry preservation, and exact
exterior-flow isolation. Sealed hollow CAD and identical solid exteriors produce
identical aerodynamic grids, pressure faces and resultants; resolved bores stay
open. Separate mass/structural geometry and other components remain unchanged.

Structural references include hydrostatic stress, strain energy/work, rigid
coordinate invariance and scaled/rotated actual CAD FEA. CFD references include
wall shock/expansion pressure, shared fluid/body impulse, settled wall/force/moment
convergence and exterior connectivity. Reports retain recorded methods/warnings,
actual plots, source hashes and null/unavailable fields; uploads/settings reject
nonfinite nested data and invalid references. Worker tests cover cancellation,
retention and immutable run snapshots. Desktop tests cover retained socket startup
and failure cleanup. Packaging provenance hashes the actual copied source and
frontend content and records a dirty build explicitly.
Packaging tests cover both LF and Windows CRLF source bytes. CI retains JUnit
reports on failure and emits bounded test messages as workflow annotations.
