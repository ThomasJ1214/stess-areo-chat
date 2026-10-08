# Validation checkpoint

Recorded 2026-10-08 during the version 0.2.0 review in the Linux cloud workspace.
The current source passed its local test, engine and native-desktop checks.
Version 0.2.0 Windows packaging is pending; the final browser check passed;
historical version 0.1.1 runner/installer evidence is retained below. All checks
use Python 3.12 and the pinned dependency specifications. Passing these
checks establishes tested implementation behavior, not certification or agreement
with a real rocket's flight/wind-tunnel measurements.

| Check | Result at this checkpoint | What it establishes |
| --- | --- | --- |
| Python suite | **302 tests passed** | Reference/limiting cases, importer/geometry handling, flight events, project/API behavior, CAD alignment invariants, solid-FEA preflight, motor-catalog safeguards, desktop source-link boundaries, backend diagnostics and numerical solvers |
| Frontend unit suite | **35 tests passed** | Unit/display bounds, editable numbers, settings restoration, load-option filtering, vectors/geometry fitting, launch presentation, local flight-map coordinates and tutorials |
| Frontend production build | Passed | Type checking and bundled frontend compilation |
| Core executable smoke | Version 0.2.0 passed on Linux from source | Real Open CASCADE solid construction, Gmsh initialization, original rocket meshing, aerodynamic analysis, complete synthetic flight and actual solid FEA |
| Solid FEA checks | Passed on Linux/CPU | Actual Gmsh tetrahedral meshing and sparse elasticity, analytical bar mechanics, reactions/residuals and pressure-transfer checks covered by the suite |
| Native desktop smoke | Version 0.2.0 passed with Qt software WebGL on Linux | Actual desktop window, rendered interface/WebGL, authenticated API health and loaded project through the embedded page; hardware graphics performance is not established |
| Native motor source links | Passed with real Qt 6.12 mouse events | Five actual link clicks and real new-window signals, one intercepted system-browser call, preserved app page and zero network requests; portable smoke script included |
| Expanded browser baseline | **18 workflows passed** with Chromium software WebGL on Linux | Tutorials/help, panel resizing/accessibility, local map/POIs, rail/launch/playback/camera, controlled motor-service UI, flight/studies/export, imports/save/reload, actual converged CFD and pressure-transfer FEA; before final CAD/FEA/CFD controls |
| Final expanded browser workflow | **23 workflows passed** | Actual mouse/keyboard resizing, small-window containment/map dialog, default/explicit CAD placement and saved manual alignment, neighbor/source invariants, automatic/manual/recommended FEA meshes, genuine CFD/pressure-transfer FEA, GPU diagnostics, unlimited progress and retained/exported cancelled CFD |
| Actual online motor lookup | Passed on Linux against ThrustCurve.org | Real J350W search and curve download/parse with file digest/provenance; no project mutation or synthetic fallback; provider certification/applicability remains unverified |
| Tutorial assets | Passed through actual readers/API | Saved project, synthetic ENG, STL and STEP dimensions/volume, coefficient CSV import and interpolation |
| Windows installer | **Version 0.2.0 pending**; version 0.1.1 historically passed | The new source needs its own locked build, tests, frozen smoke, installer, silent installation and installed engine/native API/WebGL checks |
| NVIDIA numerical backend | **Unverified on physical hardware** | CuPy/CUDA packaging and fallback logic do not establish GPU execution, numerical agreement or performance on a user's driver/device |

The Python suite includes independent analytical cases and conservation/positivity
checks; see [PHYSICS.md](PHYSICS.md), [CFD.md](CFD.md) and
[STRUCTURAL.md](STRUCTURAL.md) for their meaning and physical limits. Counts are a
checkpoint, not a promise that future revisions always have the same test count.

## Final version 0.2.0 local browser evidence

The final version 0.2.0 local browser receipt is
`build/browser-smoke-02-final23/receipt.json`: all 23 workflows passed on
2026-10-08 with zero JavaScript errors or external page requests. Its motor UI
uses a controlled provider fixture; the separate live-provider check above
establishes actual online retrieval. The cube CFD converged in 767 steps on
59,904 cells; actual pressure-transfer solid FEA mapped 100% of the selected
surface with force equilibrium error approximately 7.61e-16. The unlimited run
retained actual fields after 94 accepted steps and cancellation, exported them,
and remained ineligible for FEA pressure transfer. These are implementation
checks, not physical/grid-convergence validation of the cube's flow prediction.

## Historical version 0.1.1 Windows evidence

