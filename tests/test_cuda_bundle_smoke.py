"""Regression for an importable NVRTC that cannot load its builtin compiler.

The Windows release must compile through the normal CuPy path before a test
explicitly loads the inventory. The original gate preloaded every DLL first,
which accidentally repaired normal startup only in the test process.
"""
from __future__ import annotations

import hashlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

from rocket_workbench import cuda_bundle_smoke as smoke


@pytest.fixture
def frozen_bundle(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    root.mkdir()
    files = []
    for name in smoke._REQUIRED_DLLS:
        filename = root / "nvidia" / "cuda_nvrtc" / "bin" / name
        filename.parent.mkdir(parents=True, exist_ok=True)
        filename.write_bytes(b"native library fixture")
        files.append(str(filename))
    header_files = (
        "nvidia/cuda_runtime/include/cuda_runtime.h",
        "nvidia/cuda_nvrtc/include/nvrtc.h",
        "cupy/_core/include/cupy/carray.cuh",
        "cupy/_core/include/cupy/_cccl/libcudacxx/cuda/std/limits",
        "cupy/_core/include/cupy/_cccl/cub/cub/cub.cuh",
        "cupy/_core/include/cupy/_cccl/thrust/thrust/tuple.h",
    )
    for relative in header_files:
        filename = root / relative
        filename.parent.mkdir(parents=True, exist_ok=True)
        filename.write_text("header fixture", "utf8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(smoke, "configure_bundled_cuda", lambda: {
        "status": "configured", "bundled_root": str(root), "runtime_files": files,
        "native_preloads": [{"role": "nvrtc_builtins", "path": files[8]}], "errors": [],
    })
    return root


def _native_imports(monkeypatch, compiler, events):
    real_import = smoke.importlib.import_module

    def import_module(name, package=None):
        if name == "PySide6.QtWebEngineWidgets":
            events.append("qt-import")
            return SimpleNamespace()
        if name == "cupy":
            events.append("cupy-import")
            return SimpleNamespace(__version__="14.2.0")
        if name == "cupy.cuda.compiler":
            events.append("compiler-import")
            return compiler
        if name.startswith(("cupy.", "cupy_backends.", "cupyx.")):
            events.append("native-import:" + name)
            return SimpleNamespace()
        return real_import(name, package)

    monkeypatch.setattr(smoke.importlib, "import_module", import_module)


def test_importable_nvrtc_missing_builtins_fails_before_inventory_preloads(frozen_bundle, monkeypatch):
    events = []

    def missing_builtins(source, options, architecture, backend):
        events.append("first-compilation")
        raise RuntimeError("nvrtc: error: failed to open nvrtc-builtins64_129.dll.")

    compiler = SimpleNamespace(_preprocess=missing_builtins)
    _native_imports(monkeypatch, compiler, events)
    # If this is called first, the old test silently fixes the user's missing
    # builtins. Failure must propagate before any inventory-only native load.
    monkeypatch.setattr(smoke.ctypes, "CDLL", lambda *args, **kwargs: events.append("inventory-preload"))
    with pytest.raises(RuntimeError, match="nvrtc-builtins64_129.dll"):
        smoke.check_bundle()
    assert events == ["qt-import", "cupy-import", "compiler-import", "first-compilation"]


def test_failed_first_compilation_receipt_keeps_builtin_error(frozen_bundle, monkeypatch, tmp_path):
    events = []

    def missing_builtins(*args):
        raise RuntimeError("NVRTC_ERROR_BUILTIN_OPERATION_FAILURE (7): failed to open nvrtc-builtins64_129.dll")

    _native_imports(monkeypatch, SimpleNamespace(_preprocess=missing_builtins), events)
    output = tmp_path / "receipt.json"
    assert smoke.main(["--cuda-bundle-smoke-test", "--smoke-output", str(output)]) == 1
    import json
    receipt = json.loads(output.read_text("utf8"))
    assert receipt["status"] == "failed"
    assert "NVRTC_ERROR_BUILTIN_OPERATION_FAILURE (7)" in receipt["error"]
    assert "nvrtc-builtins64_129.dll" in receipt["details"]
    assert receipt["device_execution"] == "Not tested."


