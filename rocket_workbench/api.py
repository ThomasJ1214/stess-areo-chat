"""Local-only application API. Desktop session token prevents cross-site writes."""
from __future__ import annotations

import csv
import html
import importlib.util
import io
import json
import math
import os
import re
import secrets
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from . import __version__
from .demo import demo_project
from .jobs import JobManager, compare
from .models import Component, Conditions, FlightConfiguration, Model, Project, Transform

MAX_UPLOAD = 100 * 1024 * 1024


class AnalyzeRequest(Model):
    conditions: Conditions = Field(default_factory=Conditions)
    configuration_id: str | None = None


class JobRequest(AnalyzeRequest):
    kind: str
    options: dict = Field(default_factory=dict)


class AttachRequest(Model):
    component_id: str
    asset_id: str
    transform: Transform = Field(default_factory=Transform)
    geometry_mode: str = "replacement"


class StandaloneRequest(Model):
    asset_id: str


async def upload_bytes(file: UploadFile) -> bytes:
    result = bytearray()
    while chunk := await file.read(1024 * 1024):
        result.extend(chunk)
        if len(result) > MAX_UPLOAD:
            raise HTTPException(413, "File exceeds the 100 MiB import limit.")
    return bytes(result)


def _filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_. -]", "_", name)[:80] or "rocket"


def capabilities() -> dict:
    gpu, detail = False, "CPU; GPU compute runtime not installed"
    if importlib.util.find_spec("cupy"):
        try:
            import cupy
            gpu = cupy.cuda.runtime.getDeviceCount() > 0
            detail = "NVIDIA CUDA / CuPy" if gpu else "CPU; no compatible CUDA device detected"
        except Exception:
            detail = "CPU; CUDA runtime or compatible driver unavailable"
    return {"cad": importlib.util.find_spec("OCP") is not None,
            "fea": importlib.util.find_spec("gmsh") is not None,
            "cfd": True, "gpu_compute": gpu, "gpu_backend": detail,
            "desktop": importlib.util.find_spec("PySide6") is not None}


