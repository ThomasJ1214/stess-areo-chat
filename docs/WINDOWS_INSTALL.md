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

The [verified version 0.1.1 Windows build](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37811145867#artifacts)
produced the approximately 1.5 GB installer download and passed its installed
engine/native-desktop checks. See the [validation record](VALIDATION.md).

1. Open the repository's **Actions** tab and choose **Windows offline installer**.
2. Choose a successful run for the version you want. If there is no successful
   run, use **Run workflow** with `main` to request one. A repository owner or
   collaborator must have permission to run workflows.
3. Download the **RocketWorkbench-windows-x64-installer** artifact at the bottom
   of that run. GitHub may ask you to sign in for a private repository artifact.
4. Right-click the downloaded ZIP and choose **Extract All**. The extracted files
   include the installer, a SHA-256 checksum and a dependency manifest. Open the
   `release` folder if the download contains that folder. The package
   includes `START_HERE.txt` and `USER_GUIDE.txt`; the app also has an offline
   **User guide** button.
5. Optionally check the installer in PowerShell with
   `Get-FileHash .\RocketWorkbench-0.1.1-windows-x64-setup.exe -Algorithm SHA256`
   and compare it with the `.sha256` file supplied in that artifact.
6. Double-click `RocketWorkbench-0.1.1-windows-x64-setup.exe`. Select a user-local
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

## First engineering workflow

1. Explore the built-in demonstration project. Its motor curve is a synthetic
   example, not an approved motor certification record.
2. Import your `.ork` file and review the import warnings. Choose the intended
   flight configuration and confirm dimensions, material density, mass, CG,
   motor curve and recovery settings. Import a real `.eng`/`.rse` thrust curve
   if the OpenRocket file supplies only a motor name or digest.
3. Use the design view to select a component. Import a STEP/STP or STL model and
   choose mesh source units correctly; STEP supplies its embedded units. Attach
   it to that component; adjust scale,
   rotation and translation while inspecting the rocket. Verify its external
   shape and mass treatment before simulating.
4. Save the project to a file. Project JSON contains triangulated imported assets
   so it remains portable; the original STEP boundary representation is not
   preserved. Keep original CAD files separately.
5. Enter test conditions in the aerodynamic view and inspect results and solver
   warnings. CG/CP and aerodynamic vectors are estimates with their stated scope.
6. Start a flight job. The progress indicator reports completion and a measured
   ETA estimate; the ETA is provisional. After it finishes, pause or scrub the
   timeline, inspect event markers and graphs, and export results.
7. For CFD, begin with a coarse grid and a small iteration budget. Inspect whether
   flow has actually converged, refine the grid, and compare results. For FEA,
   choose a component, material, explicit load and clamp; perform mesh refinement
   before using its stress field. A colored plot alone establishes no accuracy.

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

**CUDA unavailable.** Update the manufacturer's compatible NVIDIA driver and
restart Windows. The app displays the execution backend. GPU memory, compatibility
and library initialization can prevent CUDA use even if Windows recognizes the
GPU; choose CPU or automatic mode to continue. Bundled CUDA cannot replace a driver.

**Slow/failed job.** Use a coarser grid or larger mesh size, inspect the error and
method budget, then rerun. CFD iterations and tetrahedron counts directly affect
resources. Cancellation is cooperative at solver checkpoints.

**Blank 3D viewport.** Update the graphics driver. Launch from PowerShell with
`$env:QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu'` before starting the executable
to diagnose the graphics path. This diagnostic uses software rendering.

**OpenRocket motor missing.** Motor names/digests are not thrust curves. Import an
authoritative thrust curve and verify the mapping; no online motor download is
required by, or silently performed by, this application.

**Local service startup.** The desktop application selects an available loopback
port automatically. Headless development defaults to `127.0.0.1:8765`; close a
previous headless instance or use `--headless --port 8766` if that port is busy.

**Remove the app.** Use Windows **Settings → Apps → Installed apps → Rocket
Workbench → Uninstall**. Your separately saved project files are yours to keep.

## Build status

The version 0.1.1 Windows workflow passed its build and installation checks for
source commit `d5a0131`.
Its installer is a real build artifact; generated binaries are kept out of Git
source history. The workflow checked silent installation, installed engineering
calculations and actual native desktop/API-session/WebGL startup using software
WebGL. Workstation graphics, physical CUDA execution and a fresh consumer PC
still require separate hardware checks. CPU tests and packaged library presence
do not validate GPU performance on your graphics hardware.
