"""Bootstrap the frozen Windows CUDA wheel layout before importing CuPy.

CUDA 12 toolkit wheels deliberately have separate ``nvidia/*`` roots. They do
not require a machine-wide CUDA_PATH, but their DLL directories must be visible
to Windows, and cuda-pathfinder must see the frozen site-package resource root.
Only resources inside PyInstaller's trusted bundle root are registered. This
module never imports CuPy, queries a driver, downloads files, or changes a user's
CUDA_PATH/PATH. It therefore also works on a machine without an NVIDIA GPU.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import site
import sys
from threading import RLock

_lock = RLock()
_configuration: dict | None = None
# Do not close directory registrations while lazy native imports may need them.
_dll_directory_handles: list[object] = []


def _bundle_dlls(root: Path) -> list[Path]:
    """Return bundled DLLs without following a path outside the resource root."""
    files: set[Path] = set()
    for package in (root / "nvidia", root / "cuda", root / "cupy" / ".data" / "lib"):
        if not package.is_dir():
            continue
        for candidate in package.rglob("*"):
            if candidate.suffix.lower() != ".dll" or not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved.is_relative_to(root):
                files.add(resolved)
    return sorted(files, key=lambda path: str(path).casefold())


def _expose_frozen_site_packages(root: Path) -> None:
    """Preserve stdlib roots and add the real frozen wheel resource location.

    cuda-pathfinder uses site.getsitepackages(), rather than sys.path, for DLL
    and kernel-header discovery. PyInstaller keeps wheel data in _MEIPASS; its
    executable directory's hypothetical Lib/site-packages does not contain it.
    An explicitly supplied prefix list keeps the standard function's behavior.
    """
    previous = site.getsitepackages
    if getattr(previous, "_rocket_frozen_root", None) == str(root):
        return

    def frozen_site_packages(prefixes=None):
        directories = list(previous(prefixes))
        if prefixes is None and str(root) not in directories:
            directories.insert(0, str(root))
        return directories

    frozen_site_packages._rocket_frozen_root = str(root)
    site.getsitepackages = frozen_site_packages


def configure_bundled_cuda() -> dict:
    """Return an idempotent, JSON-safe registration receipt, never GPU success.

    A failure is retained for application diagnostics instead of preventing CPU
    startup. Packaging's separate native import check treats it as a hard error.
    The returned copy cannot alter handle lifetime or subsequent diagnostics.
    """
    global _configuration
    with _lock:
        if _configuration is not None:
            return deepcopy(_configuration)
        result = {"status": "not_frozen", "bundled_root": None,
                  "dll_directories": [], "runtime_files": [], "errors": [],
                  "cuda_path": os.environ.get("CUDA_PATH"),
                  "search_strategy": "Frozen wheel resources and Windows AddDllDirectory; CUDA_PATH is preserved."}
        if not getattr(sys, "frozen", False):
            _configuration = result
            return deepcopy(result)
        if sys.platform != "win32":
            result["status"] = "not_windows"
            _configuration = result
            return deepcopy(result)
        bundle_value = getattr(sys, "_MEIPASS", None)
        if not bundle_value or not Path(bundle_value).is_dir():
            result.update(status="unavailable", errors=["The frozen resource directory is unavailable."])
            _configuration = result
            return deepcopy(result)
        root = Path(bundle_value).resolve()
        result["bundled_root"] = str(root)
        dlls = _bundle_dlls(root)
        result["runtime_files"] = [str(path) for path in dlls]
        if not dlls:
            result.update(status="unavailable", errors=["No bundled CUDA DLL resources were found (this may be a CPU-only developer build)."])
            _configuration = result
            return deepcopy(result)
        _expose_frozen_site_packages(root)
        # Native modules also depend on runtime libraries beside python312.dll.
        directories = [root] + sorted({path.parent for path in dlls}, key=lambda path: str(path).casefold())
        for directory in directories:
            try:
                handle = os.add_dll_directory(str(directory))
            except (OSError, AttributeError) as error:
                result["errors"].append(f"Could not register {directory}: {type(error).__name__}: {error}")
            else:
                _dll_directory_handles.append(handle)
                result["dll_directories"].append(str(directory))
        result["status"] = "configured" if not result["errors"] else "unavailable"
        _configuration = result
        return deepcopy(result)
