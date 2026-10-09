"""Bootstrap the frozen Windows CUDA wheel layout before importing CuPy.

CUDA 12 toolkit wheels deliberately have separate ``nvidia/*`` roots. They do
not require a machine-wide CUDA_PATH, but their DLL directories must be visible
to Windows, and cuda-pathfinder must see the frozen site-package resource root.
NVRTC loads its builtins lazily by name while compiling. AddDllDirectory alone
does not guarantee that legacy load uses the registered directories, so matching
bundled builtins must be loaded by absolute path before the first compilation.
Only resources inside PyInstaller's trusted bundle root are registered. This
module never imports CuPy, queries a driver, downloads files, or changes a user's
CUDA_PATH/PATH. It therefore also works on a machine without an NVIDIA GPU.
"""
from __future__ import annotations

from copy import deepcopy
import ctypes
import os
from pathlib import Path
import site
import sys
from threading import RLock

_lock = RLock()
_configuration: dict | None = None
# Do not close directory registrations while lazy native imports may need them.
_dll_directory_handles: list[object] = []
# Retain native library objects too: NVRTC's later name-based load must find the
# same builtins still loaded. These are resources, never a GPU success receipt.
_native_library_handles: list[object] = []

# The locked nvidia-cuda-nvrtc-cu12 wheel is 12.9.86. NVRTC's compiler basename
# stays nvrtc64_120_0.dll across CUDA 12 minors, while its builtins are minor-
# specific; the native version query below prevents accidentally mixing them.
_NVRTC_VERSION = (12, 9)
_NVRTC_DLL = "nvrtc64_120_0.dll"
_NVRTC_BUILTINS_DLL = "nvrtc-builtins64_129.dll"
# LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS: no cwd
# or PATH search is added, and dependencies can resolve beside the trusted DLL.
_BUNDLED_LOAD_FLAGS = 0x00001100


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


def _preload_nvrtc(dlls: list[Path], result: dict) -> None:
    """Load the locked compiler/builtins pair before any CuPy/JIT operation.

    An absolute load puts the builtins in Windows' loaded-module list, which
    NVRTC's subsequent LoadLibrary-by-name can find without changing global
    DLL search policy. The DLL inventory already rejects paths outside the
    frozen root. Require one compiler and its adjacent, minor-matched builtins
    instead of choosing an arbitrary duplicate or a machine-wide toolkit.
    """
    expected_version = ".".join(map(str, _NVRTC_VERSION))
    pairing = {"expected_version": expected_version, "version": None,
               "library_path": None, "builtins_path": None}
    result["nvrtc"] = pairing
    compilers = [path for path in dlls if path.name.casefold() == _NVRTC_DLL]
    if len(compilers) != 1:
        raise RuntimeError(f"Expected one bundled {_NVRTC_DLL}; found {len(compilers)}. "
                           "The CUDA runtime bundle is incomplete or ambiguous.")
    compiler_path = compilers[0]
    pairing["library_path"] = str(compiler_path)
    builtins = [path for path in dlls
                if path.name.casefold() == _NVRTC_BUILTINS_DLL and path.parent == compiler_path.parent]
    if len(builtins) != 1:
        raise RuntimeError(f"Bundled NVRTC {expected_version} requires {_NVRTC_BUILTINS_DLL} "
                           f"beside {compiler_path}; the matching builtins DLL is missing.")
    builtins_path = builtins[0]
    pairing["builtins_path"] = str(builtins_path)
    # Builtins MUST precede NVRTC/CuPy. Do not replace these explicit absolute
    # loads with PATH mutation, SetDllDirectory or a bare-name LoadLibrary.
    compiler = None
    for role, path in (("nvrtc_builtins", builtins_path), ("nvrtc", compiler_path)):
        try:
            library = ctypes.CDLL(str(path), winmode=_BUNDLED_LOAD_FLAGS)
        except (OSError, AttributeError) as error:
            raise RuntimeError(f"Could not preload bundled {role} DLL {path}: "
                               f"{type(error).__name__}: {error}") from error
        _native_library_handles.append(library)
        result["native_preloads"].append({"role": role, "path": str(path)})
        if role == "nvrtc":
            compiler = library
    major, minor = ctypes.c_int(), ctypes.c_int()
    try:
        compiler.nvrtcVersion.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        compiler.nvrtcVersion.restype = ctypes.c_int
        status = compiler.nvrtcVersion(ctypes.byref(major), ctypes.byref(minor))
    except (OSError, AttributeError) as error:
        raise RuntimeError(f"Could not query bundled NVRTC version: {type(error).__name__}: {error}") from error
    if status != 0:
        raise RuntimeError(f"Bundled nvrtcVersion failed with status {status}.")
    pairing["version"] = f"{major.value}.{minor.value}"
    if (major.value, minor.value) != _NVRTC_VERSION:
        raise RuntimeError(f"Bundled NVRTC version {pairing['version']} does not match "
                           f"the locked {expected_version} builtins {_NVRTC_BUILTINS_DLL}.")


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
                  "dll_directories": [], "runtime_files": [], "native_preloads": [], "errors": [],
                  "cuda_path": os.environ.get("CUDA_PATH"),
                  "search_strategy": "Frozen wheel resources, Windows AddDllDirectory and absolute matched NVRTC/builtins preloads; PATH and CUDA_PATH are preserved."}
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
        if not result["errors"]:
            try:
                _preload_nvrtc(dlls, result)
            except RuntimeError as error:
                result["errors"].append(str(error))
        result["status"] = "configured" if not result["errors"] else "unavailable"
        _configuration = result
        return deepcopy(result)
