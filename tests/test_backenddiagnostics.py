"""CUDA discovery must report actual failure stage and execute a device check."""
from types import SimpleNamespace
import builtins
import json
import sys

import numpy as np
import pytest

from rocket_workbench import backenddiagnostics
from rocket_workbench.api import capabilities
from rocket_workbench.solvers import cfd


@pytest.fixture(autouse=True)
def clear_probe(monkeypatch):
    monkeypatch.setitem(sys.modules, "rocket_workbench.bundled_cuda", SimpleNamespace(
        configure_bundled_cuda=lambda: {
            "status": "not_frozen", "bundled_root": None, "dll_directories": [],
            "cuda_path": None, "errors": [], "runtime_files": [],
        },
    ))
    backenddiagnostics._cuda_probe.cache_clear()
    yield
    backenddiagnostics._cuda_probe.cache_clear()


def _fake_cupy(*, count=1, asarray=np.asarray):
    return SimpleNamespace(
        __version__="test-version",
        float64=np.float64,
        asarray=asarray,
        cuda=SimpleNamespace(
            runtime=SimpleNamespace(
                driverGetVersion=lambda: 12080,
                runtimeGetVersion=lambda: 12060,
                getDeviceCount=lambda: count,
                getDevice=lambda: 0,
                getDeviceProperties=lambda index: {
                    "name": b"Test device", "major": 8, "minor": 6,
                    "totalGlobalMem": 8 * 1024**3,
                },
            ),
            Stream=SimpleNamespace(null=SimpleNamespace(synchronize=lambda: None)),
        ),
    )


def test_missing_optional_cupy_in_source_has_precise_reason_and_explicit_gpu_does_not_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "cupy", None)
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert not diagnostic["available"] and diagnostic["probe_stage"] == "import"
    assert "ModuleNotFoundError" in diagnostic["root_cause"]
    assert "Optional CuPy is not installed" in diagnostic["reason"]
    assert diagnostic["failure_kind"] == "optional_dependency"
    assert "reinstall" not in diagnostic["reason"]
    xp, name, warnings = cfd._backend("auto")
    assert xp is np and name == "numpy-cpu"
    assert diagnostic["reason"] in warnings[0]
    with pytest.raises(RuntimeError, match="failed at import"):
        cfd._backend("gpu")


@pytest.mark.parametrize("status,files,expected_kind", [
    ("unavailable", [], "optional_dependency"),
    ("configured", ["cudart64_12.dll"], "cupy_import"),
])
def test_absent_cupy_distinguishes_cpu_build_from_missing_package_in_cuda_bundle(monkeypatch, status, files, expected_kind):
    monkeypatch.setitem(sys.modules, "cupy", None)
    monkeypatch.setitem(sys.modules, "rocket_workbench.bundled_cuda", SimpleNamespace(
        configure_bundled_cuda=lambda: {"status": status, "runtime_files": files, "errors": []},
    ))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["failure_kind"] == expected_kind
    assert ("reinstall" in diagnostic["reason"]) == (status == "configured")


def test_kernel_failure_is_not_reported_as_available_gpu(monkeypatch):
    def missing_kernel(*args, **kwargs):
        raise RuntimeError("NVRTC library could not be loaded")
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=missing_kernel))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert not diagnostic["available"]
    assert diagnostic["probe_stage"] == "allocation"
    assert diagnostic["failure_kind"] == "bundled_runtime"
    assert "NVRTC library could not be loaded" in diagnostic["reason"]
    assert diagnostic["driver_version"] == "12.8"
    assert diagnostic["runtime_version"] == "12.6"
    assert diagnostic["devices"][0]["memory_total_bytes"] == 8 * 1024**3
    health = capabilities()
    assert not health["gpu_compute"]
    assert health["gpu_diagnostics"] == diagnostic


def test_no_device_explains_supported_numerical_vendor(monkeypatch):
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(count=0))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert not diagnostic["available"] and diagnostic["devices"] == []
    assert "AMD and Intel" in diagnostic["reason"]
    assert diagnostic["failure_kind"] == "no_device"


