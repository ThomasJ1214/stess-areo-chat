"""CUDA discovery must report actual failure stage and execute a device check."""
from types import SimpleNamespace

import numpy as np
import pytest

from rocket_workbench import backenddiagnostics
from rocket_workbench.api import capabilities
from rocket_workbench.solvers import cfd


@pytest.fixture(autouse=True)
def clear_probe():
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


def test_missing_cupy_has_precise_reason_and_explicit_gpu_does_not_fallback(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "cupy", None)
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert not diagnostic["available"] and diagnostic["probe_stage"] == "import"
    assert "ModuleNotFoundError" in diagnostic["reason"]
    assert "bundled CuPy CUDA runtime" in diagnostic["reason"]
    xp, name, warnings = cfd._backend("auto")
    assert xp is np and name == "numpy-cpu"
    assert diagnostic["reason"] in warnings[0]
    with pytest.raises(RuntimeError, match="failed at import"):
        cfd._backend("gpu")


def test_kernel_failure_is_not_reported_as_available_gpu(monkeypatch):
    import sys
    def missing_kernel(*args, **kwargs):
        raise RuntimeError("NVRTC library could not be loaded")
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=missing_kernel))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert not diagnostic["available"]
    assert diagnostic["probe_stage"] == "allocation_and_kernel"
    assert "NVRTC library could not be loaded" in diagnostic["reason"]
    assert diagnostic["driver_version"] == "12.8"
    assert diagnostic["runtime_version"] == "12.6"
    assert diagnostic["devices"][0]["memory_total_bytes"] == 8 * 1024**3
    health = capabilities()
    assert not health["gpu_compute"]
    assert health["gpu_diagnostics"] == diagnostic


def test_no_device_explains_supported_numerical_vendor(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(count=0))
    diagnostic = backenddiagnostics.cuda_diagnostics()
    assert not diagnostic["available"] and diagnostic["devices"] == []
    assert "AMD and Intel" in diagnostic["reason"]


def test_success_executes_kernel_once_and_cached_report_is_immutable(monkeypatch):
    import sys
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
    import sys
    monkeypatch.setitem(sys.modules, "cupy", _fake_cupy(asarray=lambda *args, **kwargs: np.array([0.0])))
    assert "unexpected value" in backenddiagnostics.cuda_diagnostics()["reason"]
