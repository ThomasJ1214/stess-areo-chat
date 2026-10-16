# Validation checkpoint

## 0.3.5 MUSCL source validation in progress

The selected experimental method uses primitive-variable MC reconstruction,
shared conservative Rusanov fluxes and two-stage SSPRK2. Default first-order
calculations and the exterior-connected geometry policy remain available.
Smooth-interior accuracy is distinct from first-order boundary reconstruction
and start-of-step launch-profile/source sampling. The current source is not yet
a verified 0.3.5 Windows download.

Local full regression passed 558 Python tests. The final targeted run passed
36 reconstruction/mode tests, including the two added changing-boundary and
invalid-second-stage cases. Clean-source CI must confirm the final suite count. The frontend passed
90 tests and production type/build checks. Browser/Windows verification remain
separate release gates.

Independent nondimensional reference measurements:

| Case | Resolution | Density mean absolute error | Observed refinement order |
| --- | --- | --- | --- |
| Periodic entropy advection, each of X/Y/Z | 24 cells | 0.0015108241 | — |
| Same exact finite-volume cell averages | 48 cells | 0.0004033928 | 1.905 |
| Same exact finite-volume cell averages | 96 cells | 0.0001059340 | 1.929 |
| Sod shock tube, baseline | 180 cells | 0.0183464152 | Discontinuous reference; no smooth-order claim |
| Sod shock tube, MUSCL–MC/SSPRK2 | 180 cells | 0.0038513788 | Same exact reference and physical end time |

These test errors do not establish rocket pressure, drag, transonic or turbulent
flow accuracy. The smooth wave uses exact cell averages; shock checks also retain
mass/energy conservation and the independent boundary-pressure momentum impulse.
The new kernel checks multi-axis conservation, positive reconstructed faces,
first-order wall/boundary stencils, stage rejection without clipping, and closed
Euler/laminar wall mass/energy. Real CAD checks require sealed-exterior identity
and unchanged source geometry/mass in both numerical methods.

Reproduce numerical properties with:
`uv run --no-sync pytest tests/test_cfd_reconstruction.py -o junit_family=legacy --junitxml=build/cfd-muscl-reference.xml`.
Generated XML/browser receipts are local build artifacts; CI/download links and
exact source identity will identify packaged evidence after completion.


## Verified 0.3.4 original-fin plate release

The new MITC4 static flat-plate path preserves original swept/tapered/triangular
fin planforms, actual azimuth/cant/radial placement, measured thickness and
explicit materials. It uses per-fin root clamps, signed differential pressure
or declared original-reference directional aero resultants and transverse
material-density inertial loads. Source CAD/solids, project geometry and mass
data are unchanged. Solid guards remain active; curved shells, CAD midsurfaces,
laminates, joints, CFD transfer and transient plates are unsupported.

Local checks passed 539 Python tests, 89 frontend tests, production build,
24 plate-specific kernel/adapter/API/export checks and native Qt
shell/software-WebGL/API/project startup. The final
[cross-platform CI](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38832085552)
passed all four jobs at corrected source
`f6e8c9151d5d07607bb940b24a9d1cd8aa2b6201`, including the 35-workflow browser
suite with a plate-only cold-start Forces/deformation check. Browser evidence
artifact `12017423517` is approximately 15 MB; ZIP SHA-256
`0438691f4c773eb7bef1a066998ad7625a192fb61033e75f63eaa7703e2b7adf`.
A focused signed-pressure UI check also passed; its receipt explicitly identifies
the uncommitted viewer prerequisite fix before that source commit. The previous
candidate required an aerodynamic result before enabling plate force arrows;
the corrected source removes that prerequisite.