def test_success_executes_kernel_once_and_cached_report_is_immutable(monkeypatch):
    allocations = []
    def record_array(*args, **kwargs):
        allocations.append(args[0])
        return np.asarray(*args, **kwargs)
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=record_array))
    first = backenddiagnostics.cuda_diagnostics()
    assert first["available"] and first["probe_stage"] == "complete"
    assert first["devices"][0]["name"] == "Test device"
    first["devices"][0]["name"] = "Caller mutation"
    second = backenddiagnostics.cuda_diagnostics()
    assert second["devices"][0]["name"] == "Test device"
    assert len(allocations) == 1


def test_wrong_kernel_result_fails_probe(monkeypatch):
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=lambda *args, **kwargs: np.array([0.0])))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert "unexpected value" in diagnostic["reason"]
    assert diagnostic["failure_kind"] == "verification"


def _fail_cupy_import(monkeypatch, error):
    original_import = builtins.__import__
    def intercept(name, *args, **kwargs):
        if name == "cupy":
            raise error
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", intercept)


def test_long_cupy_banner_preserves_original_dll_error_and_bounded_details(monkeypatch):
    banner = "Failed to import CuPy.\nDLL dependencies:\n" + "MSVCP140.dll -> packaged path\n" * 700
    original = "DLL load failed while importing core: cudart64_12.dll could not be found"
    _fail_cupy_import(monkeypatch, ImportError(banner + "\nOriginal error:\n" + original))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["failure_kind"] == "bundled_runtime"
    assert original in diagnostic["root_cause"]
    assert original in diagnostic["reason"]
    assert "MSVCP140.dll" not in diagnostic["reason"]
    assert "manual CUDA Toolkit installation is not required" in diagnostic["reason"]
    assert diagnostic["error_details_truncated"]
    assert len(diagnostic["error_details"]) <= 12_000
    assert "Failed to import CuPy" in diagnostic["error_details"]
    assert original in diagnostic["error_details"]
    json.dumps(diagnostic, allow_nan=False)


def test_chained_import_failure_reports_deepest_cause_not_outer_inventory(monkeypatch):
    root = OSError("[WinError 126] nvrtc64_120_0.dll could not be loaded")
    error = ImportError("Failed to import CuPy\n" + "DLL dependencies\n" * 100)
    error.__cause__ = root
    _fail_cupy_import(monkeypatch, error)
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["root_cause"] == f"OSError: {root}"
    assert str(root) in diagnostic["reason"]
    assert "direct cause" in diagnostic["error_details"]
    assert diagnostic["failure_kind"] == "bundled_runtime"


def test_driver_problem_is_distinct_from_missing_application_library(monkeypatch):
    cp = _fake_cupy()
    def incompatible_driver():
        raise RuntimeError("cudaErrorInsufficientDriver: CUDA driver version is insufficient")
    cp.cuda.runtime.driverGetVersion = incompatible_driver
    monkeypatch.setitem(sys.modules, "cupy", cp)
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["failure_kind"] == "driver"
    assert diagnostic["probe_stage"] == "driver"
    assert "compatible NVIDIA driver" in diagnostic["reason"]
    assert "reinstall the latest application build" not in diagnostic["reason"]


def test_missing_runtime_after_cupy_import_is_reported_as_packaged_runtime(monkeypatch):
    cp = _fake_cupy()
    def unavailable_runtime():
        raise OSError("cudart64_12.dll could not be loaded")
    cp.cuda.runtime.runtimeGetVersion = unavailable_runtime
    monkeypatch.setitem(sys.modules, "cupy", cp)
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["failure_kind"] == "bundled_runtime"
    assert diagnostic["probe_stage"] == "runtime"
    assert diagnostic["driver_version"] == "12.8"


@pytest.mark.parametrize("library,expected_kind", [
    ("nvcuda.dll", "driver"), ("cudart64_12.dll", "bundled_runtime"),
])
def test_lazy_dll_load_during_driver_query_identifies_library_owner(monkeypatch, library, expected_kind):
    cp = _fake_cupy()
    def missing_library():
        raise OSError(f"DLL load failed: {library} could not be found")
    cp.cuda.runtime.driverGetVersion = missing_library
    monkeypatch.setitem(sys.modules, "cupy", cp)
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["failure_kind"] == expected_kind
    assert library in diagnostic["root_cause"]


def test_memory_failure_suggests_smaller_grid_instead_of_toolkit_install(monkeypatch):
    def insufficient_memory(*args, **kwargs):
        raise RuntimeError("cudaErrorMemoryAllocation: out of memory")
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=insufficient_memory))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["probe_stage"] == "allocation"
    assert diagnostic["failure_kind"] == "device_memory"
    assert "reduce the simulation grid" in diagnostic["reason"]


