# Development

## Reproducible checkout

Use the selected checkout directly. Cloud tasks already have isolated workspaces;
do not create another Git worktree unless explicitly requested. Keep local
projects, credentials and generated dependency/build directories out of Git.

Required build tools: Git, CPython 3.12 x64, Node.js 22, and uv 0.9 or newer. The
Windows installer builder also needs Inno Setup 6. The frontend lockfile uses npm.

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

Optional `gpu` installs the CUDA runtime/toolkit wheels needed by numerical
CuPy kernels. Omit that extra for CPU development. `desktop` installs PySide6 and
QtWebEngine; omit it for API/tests on a headless machine. Do not manually upgrade
individual dependencies inside the virtual environment: the lock records the
resolved combination.

On Debian/Ubuntu, CAD and Gmsh may need shared libraries:

```bash
sudo apt-get update
sudo apt-get install -y libgl1 libglu1-mesa libxrender1 libxext6
uv sync --locked --extra dev
```

For a sandboxed cloud environment whose default cache is not writable, set
`UV_CACHE_DIR=/tmp/rocket-uv-cache` and `npm_config_cache=/tmp/rocket-npm-cache`
for those commands. These are caches, not repository settings or credentials.

## Live development

In one terminal:

```powershell
uv run --no-sync rocket-workbench --headless --host 127.0.0.1 --port 8765
```

In another:

```powershell
cd web
npm run dev
```

Vite proxies `/api` to the local API. Development can use the browser viewport;
the desktop release loads the bundled frontend with a session token. Bind the
API to loopback for normal use. The default desktop app does not expose a public
network service. Project files can contain large meshes; import limits and
numerical job budgets intentionally reject resource-exhausting inputs.

## Verification

```powershell
uv run --no-sync pytest
uv run --no-sync rocket-workbench --smoke-test
cd web
npm test
npm run build
```

Tests check physical limiting cases, analytical mechanics, importer behavior,
mesh handling and application interfaces. Method-specific documents describe
the equations, references and limitations. Maintain tests against independent
reference values and conservation laws; tests that repeat an implementation do
not establish engineering accuracy. GPU execution needs a real supported device
and must be checked separately from CPU fallback. A successful frontend build
checks types and bundling but is not an interactive viewport test.

The standard CI runs Python tests and smoke checks on Linux and Windows and
tests/builds the frontend. A browser-workflows job runs the isolated full browser
check. The installer workflow additionally freezes dependencies,
creates an installer, performs a silent user-local installation, and runs the
installed engine's smoke check plus the actual native desktop/session/WebGL
startup check. The hosted Windows VM uses software WebGL for that check and
normally has no NVIDIA GPU. It does not validate workstation graphics/CUDA
performance or every interaction.

See [VALIDATION.md](VALIDATION.md) for the recorded checks and remaining Windows,
hardware and physical-model validation gaps.

With the `desktop` extra and built frontend installed, run
`uv run --no-sync rocket-workbench --desktop-smoke-test` to start the actual Qt
window, local session and WebGL scene and exit automatically after its check.
Headless/Linux hosts need a usable display/graphics path; a browser-only check
does not validate Qt startup. The smoke mode's 30-second UI deadline is a check,
not a simulation time limit.

The desktop keeps its loopback listener bound while the API starts, so launching
two application instances cannot select the same released port. Startup logs
include the application/Python version and session path, without the session
token. `uv run --no-sync rocket-workbench --version` reports the source version.
Add `--smoke-output build/engine-smoke.json` to `--smoke-test` to preserve its
actual capability, flight and FEA evidence even in windowed Windows executables
that have no terminal output. A previous receipt is removed before the check;
only a successful check writes a replacement.

### Browser workflow check

Install the optional developer-only `browser` extra and a Playwright Chromium
binary after building `web/dist`:

```powershell
uv sync --locked --extra dev --extra browser
uv run --no-sync playwright install chromium
uv run --no-sync python scripts/browser_smoke.py
```

Keep `--extra desktop`/`--extra gpu` on the sync command if you also use those
extras; uv synchronizes exactly the requested dependency set. The browser extra
is not an end-user installer requirement. Browser installation downloads a
development test binary; the application itself stays local/offline. Linux may
need Playwright system libraries (`playwright install-deps chromium`).

The script starts and stops an isolated loopback API automatically, uses actual
solvers and imports, aborts external page requests, and writes screenshots,
exported data, a server log and `receipt.json` under `build/browser-smoke/`.
It covers STEP/CAD replacement, project roundtrip, flight playback/export,
portable edited analysis/solver settings, studies, converged CFD, one-way
pressure-transfer FEA and the upstream ORK fixture. It also downloads the actual
flight input project and verifies its content digest against the result's
recorded project digest. The receipt records source revision, dirty state,
timestamps and either completed checks or failure details.
Its software WebGL run is distinct from the native Qt startup check and from
hardware GPU validation. Use `--artifacts <directory>` to change its output.

