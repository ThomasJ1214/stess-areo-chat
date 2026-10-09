"""Frozen CUDA bootstrap isolation and native-resource discovery boundaries."""
from __future__ import annotations

import importlib
import ctypes
import os
from pathlib import Path
import site
import sys

import pytest

import rocket_workbench.bundled_cuda as bundled_cuda


@pytest.fixture
def bootstrap(monkeypatch):
    # A real process initializes once. Each test represents a fresh process.
    module = importlib.reload(bundled_cuda)
    original_site_packages = site.getsitepackages
    monkeypatch.setattr(site, "getsitepackages", original_site_packages)
    yield module
    module._dll_directory_handles.clear()
    module._native_library_handles.clear()
    module._configuration = None


def _frozen_windows(monkeypatch, root: Path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")


def _write_compiler_pair(root: Path, *, builtins: bool = True) -> Path:
    compiler = root / "nvidia" / "cuda_nvrtc" / "bin"
    compiler.mkdir(parents=True)
    (compiler / "nvrtc64_120_0.dll").write_bytes(b"compiler")
    if builtins:
        (compiler / "nvrtc-builtins64_129.dll").write_bytes(b"minor-matched builtins")
    return compiler


def _mock_native_loader(monkeypatch, *, version=(12, 9), status=0, failing_name=None):
    """Stand in for the platform loader; native compilation is checked on Windows."""
    loaded = []
    handles = []

    class VersionQuery:
        def __call__(self, major, minor):
            ctypes.cast(major, ctypes.POINTER(ctypes.c_int))[0] = version[0]
            ctypes.cast(minor, ctypes.POINTER(ctypes.c_int))[0] = version[1]
            return status

    class Library:
        def __init__(self):
            self.nvrtcVersion = VersionQuery()

    def load(path, *, winmode):
        loaded.append((path, winmode))
        if Path(path).name == failing_name:
            raise OSError("Windows native loader rejected this resource")
        handle = Library()
        handles.append(handle)
        return handle

    monkeypatch.setattr(ctypes, "CDLL", load)
    return loaded, handles


def test_bootstrap_exposes_real_frozen_headers_and_retains_native_search_handles(bootstrap, monkeypatch, tmp_path):
    root = tmp_path / "Rocket Workbench user path"
    runtime = root / "nvidia" / "cuda_runtime"
    compiler = _write_compiler_pair(root)
    for directory in (runtime / "bin", runtime / "include"):
        directory.mkdir(parents=True)
    (runtime / "bin" / "cudart64_12.dll").write_bytes(b"runtime")
    (runtime / "include" / "cuda_runtime.h").write_text("runtime header")
    unrelated = root / "user-project"
    unrelated.mkdir()
    (unrelated / "untrusted.dll").write_bytes(b"not a toolkit resource")
    monkeypatch.setenv("CUDA_PATH", "existing user setting")
    monkeypatch.setenv("PATH", "existing process search path")
    _frozen_windows(monkeypatch, root)
    loaded, native_handles = _mock_native_loader(monkeypatch)
    calls = []
    handles = []

    def add_directory(path):
        calls.append(path)
        handle = object()
        handles.append(handle)
        return handle

    monkeypatch.setattr(os, "add_dll_directory", add_directory, raising=False)
    previous_roots = site.getsitepackages()
    explicit_roots = site.getsitepackages(["explicit prefix"])
    receipt = bootstrap.configure_bundled_cuda()
    assert receipt["status"] == "configured"
    assert set(calls) == {str(root), str(runtime / "bin"), str(compiler)}
    assert bootstrap._dll_directory_handles == handles
    # This is the important loader sequence: the minor-matched builtins are in
    # Windows' module list before NVRTC can lazily request them by basename.
    assert loaded == [(str(compiler / "nvrtc-builtins64_129.dll"), 0x00001100),
                      (str(compiler / "nvrtc64_120_0.dll"), 0x00001100)]
    assert bootstrap._native_library_handles == native_handles
    assert receipt["native_preloads"] == [
        {"role": "nvrtc_builtins", "path": str(compiler / "nvrtc-builtins64_129.dll")},
        {"role": "nvrtc", "path": str(compiler / "nvrtc64_120_0.dll")}]
    assert receipt["nvrtc"]["version"] == "12.9"
    assert os.environ["CUDA_PATH"] == "existing user setting"
    assert os.environ["PATH"] == "existing process search path"
    assert all(root in site.getsitepackages() for root in previous_roots)
    assert site.getsitepackages()[0] == str(root)
    assert site.getsitepackages(["explicit prefix"]) == explicit_roots
    # Independent resource lookup through the public site API used by the
    # upstream pathfinder now sees the actual shipped header, not build venvs.
    found_headers = [Path(root) / "nvidia" / "cuda_runtime" / "include" / "cuda_runtime.h"
                     for root in site.getsitepackages()]
    assert next(path for path in found_headers if path.is_file()).read_text() == "runtime header"
    receipt["dll_directories"].clear()
    receipt["native_preloads"].clear()
    assert bootstrap.configure_bundled_cuda()["dll_directories"]
    assert len(bootstrap.configure_bundled_cuda()["native_preloads"]) == 2
    assert len(calls) == 3  # Idempotence avoids accumulating native registrations.
    assert len(loaded) == 2  # Nor are the lifetime-held libraries reloaded.


def test_bootstrap_does_not_register_symlinked_dlls_outside_the_bundle(bootstrap, monkeypatch, tmp_path):
    root = tmp_path / "bundle"
    native = root / "nvidia" / "cuda_runtime" / "bin"
    native.mkdir(parents=True)
    foreign = tmp_path / "foreign.dll"
    foreign.write_bytes(b"foreign native code")
    try:
        (native / "cudart64_12.dll").symlink_to(foreign)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links.")
    _frozen_windows(monkeypatch, root)
    calls = []
    monkeypatch.setattr(os, "add_dll_directory", lambda path: calls.append(path), raising=False)
    receipt = bootstrap.configure_bundled_cuda()
    assert receipt["status"] == "unavailable"
    assert not receipt["runtime_files"]
    assert calls == []


def test_directory_registration_failure_is_reported_without_disabling_cpu_startup(bootstrap, monkeypatch, tmp_path):
    native = tmp_path / "nvidia" / "cuda_runtime" / "bin"
    native.mkdir(parents=True)
    (native / "cudart64_12.dll").write_bytes(b"runtime")
    _frozen_windows(monkeypatch, tmp_path)

    def denied(path):
        raise OSError("native loader denied directory")

    monkeypatch.setattr(os, "add_dll_directory", denied, raising=False)
    receipt = bootstrap.configure_bundled_cuda()
    assert receipt["status"] == "unavailable"
    assert "native loader denied directory" in receipt["errors"][0]
    assert receipt["dll_directories"] == []
    assert receipt["native_preloads"] == []


def test_missing_nvrtc_builtins_reports_exact_resource_without_trying_a_global_toolkit(bootstrap, monkeypatch, tmp_path):
    _write_compiler_pair(tmp_path, builtins=False)
    _frozen_windows(monkeypatch, tmp_path)
    monkeypatch.setattr(os, "add_dll_directory", lambda path: object(), raising=False)
    loaded, _ = _mock_native_loader(monkeypatch)
    receipt = bootstrap.configure_bundled_cuda()
    assert receipt["status"] == "unavailable"
    assert "nvrtc-builtins64_129.dll" in receipt["errors"][0]
    assert "missing" in receipt["errors"][0]
    assert receipt["nvrtc"]["expected_version"] == "12.9"
    assert receipt["native_preloads"] == []
    assert loaded == []


def test_nvrtc_different_minor_is_rejected_even_though_compiler_basename_matches(bootstrap, monkeypatch, tmp_path):
    _write_compiler_pair(tmp_path)
    _frozen_windows(monkeypatch, tmp_path)
    monkeypatch.setattr(os, "add_dll_directory", lambda path: object(), raising=False)
    _mock_native_loader(monkeypatch, version=(12, 8))
    receipt = bootstrap.configure_bundled_cuda()
    assert receipt["status"] == "unavailable"
    assert receipt["nvrtc"]["version"] == "12.8"
    assert "does not match" in receipt["errors"][0]
    assert "12.9" in receipt["errors"][0]


@pytest.mark.parametrize("failed_name,completed_loads", [
    ("nvrtc-builtins64_129.dll", 0), ("nvrtc64_120_0.dll", 1)])
def test_native_preload_failure_is_reported_and_successful_handles_remain_alive(bootstrap, monkeypatch, tmp_path, failed_name, completed_loads):
    _write_compiler_pair(tmp_path)
    _frozen_windows(monkeypatch, tmp_path)
    monkeypatch.setattr(os, "add_dll_directory", lambda path: object(), raising=False)
    loaded, handles = _mock_native_loader(monkeypatch, failing_name=failed_name)
    receipt = bootstrap.configure_bundled_cuda()
    assert receipt["status"] == "unavailable"
    assert failed_name in receipt["errors"][0]
    assert "native loader rejected" in receipt["errors"][0]
    assert len(receipt["native_preloads"]) == completed_loads
    assert bootstrap._native_library_handles == handles
    assert all(Path(path).is_relative_to(tmp_path) for path, flags in loaded)
    # A cached failure cannot silently retry or become a success later.
    before = len(loaded)
    receipt["errors"].clear()
    assert bootstrap.configure_bundled_cuda()["errors"]
    assert len(loaded) == before


def test_nvrtc_version_query_failure_is_not_a_configured_bundle(bootstrap, monkeypatch, tmp_path):
    _write_compiler_pair(tmp_path)
    _frozen_windows(monkeypatch, tmp_path)
    monkeypatch.setattr(os, "add_dll_directory", lambda path: object(), raising=False)
    _mock_native_loader(monkeypatch, status=6)
    receipt = bootstrap.configure_bundled_cuda()
    assert receipt["status"] == "unavailable"
    assert "nvrtcVersion failed with status 6" in receipt["errors"][0]


def test_duplicate_nvrtc_compilers_do_not_select_an_arbitrary_bundle_copy(bootstrap, monkeypatch, tmp_path):
    _write_compiler_pair(tmp_path)
    other = tmp_path / "cuda" / "alternate"
    other.mkdir(parents=True)
    (other / "nvrtc64_120_0.dll").write_bytes(b"different compiler")
    _frozen_windows(monkeypatch, tmp_path)
    monkeypatch.setattr(os, "add_dll_directory", lambda path: object(), raising=False)
    loaded, _ = _mock_native_loader(monkeypatch)
    receipt = bootstrap.configure_bundled_cuda()
    assert receipt["status"] == "unavailable"
    assert "found 2" in receipt["errors"][0]
    assert "ambiguous" in receipt["errors"][0]
    assert loaded == []


def test_source_execution_does_not_change_site_discovery_or_native_environment(bootstrap, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    original = site.getsitepackages
    previous_path = os.environ.get("PATH")
    previous_cuda = os.environ.get("CUDA_PATH")
    assert bootstrap.configure_bundled_cuda()["status"] == "not_frozen"
    assert site.getsitepackages is original
    assert os.environ.get("PATH") == previous_path
    assert os.environ.get("CUDA_PATH") == previous_cuda


def test_native_packaging_check_refuses_non_frozen_execution_and_records_the_failure(tmp_path):
    from rocket_workbench.cuda_bundle_smoke import main
    import json
    output = tmp_path / "cuda-receipt.json"
    assert main(["--cuda-bundle-smoke-test", "--smoke-output", str(output)]) == 1
    receipt = json.loads(output.read_text())
    assert receipt["status"] == "failed"
    assert "frozen Windows application" in receipt["error"]
    assert receipt["device_execution"] == "Not tested."