The [corrected Windows build](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38832085653)
passed frozen/installed engine, flight, solid and actual MITC4 fin-plate FEA,
launch-driven Euler/laminar CFD, CUDA native import/offline compilation and
native desktop/API/software-WebGL checks. The plate receipt records real mesh,
stress/displacement and equilibrium results; no physical NVIDIA execution is
claimed. Installer binary source is exactly `f6e8c9151d5d07607bb940b24a9d1cd8aa2b6201`.
Artifact `12018645971` is approximately 1.5 GB and is named
`RocketWorkbench-windows-x64-installer`. Installer ZIP SHA-256:
`34a4bee70b82b83a1f03135807673580bb469fedd539ae479f2e3a45b1cb3c27`.

The [independent original-download verification](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38832913110)
passed on a fresh Windows runner. It downloaded the existing original artifact
without rebuilding, checked the shipped checksum and exact clean source identity,
installed it and repeated the packaged numerical, plate equilibrium, CUDA
compiler and native UI checks. Actual setup EXE SHA-256:
`7c871b6952fc8f5f33b31fdaeb6d5843dbce6f28e6ffdd5e6ff940380aa6cca6`.
Proof artifact `12018606729` contains evidence, not the installer; proof ZIP
SHA-256 `562f3218897067c4fec36c99cf083a99df462dd3a97c7973fce05f06a106a1cf`.
Documentation/verification-only commits after the binary source do not change
these installer bytes. Physical GPU execution and measured flight/wind-tunnel
validation remain open; numerical reference tests do not establish those claims.

## Verified 0.3.3 release

The default original-fin beam integrator now propagates the complete modal
basis exactly for piecewise-linear recorded loads. Independent checks compare
unforced phase/energy, a damped ramp against adaptive DOP853 integration, and
split-interval composition, including very small intervals and high frequencies.
This removes modal time-integration error for that prescribed load model; it
does not recover unrecorded forcing or stress extrema between output samples.
Legacy Newmark remains selectable with its fundamental-period discretization
clearly labeled. One/two-fin directional load partitions are unavailable until
an independently justified model is implemented.

Incomplete flights retain observed-history numbers and termination/coverage
flags. They cannot contribute to completed-flight statistics or final flight
comparison deltas. Completed flights with explicitly invalid operating/static
stability flags are also excluded from aggregates. Each statistic declares its
actual sample count. CSV/HTML retain wind, inertia, structural coverage and
numerical context; laminar comparisons retain actual viscous/total loads.

Local checks passed 515 Python tests, 88 frontend tests, and the production
build. The engine smoke completed a synthetic launch and actual solid FEA. Native Qt
startup passed shell, software WebGL, API and project checks for 0.3.3.
A clean-source browser run passed all 33 real workflows at
`fba1524a7e4b4ceb9089ff539969f10f2891c474`, including exact-integrator selection,
legacy-control visibility and complete-basis result metadata. The
[full cross-platform CI](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38794768306)
passed all four jobs: 515 Python tests on each of Windows/Linux, 88 frontend
tests/build and 33 browser workflows. Browser artifact `12002316718` is 14.4 MB;
ZIP SHA-256 `9f64209d7fbeab44dfe37305d26608735bbe0a115ad093afde8f88e32b122032`.
The companion [verification-branch CI](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38796300253)
also passed all four jobs.

