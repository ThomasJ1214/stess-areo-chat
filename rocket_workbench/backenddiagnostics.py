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
import traceback


_ERROR_DETAIL_LIMIT = 12_000


def _bounded_details(value: str, limit: int) -> tuple[str, bool]:
    """Keep the final cause when a dependency emits a long DLL inventory first."""
    if len(value) <= limit:
        return value, False
    marker = "\n... diagnostic text truncated; beginning and final cause retained ...\n"
    remaining = limit - len(marker)
    head = remaining * 2 // 3
    return value[:head] + marker + value[-(remaining - head):], True


def _exception_details(exc: Exception) -> tuple[str, str, bool]:
    """Separate a short root cause from a bounded traceback without locals."""
    root = exc
    seen = {id(root)}
    compiler_log = None
    while True:
        message = str(root).strip()
        # CuPy wraps NVRTC's numeric status in CompileException with the actual
        # compiler log. Following its context alone loses the missing-DLL name.
        if compiler_log is None and message.lower().startswith("nvrtc:"):
            compiler_log = (type(root).__name__, message)
        next_cause = root.__cause__
        if next_cause is None and not root.__suppress_context__:
            next_cause = root.__context__
        if next_cause is None or id(next_cause) in seen:
            break
        seen.add(id(next_cause))
        root = next_cause
    message = str(root).strip()
    label = type(root).__name__
    if compiler_log is not None:
        label, message = compiler_log
    # Some CuPy releases place the original exception at the end of the banner
    # without preserving an exception chain. Its DLL inventory is not the cause.
    for marker in ("Original error:", "Original error was:"):
        if marker.lower() in message.lower():
            index = message.lower().rfind(marker.lower())
            message = message[index + len(marker):].strip()
            break
    cause, _ = _bounded_details(f"{label}: {message}", 900)
    details = "".join(traceback.TracebackException.from_exception(exc, capture_locals=False).format())
    details, truncated = _bounded_details(details, _ERROR_DETAIL_LIMIT)
    return cause, details, truncated


def _failure_reason(stage: str, cause: str, exc: Exception, runtime_setup: dict) -> tuple[str, str]:
    """Avoid advising driver changes for a missing library in our installer."""
    lowered = cause.lower()
    no_device = any(token in lowered for token in ("cudaerrornodevice", "no cuda-capable device", "no nvidia device"))
    driver_library = "nvcuda.dll" in lowered or "libcuda.so" in lowered
    driver_failure = driver_library or any(token in lowered for token in (
        "cudaerrorinsufficientdriver", "driver version is insufficient", "cudaerrorsystemdrivermismatch",
    ))
    missing_library = any(token in lowered for token in (
        "dll load failed", "could not be found", "could not be loaded", "cannot open shared object",
        "library not found", "failed to load", "specified module",
    ))
    missing_library = missing_library or (
        "failed to open" in lowered and (".dll" in lowered or ".so" in lowered)
    )
    missing_cupy = isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", None) == "cupy"
    source_environment = runtime_setup.get("status") in {"not_frozen", "not_windows"}
    omitted_runtime = runtime_setup.get("status") == "unavailable" and not runtime_setup.get("runtime_files")
    if stage == "import" and missing_cupy and (source_environment or omitted_runtime):
        if source_environment:
            return "optional_dependency", ("Optional CuPy is not installed in this source environment. "
                                           "Install the gpu extra for CUDA development, or use CPU/automatic mode. "
                                           "Numerical CUDA support is separate from 3D graphics.")
        return "optional_dependency", ("CuPy CUDA execution is not included in this application build. "
                                       "Use CPU/automatic mode, or install the standard GPU-enabled installer "
                                       "for a supported NVIDIA GPU and driver.")
    if no_device:
        return "no_device", ("No NVIDIA CUDA device was detected. AMD and Intel GPUs can render the viewport "
                             f"but cannot execute this CUDA solver. {cause}")
    if driver_failure:
        return "driver", (f"The NVIDIA CUDA driver could not initialize. {cause} "
                           "Check the compatible NVIDIA driver and restart the app after updating it.")
    if stage == "import" or missing_library:
        kind = "cupy_import" if isinstance(exc, ModuleNotFoundError) else "bundled_runtime"
        return kind, (f"The bundled CuPy CUDA runtime could not be loaded. {cause} "
                      "Open GPU diagnostics for the complete error and bundled-library paths. "
                      "If a bundled library is missing, reinstall the latest application build; "
                      "a manual CUDA Toolkit installation is not required.")
    if stage == "driver":
        return "driver", (f"The NVIDIA CUDA driver could not initialize. {cause} "
                           "Check the compatible NVIDIA driver and restart the app after updating it.")
    if "memoryallocation" in lowered or "out of memory" in lowered:
        return "device_memory", (f"CUDA device memory allocation failed. {cause} "
                                  "Free GPU memory or reduce the simulation grid before retrying.")
    if stage == "verification":
        return "verification", f"The CUDA numerical verification returned an invalid result. {cause}"
    return stage, (f"The CUDA execution check failed during {stage}. {cause} "
                   "Open GPU diagnostics for the complete error; use CPU or automatic mode to continue.")


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
        "failure_kind": None,
        "root_cause": None,
        "error_details": "",
        "error_details_truncated": False,
        "bundled_runtime": {},
    }
    try:
        from .bundled_cuda import configure_bundled_cuda
        result["bundled_runtime"] = configure_bundled_cuda()
        setup = result["bundled_runtime"]
        if setup.get("status") == "unavailable" and setup.get("runtime_files") and setup.get("errors"):
            raise OSError("Bundled CUDA initialization failed: " + "; ".join(setup["errors"]))
        import cupy as cp
        result["cupy_version"] = str(cp.__version__)
        result["probe_stage"] = "driver"
        result["driver_version"] = _version(int(cp.cuda.runtime.driverGetVersion()))
        result["probe_stage"] = "runtime"
        result["runtime_version"] = _version(int(cp.cuda.runtime.runtimeGetVersion()))
        result["probe_stage"] = "device_discovery"
        count = cp.cuda.runtime.getDeviceCount()
        if count == 0:
            result["failure_kind"] = "no_device"
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
        result["probe_stage"] = "allocation"
        # Elementwise arithmetic and a reduction exercise runtime allocation,
        # CUDA kernel compilation and actual device execution, not just enumeration.
        values = cp.asarray([1.0, 2.0, 3.0], dtype=cp.float64)
        result["probe_stage"] = "kernel"
        actual = float((values * values).sum().item())
        result["probe_stage"] = "synchronization"
        cp.cuda.Stream.null.synchronize()
        if not math.isfinite(actual) or actual != 14.0:
            result["probe_stage"] = "verification"
            raise RuntimeError("The CUDA verification reduction returned an unexpected value.")
        result.update(available=True, probe_stage="complete", reason="CUDA numerical execution check passed.")
    except Exception as exc:
        cause, details, truncated = _exception_details(exc)
        result["root_cause"] = cause
        result["error_details"] = details
        result["error_details_truncated"] = truncated
        result["failure_kind"], result["reason"] = _failure_reason(result["probe_stage"], cause, exc, result["bundled_runtime"])
    return result


def cuda_diagnostics() -> dict:
    """Return a copy so callers cannot mutate the cached hardware report."""
    return copy.deepcopy(_cuda_probe())
