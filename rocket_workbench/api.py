"""Local-only application API. Desktop session token prevents cross-site writes."""
from __future__ import annotations

import csv
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
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import Field, JsonValue, ValidationError
from starlette.concurrency import run_in_threadpool

from . import __version__
from .alignment import AlignmentOptions, propose_alignment
from .demo import demo_project
from .jobs import JobManager, compare
from .models import AnalysisSettings, Component, Conditions, FlightConfiguration, Model, Project, Transform, validate_project_references

MAX_UPLOAD = 100 * 1024 * 1024


class AnalyzeRequest(Model):
    conditions: Conditions = Field(default_factory=Conditions)
    configuration_id: str | None = None


class JobRequest(AnalyzeRequest):
    kind: str
    options: dict[str, JsonValue] = Field(default_factory=dict)


class SettingsRequest(Model):
    project_id: str
    settings: AnalysisSettings


class AlignmentRequest(AlignmentOptions):
    component_id: str
    asset_id: str
    include_mesh: bool = False


class AttachRequest(Model):
    component_id: str
    asset_id: str
    transform: Transform = Field(default_factory=Transform)
    geometry_mode: str = "replacement"
    auto_align: bool = False
    alignment_options: AlignmentOptions = Field(default_factory=AlignmentOptions)


class StandaloneRequest(Model):
    asset_id: str


class FeaPreflightRequest(Model):
    component_id: str
    options: dict[str, JsonValue] = Field(default_factory=dict)


class MotorSearchRequest(Model):
    query: str = Field(default="", max_length=80)
    manufacturer: str = Field(default="", max_length=80)
    limit: int = Field(default=30, ge=1, le=50)


class MotorPreviewRequest(Model):
    motor_id: str = Field(pattern=r"^[a-fA-F0-9]{24}$")
    simfile_id: str = Field(pattern=r"^[a-fA-F0-9]{24}$")