The version 0.1.1 [cross-platform test workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37811145726)
and [Windows installer workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37811145867)
passed their engineering, browser, packaging and installed-app checks for source commit
`d5a0131ab612870878f95ed8328f3de7951419ef`. The installer artifact is approximately
1.5 GB and includes an executable checksum and dependency/source manifest.
The Windows hosted runner tested software WebGL and CPU numerical execution;
it did not test a physical NVIDIA GPU or a fresh consumer PC. Documentation-only
commits after this source revision do not imply the binary was rebuilt. This
artifact does not contain the version 0.2.0 interface and solver-usability changes.

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

## Version 0.2.0 local review evidence

`build/engine-smoke-02.json` records version 0.2.0, 12,698 geometry vertices,
3,409 synthetic flight samples and an actual 741-element Gmsh solid solve with
force-equilibrium error `8.53e-16`. These are executed CPU calculations, not
illustrative fields. The synthetic flight reached recovery and ground contact;
its motor and aerodynamic assumptions are tutorial inputs, not measured data.
The native Qt check in `/tmp/rocket-desktop-02/application.log` passed desktop
shell, WebGL, authenticated API and project-load checks using software rendering.

The expanded baseline receipt `build/browser-smoke-02-stable/receipt.json` passed
18 workflows on 2026-10-08 at 6:42 PM EDT. It covers offline full-app/per-page
tutorials, progress restoration, help-definition focus/dismissal, accessible
panel resizing, camera follow/manual control, rail/ground launch playback,
map/trajectory/landing conventions and saved visual points of interest. The
motor-search UI check used controlled provider fixtures and failure recovery;
it is separate from the actual live-service check below. It also ran real
flight, studies, CAD import/roundtrip, CFD convergence and pressure-transfer FEA.
That baseline predates final automatic alignment, FEA-readiness and CFD-run-mode
controls. A new expanded receipt is still required for those final controls;
the baseline must not be presented as their completed end-to-end validation.
Local receipts identify the current checkout as modified; a later release
manifest must identify its own committed source and installed-app evidence.

### Actual live motor service

`build/live-motor-smoke-cloud.json` records real HTTPS search/download requests
to ThrustCurve.org on 2026-10-08, with no project changes or synthetic fallback.
It matched AeroTech J350W and parsed the provider's
[RockSim curve](https://www.thrustcurve.org/simfiles/5f4294d20002e900000003c0/)
(`simfile_id:5f4294d20002e900000003c0`): 1,214 downloaded bytes, 12 thrust samples,
integrated impulse `649.55867090565 N·s`, and final sample time `1.5 s`.
The raw file SHA-256 is
`12688977e4021fd3ba716cf04d4fde56b7efeec67a5df817d033f068afc972c1`.
The provider declared this file's source as `user` and supplied no license text.
Its catalog summary reports 700 N·s; it is distinct from integration of this
downloaded curve. This difference reinforces the need to review a particular
file instead of assigning a motor from its catalog name alone. Certification,
licensing and applicability to the user's actual hardware were not independently
verified. This is Linux/cloud service-integration evidence; Windows live-provider
integration still needs its own check. Use the optional command documented in
[DEVELOPMENT.md](DEVELOPMENT.md) to reproduce a bounded live check.

### New scientific and integration coverage

CAD tests exercise surface-area axis estimation under triangle subdivision,
rigid placement and mass invariants, cubic mass scaling for explicit uniform
fit, symmetric-axis fallback, reversal, nose direction/shoulder handling,
single-reference placement of repeated parts, adjacent axial gap diagnostics,
and read-only preview/attachment over HTTP. Source assets, neighboring parts and
structural geometry remain unchanged; a placement proposal is not a CAD union
or a structural connection.

FEA preflight tests preserve thickness/2 resolution for original thin parts,
reject impossible whole-part budgets, reject ambiguous/open solids consistently
with the solver, and avoid native meshing or project mutation during inspection.
They include actual thin-fin and small CAD-bar solves and geometry-specific
recommendations without inventing CAD wall thickness.

CFD tests cover zero/nonzero elapsed-time limits, honest partial states,
convergence-only cancellation beyond former work ceilings, bounded history and
axis-aware fin-resolution diagnostics. Existing conservation, wall-flux and
exterior-connectivity references remain enforced. CUDA diagnostic tests use
controlled library/device fixtures to distinguish import, device and kernel
failures and verify cache isolation. They are not physical GPU execution tests.
Motor-client tests cover bounded fixed-provider requests, timeouts, invalid data,
provenance/integrity, review-token/project consistency and offline failure without
fabricated success or automatic configuration assignment.

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