The [Windows installer build](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38794768307)
passed frozen and installed engine/solid FEA, 6DOF/Dryden and causal environment
changes, complete-basis exact modal fin integration, partial-study exclusion,
launch-driven Euler/laminar CFD, normal-startup CUDA import/offline compilation,
native desktop/API/WebGL and preference-restart checks. Binary source is exactly
`fba1524a7e4b4ceb9089ff539969f10f2891c474`. Uploaded installer artifact
`12001834964` is approximately 1.5 GB, named
`RocketWorkbench-windows-x64-installer`. ZIP SHA-256:
`63a9fec01a4ee071477a5e9c4aa55709611ea010040675322a3f72c5fd8bab9b`.
The [independent original-download check](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38796300295)
passed: it downloaded the original uploaded archive without rebuilding, matched
the shipped installer checksum and exact source identity, installed on a fresh
Windows runner and repeated real engine/solid FEA, saved-launch Euler CFD,
6DOF/Dryden/causal changes, exact fin integration, partial-study exclusion,
launch-driven laminar fields, normal-startup CUDA compiler and native UI/API/WebGL.
Actual installer EXE SHA-256:
`4b075cfd39560cdee0a58b6748edfd38dd8d3ad5c945c0a2b90ece8e3f251974`.
Proof artifact `12002339088` is 179 KB; ZIP SHA-256
`1e39ab9ae33fa3f4575a25d7bac855c188983348763adf586cb1ad3f5306bede`.
This is evidence only; download the 1.5 GB installer from the original build.
Later documentation/research changes do not replace those installer bytes.
Hosted Windows graphics are software WebGL. CUDA compilation does not establish
physical NVIDIA solver execution. Measured flight validation, turbulent CFD,
whole-vehicle/laminate/transient solid FEA remain separate work.

Draft plate/MUSCL work in research/prototypes is outside the application package,
not a solver capability. The plate draft now has repeatable rigid/constant-curvature,
distorted-element, geometry-guard, mesh-connectivity and 12 square-plate Navier
reference checks. See [research evidence](../research/PLATE_REFERENCE.md) for the
precise source hash, results and still-unverified application/stress integration.
MUSCL remains unvalidated and unintegrated.


## Verified 0.3.2 release

This update adds optional adaptive quaternion/Euler rigid-body flight with actual
mass-normalized inertia and declared small-angle aerodynamic limits; stationary
seeded temporal Dryden gusts, optional shear, causal wind/temperature schedules
and assumed finite canopy inflation. Original-fin dynamics use genuine tapered
Hermite beam mass/stiffness matrices and complete-basis Newmark integration.
Experimental laminar CFD adds conservative molecular viscosity/heat conduction
and real wall tractions, without claiming resolved rocket boundary layers or
turbulence. Smooth display interpolation changes no engineering samples.

Local verification passed the final **503-test full Python suite** after review
tightened physical inertia validation and excluded ambiguous CAD volumes from
inertia estimation. The frontend suite passed **87 tests**; the production build
and native Qt shell/WebGL/API/project startup also
passed. Independent checks include rigid-body angular momentum/energy, exact
constant-torque and vacuum-thrust motion, step refinement, dual recovery,
Dryden covariance/statistics, quaternion profile SLERP consistency, beam static/
modal/transient references, viscous conservation and adiabatic-wall force/energy.
These are equation/discretization checks, not measured flight validation.

The PowerShell installed-API procedure passed against the source executable
wrapper: actual 104/118-row rigid-body trajectories, unchanged physical prefix
before a scheduled change, 4,571 fin substeps with explicit unavailable rows,
and four computed launch-driven laminar fields. These source checks were
followed by the frozen/installed Windows checks below.
The [corrected full CI run](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38770788126)
passed all four jobs: 503 engineering/API tests on each of Windows and Linux,
87 frontend tests, production build and **33 real browser workflows**. Those
workflows include actual 6DOF/Dryden/fin dynamics, stale input protection, causal
live environment changes, selected-time resume and actual laminar CFD playback.
The browser evidence artifact is `11991966791` (14.4 MB; ZIP SHA-256
`441f5093c26cff4cfddaeba83a786bea8c569fae862562a0856ef86f170479c5`).

Binary source is `26fee162254ee7eaf68095bdf7e25e7ef51edd26`. CI source
`454828d36c8ecdde8519507a440d3efd1c699c1d` corrects two browser assertions
to match the existing component PUT endpoint and transient `summary.status`.
The earlier browser run failed those assertions; application behavior was
unchanged. A Git comparison confirms identical `rocket_workbench/`, `web/`,
dependency declarations/locks, assets and installer/build inputs between these
commits.

