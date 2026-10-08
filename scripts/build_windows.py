"""Build an offline, single-download Windows installer from locked dependencies.

Run on Windows after `uv sync --locked --extra desktop --extra dev --extra gpu`.
No downloads occur during application startup or end-user installation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str], *, cwd: Path = ROOT, env: dict | None = None,
        timeout_seconds: int | None = None) -> None:
    print("Running:", " ".join(arguments), flush=True)
    subprocess.run(arguments, cwd=cwd, env=env, check=True, timeout=timeout_seconds)


def file_record(path: Path, relative_path: str) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": relative_path, "bytes": path.stat().st_size, "sha256": digest}


def prepare_source_and_manifest(*, gpu_requested: bool = True) -> str:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    from rocket_workbench import __version__
    if version != __version__:
        raise RuntimeError("Application and packaging versions differ; update pyproject.toml and rocket_workbench/__init__.py together.")
    source_dir = ROOT / "build" / "source"
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    # Include precisely repository source, never untracked files, local projects,
    # credentials, dependency caches, or generated application outputs.
    source_files = []
    for filename in sorted(subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")):
        if not filename:
            continue
        # Upstream GPL test data is repository validation material, not app data.
        if filename.startswith("tests/fixtures/openrocket/"):
            continue
        path = ROOT / filename
        if not path.is_file():
            continue
        destination = source_dir / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        source_files.append(file_record(destination, filename))
    notices_root = ROOT / "build" / "notices"
    if notices_root.exists():
        shutil.rmtree(notices_root)
    notices_dir = notices_root / "frontend"
    notices_dir.mkdir(parents=True, exist_ok=True)
    frontend_packages = []
    lock = json.loads((ROOT / "web" / "package-lock.json").read_text("utf-8"))
    for location, package in lock.get("packages", {}).items():
        if not location:
            continue
        package_dir = ROOT / "web" / location
        package_file = package_dir / "package.json"
        if not package_file.is_file():
            continue
        installed = json.loads(package_file.read_text("utf-8"))
        name, package_version = installed.get("name", location), installed.get("version", package.get("version"))
        frontend_packages.append({"name": name, "version": package_version, "license": installed.get("license")})
        safe_name = str(name).replace("/", "_").replace("\\", "_") + "-" + str(package_version)
        for notice in package_dir.iterdir():
            if notice.is_file() and notice.name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "THIRD_PARTY")):
                destination = notices_dir / safe_name / notice.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(notice, destination)
    (notices_dir / "package_licenses.json").write_text(json.dumps(frontend_packages, indent=2), "utf-8")
    packages = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name") or "unnamed"
        packages.append({"name": name, "version": dist.version,
                         "license": dist.metadata.get("License-Expression") or dist.metadata.get("License")})
        # Older native wheels put licenses outside dist-info (e.g. OCP and Gmsh).
        # Preserve those notices too, rather than relying only on copy_metadata.
        for item in dist.files or []:
            if not Path(str(item)).name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "COPYRIGHT", "EULA")):
                continue
            source = Path(dist.locate_file(item)).resolve()
            if not source.is_file():
                continue
            relative_parts = ["_parent" if part == ".." else part for part in Path(str(item)).parts]
            destination = notices_root / "python" / f"{name}-{dist.version}" / Path(*relative_parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT).strip())
    frontend_files = [file_record(path, path.relative_to(ROOT / "web" / "dist").as_posix())
                      for path in sorted((ROOT / "web" / "dist").rglob("*")) if path.is_file()]
    source_digest = hashlib.sha256(json.dumps(source_files, sort_keys=True, separators=(",", ":")).encode("utf8")).hexdigest()
    manifest = {"application_version": version, "python": sys.version,
                "build_platform": platform.platform(), "build_architecture": platform.machine(),
                "gpu_runtime_requested": gpu_requested,
                "package_inventory_scope": "Installed build-environment distributions; PyInstaller exclusions apply to the executable.",
                "packages": sorted(packages, key=lambda item: (item["name"] or "").lower()),
                "frontend_packages": sorted(frontend_packages, key=lambda item: item["name"].lower()),
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
                "source_dirty": dirty, "source_snapshot_sha256": source_digest,
                "source_files": source_files, "frontend_files": frontend_files,
                "lockfiles": [file_record(ROOT / path, path) for path in ("uv.lock", "web/package-lock.json")]}
    (ROOT / "build" / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-only", action="store_true", help="Developer build without bundled CUDA; default bundles it.")
    parser.add_argument("--skip-web-build", action="store_true", help="Use an already-built web/dist.")
    parser.add_argument("--skip-installer", action="store_true", help="Produce only the portable application directory.")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows application packaging must run on Windows x64. Use the Windows build workflow.")
    if struct.calcsize("P") != 8 or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("Use a Windows x64 Python interpreter; native ARM64 and 32-bit builds are unsupported.")
    if sys.version_info[:2] != (3, 12):
        parser.error("Use the pinned Python 3.12 interpreter.")
    if not args.skip_web_build:
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            parser.error("Install Node.js 22 before building, or use --skip-web-build with valid web/dist.")
        run([npm, "ci"], cwd=ROOT / "web")
        run([npm, "run", "build"], cwd=ROOT / "web")
    if not (ROOT / "web" / "dist" / "index.html").is_file():
        parser.error("web/dist/index.html is missing; build the frontend first.")
    version = prepare_source_and_manifest(gpu_requested=not args.cpu_only)
    bundle_env = dict(os.environ, ROCKET_BUNDLE_GPU="0" if args.cpu_only else "1")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         str(ROOT / "scripts" / "rocket-workbench.spec")], env=bundle_env)
    executable = ROOT / "dist" / "RocketWorkbench" / "RocketWorkbench.exe"
    run([str(executable), "--smoke-test", "--smoke-output", str(ROOT / "build" / "frozen-smoke.json")], timeout_seconds=360)
    if args.skip_installer:
        print(f"Portable application directory: {executable.parent}")
        return
    iscc = shutil.which("ISCC.exe") or shutil.which("iscc")
    if not iscc:
        candidate = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe"
        iscc = str(candidate) if candidate.is_file() else None
    if not iscc:
        parser.error("Install Inno Setup 6 (https://jrsoftware.org/isinfo.php), then rerun with --skip-web-build.")
    run([iscc, f"/DAppVersion={version}", f"/DBuildRoot={ROOT}", str(ROOT / "scripts" / "installer.iss")])
    installer = ROOT / "release" / f"RocketWorkbench-{version}-windows-x64-setup.exe"
    with installer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    installer.with_suffix(installer.suffix + ".sha256").write_text(f"{digest}  {installer.name}\n", "utf-8")
    (installer.parent / "START_HERE.txt").write_text(
        f"ROCKET WORKBENCH {version} - WINDOWS INSTALLATION\n\n"
        "1. Extract the entire downloaded ZIP (right-click, Extract All).\n"
        f"2. Open the release folder and double-click {installer.name}.\n"
        "3. Accept the license and choose the default user-local installation.\n"
        "4. Open Rocket Workbench from Start. Click Getting started for the guided tour.\n"
        "5. Use Tutorial on each page and ? beside an unfamiliar term for help.\n"
        "6. Import your .ork file, review the motor/recovery setup, then click Launch.\n\n"
        "Python, Node.js, CAD programs, Gmsh and CUDA Toolkit setup are not needed.\n"
        "The NVIDIA driver is required for optional NVIDIA numerical GPU use.\n"
        "The installer includes the runtime and engineering solvers; calculations work offline.\n"
        "Optional Find motor online uses internet to retrieve actual motor curves.\n\n"
        "Read USER_GUIDE.txt for the complete workflow and engineering limits.\n"
        "The .sha256 file identifies the installer checksum. Build manifests and\n"
        "installed-engine/desktop smoke receipts are in the artifact's build folder.\n",
        "utf-8")
    shutil.copyfile(ROOT / "docs" / "USER_GUIDE.md", installer.parent / "USER_GUIDE.txt")
    print(f"Installer: {installer}")


if __name__ == "__main__":
    main()
