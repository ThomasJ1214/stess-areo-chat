"""Build provenance identifies the actual copied source and frontend content."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from rocket_workbench import __version__
from scripts import build_windows


def build_checkout(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(build_windows, "ROOT", tmp_path)
    monkeypatch.setattr(build_windows.importlib.metadata, "distributions", lambda: [])
    (tmp_path / "web" / "dist").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{__version__}"\n', "utf8")
    (tmp_path / "uv.lock").write_text("version = 1\n", "utf8")
    (tmp_path / "web" / "package-lock.json").write_text('{"packages": {}}', "utf8")
    (tmp_path / "web" / "dist" / "index.html").write_text("compiled UI", "utf8")
    (tmp_path / "source.py").write_text("original source\n", "utf8")
    (tmp_path / "tests" / "fixtures" / "openrocket").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "openrocket" / "example.ork").write_bytes(b"upstream fixture")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "pyproject.toml", "uv.lock", "web/package-lock.json", "source.py", "tests"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Packaging test", "-c", "user.email=packaging@example.invalid", "commit", "--quiet", "-m", "Fixture"], cwd=tmp_path, check=True)


def test_manifest_captures_changes_and_omits_untracked_private_files(tmp_path, monkeypatch):
    build_checkout(tmp_path, monkeypatch)
    build_windows.prepare_source_and_manifest(gpu_requested=False)
    manifest_path = tmp_path / "build" / "bundle_manifest.json"
    original = json.loads(manifest_path.read_text("utf8"))
    assert not original["source_dirty"]
    assert original["gpu_runtime_requested"] is False
    expected = hashlib.sha256(b"original source\n").hexdigest()
    assert next(row for row in original["source_files"] if row["path"] == "source.py")["sha256"] == expected
    assert original["frontend_files"][0]["sha256"] == hashlib.sha256(b"compiled UI").hexdigest()
    assert {row["path"] for row in original["lockfiles"]} == {"uv.lock", "web/package-lock.json"}

    (tmp_path / "source.py").write_text("modified source\n", "utf8")
    (tmp_path / "private-project.json").write_text("private project data", "utf8")
    build_windows.prepare_source_and_manifest(gpu_requested=True)
    changed = json.loads(manifest_path.read_text("utf8"))
    assert changed["source_commit"] == original["source_commit"]
    assert changed["source_dirty"] and changed["gpu_runtime_requested"]
    assert changed["source_snapshot_sha256"] != original["source_snapshot_sha256"]
    assert (tmp_path / "build" / "source" / "source.py").read_text("utf8") == "modified source\n"
    assert not (tmp_path / "build" / "source" / "private-project.json").exists()
    assert not (tmp_path / "build" / "source" / "tests" / "fixtures" / "openrocket").exists()


def test_manifest_rejects_mismatched_application_version(tmp_path, monkeypatch):
    build_checkout(tmp_path, monkeypatch)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "999.0.0"\n', "utf8")
    with pytest.raises(RuntimeError, match="versions differ"):
        build_windows.prepare_source_and_manifest()
