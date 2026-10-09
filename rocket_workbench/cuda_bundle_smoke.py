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


def _compile_offline_ptx(nvrtc, include_directory: Path, cupy_include: Path) -> dict:
    """Compile a CUDA-runtime-header kernel using NVRTC, without a CUDA context."""
    program = ctypes.c_void_p()
    nvrtc.nvrtcCreateProgram.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p,
                                       ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
    nvrtc.nvrtcCompileProgram.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
    nvrtc.nvrtcGetProgramLogSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    nvrtc.nvrtcGetProgramLog.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    nvrtc.nvrtcGetPTXSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    nvrtc.nvrtcGetPTX.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    nvrtc.nvrtcDestroyProgram.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    nvrtc.nvrtcVersion.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    source = (b'#include <cuda_runtime.h>\n#include <cupy/carray.cuh>\n#include <cuda/std/limits>\n'
              b'extern "C" __global__ void bundled_check(double* x) { '
              b'x[threadIdx.x] *= cuda::std::numeric_limits<double>::digits > 0 ? 2.0 : 0.0; }\n')
    if nvrtc.nvrtcCreateProgram(ctypes.byref(program), source, b"bundled_check.cu", 0, None, None) != 0:
        raise RuntimeError("Bundled NVRTC could not create an offline compilation program.")
    try:
        include_paths = (include_directory, cupy_include,
                         cupy_include / "cupy" / "_cccl" / "libcudacxx")
        arguments = [b"--gpu-architecture=compute_75", b"--std=c++17"]
        arguments += [("--include-path=" + str(path)).encode("utf8") for path in include_paths]
        options = (ctypes.c_char_p * len(arguments))(*arguments)
        compilation_status = nvrtc.nvrtcCompileProgram(program, len(options), options)
        log_size = ctypes.c_size_t()
        nvrtc.nvrtcGetProgramLogSize(program, ctypes.byref(log_size))
        log = ctypes.create_string_buffer(max(1, log_size.value))
        nvrtc.nvrtcGetProgramLog(program, log)
        if compilation_status != 0:
            raise RuntimeError(f"Bundled offline NVRTC compilation failed ({compilation_status}): {log.value.decode('utf8', 'replace')}")
        ptx_size = ctypes.c_size_t()
        if nvrtc.nvrtcGetPTXSize(program, ctypes.byref(ptx_size)) != 0 or ptx_size.value <= 1:
            raise RuntimeError("NVRTC reported success but returned no compiled PTX.")
        ptx = ctypes.create_string_buffer(ptx_size.value)
        if nvrtc.nvrtcGetPTX(program, ptx) != 0 or b"bundled_check" not in ptx.value:
            raise RuntimeError("NVRTC did not return the compiled reference kernel.")
        major, minor = ctypes.c_int(), ctypes.c_int()
        if nvrtc.nvrtcVersion(ctypes.byref(major), ctypes.byref(minor)) != 0:
            raise RuntimeError("Bundled NVRTC version query failed.")
        return {"nvrtc_version": f"{major.value}.{minor.value}", "ptx_bytes": len(ptx.value),
                "ptx_sha256": hashlib.sha256(ptx.value).hexdigest(),
                "compile_log": log.value.decode("utf8", "replace"),
                "compiled_headers": ["cuda_runtime.h", "cupy/carray.cuh", "cuda/std/limits"],
                "target": "compute_75 (offline compilation target; no device requested)"}
    finally:
        nvrtc.nvrtcDestroyProgram(ctypes.byref(program))


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
    cupy_include = root / "cupy" / "_core" / "include"
    for relative in ("cupy/carray.cuh", "cupy/_cccl/libcudacxx/cuda/std/limits",
                     "cupy/_cccl/cub/cub/cub.cuh", "cupy/_cccl/thrust/thrust/tuple.h"):
        if not (cupy_include / relative).is_file():
            raise RuntimeError(f"Bundled CuPy kernel headers are missing: {relative}")
    compiler = _compile_offline_ptx(loaded["nvrtc64_120_0.dll"], Path(headers["cudart"]), cupy_include)
    from . import __version__
    return {"status": "ok", "application_version": __version__, "cupy_version": cp.__version__,
            "scope": "Frozen native imports, bundled CUDA DLL loading, header discovery and offline NVRTC PTX compilation.",
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
