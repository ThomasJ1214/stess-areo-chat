# Windows installation and first use

After installation, follow the [step-by-step user guide](USER_GUIDE.md). It shows
the actual buttons, how to align/replace one CAD component, exterior-only airflow,
motor/recovery setup, playback, numerical solvers and saving/exporting your work.

## Requirements

- Windows 10 or 11, 64-bit x64-compatible system.
- A current graphics driver. GPU acceleration of the 3D view uses WebGL through
  QtWebEngine. Numerical CUDA execution needs a compatible NVIDIA GPU and driver;
  AMD/Intel graphics do not supply CUDA.
- Recommended: a modern multi-core CPU, 32 GB RAM, and ample free storage. A finer
  CFD grid or larger solid FEA mesh may require considerably more RAM/VRAM. Read
  the displayed cell/mesh budgets before starting a large run.
- The installer includes the app, its desktop runtime, CAD importer, mesher,
  engineering solvers and CUDA runtime libraries. It can be a large download.

## Get the one-download package

Open the [verified **0.3.0** installer run](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37934882324#artifacts).
The approximately 1.5 GB package includes guided tutorials, a resizable workspace,
live motor search, launch playback, a local flight map, CAD automatic placement,
and CFD/FEA setup guidance. See the [validation record](VALIDATION.md) for recorded
checks; require a successful run before using its installer.

1. Sign in to GitHub, then open the linked installer run above and confirm its
   status is **Success**.
2. Scroll down to **Artifacts**. If the download has expired, open the repository's
   **Actions → Windows offline installer**, then use **Run workflow** with `main`.
   A repository owner or collaborator must have permission to run workflows.
3. Download the **RocketWorkbench-windows-x64-installer** artifact at the bottom
   of that run. Use an account with access to the repository if it is private.
4. Right-click the downloaded ZIP and choose **Extract All**. The extracted files
   include the installer, a SHA-256 checksum and a dependency manifest. Open the
   `release` folder if the download contains that folder. The package
   includes `START_HERE.txt` and `USER_GUIDE.txt`; the app also has an offline
   **User guide**, **Getting started**, and per-page **Tutorial** buttons.
5. Optionally check the installer in PowerShell with
   `Get-FileHash .\RocketWorkbench-0.3.0-windows-x64-setup.exe -Algorithm SHA256`
   and compare it with the `.sha256` file supplied in that artifact.
6. Double-click `RocketWorkbench-0.3.0-windows-x64-setup.exe`. Select a user-local
   install location and optionally enable the desktop shortcut. No administrator
   privileges are required for the default location.
7. Open **Rocket Workbench** from Start or the desktop shortcut.

The version in the filename follows `pyproject.toml`. The package is unsigned
unless its builder separately signs it; Windows can display a publisher warning.
Check the file came from your repository workflow before deciding to run it.
The app does not download solvers at startup. An existing NVIDIA display driver
is the one external GPU runtime prerequisite.

GitHub may require sign-in even for a public repository's artifact. Artifacts
expire after 30 days; request a new workflow run if the download has expired.
If a direct artifact link shows **404**, sign in first, reopen the installer run
above and click the artifact name under **Artifacts**. A signed-out 404 does not
mean the installer build failed.

## Upgrade an existing installation

1. Save your open project, then close every Rocket Workbench window.
2. Extract the new package and run its setup EXE. Use the same installation
   folder as before so your Start menu shortcut opens the new version.
3. Open the app and check that the header shows **0.3.0**. Your separately saved
   projects and the session directory are outside the application installation.
4. Open **CFD → GPU diagnostics** before a large GPU run. On a supported NVIDIA
   system, the report should identify the GPU and a successful device allocation
   and compiled reduction. If it fails, use **Copy diagnostics** to retain the complete
   cause; an unset `CUDA_PATH` alone is expected with the bundled runtime.

## First engineering workflow

1. Explore the built-in demonstration project. Its motor curve is a synthetic
   example, not an approved motor certification record. Click **Getting started**
   for the complete walkthrough, then **Tutorial** on each page you want to learn.
   Click **?** beside unfamiliar engineering terms for a definition.
2. Import your `.ork` file and review the import warnings. Choose the intended
   flight configuration and confirm dimensions, material density, mass, CG,
   motor curve and recovery settings. Import a real `.eng`/`.rse` thrust curve
   if the OpenRocket file supplies only a motor name or digest. Alternatively,
   use **Find motor online**, review a ThrustCurve.org curve, import it, and
   deliberately assign it in **Design → Flight setup**.
3. Use the design view to select a component. Import a STEP/STP or STL model and
   choose mesh source units correctly; STEP supplies its embedded units. Leave
   **Automatic alignment** on, click **Preview automatic alignment**, review
   **Source axis**, **Reverse direction** and **Placement anchor**, then **Attach
   & use detailed geometry**. Default placement preserves actual dimensions;
   **Fit selected length** is an explicit uniform resize. Compare with **Original
   geometry** and inspect joints. Turn automatic alignment off for manual edits.
   Verify the external shape and mass treatment before simulating.
4. Save the project to a file. Project JSON contains triangulated imported assets
   so it remains portable; the original STEP boundary representation is not
   preserved. Keep original CAD files separately.
5. Enter test conditions in the aerodynamic view and inspect results and solver
   warnings. CG/CP and aerodynamic vectors are estimates with their stated scope.
6. Open **Flight** and press the large red **Launch** button. The progress
   indicator reports calculation completion and a provisional ETA. After the
   flight is calculated, playback starts from the rail and the camera follows it.
   Adjust the camera manually; automatic **Follow** resumes after five seconds
   without input. Pause or scrub the timeline, inspect event markers, graphs and
   the north-up local map, then export results.
7. For CFD, begin with a modest grid. **Steady-state** runs until numerical
   convergence or cancellation, with no time/step cutoff. **Transient** resolves
   the chosen physical duration. Select launch history and a short flight
   interval to follow actual calculated airspeed/wind/atmosphere, or a fixed
   freestream wind test. Play/scrub the saved computed flow frames. Inspect actual
   convergence and backend; cancelled forces are partial and completed transient
   loads are instantaneous. X-ray/cutaway and high streamline quality help
   inspect the view without changing CAD or the solved field. Compare grid/domain
   refinements. For FEA, choose a component, material, explicit load and clamp.
   Leave **Automatic mesh sizing** on and read **Mesh readiness**; **Use recommended
   mesh** can raise the budget within its permitted limit. Use **Use beam/fin
   estimates** or a smaller externally prepared CAD part when a whole thin solid
   cannot fit. Perform refinement before using stress; a heatmap alone establishes
   no accuracy.

The installer includes [synthetic tutorial assets](../examples/README.md) under
`_internal/examples/`. They exercise project, motor, CAD and coefficient import;
they are fabricated data, not measured rocket performance.

## CAD-only flight and supplied coefficients

After importing a model, **Design → Geometry → New project from CAD** creates a
project using its actual triangle geometry. Orient the source nose-to-tail along
X. Its bounding circular dimensions are bookkeeping, not a valid aerodynamic
nose/fin model. Check mass/CG and material assumptions; a closed mesh is treated
as a uniformly filled solid unless you supply overrides.

For CAD-only passive flight, select a motor, define recovery and import a suitable
coefficient CSV using **Import aerodynamic polar .csv**. The required header is
`mach,cd,cna,cp_m`; an optional `source` records provenance. Use a positive CNa
per radian, CD and CNa based on the project's reported reference area, and CP in
metres from the nose. Include Mach zero through the highest expected flight Mach.
The table is linearly interpolated only inside its coverage. Rows outside it use
reference estimates with warnings and `polar_applied=false` in exported data.

Import binds the table to that configuration and exact shape. Shape/alignment
edits make it stale and require deliberate re-import. That binding establishes
the selected shape; it cannot verify coefficient accuracy. Results from an
experimental, unconverged Euler job must not be presented as a validated polar.

## Apply CFD pressure to structures

Finish a CFD job and inspect its convergence, grid/domain sensitivity and warnings.
In **Structures**, select the desired actual mesh component and choose
**Converged CFD surface pressure**. The app requires that the completed job still
matches the current geometry. Review its material, clamp and mesh resolution.

FEA receives gauge wall pressures through nearest compatible surface samples.
It reports mapped area coverage and transfer distances; unmapped faces receive
zero gauge pressure. Check force resultants and refine the grids. This is a
one-way, quasi-static load transfer, not coupled fluid-structure interaction or
transient stress simulation at every launch frame. A numerically converged Euler
field can still have significant physical-model and discretization error.

## Troubleshooting

**No importer/solver installation required.** If the installed app reports an
unavailable bundled capability, save the error, version and dependency manifest
and rebuild using the Windows workflow. Do not install random solver executables
into the application directory.

**Startup or session error.** Desktop service diagnostics are written to
`%LOCALAPPDATA%\RocketWorkbench\application.log` by default. Provide that log
and the version when reporting a failure. The desktop automatically selects a
free loopback port and keeps the embedded browser profile in memory.
For a rebuilt package, Windows **Properties → Details** on `RocketWorkbench.exe`
shows its product version; the startup log records it as well.

Saved project state is in `%LOCALAPPDATA%\RocketWorkbench\last-project.json`.
Keep a backup before changing it. To recover from a broken session, close every
Rocket Workbench window, rename that file to `last-project.backup.json`, and
restart; the app opens its demonstration project. Reload your saved project
through the interface. Uninstalling leaves this session directory and separately
saved projects available.

**CUDA unavailable.** Open **GPU diagnostics** first. It identifies the failing
check, original error, bundled-library paths, and driver/device details when
available. If the failure is importing CuPy or loading a bundled DLL, reinstall
the latest application build; installing a separate CUDA Toolkit is not required.
An unset `CUDA_PATH` is expected for the bundled split CUDA wheels and does not
prove that the runtime is missing.

If the diagnostic identifies an NVIDIA driver problem, install the manufacturer's
compatible NVIDIA driver and restart Windows. If no supported NVIDIA device is
present, use CPU or automatic mode. If allocation fails because VRAM is full,
close other GPU workloads or use a smaller grid. Automatic mode records its CPU
fallback; explicit GPU mode reports the failure. A working 3D viewport does not
establish numerical CUDA support. The capability probe is cached; restart the app
after changing the driver or application installation.

**An older CFD result stopped at “wall clock budget.”** That result remains a
partial solution after upgrading. Current CFD has no wall/step timeouts; rerun
in steady or transient mode, and cancel when needed. Steady convergence may
never occur. At Mach below 0.3 the pressure-drag warning remains relevant even if
numerical convergence is reached. Refining a grid adds work; a faster or longer
run does not establish physical accuracy.

**FEA says mesh size must be ≤ thickness/2.** Keep this requirement; coarse
solid elements across a thin wall can give misleading stiffness. Read **Mesh
readiness** and choose **Use recommended mesh** if the budget permits. If it exceeds even
the maximum budget, choose **Use beam/fin estimates** where supported or import a smaller physical
CAD part prepared outside the app with justified local loads/supports. Shell FEA
and region cutting are not included. CAD thickness is unknown and still needs
measurement and a refinement study.

**Slow/failed job.** Inspect the error, actual backend and method budget before
rerunning. A coarser CFD grid can help diagnose a workflow but reduces geometric
resolution. FEA mesh size must still resolve thin features; do not bypass its
thickness guard to finish a job. Cancellation is cooperative at solver checkpoints.

**CAD does not sit on the selected part.** Check source units, enable **Automatic
alignment**, and click **Preview automatic alignment**. The proposed axis/direction
is a guess: use **Reverse direction** or choose **Source axis** X/Y/Z, then attach
and compare with original geometry. Turn automatic alignment off for manual
alignment as needed. Default placement preserves real dimensions. Explicit
**Fit selected length** changes all dimensions and computed volume/mass. Review reported
gaps/overlaps at neighboring parts; placement does not create a structural bond
or a material Boolean union.

**Blank 3D viewport.** Update the graphics driver. Launch from PowerShell with
`$env:QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu'` before starting the executable
to diagnose the graphics path. This diagnostic uses software rendering.

**OpenRocket motor missing.** Motor names/digests are not thrust curves. Import an
authoritative local curve or choose **Find motor online** to search ThrustCurve.org.
Review the selected curve and source before importing, then assign it to the
intended configuration. Only requested motor searches/downloads require internet;
the engineering solvers and embedded project curves work offline. A service
outage does not prevent using a local `.eng`/`.rse` file.

**Panels hide a control.** Click **Show assembly** or **Show setup**, resize the
dividers, or choose **Reset layout**. A **Tutorial** explains the controls for
the current page; **User guide** provides instructions without relying on panel
positions.

**Local service startup.** The desktop application selects an available loopback
port automatically. Headless development defaults to `127.0.0.1:8765`; close a
previous headless instance or use `--headless --port 8766` if that port is busy.

**Remove the app.** Use Windows **Settings → Apps → Installed apps → Rocket
Workbench → Uninstall**. Your separately saved project files are yours to keep.

## Build status

The linked version **0.3.0** installer was built from source
`893c7274b1932d6496aa2aa509601075a6f66eb0`. Its Windows checks passed frozen and
installed engineering calculations, actual CuPy native imports, bundled CUDA DLL
and header discovery, offline kernel compilation, silent installation, native
desktop/API-session/WebGL startup, and preference restoration across fresh
sessions at a narrow window size. The hosted runner used software WebGL and had
no physical NVIDIA GPU. Workstation graphics, numerical GPU execution and a
fresh consumer PC need separate hardware checks. See [VALIDATION.md](VALIDATION.md)
for receipts and artifact identity. Documentation-only commits after the binary's
source revision do not rebuild it; generated binaries are kept out of Git history.

The [independent download/reinstall workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37948824649)
also passed. It downloaded the existing package, checked its actual EXE checksum,
installed it on a fresh Windows runner, and ran the engineering, CUDA packaging,
and native desktop/API/WebGL checks again. Download the installer from the
original installer run linked above; this separate verification run contains
only small evidence files.
