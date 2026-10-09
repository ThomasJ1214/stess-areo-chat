"""Check shipped CUDA imports and offline NVRTC compilation without a GPU.

This is a packaging check, not hardware validation. It must pass on the Windows
build runner even when there is no NVIDIA device or driver. Missing libraries,
missing headers and CuPy native import errors must not pass as CPU fallback.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import traceback

from .bundled_cuda import configure_bundled_cuda

_REQUIRED_DLLS = (
    "cudart64_12.dll", "cublas64_12.dll", "cublaslt64_12.dll",
    "cufft64_11.dll", "curand64_10.dll", "cusolver64_11.dll",
    "cusparse64_12.dll", "nvrtc64_120_0.dll", "nvrtc-builtins64_129.dll",
    "nvjitlink_120_0.dll",
)


def _compile_offline_ptx(compiler, include_directory: Path, cupy_include: Path) -> dict:
    """Exercise CuPy's real compiler path before the gate loads any extra DLLs.

    These private APIs are from the locked CuPy version. ``_preprocess`` is the
    very first NVRTC compilation made by normal CuPy elementwise kernels. Using
    it here catches a compiler that imports successfully but cannot load its
    builtins. Neither it nor ``_NVRTCProgram`` requests a device or CUDA context.
    Direct compilation bypasses the on-disk kernel cache, so a cached success
    cannot hide missing native resources in a newly installed application.
    """
    source = ('#include <cuda_runtime.h>\n#include <cupy/carray.cuh>\n#include <cuda/std/limits>\n'
              'extern "C" __global__ void bundled_check(double* x) { '
              'x[threadIdx.x] *= cuda::std::numeric_limits<double>::digits > 0 ? 2.0 : 0.0; }\n')
    include_paths = (include_directory, cupy_include,
                     cupy_include / "cupy" / "_cccl" / "libcudacxx")
    common_options = ("--std=c++17",) + tuple("--include-path=" + str(path) for path in include_paths)
    compilations = []
    for architecture in ("75", "89"):
        # Match compiler.py::_compile_with_cache_cuda -> _preprocess ->
        # _NVRTCProgram.compile, without invoking the GPU-dependent cache API.
        compiler._preprocess("", common_options, architecture, "nvrtc")
        log = io.StringIO()
        options = common_options + ("--gpu-architecture=compute_" + architecture,)
        program = compiler._NVRTCProgram(source, "bundled_check.cu")
        try:
            ptx, _ = program.compile(options, log_stream=log)
        finally:
            # CuPy's program destructor releases NVRTC resources. Retaining it
            # would unnecessarily keep compiler programs alive for later checks.
            del program
        if not isinstance(ptx, bytes) or b"bundled_check" not in ptx:
            raise RuntimeError("NVRTC did not return the compiled reference kernel.")
        compilations.append({"target": "compute_" + architecture, "ptx_bytes": len(ptx),
                             "ptx_sha256": hashlib.sha256(ptx).hexdigest(),
                             "compile_log": log.getvalue()})
    major, minor = compiler.nvrtc.getVersion()
    return {"nvrtc_version": f"{major}.{minor}",
            "ptx_bytes": sum(row["ptx_bytes"] for row in compilations),
            "ptx_bytes_scope": "Sum of freshly compiled PTX bytes for both offline targets.",
            "compiled_headers": ["cuda_runtime.h", "cupy/carray.cuh", "cuda/std/limits"],
            "targets": [row["target"] for row in compilations],
            "compilations": compilations,
            "compiler_path": "cupy.cuda.compiler._preprocess and _NVRTCProgram.compile",
            "cache": "Bypassed; both targets compile freshly through CuPy's NVRTC binding.",
            "startup_path_verified": True,
            "test_only_preloads_before_compilation": False,
            "device_execution": "Not tested; these offline targets do not request a device or context."}


def _kernel_header_paths(root: Path) -> tuple[Path, Path]:
    """Inspect shipped headers without invoking a native library loader."""
    include_directory = root / "nvidia" / "cuda_runtime" / "include"
    cupy_include = root / "cupy" / "_core" / "include"
    expected = [include_directory / "cuda_runtime.h"] + [cupy_include / relative for relative in (
        "cupy/carray.cuh", "cupy/_cccl/libcudacxx/cuda/std/limits",
        "cupy/_cccl/cub/cub/cub.cuh", "cupy/_cccl/thrust/thrust/tuple.h")]
    for path in expected:
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise RuntimeError(f"Bundled CUDA/CuPy kernel header is missing or outside the bundle: {path}")
    return include_directory, cupy_include


def check_bundle() -> dict:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("The CUDA bundle check must run inside the frozen Windows application.")
    registration = configure_bundled_cuda()
    if registration["status"] != "configured":
        raise RuntimeError(f"Bundled CUDA registration failed: {registration['errors']}")
    root = Path(registration["bundled_root"])
    files = {Path(filename).name.lower(): Path(filename) for filename in registration["runtime_files"]}
    missing = [name for name in _REQUIRED_DLLS if name not in files]
    if missing:
        raise RuntimeError("Required CUDA DLLs are missing from the bundle: " + ", ".join(missing))
    # Actual desktop startup loads Qt before the health request imports CuPy.
    # Cover that native MSVC/DLL order too; no QApplication/window is needed.
    importlib.import_module("PySide6.QtWebEngineWidgets")
    # This MUST precede explicit native loads: otherwise preloading DLLs here
    # could hide a broken bootstrap that still fails during normal app startup.
    try:
        cp = importlib.import_module("cupy")
    except Exception as error:
        raise RuntimeError(f"CuPy native import failed after Qt native loading: {type(error).__name__}: {error}") from error
    # First compile through normal CuPy, in this fresh executable process. Do
    # not move the explicit inventory loads above this: loading builtins only
    # inside a test made 0.3.0 falsely pass while normal application use failed.
    include_directory, cupy_include = _kernel_header_paths(root)
    native_compiler = importlib.import_module("cupy.cuda.compiler")
    compiler = _compile_offline_ptx(native_compiler, include_directory, cupy_include)
    for module in ("cupy_backends.cuda.libs.cublas", "cupy.cuda.cufft",
                   "cupy_backends.cuda.libs.curand", "cupy_backends.cuda.libs.cusolver",
                   "cupy_backends.cuda.libs.cusparse", "cupy_backends.cuda.libs.nvrtc",
                   "cupyx.scipy.sparse.linalg"):
        importlib.import_module(module)
    # Explicit absolute loads prove shipped resources, rather than a toolkit on
    # the build machine, satisfy the native Windows dependency loader.
    loaded = {}
    records = []
    for name in _REQUIRED_DLLS:
        path = files[name]
        loaded[name] = ctypes.CDLL(str(path), winmode=0x00001100)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        records.append({"path": path.relative_to(root).as_posix(),
                        "bytes": path.stat().st_size, "sha256": digest})
    from cuda.pathfinder import find_nvidia_header_directory, load_nvidia_dynamic_lib
    located_libraries = {}
    for name in ("cudart", "nvrtc", "cublas", "cufft", "curand", "cusolver", "cusparse", "nvJitLink"):
        located = load_nvidia_dynamic_lib(name)
        path = Path(located.abs_path).resolve()
        if not path.is_relative_to(root):
            raise RuntimeError(f"cuda-pathfinder selected {name} outside the bundle: {path}")
        located_libraries[name] = {"path": path.relative_to(root).as_posix(), "found_via": located.found_via}
    headers = {}
    for name, filename in (("cudart", "cuda_runtime.h"), ("nvrtc", "nvrtc.h")):
        value = find_nvidia_header_directory(name)
        path = Path(value).resolve() if value else None
        if path is None or not path.is_relative_to(root) or not (path / filename).is_file():
            raise RuntimeError(f"Bundled {name} compilation headers could not be discovered: {value}")
        headers[name] = str(path)
    from . import __version__
    return {"status": "ok", "application_version": __version__, "cupy_version": cp.__version__,
            "scope": "Fresh normal startup, CuPy offline NVRTC compilation for compute_75/89 before test-only DLL loads, then bundled resource verification.",
            "device_execution": "Not tested; no NVIDIA device or driver is required for this packaging check.",
            "native_import_order": "PySide6.QtWebEngineWidgets before CuPy, as in desktop startup.",
            "registration": registration, "libraries": records, "pathfinder_libraries": located_libraries,
            "headers": {name: Path(path).relative_to(root).as_posix() for name, path in headers.items()},
            "cupy_kernel_headers": cupy_include.relative_to(root).as_posix(),
            "compiler": compiler}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cuda-bundle-smoke-test", action="store_true")
    parser.add_argument("--smoke-output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        receipt = check_bundle()
        exit_code = 0
    except Exception as error:
        receipt = {"status": "failed", "scope": "Windows bundled CUDA native packaging check",
                   "error": f"{type(error).__name__}: {error}", "details": traceback.format_exc(),
                   "registration": configure_bundled_cuda(), "device_execution": "Not tested."}
        exit_code = 1
    arguments.smoke_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.smoke_output.write_text(json.dumps(receipt, indent=2, allow_nan=False), "utf8")
    print(json.dumps(receipt, allow_nan=False))
    return exit_code