def create_app(token: str | None = None, data_dir: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        yield
        application.state.jobs.shutdown()

    app = FastAPI(title="Rocket Workbench local API", version=__version__, lifespan=lifespan)
    lock = threading.RLock()
    app.state.project = demo_project()
    app.state.jobs = JobManager()
    if data_dir:
        data_dir.mkdir(parents=True, exist_ok=True)
        session = data_dir / "last-project.json"
        if session.exists():
            try:
                app.state.project = Project.model_validate_json(session.read_text(encoding="utf8"))
            except (OSError, ValidationError):
                # Keep a recoverable invalid file rather than overwriting it at startup.
                app.state.project.import_warnings.append("Previous session could not be restored; original file was preserved.")

    def project():
        with lock:
            return app.state.project.model_copy(deep=True)

    def save(value: Project):
        # Validate cross-references at persistence boundaries, so importers can
        # construct their hierarchy incrementally without invalid intermediate states.
        collections = [value.components, value.configurations, value.materials, value.motors, value.assets]
        for collection in collections:
            identities = [item.id for item in collection]
            if any(not identity.strip() for identity in identities) or len(set(identities)) != len(identities):
                raise ValueError("Project identifiers must be nonempty and unique within each collection.")
        components = {item.id: item for item in value.components}
        materials, motors, assets = ({item.id for item in collection} for collection in [value.materials, value.motors, value.assets])
        if not value.configurations or value.active_configuration_id not in {cfg.id for cfg in value.configurations}:
            raise ValueError("Project must contain the selected flight configuration.")
        for item in value.components:
            if item.parent_id and item.parent_id not in components:
                raise ValueError(f"{item.name}: parent component does not exist.")
            if item.material_id and item.material_id not in materials:
                raise ValueError(f"{item.name}: material does not exist.")
            if item.asset_id and item.asset_id not in assets:
                raise ValueError(f"{item.name}: imported geometry asset does not exist.")
            seen, parent = {item.id}, item.parent_id
            while parent:
                if parent in seen:
                    raise ValueError("Component hierarchy contains a cycle.")
                seen.add(parent)
                parent = components[parent].parent_id
        for cfg in value.configurations:
            if cfg.motor_id and cfg.motor_id not in motors:
                raise ValueError(f"{cfg.name}: assigned motor does not exist.")
            if cfg.motor_mount_id and cfg.motor_mount_id not in components:
                raise ValueError(f"{cfg.name}: motor mount does not exist.")
            if cfg.active_component_ids is not None and any(identity not in components for identity in cfg.active_component_ids):
                raise ValueError(f"{cfg.name}: enabled component does not exist.")
        with lock:
            if data_dir:
                destination = data_dir / "last-project.json"
                temporary = data_dir / "last-project.tmp"
                temporary.write_text(value.model_dump_json(), encoding="utf8")
                os.replace(temporary, destination)
            app.state.project = value
            return value

    @app.middleware("http")
    async def local_session(request: Request, call_next):
        host = request.headers.get("host", "").split(":", 1)[0]
        if host not in {"localhost", "127.0.0.1", "testserver"}:
            return JSONResponse({"detail": "Only local connections are supported."}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).hostname not in {"localhost", "127.0.0.1"}:
                return JSONResponse({"detail": "Foreign browser origins are not permitted."}, status_code=403)
        if token and request.url.path.startswith("/api/"):
            supplied = request.headers.get("x-rocket-session", "")
            if not secrets.compare_digest(token, supplied):
                return JSONResponse({"detail": "Missing or invalid desktop session token."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def bad_value(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def unavailable(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "capabilities": capabilities()}

    @app.get("/api/project")
    def get_project():
        return project()

    @app.put("/api/project")
    def update_project(value: Project):
        return save(value)

    @app.post("/api/project/demo")
    def demo():
        return save(demo_project())

    @app.post("/api/import/ork")
    async def import_ork(file: UploadFile = File(...)):
        from .imports import import_ork
        value = await run_in_threadpool(import_ork, await upload_bytes(file), file.filename or "project.ork")
        return save(value)

    @app.post("/api/import/geometry")
    async def import_cad(file: UploadFile = File(...), units: str = Form("mm")):
        from .geometry import import_geometry
        asset = await run_in_threadpool(import_geometry, await upload_bytes(file), file.filename or "model.stl", units)
        value = project()
        value.assets.append(asset)
        save(value)
        return asset

    @app.post("/api/import/motor")
    async def import_thrust(file: UploadFile = File(...)):
        from .imports import import_motor
        motors = await run_in_threadpool(import_motor, await upload_bytes(file), file.filename or "motor.eng")
        value = project()
        value.motors.extend(motors)
        save(value)
        return motors

    @app.post("/api/import/polar")
    async def import_polar(file: UploadFile = File(...)):
        from .solvers.aero import geometry_signature
        try:
            reader = csv.DictReader((await upload_bytes(file)).decode("utf-8-sig").splitlines())
        except UnicodeDecodeError as exc:
            raise ValueError("Aerodynamic polar CSV must use UTF-8 encoding.") from exc
        required = {"mach", "cd", "cna", "cp_m"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV requires columns mach,cd,cna,cp_m. CP must be metres from the rocket nose; CNa is per radian.")
        value = project()
        signature = geometry_signature(value, value.active_configuration_id)
        rows = []
        for row in reader:
            if len(rows) >= 2000:
                raise ValueError("A polar may contain at most 2,000 rows.")
            try:
                numeric = {key: float(row[key]) for key in required}
            except (ValueError, TypeError) as exc:
                raise ValueError("Every polar row must contain numeric Mach, CD, CNa and CP.") from exc
            if not all(math.isfinite(v) for v in numeric.values()) or not 0 <= numeric["mach"] <= 2 or numeric["cd"] < 0 or numeric["cna"] <= 0:
                raise ValueError("Polar values must be finite; Mach 0–2, CD nonnegative and CNa positive.")
            rows.append(numeric | {"configuration_id": value.active_configuration_id, "geometry_signature": signature,
                "source": (row.get("source") or f"User-supplied {file.filename or 'CSV'}")[:400],
                "fidelity": "User-supplied aerodynamic polar; validation and viscous corrections depend on the data source."})
        if len(rows) < 2 or len({row["mach"] for row in rows}) != len(rows):
            raise ValueError("Supply at least two rows at distinct Mach numbers.")
        prior = value.metadata.get("aerodynamic_polars", [])
        value.metadata["aerodynamic_polars"] = [row for row in prior if row.get("configuration_id") != value.active_configuration_id] + sorted(rows, key=lambda row: row["mach"])
        return save(value)

    @app.post("/api/project/load")
    async def load_project(file: UploadFile = File(...)):
        try:
            value = Project.model_validate_json(await upload_bytes(file))
        except ValidationError as exc:
            raise ValueError("Invalid Rocket Workbench project file: " + str(exc)) from exc
        return save(value)

    @app.get("/api/project/download")
    def download():
        value = project()
        return Response(value.model_dump_json(indent=2), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{_filename(value.name)}.rocket.json"'})

    @app.post("/api/geometry/attach")
    def attach(request: AttachRequest):
        value = project()
        component = next((c for c in value.components if c.id == request.component_id), None)
        if component is None or not any(a.id == request.asset_id for a in value.assets):
            raise ValueError("Choose an existing component and imported geometry asset.")
        if request.geometry_mode not in {"original", "replacement"}:
            raise ValueError("Geometry mode must be original or replacement.")
        component.asset_id, component.transform = request.asset_id, request.transform
        component.geometry_mode = request.geometry_mode
        return save(value)

    @app.post("/api/geometry/standalone")
    def standalone(request: StandaloneRequest):
        import numpy as np
        previous = project()
        asset = next((a for a in previous.assets if a.id == request.asset_id), None)
        if asset is None or not asset.vertices:
            raise ValueError("Select an imported geometry asset first.")
        vertices = np.asarray(asset.vertices)
        lower, upper = vertices.min(axis=0), vertices.max(axis=0)
        extent = upper - lower
        length, radius = float(extent[0]), float(max(extent[1:]) / 2)
        if length <= 0 or radius <= 0:
            raise ValueError("Standalone geometry must have length along X and a nonzero transverse extent. Align the source CAD nose-to-tail along X.")
        center = (lower + upper) / 2
        material = previous.materials[0] if previous.materials else None
        component = Component(name=asset.name, kind="bodytube", length=length, radius=radius,
            thickness=min(0.002, radius / 2), asset_id=asset.id, geometry_mode="replacement",
            material_id=material.id if material else None,
            transform=Transform(translation=[-float(lower[0]), -float(center[1]), -float(center[2])]),
            metadata={"cad_only": True, "reference_geometry_is_placeholder": True})
        return save(Project(name=Path(asset.name).stem, components=[component], assets=[asset],
            materials=previous.materials, motors=previous.motors, configurations=[FlightConfiguration(name="CAD configuration")],
            import_warnings=["Standalone CAD: the circular reference dimensions are for bookkeeping only. Empirical CP and stability are unavailable without a suitable supplied aerodynamic polar.",
                             "Assign actual material/mass, a validated motor, and justified recovery settings before simulating flight."],
            metadata={"cad_only": True}))

    @app.get("/api/geometry/properties/{component_id}")
    def properties(component_id: str):
        from .geometry import geometry_properties
        value = project()
        component = next((c for c in value.components if c.id == component_id), None)
        if component is None:
            raise ValueError("Component does not exist")
        return {"original": geometry_properties(value, component, True),
                "replacement": geometry_properties(value, component, False)}

    @app.get("/api/mesh")
    def meshes(original: bool = False):
        from .geometry import component_mesh
        from .models import active_components
        value, answer = project(), []
        for component in active_components(value):
            mesh = component_mesh(value, component, original)
            answer.append({"id": component.id, "name": component.name, "vertices": mesh.vertices.tolist(), "faces": mesh.faces.tolist()})
        return {"components": answer}

    @app.post("/api/analyze")
    def analysis(request: AnalyzeRequest):
        from .solvers.aero import analyze
        from .solvers.structure import analyze as structural
        value = project()
        return {"aero": analyze(value, request.conditions, request.configuration_id),
                "structure": structural(value, request.conditions, request.configuration_id)}

    @app.post("/api/compare")
    def comparison(request: AnalyzeRequest):
        return compare(project(), request.conditions, request.configuration_id)

    @app.post("/api/jobs")
    def start_job(request: JobRequest):
        return app.state.jobs.submit(project(), request.kind, request.conditions, request.configuration_id, request.options)

    @app.get("/api/jobs/{identity}")
    def get_job(identity: str):
        try:
            return app.state.jobs.get(identity)
        except KeyError:
            raise HTTPException(404, "Job not found or expired.")

    @app.post("/api/jobs/{identity}/cancel")
    def cancel_job(identity: str):
        try:
            return app.state.jobs.cancel(identity)
        except KeyError:
            raise HTTPException(404, "Job not found or expired.")

    @app.get("/api/jobs/{identity}/export")
    def export(identity: str, format: str = "json", dataset: str = "auto"):
        try:
            job = app.state.jobs.get(identity)
        except KeyError:
            raise HTTPException(404, "Job not found or expired.")
        if job["status"] != "completed":
            raise ValueError("Only completed simulations can be exported.")
        result = job["result"]
        if format == "json":
            content, content_type = json.dumps(result, indent=2, allow_nan=False), "application/json"
        elif format == "csv":
            if dataset != "auto":
                if dataset not in {"trajectory", "rows", "history", "surface", "samples", "components"}:
                    raise ValueError("Unknown export dataset")
                rows = result.get(dataset, [])
            elif "vertices" in result and "displacements" in result:
                rows = [{"node": i, "x_m": v[0], "y_m": v[1], "z_m": v[2],
                         "ux_m": d[0], "uy_m": d[1], "uz_m": d[2],
                         "von_mises_pa": result["von_mises_pa"][i]}
                        for i, (v, d) in enumerate(zip(result["vertices"], result["displacements"]))]
            else:
                rows = result.get("trajectory", result.get("rows", result.get("history", result.get("components", []))))
            if not rows or not isinstance(rows[0], dict):
                raise ValueError("This result has no tabular data. Export JSON instead.")
            fields = list(dict.fromkeys(key for row in rows for key in row))
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows([{key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in row.items()} for row in rows])
            content, content_type = stream.getvalue(), "text/csv"
        elif format == "html":
            content = "<!doctype html><meta charset='utf-8'><title>Rocket Workbench report</title><style>body{font:15px system-ui;max-width:1100px;margin:3rem auto;color:#182330}pre{white-space:pre-wrap;background:#f3f5f8;padding:1rem}</style>"
            content += "<h1>Rocket Workbench simulation report</h1><p>All result quantities use SI units. Fidelity and warnings are part of the results.</p>"
            content += "<h2>" + html.escape(job["kind"]) + "</h2><pre>" + html.escape(json.dumps(result, indent=2, allow_nan=False)) + "</pre>"
            content_type = "text/html"
        else:
            raise ValueError("Export format must be csv, json or html")
        return Response(content, media_type=content_type, headers={"Content-Disposition": f'attachment; filename="rocket-{job["kind"]}-{identity[:8]}.{format}"'})

    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    dist = base / "web" / "dist"

    @app.get("/{path:path}")
    def static(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API endpoint not found.")
        target = (dist / path).resolve()
        if dist.resolve() not in target.parents and target != dist.resolve():
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(target)
        if (dist / "index.html").exists():
            return FileResponse(dist / "index.html")
        return HTMLResponse("<h1>Rocket Workbench</h1><p>Frontend assets have not been built. Run npm ci and npm run build inside web.</p>", status_code=503)

    return app
