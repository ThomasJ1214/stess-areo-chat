# Validation checkpoint

Recorded 2026-10-09 during the version 0.3.0 review, using the Linux cloud
workspace and GitHub-hosted Linux/Windows runners.
The final clean source passed **332 Python tests**, **48 frontend tests**, and the
production frontend build. The version 0.3.0 engine smoke passed with 3,409
synthetic flight samples and
a real 731-element solid solve (equilibrium error 5.85e-15). Native Qt startup
passed shell, WebGL, authenticated API and project-load checks. Native preference
checks passed reload and two fresh-origin launches, including final-edit flushing;
receipts are `build/native-preferences-smoke.json` and
`build/production-preferences-smoke.json` (source executable, `frozen:false`).
The final local browser check passed all **25 workflows** with zero JavaScript
errors or external page requests. Its receipt,
`build/browser-smoke-03-final/receipt.json`, records the precommit 0.3.0 working
tree. Windows package checks passed as detailed below. Physical NVIDIA
execution and hardware performance remain unverified in this CPU cloud environment.

The [0.3.0 cross-platform workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37934882373)
passed all four Linux/Windows engineering, frontend and browser jobs for source
`893c7274b1932d6496aa2aa509601075a6f66eb0`. Its browser evidence artifact is
`11618071492` (8.05 MB; ZIP SHA-256
`62a51dc09eed8369b49433359c3a3754fb55e9b40199ad42c9cd47f00ccb95da`).
This clean-source run separately verifies the final integrated browser workflows.

The 0.3.0 change repairs frozen CUDA resource discovery and adds a hard packaging
check: real CuPy native imports, ten shipped CUDA DLLs, header discovery and offline
NVRTC PTX compilation. This check requires no GPU, and import failures cannot
pass as CPU fallback. Both the frozen executable and silently installed executable
must pass it. The first strict Windows check caught a missing `graphlib` import
in a compiled CuPy extension; the corrected source explicitly includes that
module. This was a packaging failure, and no installer from that failed run was
accepted. A physical-device check remains separate.

A later Windows candidate passed frozen and installed CUDA, engineering and
native desktop/WebGL checks, then failed the preference smoke test. Reproduction
with the original hook at 900 pixels identified its wait for **Hide assembly**:
responsive layout had already collapsed that panel. The corrected test opens it,
sets a nondefault 210-pixel width, hides it and verifies restoration across two
fresh ports. Tutorial progress, map points and final-close flushing remain
required. Source Qt and the production CLI hook both passed these stronger
checks, followed by the actual installed Windows executable. The final Windows
run passed all release gates.

The [0.3.0 Windows installer workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37934882324)
passed frozen engineering and strict CuPy/CUDA import, DLL/header and offline
kernel compilation checks, silent installation, installed engineering and CUDA
checks, native desktop/authenticated API/WebGL, and two-session preference
restoration at a 900-pixel window width. It built from the same clean source
`893c7274b1932d6496aa2aa509601075a6f66eb0`. The artifact contains its dependency/source
manifest, EXE SHA-256, engine/CUDA/native/preference receipts and beginner guides.
The hosted runner used software WebGL and no physical NVIDIA GPU: this verifies
package behavior, not RTX 4070 Super numerical performance or a fresh consumer PC.
Documentation-only commits after this source do not change the binary's identity.
The [installer artifact](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37934882324/artifacts/11619041385)
is `11619041385`, approximately 1.5 GB. Its **ZIP archive** SHA-256 is
`6d2f6a8852696570ae4d25889aa414c3185cb94448cba9a8615f407881d9172b`;
this is distinct from the setup EXE's checksum in `release/*.exe.sha256`.

### Independent download and fresh installation

On 2026-10-09 the [download verification workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37948824649)
downloaded that existing 1.5 GB artifact through authenticated GitHub Actions.
It verified the actual EXE SHA-256 against the shipped checksum, Windows PE
headers, version/source manifest and archived successful receipts. It then
silently installed the downloaded EXE in a fresh Windows runner and passed real
flight/solid-FEA, bundled CUDA import/header/offline compiler, and native
desktop/authenticated API/project/WebGL checks. No application was rebuilt.
The setup EXE SHA-256 is
`41c1bbfb139dc3f9489d9c6a74c97fa4703158b98ec3c6afc42f5f5b94ffdeaa`.
Compact proof artifact `11624444614` contains `verification.json`, native logs
and fresh engine/CUDA receipts (200 KB ZIP; archive SHA-256
`cc4906e4bc97718274d95fb8e72e57e94af46aa3eda3d972bb1890beba03fe4a`).
The verification helper/workflow is source `a72764e`; the downloaded app remains
the original clean `893c727` binary. Physical NVIDIA execution remains separate.

GitHub requires sign-in for artifact downloads, including public repository
artifacts. A signed-out direct artifact URL can return 404. Use the original
installer run's **Artifacts** section after signing in; the verification run's
small artifact contains evidence, not the installer.

Continuous streamlines use the actual exported velocity field, with conservative
wall masks and no interpolation through solids or sealed cavities. Independent
uniform/linear/circular flow references and thin-wall tests exercise the renderer.
The camera uses actual trajectory coordinates, bounded velocity-aware framing and
manual-control grace; flight attitude remains illustrative. Native preferences
use a bounded UI-only file while the session profile stays in memory.

## Historical version 0.2.0 checkpoint

The [0.2.0 cross-platform workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37857090831)
and [Windows packaging workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37857090849)
passed for source `7ebf0fd4ac891b19726ac7c2378a323c469ea07a`.
Its CPU-based packaging smoke did not catch a frozen CuPy import failure reported
on an RTX 4070 Super. That installer is superseded by the CUDA packaging repair;
it must not be described as GPU-verified. The prior evidence is retained below.

Recorded 2026-10-08 during the version 0.2.0 review in the Linux cloud workspace.
The current source passed its local test, engine and native-desktop checks.
Version 0.2.0 Windows packaging and the final browser check passed;
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
| Windows installer | **Version 0.2.0 CPU checks passed**; native CuPy import failure reported | Locked build, frozen/installed CPU engine and native API/WebGL checks passed; the old checks did not require a successful CUDA import |
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
