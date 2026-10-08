# Third-party notices

Rocket Workbench source is under the MIT license in `LICENSE`. Dependencies keep
their own licenses. Private use does not change those licenses. A binary with
these libraries is not covered solely by the application's MIT license.

The installer retains installed distribution metadata and available license
files under its `_internal` directory. `bundle_manifest.json` identifies the
exact packages in a build; `uv.lock` and `web/package-lock.json` identify resolved
versions and artifact hashes. See those files for the actual dependency set.
The manifest's package inventory includes installed build-environment packages;
PyInstaller's exclusions mean that inventory is broader than the executable's
runtime imports. Source, compiled frontend and lockfile content hashes identify
the actual inputs independently of the recorded Git revision.

| Dependency | Purpose | Upstream license / terms |
| --- | --- | --- |
| Python | Embedded interpreter | Python Software Foundation license |
| FastAPI, Pydantic, Uvicorn, python-multipart, defusedxml | Local API, model validation, safe imports | MIT, BSD, or Apache-2.0 as stated by each distribution |
| NumPy, SciPy | Arrays, integration, sparse linear algebra | BSD-3-Clause; bundled numerical libraries have additional notices |
| trimesh | Triangular geometry and diagnostics | MIT |
| cadquery-ocp / Open CASCADE | STEP import and tessellation | Wrapper Apache-2.0; Open CASCADE LGPL-2.1 with additional exception |
| VTK | cadquery-ocp dependency | BSD-3-Clause |
| Gmsh | Tetrahedral meshing | GPL-2.0-or-later; read the included Gmsh license |
| PySide6 / Qt / QtWebEngine / Chromium | Desktop window and GPU viewport | LGPL/GPL/commercial options and Chromium third-party notices; QtWebEngine includes additional third-party software |
| React, Three.js, react-three-fiber, Recharts, Vite | Interface, 3D scene, graphs and build tools | MIT and other permissive dependency licenses; see frontend notice inventory |
| CuPy | Optional numerical GPU execution | MIT |
| NVIDIA CUDA Toolkit wheel libraries | Bundled GPU runtime and compilation libraries | NVIDIA CUDA Toolkit license and component redistribution terms |
| PyInstaller | Application bundling | GPL-2.0-or-later with bootloader exception |
| Inno Setup | Installer builder | Inno Setup license |

The OpenRocket application is not bundled or executed. `.ork` import is an
independent reader. OpenRocket is a trademark/name of its respective project;
this application is not affiliated with that project.

The imported-project test fixture `Dual parachute deployment.ork` is from the
upstream OpenRocket project at commit
`591c5e5f7b7377e48f2bd5e501cef25cdfbd61d8`. Its accompanying attribution and GPL
license are retained under `tests/fixtures/`. That fixture's license does not
replace the MIT license of this independently written application's source.

The builder collects frontend package license/notice files in
`_internal/notices/frontend/` and includes a package license inventory. Installed
Python/native-library license files are copied to `_internal/notices/python/`,
including notices stored outside distribution metadata. Available distribution
metadata is retained as well.

The Windows package is intended for the requested private use. Before providing
it to others, review all dependency licenses, retain notices, provide required
corresponding source for GPL components such as Gmsh, satisfy Qt replacement and
source obligations, and obey NVIDIA redistribution terms. The build includes
this application's tracked source, excluding the upstream OpenRocket test
fixtures, but that snapshot alone is **not** the full
corresponding source of third-party native libraries. The workflow uploads an
artifact for repository members; it does not automatically publish a release.

Upstream license/source locations:

- https://www.python.org/psf/license/
- https://numpy.org/doc/stable/license.html
- https://scipy.org/about/#license
- https://github.com/CadQuery/OCP and https://dev.opencascade.org/resources/licensing
- https://gmsh.info/ and https://gitlab.onelab.info/gmsh/gmsh
- https://doc.qt.io/qt-6/licensing.html and https://doc.qt.io/qt-6/qtwebengine-licensing.html
- https://docs.cupy.dev/en/stable/license.html
- https://docs.nvidia.com/cuda/eula/index.html
- https://pyinstaller.org/en/stable/license.html
- https://jrsoftware.org/isinfo.php
