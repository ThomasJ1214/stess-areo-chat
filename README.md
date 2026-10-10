# Rocket Workbench

A Windows desktop workbench for high-power rocket design studies, intended for
passive rockets up to 12 ft (3.66 m) and Mach 2, with single or dual deployment.
Import OpenRocket projects or start from a CAD asset, inspect the rocket in 3D,
replace selected parts with detailed geometry, and compare results. Work happens
locally; engineering calculations and saved projects work offline. An optional
user-requested motor search retrieves real curve data from ThrustCurve.org.

The implementation distinguishes fast engineering estimates, a point-mass flight
model, experimental inviscid CFD, and linear static solid FEA. Results and warnings
identify the method used. This is a design and learning tool: matching a maximum
Mach setting does not establish validated supersonic accuracy.

## Install on Windows

Open the [verified version 0.3.1 installer run](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/37985799359#artifacts),
sign in to GitHub, and download **RocketWorkbench-windows-x64-installer**
(approximately 1.5 GB). Unzip it, open `release/` if present, and run
`RocketWorkbench-0.3.1-windows-x64-setup.exe`. No Python, Node.js, separate CAD
program, Gmsh installation, or CUDA Toolkit installation is required for use.

Artifacts are retained for 30 days. If the download has expired, run the
[Windows offline installer workflow](https://github.com/ThomasJ1214/stess-areo-chat/actions/workflows/windows-build.yml)
again. The artifact's manifest identifies the exact source commit and dependency
versions. Review [validation evidence](docs/VALIDATION.md); download-documentation
updates do not change an existing binary's identity.

This installer was built from `da4baab51c99911bd648fd3de935c4c9f3033af6`.
Frozen and installed CuPy/CUDA imports and normal-startup offline compilation
for `compute_75` and `compute_89` passed without test-only DLL preloads,
along with installed engineering, native desktop/WebGL and preference-restart
checks. Physical NVIDIA execution and performance need a real-device check.
Close an earlier app version before running the new installer, then open
**CFD → GPU diagnostics** to check your device.

The [independent download/reinstall check](https://github.com/ThomasJ1214/stess-areo-chat/actions/runs/38009992042)
also passed: it downloaded the original package, verified the EXE checksum,
installed it on a fresh Windows runner, and tested its engine, launch-driven
transient CFD, CUDA packaging and native UI. The CFD check independently matched
changing boundary speeds to the saved vehicle-minus-wind trajectory.
If a direct artifact link returns 404, sign in and click
**RocketWorkbench-windows-x64-installer** under the original run's **Artifacts**.

See [step-by-step Windows installation](docs/WINDOWS_INSTALL.md). The normal build
includes CUDA runtime libraries for supported NVIDIA GPU calculations. An NVIDIA
driver must already be installed. Other GPUs still render the viewport; numerical
solvers use their reported CPU backend when CUDA is unavailable. Large CFD/FEA
jobs need substantial RAM and/or VRAM.

Start with the [step-by-step user guide](docs/USER_GUIDE.md) for OpenRocket setup,
CAD replacement, exterior airflow, launch playback, CFD/FEA, studies and exports.
The app also includes **Getting started**, a **Tutorial** for every page, an
offline **User guide**, and **?** definitions beside unfamiliar engineering terms.
Resize or hide the assembly/setup panels, focus the 3D view, or reset the layout
to keep the controls and results you need visible.

## What is implemented

| Workflow | Calculation and practical scope |
| --- | --- |
| OpenRocket import | `.ork` XML/ZIP/GZIP, hierarchy, component geometry, overrides, configurations, recovery settings, supported motor assignments; import warnings preserve unsupported features |
| CAD replacement | STEP/STP through Open CASCADE; STL, OBJ and PLY; automatic selected-part placement preserving dimensions, preview/reverse/manual alignment and explicit uniform fit; original/replacement comparison |
| CAD-only projects | Start from an imported mesh; inspect mass/geometry and run CFD/FEA; passive flight requires supplied geometry-specific aerodynamic coefficients |
| 3D inspection | GPU-rendered scene, component selection, original/replacement geometry, CG/CP and aerodynamic force visualization; resizable/collapsible panels |
| Motor lookup | Explicit ThrustCurve.org search, curve/source preview and review before import; local ENG/RSE remains available offline |
| Fast aerodynamics | Standard atmosphere, mass/CG, small-angle Barrowman reference geometry, drag/loading estimates and transparent unvalidated Mach corrections; import signature-bound coefficient CSV |
| Flight | Passive point-mass launch with error-controlled integration, changing motor mass, single/dual recovery, wind and deterministic gusts; red Launch button, rail/flat-ground scene, playback, load/stress/wind graphs, following camera and north-up landing map |
| Structural estimates | Beam/fin stress and deflection with custom isotropic material properties |
| Solid FEA | Read-only solid/mesh preflight, Gmsh tetrahedra, linear isotropic elasticity, declared clamp/load boundaries and solved displacement/von Mises fields; thin-part/resource guards remain enforced |
| CFD | Experimental 3D compressible inviscid Euler finite volumes; steady-state and actual time-resolved transient modes, launch-driven airflow, saved frame playback, cancellation and qualified ETA; no runtime/step ceilings |
| Pressure-transfer FEA | One-way mapping from a completed, numerically converged and geometry-matched CFD job; mapped coverage/distances are reported |
| Studies | Parameter/wind sweeps, seeded Monte Carlo, configuration and original/replacement comparisons |
| Data | Self-contained project JSON with imported mesh assets; simulation JSON/CSV and HTML reports; metric and US customary display units |

CAD replacements influence mass properties and geometry-based numerical solvers.
Automatic attachment places only the selected replacement; it does not edit
neighboring CAD, fuse material meshes or invent structural connections. CFD uses
a separate assembled exterior-flow mask and preserves source cavities for mass
and FEA. Open passages remain open when resolved by the grid.
The default fast model retains OpenRocket reference geometry for CP and stability;
it flags estimates that do not resolve arbitrary CAD changes. A supplied
Mach/CD/CNa/CP table can drive current-geometry aerodynamics and flight within
its Mach coverage. The table is bound to the selected configuration and exact
geometry; source accuracy still requires independent validation. CFD excludes
viscosity, skin friction and physical turbulence. Low-Mach pressure drag is
particularly unreliable with this scheme, even after numerical convergence.
A cancelled run returns a labeled partial field. Unlimited runtime does not
guarantee convergence or physical accuracy. Transient launch flow prescribes a
one-way boundary history around fixed geometry; it does not solve moving-body
attitude or feedback into flight. Solid FEA may need
more elements than the budget permits for whole thin parts; use supported beam/fin
estimates or a smaller physical CAD part. Shell FEA and region cutting are not
included. Flight
does not integrate attitude, weathercocking, active guidance or fin flutter. FEA
does not model composite layups, yielding, contact, buckling or transient recovery
shock. Imported unsupported configurations cannot become reliable simulations by
silently omitting their physics.

Read the method-specific documentation before interpreting results:
[aerodynamics and flight](docs/PHYSICS.md), [CFD](docs/CFD.md), and
[structures](docs/STRUCTURAL.md). Reference tests exercise known limiting cases;
they are not flight-test or wind-tunnel validation. Try the explicitly
[synthetic tutorial project, motor, polar and payload CAD](examples/README.md).

## Develop and run from source

Use Python 3.12, Node.js 22 and [uv](https://docs.astral.sh/uv/). In PowerShell:

```powershell
git clone https://github.com/ThomasJ1214/stess-areo-chat.git
cd stess-areo-chat
uv sync --locked --extra desktop --extra dev --extra gpu
cd web
npm ci
npm run build
cd ..
uv run --no-sync rocket-workbench
```

For a smaller CPU development installation, omit `--extra gpu`. Both installs
include the CAD and meshing dependencies. Dependency downloads are required when
setting up development; subsequent app execution is local.

```powershell
uv run --no-sync pytest
uv run --no-sync rocket-workbench --smoke-test
uv run --no-sync python scripts/build_windows.py
```

The last command must run on Windows and requires Inno Setup 6. It creates the
installer under `release/`. [Developer instructions](docs/DEVELOPMENT.md) cover
live frontend development, Linux prerequisites, tests, locking and packaging.

## Repository

`rocket_workbench/` contains file readers, geometry, engineering solvers, jobs,
local API and desktop startup. `web/` contains the React/TypeScript interface.
`tests/` holds scientific reference and integration checks. `scripts/` and
`.github/workflows/` build and validate the offline Windows package.

See the [architecture](docs/ARCHITECTURE.md), [development and validation plan](docs/DEVELOPMENT_PLAN.md),
[shared interfaces](docs/INTERFACES.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
The [validation checkpoint](docs/VALIDATION.md) records tested behavior,
verified installer identity and remaining physics/hardware limits.
Application source is MIT-licensed; bundled dependencies retain their own terms.