def test_normal_cupy_compilation_for_both_architectures_precedes_resource_loads(frozen_bundle, monkeypatch):
    events = []
    compiled = []

    def preprocess(source, options, architecture, backend):
        assert source == "" and backend == "nvrtc"
        events.append("preprocess:" + architecture)
        return "// fresh NVRTC preprocessing"

    class Program:
        def __init__(self, source, name):
            assert '#include <cuda_runtime.h>' in source
            assert '#include <cupy/carray.cuh>' in source
            assert '#include <cuda/std/limits>' in source
            assert name == "bundled_check.cu"

        def compile(self, options, log_stream):
            target = next(option.split("=", 1)[1] for option in options if option.startswith("--gpu-architecture="))
            events.append("compile:" + target)
            ptx = b"// compiled PTX reference: bundled_check " + target.encode("ascii")
            compiled.append(ptx)
            log_stream.write("actual compiler log for " + target)
            return ptx, None

    compiler = SimpleNamespace(_preprocess=preprocess, _NVRTCProgram=Program,
                               nvrtc=SimpleNamespace(getVersion=lambda: (12, 9)))
    _native_imports(monkeypatch, compiler, events)
    monkeypatch.setattr(smoke.ctypes, "CDLL", lambda *args, **kwargs: events.append("inventory-preload"))
    pathfinder = ModuleType("cuda.pathfinder")
    native_by_name = {"cudart": "cudart64_12.dll", "nvrtc": "nvrtc64_120_0.dll",
                      "cublas": "cublas64_12.dll", "cufft": "cufft64_11.dll",
                      "curand": "curand64_10.dll", "cusolver": "cusolver64_11.dll",
                      "cusparse": "cusparse64_12.dll", "nvJitLink": "nvjitlink_120_0.dll"}
    pathfinder.load_nvidia_dynamic_lib = lambda name: SimpleNamespace(
        abs_path=str(frozen_bundle / "nvidia" / "cuda_nvrtc" / "bin" / native_by_name[name]),
        found_via="trusted bundle fixture")
    pathfinder.find_nvidia_header_directory = lambda name: str(
        frozen_bundle / "nvidia" / ("cuda_runtime" if name == "cudart" else "cuda_nvrtc") / "include")
    monkeypatch.setitem(sys.modules, "cuda.pathfinder", pathfinder)
    receipt = smoke.check_bundle()
    assert events[:7] == ["qt-import", "cupy-import", "compiler-import", "preprocess:75", "compile:compute_75",
                          "preprocess:89", "compile:compute_89"]
    assert events.count("inventory-preload") == 10
    assert receipt["compiler"]["targets"] == ["compute_75", "compute_89"]
    assert receipt["compiler"]["startup_path_verified"] is True
    assert receipt["compiler"]["test_only_preloads_before_compilation"] is False
    assert receipt["compiler"]["ptx_bytes"] == sum(map(len, compiled))
    assert [row["ptx_sha256"] for row in receipt["compiler"]["compilations"]] == [
        hashlib.sha256(ptx).hexdigest() for ptx in compiled]
    assert "Not tested" in receipt["device_execution"]


def test_success_without_reference_kernel_is_rejected_before_inventory(frozen_bundle, monkeypatch):
    events = []
    compiler = SimpleNamespace(_preprocess=lambda *args: "",
                               _NVRTCProgram=lambda *args: SimpleNamespace(compile=lambda *args, **kwargs: (b"", None)))
    _native_imports(monkeypatch, compiler, events)
    monkeypatch.setattr(smoke.ctypes, "CDLL", lambda *args, **kwargs: events.append("inventory-preload"))
    with pytest.raises(RuntimeError, match="compiled reference kernel"):
        smoke.check_bundle()
    assert "inventory-preload" not in events


def test_offline_compilation_does_not_accept_headers_outside_bundle(frozen_bundle, tmp_path):
    header = frozen_bundle / "nvidia" / "cuda_runtime" / "include" / "cuda_runtime.h"
    foreign = tmp_path / "foreign-header.h"
    foreign.write_text("not shipped", "utf8")
    header.unlink()
    try:
        header.symlink_to(foreign)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links.")
    with pytest.raises(RuntimeError, match="missing or outside the bundle"):
        smoke._kernel_header_paths(frozen_bundle)