def test_actual_kernel_failure_is_separate_from_allocation(monkeypatch):
    class KernelFailure:
        def __mul__(self, other):
            raise RuntimeError("Compiled CUDA multiplication could not execute")
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=lambda *args, **kwargs: KernelFailure()))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["probe_stage"] == "kernel"
    assert diagnostic["failure_kind"] == "kernel"
    assert "multiplication could not execute" in diagnostic["root_cause"]


def test_nvrtc_compilation_error_is_not_mistaken_for_a_missing_library(monkeypatch):
    class CompileFailure:
        def __mul__(self, other):
            raise RuntimeError("NVRTC_ERROR_COMPILATION: unsupported GPU architecture")
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=lambda *args, **kwargs: CompileFailure()))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["failure_kind"] == "kernel"
    assert "reinstall" not in diagnostic["reason"]


def test_nvrtc_wrapper_preserves_missing_builtins_log_instead_of_numeric_status(monkeypatch):
    class CompileException(RuntimeError):
        pass

    class KernelFailure:
        def __mul__(self, other):
            try:
                raise RuntimeError("NVRTC_ERROR_BUILTIN_OPERATION_FAILURE (7)")
            except RuntimeError:
                raise CompileException(
                    "nvrtc: error: failed to open nvrtc-builtins64_129.dll.\n"
                    "Make sure that nvrtc-builtins64_129.dll is installed correctly."
                )

    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=lambda *args, **kwargs: KernelFailure()))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["probe_stage"] == "kernel"
    assert diagnostic["failure_kind"] == "bundled_runtime"
    assert "failed to open nvrtc-builtins64_129.dll" in diagnostic["root_cause"]
    assert "nvrtc-builtins64_129.dll" in diagnostic["reason"]
    assert "compatible NVIDIA driver" not in diagnostic["reason"]
    assert "NVRTC_ERROR_BUILTIN_OPERATION_FAILURE" in diagnostic["error_details"]


def test_compiler_log_keeps_architecture_failure_distinct_from_missing_dll(monkeypatch):
    class CompileFailure:
        def __mul__(self, other):
            try:
                raise RuntimeError("NVRTC_ERROR_COMPILATION (6)")
            except RuntimeError:
                raise RuntimeError("nvrtc: error: invalid value for --gpu-architecture")

    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=lambda *args, **kwargs: CompileFailure()))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["failure_kind"] == "kernel"
    assert "invalid value for --gpu-architecture" in diagnostic["root_cause"]
    assert "reinstall" not in diagnostic["reason"]


def test_failed_bundled_preload_stops_before_driver_or_kernel(monkeypatch):
    calls = []
    cp = _fake_cupy()
    cp.cuda.runtime.driverGetVersion = lambda: calls.append("driver")
    monkeypatch.setitem(sys.modules, "cupy", cp)
    monkeypatch.setitem(sys.modules, "rocket_workbench.bundled_cuda", SimpleNamespace(
        configure_bundled_cuda=lambda: {
            "status": "unavailable", "runtime_files": ["nvrtc64_120_0.dll"],
            "errors": ["Missing bundled nvrtc-builtins64_129.dll"],
        },
    ))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert diagnostic["probe_stage"] == "import"
    assert diagnostic["failure_kind"] == "bundled_runtime"
    assert "nvrtc-builtins64_129.dll" in diagnostic["root_cause"]
    assert not calls


def test_bundled_runtime_file_report_is_retained_and_cached_without_caller_mutation(monkeypatch):
    calls = []
    files = [{"path": "_internal/nvidia/cuda_runtime/bin/cudart64_12.dll", "exists": True}]
    def configure():
        calls.append(True)
        return {"status": "configured", "runtime_files": files, "errors": []}
    monkeypatch.setitem(sys.modules, "rocket_workbench.bundled_cuda", SimpleNamespace(configure_bundled_cuda=configure))
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy())
    first = backenddiagnostics.cuda_diagnostics()
    assert first["bundled_runtime"]["runtime_files"][0]["exists"]
    first["bundled_runtime"]["runtime_files"][0]["exists"] = False
    assert backenddiagnostics.cuda_diagnostics()["bundled_runtime"]["runtime_files"][0]["exists"]
    assert len(calls) == 1
