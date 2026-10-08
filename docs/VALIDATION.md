# Validation checkpoint

Recorded 2026-10-08 for the initial implementation in the Linux cloud workspace,
using Python 3.12 and the pinned dependency specifications. Passing these
checks establishes tested implementation behavior, not certification or agreement
with a real rocket's flight/wind-tunnel measurements.

| Check | Result at this checkpoint | What it establishes |
| --- | --- | --- |
| Python suite | **144 tests passed** | Reference/limiting cases, importer and geometry handling, flight events, project/API behavior, scientific solvers and integration safeguards |
| Frontend unit suite | **6 tests passed** | Unit conversion, small nonzero result formatting, timeline/CSV helpers and perspective geometry fitting |
| Frontend production build | Passed | Type checking and bundled frontend compilation |
| Core executable smoke | Passed on Linux from source | Real Open CASCADE solid construction, Gmsh initialization, original rocket meshing, aerodynamic analysis and complete synthetic flight |
| Solid FEA checks | Passed on Linux/CPU | Actual Gmsh tetrahedral meshing and sparse elasticity, analytical bar mechanics, reactions/residuals and pressure-transfer checks covered by the suite |
| Native desktop smoke | Passed with Qt software WebGL on Linux | Actual desktop window, rendered interface/WebGL, authenticated API health and loaded project through the embedded page; hardware graphics performance is not established |
| Full browser workflow | Passed with Chromium software WebGL on Linux | Actual flight/playback/CSV, three-point sweep, original/current flight comparison, STEP attachment/project roundtrip, CAD-only STL, genuinely converged CFD, pressure-transfer FEA/deformation and upstream ORK configuration selection; no external page requests or JavaScript errors |
| Tutorial assets | Passed through actual readers/API | Saved project, synthetic ENG, STL and STEP dimensions/volume, coefficient CSV import and interpolation |
| Windows installer | **Unverified; not built in this Linux environment** | The repository provides a Windows workflow/build recipe, not a prebuilt or validated Windows release |
| NVIDIA numerical backend | **Unverified on physical hardware** | CuPy/CUDA packaging and fallback logic do not establish GPU execution, numerical agreement or performance on a user's driver/device |

The Python suite includes independent analytical cases and conservation/positivity
checks; see [PHYSICS.md](PHYSICS.md), [CFD.md](CFD.md) and
[STRUCTURAL.md](STRUCTURAL.md) for their meaning and physical limits. Counts are a
checkpoint, not a promise that future revisions always have the same test count.

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
`build/browser-smoke/`. The checkpoint run completed successfully and wrote a
passed receipt on 2026-10-08. The pressure-transfer check required more than
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