The [Windows build](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38770023582)
passed frozen and installed engine tests, actual installed 6DOF/Dryden/causal
wind changes, dynamic fin FEM, launch-driven laminar CFD, bundled CUDA
normal-startup import and offline compiler checks, native desktop/API/WebGL and
preference restoration across fresh sessions. It compiles uncached `compute_75`
and `compute_89` PTX without test-only library preloads. The hosted VM uses
software WebGL and does not establish physical NVIDIA solver execution.
The uploaded installer artifact is `11991868302`, approximately 1.5 GB, named
`RocketWorkbench-windows-x64-installer`. Its ZIP SHA-256 is
`bc2692e98f40b7d4b43ad4c56592235d2399ffac5b48a0ef99ab13c9b5ff9d11`.

The [independent download/reinstall verification](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38773050948)
also passed. It downloaded the original uploaded archive without rebuilding,
checked its shipped EXE checksum and exact clean source identity, installed on a
fresh Windows runner, and repeated real flight/solid FEA, saved-launch Euler
CFD, 6DOF/Dryden, causal wind/temperature changes, dynamic original-fin FEM,
launch-driven laminar fields, normal-startup CUDA preprocessing/compiler and
native desktop/API/WebGL checks. The actual installer EXE SHA-256 is
`3f9e10b234d0645baa6d9c710ca290723254cdb9f8619a5aabf1b69068528ad5`.
Its compact proof artifact is `11992378078` (206 KB; ZIP SHA-256
`81ceff36fd9a872b83fd60f6386d3e3f9104785b7061cb6ea8f74218b15c8a7a`).
That proof is not the installer: download `RocketWorkbench-windows-x64-installer`
from the original build run's Artifacts section after signing in.

All prescribed numerical jobs in the installed advanced smoke use CPU backends.
CUDA compilation/software WebGL checks do not establish real NVIDIA execution,
VRAM limits or performance. No measured flight-log/wind-tunnel correlation,
validated turbulent rocket CFD, whole-vehicle transient FEA, laminate failure or
recovery opening-shock validation is claimed. These remain engineering work.

## Verified 0.3.1 release

The 0.3.1 changes add error-controlled flight integration and exported force
vectors, launch-driven physical-time CFD, separate steady/transient states,
qualified ETA, real snapshot playback, and higher-quality streamlines with
X-ray/cutaway inspection. CFD has no wall-clock or step-count stopping ceilings.
The NVRTC repair preloads the matched bundled builtins through production startup;
the stricter compiler check exercises normal CuPy preprocessing before any
test-only DLL loads, then compiles uncached `compute_75` and `compute_89` PTX.

The final local suites passed **411 Python tests** and **64 frontend tests**,
with a successful production build. Native Qt shell/WebGL/API/project startup
and two fresh 900-pixel preference sessions passed. New independent
references include variable-mass rocket motion, quadratic drag, actual-time
transient uniform flow, whole/selected flight-profile consistency and changing
atmospheric pressure. The streamline review found High-quality lines stopping
at ordinary fluid-cell interpolation interfaces: a bounded retry repair restores
full-domain lines without relaxing masks or numerical tolerance. An independent
piecewise-affine velocity test reproduces the failure; the actual solved box
field now produces 11,672 Standard segments and 26,511 High segments, with
both reaching the full exported domain. This is display verification, not
grid refinement or hardware performance validation.

The clean source `da4baab51c99911bd648fd3de935c4c9f3033af6` also passed all
**28 browser workflows**, with no JavaScript errors or external page requests;
`build/browser-smoke-031-final/receipt.json` identifies that source. These include
an actual launch driving transient CFD with changing saved flow states,
frame selection/playback, High-quality streamlines, X-ray/cutaway inspection,
load/stress/wind graphs, converged steady pressure transfer to FEA, cancellation
and CAD imports. The [cross-platform workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37985799273)
passed all four engineering, frontend and browser jobs for the same source.
Its browser evidence artifact is `11642574780` (12.5 MB; ZIP SHA-256
`4d0794d3e91a225bc969d42c158c5b6cf4e12a361d2eef5285b1581f8d9bc44c`).