To reuse a compatible already-installed Chromium instead of downloading one:

```powershell
uv run --no-sync python scripts/browser_smoke.py --browser "C:\path\to\chrome.exe"
```

In restricted cloud workspaces, a writable browser cache can be selected with
`PLAYWRIGHT_BROWSERS_PATH=/tmp/rocket-playwright-browsers` before both install and
run commands. Do not claim a run passed unless its assertions and receipt finish
successfully.

## Dependency updates

Python direct dependencies are pinned in `pyproject.toml`. `uv.lock` resolves
transitive versions across supported environments and records artifact hashes.
`uv sync --locked` refuses a stale project/lock pairing. Do not turn off artifact
hash or TLS verification to work around installation failures.

To make an intentional update:

1. Review upstream changelogs, license terms, Windows/Python wheel availability
   and numerical/API compatibility.
2. Update the relevant direct pin and run `uv lock`.
3. Update frontend declarations with npm as needed and commit `package-lock.json`.
4. Run reference tests, frontend build, and the Windows packaging workflow.
5. Record changes in solver behavior or validation scope when relevant.

The scientific core does not depend on a GPU library: absence of CUDA is a
capability state, not a reason to fabricate results. Explicit GPU requests must
report inability to run rather than silently claim GPU completion.

## Windows package

On Windows after installing all three extras and Inno Setup 6:

```powershell
uv run --no-sync python scripts/build_windows.py
```

The script runs the frozen lockfile frontend build (`npm ci`), generates a
dependency manifest and tracked source snapshot, invokes PyInstaller, smoke-checks
the executable, and compiles the Inno Setup installer. Output:

- `dist/RocketWorkbench/`: portable application directory; keep its entire tree.
- `release/RocketWorkbench-<version>-windows-x64-setup.exe`: one-download installer.
- `release/*.sha256`: installer checksum.

`--cpu-only` makes a developer build that omits CUDA; the default packages it.
`--skip-web-build` reuses an existing checked frontend build.
`--skip-installer` stops after the portable directory and smoke test. Packaging
must run on Windows, not under Linux cross-compilation. Freezing retains Qt native
libraries/resources and preserves Gmsh/CUDA library search layouts.

The application source snapshot uses Git-tracked files, excluding upstream
OpenRocket test data (which remains in the repository with its GPL attribution).
Commit reviewed changes
before making a release build so its manifest identifies the correct revision.
Nothing in the build script pushes Git commits or changes repository visibility.
GitHub's **Windows offline installer** workflow runs on pushes to `main` or a
version tag, and can be triggered manually; it uploads artifacts without
publishing a public release.

The manifest records the Git revision, tracked-file dirty state, SHA-256 hashes
of copied source files, built frontend files and both dependency lockfiles, plus
platform and whether CUDA bundling was requested. A local modified checkout is
identified as dirty; its snapshot digest distinguishes it from that commit's
original contents. Untracked files and upstream OpenRocket test fixtures are
excluded from the shipped source snapshot. Its package inventory describes the
build environment; PyInstaller excludes development modules from the executable.
Changing versions requires matching `pyproject.toml` and the Python application
version; packaging rejects mismatches and unsupported non-x64 interpreters.

Unattended frozen/installed engine checks have a six-minute process deadline.
The Windows workflow bounds installation to ten minutes and native startup to
90 seconds, stops a timed-out process tree, and retains installer/application
diagnostics on failure. These checks are independent of simulation budgets.

Check [third-party notices](../THIRD_PARTY_NOTICES.md) before distributing binaries
outside the requested private use. Build artifacts are unsigned unless a signing
process is added. Never store signing keys or private credentials in Git.

## Add a solver or file format

Use the contracts in [INTERFACES.md](INTERFACES.md) and serializable Pydantic
models. Keep internal physics in SI units. Return method/fidelity, warnings and
actual execution backend with results. Solvers receive progress and cancellation
callbacks; the job layer owns elapsed time, ETA, cancellation and export. A new
format should map to project/mesh assets without teaching the UI its parser.

Document boundary conditions, supported inputs, physical limits, uncertainty,
convergence criteria and independent reference tests before exposing an advanced
solver as available. Do not fill an unimplemented stress/pressure visualization
with invented values.

## Tutorial assets and data pathways

[examples/README.md](../examples/README.md) explains the synthetic project,
motor, polar, STL and STEP files shipped with the app. Regenerate these with
`uv run --no-sync python scripts/generate_examples.py`. The labels identify
invented data; do not relabel it as measured or validated.

Coefficient CSV is bound to the selected configuration and shape signature.
Unit/display edits and material changes cannot secretly reinterpret supplied
coefficients. Shape/asset/alignment edits require explicit re-import. For
one-way CFD-pressure FEA, the job layer verifies the completed CFD state and
current shape before forwarding surface samples; the structural mapper reports
coverage and distance limits. These invariants need integration checks when
editing the project schema, importer metadata or job/result storage.