class MotorImportRequest(Model):
    project_id: str
    review_token: str = Field(min_length=1, max_length=100)


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
    from .backenddiagnostics import cuda_diagnostics
    diagnostics = cuda_diagnostics()
    gpu = diagnostics["available"]
    detail = "NVIDIA CUDA / CuPy" if gpu else f"CPU; {diagnostics['reason']}"
    return {"cad": importlib.util.find_spec("OCP") is not None,
            "fea": importlib.util.find_spec("gmsh") is not None,
            "cfd": True, "gpu_compute": gpu, "gpu_backend": detail,
            "gpu_diagnostics": diagnostics,
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
    from .motor_catalog import MotorCatalog
    app.state.motor_catalog = MotorCatalog()
    if data_dir:
        data_dir.mkdir(parents=True, exist_ok=True)
        session = data_dir / "last-project.json"
        if session.exists():
            try:
                restored = Project.model_validate_json(session.read_text(encoding="utf8"))
                validate_project_references(restored)
                app.state.project = restored
            except (OSError, ValueError):
                # Keep a recoverable invalid file rather than overwriting it at startup.
                app.state.project.import_warnings.append("Previous session could not be restored; original file was preserved.")

    def project():
        with lock:
            return app.state.project.model_copy(deep=True)

    def save(value: Project):
        validate_project_references(value)
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

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc):
        # Do not echo arbitrary uploaded data into an error response. In
        # particular, a rejected NaN/Infinity input is not valid response JSON.
        return JSONResponse({"detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                                        for error in exc.errors()]}, status_code=422)

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

    @app.put("/api/project/settings")
    def update_settings(request: SettingsRequest):
        # Patch the latest state atomically: delayed UI saves may never replace
        # component edits or conditions belonging to a different project.
        with lock:
            if request.project_id != app.state.project.id:
                raise HTTPException(409, "The project changed before these settings were saved.")
            value = project()
            value.analysis_settings = request.settings
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

    # Catalog lookups only transmit the entered designation/manufacturer and
    # selected provider IDs; project geometry and simulation data stay local.
    @app.post("/api/motors/search")
    async def search_motors(request: MotorSearchRequest):
        from .motor_catalog import CatalogUnavailable
        try:
            return await run_in_threadpool(app.state.motor_catalog.search, request.query, request.manufacturer, request.limit)
        except CatalogUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/motors/{motor_id}/curves")
    async def motor_curves(motor_id: str):
        from .motor_catalog import CatalogUnavailable
        try:
            return await run_in_threadpool(app.state.motor_catalog.curves, motor_id)
        except CatalogUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/motors/preview")
    async def preview_motor(request: MotorPreviewRequest):
        from .motor_catalog import CatalogUnavailable
        try:
            return await run_in_threadpool(app.state.motor_catalog.preview, request.motor_id, request.simfile_id)
        except CatalogUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/motors/import")
    def import_reviewed_motor(request: MotorImportRequest):
        motor = app.state.motor_catalog.reviewed_motor(request.review_token)
        # Import into the latest project under the lock, so a slow network
        # lookup cannot overwrite design edits or a newly opened project.
        with lock:
            if request.project_id != app.state.project.id:
                raise HTTPException(409, "The project changed during motor review. Search/preview again in the current project.")
            value = project()
            if not any(item.provenance.get("provider") == motor.provenance.get("provider")
                       and item.provenance.get("simfile_id") == motor.provenance.get("simfile_id")
                       and item.provenance.get("curve_sha256") == motor.provenance.get("curve_sha256") for item in value.motors):
                value.motors.append(motor)
            return save(value)

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

    @app.post("/api/geometry/alignment")
    def alignment(request: AlignmentRequest):
        value = project()
        component = next((c for c in value.components if c.id == request.component_id), None)
        asset = next((a for a in value.assets if a.id == request.asset_id), None)
        if component is None or asset is None:
            raise ValueError("Choose an existing component and imported geometry asset.")
        options = AlignmentOptions.model_validate(request.model_dump(exclude={"component_id", "asset_id", "include_mesh"}))
        return propose_alignment(value, component, asset, options, include_mesh=request.include_mesh)

    @app.post("/api/geometry/attach")
    def attach(request: AttachRequest):
        value = project()
        component = next((c for c in value.components if c.id == request.component_id), None)
        asset = next((a for a in value.assets if a.id == request.asset_id), None)
        if component is None or asset is None:
            raise ValueError("Choose an existing component and imported geometry asset.")
        if request.geometry_mode not in {"original", "replacement"}:
            raise ValueError("Geometry mode must be original or replacement.")
        transform = request.transform
        if request.auto_align:
            proposal = propose_alignment(value, component, asset, request.alignment_options)
            transform = Transform.model_validate(proposal["transform"])
        component.asset_id, component.transform = request.asset_id, transform
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

    @app.post("/api/fea/preflight")
    async def fea_preflight(request: FeaPreflightRequest):
        from .fea_setup import preflight
        return await run_in_threadpool(preflight, project(), request.component_id, request.options)

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

    @app.get("/api/jobs/{identity}/project")
    def input_project(identity: str):
        try:
            snapshot = app.state.jobs.input_project(identity)
        except KeyError:
            raise HTTPException(404, "Job not found or expired.")
        return Response(snapshot.model_dump_json(indent=2), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{_filename(snapshot.name)}-run-{identity[:8]}.rocket.json"'})

    @app.get("/api/jobs/{identity}/export")
    def export(identity: str, format: str = "json", dataset: str = "auto"):
        try:
            job = app.state.jobs.get(identity)
        except KeyError:
            raise HTTPException(404, "Job not found or expired.")
        if job["status"] != "completed" and not (job["status"] == "cancelled" and job["kind"] == "cfd" and job.get("result") is not None):
            raise ValueError("Export requires a completed simulation or actual retained partial CFD fields.")
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
            # Keep ordinary rectangular CSV data and its scientific context in
            # the same file. Global metadata occupies dedicated columns of the
            # first data row; do not repeat kilobytes across every mesh node.
            context = {key: result[key] for key in
                ["fidelity", "backend", "warnings", "validity", "inputs", "summary", "conventions"] if key in result}
            rows = [dict(row) for row in rows]
            rows[0].update({f"_result_{key}": value for key, value in context.items()})
            fields = list(dict.fromkeys(key for row in rows for key in row))
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            def csv_value(value):
                if isinstance(value, (dict, list)):
                    return json.dumps(value, allow_nan=False)
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    return "'" + value
                return value
            writer.writerows([{key: csv_value(value) for key, value in row.items()} for row in rows])
            content, content_type = stream.getvalue(), "text/csv"
        elif format == "html":
            from .reports import render_report
            content = render_report(job["kind"], result)
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