The [0.3.1 Windows installer workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37985799359)
passed all build, frozen-engine, frozen-CUDA, silent-installation,
installed-engine, installed-CUDA, native desktop/API/WebGL and two-session
preference checks for that same clean source. Normal CuPy preprocessing ran
before any smoke-test DLL loads, and uncached compilation succeeded for both
`compute_75` and `compute_89` (the RTX 4070 Super architecture target). This
specifically exercises the production path implicated by the reported
`nvrtc-builtins64_129.dll` error. Both frozen and installed receipts require
`startup_path_verified:true` and `test_only_preloads_before_compilation:false`.

The [installer artifact](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37985799359/artifacts/11643897100)
is `11643897100`, approximately 1.5 GB. Its **ZIP archive** SHA-256 is
`545dcf1989572c4fcc059df7fd73a543f0b6c3a555f2bfc5b07fdc20c27af9e5`.
The setup **EXE** SHA-256 is
`62a656e11dfe6ceca4ccdbb4bcb5666ef71f2e26e5c6b6f8b99df25eb9ef2e45`;
the archive and executable checksums identify different files.

### Independent 0.3.1 download and fresh installation

The [download verification workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38009992042)
downloaded the existing uploaded installer without rebuilding it. It checked
the actual EXE checksum, PE headers, clean-source/version manifest and archived
receipts, silently installed the EXE on a separate fresh Windows runner, and
passed actual flight/solid-FEA, normal-startup CUDA preprocessing/uncached PTX
and native desktop/authenticated API/project/WebGL checks.

The installed EXE also calculated a complete launch through its headless API.
That saved trajectory then drove real CPU transient Euler CFD over launch time
1.0–1.0001 seconds. The check required distinct accepted-state frames, finite
velocity/pressure/density/Mach/force/moment fields, exact physical/start/end
timestamps, matching source job/project digest and changing freestream speeds.
Each frame's boundary speed was independently matched to interpolated saved
vehicle-minus-wind vectors. The completed transient result had to retain
`converged:false` and `pressure_force_steady:false`. This short interval verifies
installed solver integration and provenance, not aerodynamic convergence or
physical launch accuracy.

Compact proof artifact `11652933064` contains `verification.json`, installation
and native logs, and fresh engine/CUDA/launch-CFD receipts (205 KB ZIP; archive
SHA-256 `176c6aa349fe85a5859c9fdf9ae5922ddfb131deb27b5ce1bde4768b85b40e04`).
The verification helper/workflow source is `db89d37`; the downloaded binary
remains clean source `da4baab51c99911bd648fd3de935c4c9f3033af6`.
Sign in to GitHub and use the original installer run's **Artifacts** section;
the small verification artifact contains evidence, not the installer.

The hosted runners used software WebGL without a physical NVIDIA device.
No physical GPU execution/performance, measured flight comparison, resolved
turbulence or six-degree-of-freedom validation is claimed. The historical 0.3.0
evidence below is separate from these stricter 0.3.1 checks.

## Earlier verified 0.3.0 release

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
drag benchmark has been completed. Default Euler CFD lacks viscosity; optional
laminar CFD adds molecular transport but typical rocket grids do not establish
resolved boundary layers. Neither includes physical turbulence closure.
Steadiness is separate from grid/domain convergence. Solid FEA is isotropic
linear static elasticity; dynamic beam FEA supports original fins with declared
loads/materials/root support, excluding rotating-base forcing, plates/torsion,
whole-rocket dynamics and flutter. Pressure transfer is pressure-only,
nearest-sample, one-way and not force-conservative. Optional rigid-body flight
integrates attitude using small-angle reference moments and explicitly stops at
meaningful unsupported high incidence. Roll aerodynamics, canopy suspension and
recovery shock remain absent. Dryden gusts are a seeded temporal surrogate rather
than measured/resolved weather. Supplied coefficient tables retain their source uncertainty.
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
