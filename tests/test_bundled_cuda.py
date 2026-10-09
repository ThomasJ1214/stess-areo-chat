"""Frozen CUDA bootstrap isolation and native-resource discovery boundaries."""
from __future__ import annotations

import importlib
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
    module._configuration = None


def _frozen_windows(monkeypatch, root: Path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")


def test_bootstrap_exposes_real_frozen_headers_and_retains_native_search_handles(bootstrap, monkeypatch, tmp_path):
    runtime = tmp_path / "nvidia" / "cuda_runtime"
    compiler = tmp_path / "nvidia" / "cuda_nvrtc"
    for directory in (runtime / "bin", runtime / "include", compiler / "bin"):
        directory.mkdir(parents=True)
    (runtime / "bin" / "cudart64_12.dll").write_bytes(b"runtime")
    (runtime / "include" / "cuda_runtime.h").write_text("runtime header")
    (compiler / "bin" / "nvrtc64_120_0.dll").write_bytes(b"compiler")
    unrelated = tmp_path / "user-project"
    unrelated.mkdir()
    (unrelated / "untrusted.dll").write_bytes(b"not a toolkit resource")
    monkeypatch.setenv("CUDA_PATH", "existing user setting")
    monkeypatch.setenv("PATH", "existing process search path")
    _frozen_windows(monkeypatch, tmp_path)
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
    assert set(calls) == {str(tmp_path), str(runtime / "bin"), str(compiler / "bin")}
    assert bootstrap._dll_directory_handles == handles
    assert os.environ["CUDA_PATH"] == "existing user setting"
    assert os.environ["PATH"] == "existing process search path"
    assert all(root in site.getsitepackages() for root in previous_roots)
    assert site.getsitepackages()[0] == str(tmp_path)
    assert site.getsitepackages(["explicit prefix"]) == explicit_roots
    # Independent resource lookup through the public site API used by the
    # upstream pathfinder now sees the actual shipped header, not build venvs.
    found_headers = [Path(root) / "nvidia" / "cuda_runtime" / "include" / "cuda_runtime.h"
                     for root in site.getsitepackages()]
    assert next(path for path in found_headers if path.is_file()).read_text() == "runtime header"
    receipt["dll_directories"].clear()
    assert bootstrap.configure_bundled_cuda()["dll_directories"]
    assert len(calls) == 3  # Idempotence avoids accumulating native registrations.


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
