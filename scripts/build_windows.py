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
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str], *, cwd: Path = ROOT, env: dict | None = None) -> None:
    print("Running:", " ".join(arguments), flush=True)
    subprocess.run(arguments, cwd=cwd, env=env, check=True)


def prepare_source_and_manifest() -> str:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    source_dir = ROOT / "build" / "source"
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    # Include precisely repository source, never untracked files, local projects,
    # credentials, dependency caches, or generated application outputs.
    for filename in subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0"):
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
    manifest = {"application_version": version, "python": sys.version,
                "packages": sorted(packages, key=lambda item: (item["name"] or "").lower()),
                "frontend_packages": sorted(frontend_packages, key=lambda item: item["name"].lower()),
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()}
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
    version = prepare_source_and_manifest()
    bundle_env = dict(os.environ, ROCKET_BUNDLE_GPU="0" if args.cpu_only else "1")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         str(ROOT / "scripts" / "rocket-workbench.spec")], env=bundle_env)
    executable = ROOT / "dist" / "RocketWorkbench" / "RocketWorkbench.exe"
    run([str(executable), "--smoke-test"])
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
    print(f"Installer: {installer}")


if __name__ == "__main__":
    main()
