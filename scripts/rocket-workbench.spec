# -*- mode: python ; coding: utf-8 -*-
"""Windows onedir bundle. Run through build_windows.py after locked installation."""
from pathlib import Path
from importlib import metadata, util
import json
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_delvewheel_libs_directory, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct,
)

root = Path(SPECPATH).parent
app_version = json.loads((root / "build" / "bundle_manifest.json").read_text("utf8"))["application_version"]
version_numbers = tuple(int(part) for part in app_version.split("."))
version_numbers = (version_numbers + (0, 0, 0, 0))[:4]
version_resource = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_numbers, prodvers=version_numbers,
        mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("CompanyName", "Rocket Workbench contributors"),
        StringStruct("FileDescription", "Rocket Workbench desktop engineering application"),
        StringStruct("FileVersion", app_version),
        StringStruct("InternalName", "RocketWorkbench"),
        StringStruct("OriginalFilename", "RocketWorkbench.exe"),
        StringStruct("ProductName", "Rocket Workbench"),
        StringStruct("ProductVersion", app_version),
    ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)
datas = [(str(root / "web" / "dist"), "web/dist"),
         (str(root / "examples"), "examples"),
         (str(root / "docs"), "docs"),
         (str(root / "LICENSE"), "."),
         (str(root / "THIRD_PARTY_NOTICES.md"), "."),
         (str(root / "build" / "bundle_manifest.json"), "."),
         (str(root / "build" / "notices"), "notices"),
         (str(root / "build" / "source"), "source")]
binaries = []
hiddenimports = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                 "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                 "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"]

# Native CAD and scientific extensions require more than their top-level module.
for module in ("numpy", "scipy", "OCP", "trimesh", "defusedxml"):
    package_datas, package_binaries, package_imports = collect_all(module)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

# The Windows OCP wrapper explicitly registers both sibling DLL directories.
# VTK's Python viewer modules are not used, but its native libraries are linked
# by the OCP extension and must retain this layout.
datas, binaries = collect_delvewheel_libs_directory(
    "OCP", libdir_name="cadquery_ocp.libs", datas=datas, binaries=binaries)
datas, binaries = collect_delvewheel_libs_directory(
    "vtkmodules", libdir_name="vtk.libs", datas=datas, binaries=binaries)

# Gmsh is a single-file module whose wheel stores its library outside gmsh.py.
# Preserve its documented ../lib search path in the frozen application.
gmsh_distribution = metadata.distribution("gmsh")
gmsh_dlls = []
for item in gmsh_distribution.files or []:
    if Path(str(item)).name.lower().startswith("gmsh") and Path(str(item)).suffix.lower() == ".dll":
        path = Path(gmsh_distribution.locate_file(item)).resolve()
        if path.is_file():
            gmsh_dlls.append((str(path), "lib"))
if not gmsh_dlls:
    raise RuntimeError("The Gmsh Windows DLL was not found; install the locked Windows wheel.")
binaries += gmsh_dlls
hiddenimports.append("gmsh")

gpu_requested = os.environ.get("ROCKET_BUNDLE_GPU", "1") == "1"
if gpu_requested:
    if util.find_spec("cupy") is None:
        raise RuntimeError("GPU bundle requires: uv sync --locked --extra desktop --extra dev --extra gpu")
    for module in ("cupy", "cupyx", "cuda"):
        package_datas, package_binaries, package_imports = collect_all(module)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_imports
    # CUDA Toolkit wheels use a namespace package and platform native libraries.
    # Their original layout lets cuda-pathfinder locate runtime/NVRTC libraries.
    for distribution in metadata.distributions():
        name = (distribution.metadata.get("Name") or "").lower()
        if name.startswith("nvidia-") or name.startswith("cuda-"):
            for item in distribution.files or []:
                source = Path(distribution.locate_file(item)).resolve()
                parts = Path(str(item)).parts
                if not source.is_file() or ".." in parts or not parts:
                    continue
                if parts[0] not in {"nvidia", "cuda"}:
                    continue
                destination = str(Path(*parts[:-1])) or "."
                if source.suffix.lower() in {".dll", ".pyd"}:
                    binaries.append((str(source), destination))
                else:
                    datas.append((str(source), destination))

# Keep licenses and metadata for runtime library discovery and user review.
for distribution in metadata.distributions():
    name = distribution.metadata.get("Name")
    if not name:
        continue
    try:
        datas += copy_metadata(name)
    except Exception:
        # Editable local source may not expose a conventional dist-info directory.
        pass

a = Analysis(
    [str(root / "scripts" / "desktop_entry.py")],
    pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "vtk"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="RocketWorkbench", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False,
          version=version_resource,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="RocketWorkbench")
