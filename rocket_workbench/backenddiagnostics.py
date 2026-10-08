"""Cached, actual CUDA execution checks shared by the local API and solvers.

Rendering support is separate from NVIDIA CUDA numerical execution. The first
check performs a tiny allocation and compiled float64 reduction, then retains
the result until application restart so health polling does not compile kernels
or repeatedly initialize the driver.
"""
from __future__ import annotations

import copy
from functools import lru_cache
import math


def _version(number: int) -> str:
    return f"{number // 1000}.{(number % 1000) // 10}"


@lru_cache(maxsize=1)
def _cuda_probe() -> dict:
    result = {
        "available": False,
        "supported_vendor": "NVIDIA",
        "backend": "cupy-cuda",
        "check": "CUDA device allocation and compiled float64 reduction",
        "cached_until_restart": True,
        "probe_stage": "import",
        "cupy_version": None,
        "driver_version": None,
        "runtime_version": None,
        "devices": [],
        "reason": "",
    }
    try:
        import cupy as cp
        result["cupy_version"] = str(cp.__version__)
        result["probe_stage"] = "driver"
        result["driver_version"] = _version(int(cp.cuda.runtime.driverGetVersion()))
        result["runtime_version"] = _version(int(cp.cuda.runtime.runtimeGetVersion()))
        count = cp.cuda.runtime.getDeviceCount()
        if count == 0:
            result["reason"] = "No NVIDIA CUDA device was detected. AMD and Intel GPUs can render the viewport but cannot execute this CUDA solver."
            return result
        for index in range(count):
            props = cp.cuda.runtime.getDeviceProperties(index)
            name = props["name"]
            if isinstance(name, bytes):
                name = name.decode("utf8", errors="replace")
            result["devices"].append({
                "index": index,
                "name": str(name),
                "compute_capability": f"{props['major']}.{props['minor']}",
                "memory_total_bytes": int(props["totalGlobalMem"]),
            })
        result["selected_device"] = int(cp.cuda.runtime.getDevice())
        result["probe_stage"] = "allocation_and_kernel"
        # Elementwise arithmetic and a reduction exercise runtime allocation,
        # CUDA kernel compilation and actual device execution, not just enumeration.
        values = cp.asarray([1.0, 2.0, 3.0], dtype=cp.float64)
        actual = float((values * values).sum().item())
        cp.cuda.Stream.null.synchronize()
        if not math.isfinite(actual) or actual != 14.0:
            raise RuntimeError("The CUDA verification reduction returned an unexpected value.")
        result.update(available=True, probe_stage="complete", reason="CUDA numerical execution check passed.")
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {str(exc)[:800]}"
        if result["probe_stage"] == "import":
            result["reason"] += " The bundled CuPy CUDA runtime could not be loaded."
        else:
            result["reason"] += " Check the installed NVIDIA driver and restart the app after changing the driver."
    return result


def cuda_diagnostics() -> dict:
    """Return a copy so callers cannot mutate the cached hardware report."""
    return copy.deepcopy(_cuda_probe())
