"""Bounded background jobs with cancellation, progress and honest ETA estimates."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import numpy as np

from . import __version__
from .models import Conditions, Project


class JobManager:
    def __init__(self, workers: int = 1):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rocket-simulation")
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.closed = False

    def submit(self, project: Project, kind: str, conditions: Conditions,
               configuration_id: str | None = None, options: dict | None = None) -> dict:
        if kind not in {"flight", "cfd", "fea", "sweep", "monte_carlo", "comparison"}:
            raise ValueError("Unknown simulation kind")
        options = copy.deepcopy(options or {})
        progress_basis = "completion_fraction"
        if kind == "cfd":
            # CFD numerical convergence has no predictable completion fraction.
            # A finite stopping budget can report budget usage; zero wall time
            # plus convergence-only mode has no finite stopping budget at all.
            try:
                no_wall_timeout = float(options.get("max_wall_seconds", 1200)) == 0
            except (TypeError, ValueError):
                no_wall_timeout = False  # Solver validation reports invalid inputs.
            progress_basis = "convergence_unknown" if options.get("run_until_converged") is True and no_wall_timeout else "budget_usage"
        cfd_source = None
        # Keep a portable input project for the run, separate from large solved
        # fields and never included in every progress-poll response.
        snapshot = project.model_copy(deep=True)
        snapshot.active_configuration_id = configuration_id or project.active_configuration_id
        snapshot.analysis_settings.conditions = conditions.model_copy(deep=True)
        if kind == "cfd":
            snapshot.analysis_settings.cfd_options = copy.deepcopy(options)
        elif kind == "fea":
            snapshot.analysis_settings.fea_options = copy.deepcopy(options)
        elif kind in {"sweep", "monte_carlo", "comparison"}:
            snapshot.analysis_settings.study_options = copy.deepcopy(options)
            snapshot.analysis_settings.study_mode = kind
        project_hash = hashlib.sha256(json.dumps(snapshot.model_dump(mode="json"),
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        from .solvers.aero import geometry_signature
        signature = geometry_signature(project, configuration_id)
        if kind == "fea" and options.get("load_mode") == "cfd_pressure":
            from .models import active_components
            component = next((c for c in active_components(project, configuration_id) if c.id == options.get("component_id")), None)
            if component is None or not component.external:
                raise ValueError("CFD pressures can only be transferred to a component included in the external flow geometry.")
            try:
                prior = self.get(str(options.get("cfd_job_id", "")))
            except KeyError as exc:
                raise ValueError("Select an available completed CFD job before transferring pressures.") from exc
            if prior["kind"] != "cfd" or prior["status"] != "completed" or not prior["result"]["summary"]["converged"]:
                raise ValueError("Pressure-transfer FEA requires a completed, numerically converged CFD job.")
            if prior.get("geometry_signature") != signature:
                raise ValueError("Rocket geometry changed after the CFD solve. Recompute CFD before transferring pressures.")
            cfd = prior["result"]
            cfd_source = {"job_id": prior["id"], "inputs": copy.deepcopy(cfd.get("inputs", {})),
                "surface_sha256": hashlib.sha256(json.dumps(cfd["surface"], sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                "mesh_sha256": cfd["summary"].get("mesh_sha256"), "fidelity": cfd["fidelity"],
                "replay": "The linked CFD job is session-local. Export its full result or rerun its recorded inputs before applying pressure in a new session."}
            from .geometry import project_mesh
            current_mesh = project_mesh(project, configuration_id)
            mesh_hash = hashlib.sha256(np.asarray(current_mesh.vertices, dtype="<f8").tobytes() +
                                       np.asarray(current_mesh.faces, dtype="<i8").tobytes()).hexdigest()
            if cfd["summary"].get("mesh_sha256") != mesh_hash:
                raise ValueError("CFD was solved on different geometry. Recompute the current geometry before pressure transfer.")
            if cfd["summary"].get("nonpositive_wall_faces", 0):
                raise ValueError("CFD has nonphysical wall pressures; refine/recompute it before structural pressure transfer.")
            options.update(cfd_surface=cfd["surface"], cfd_converged=True,
                cfd_freestream_pressure_pa=cfd["summary"]["freestream_pressure_pa"],
                cfd_cell_spacing_m=cfd["summary"]["cell_spacing_m"],
                cfd_fidelity=cfd["fidelity"], cfd_warnings=cfd["warnings"])
        with self.lock:
            if self.closed:
                raise RuntimeError("Simulation workers are shutting down.")
            if sum(j["status"] in {"queued", "running"} for j in self.jobs.values()) >= 4:
                raise ValueError("Four jobs are already pending. Finish or cancel one first.")
            # Bound retained results as CFD/FEA outputs can be large.
            while len(self.jobs) >= 12:
                completed = next((k for k, j in self.jobs.items() if j["status"] not in {"running", "queued"}), None)
                if completed is None:
                    break
                del self.jobs[completed]
            identity = uuid4().hex
            self.jobs[identity] = {"id": identity, "kind": kind, "geometry_signature": signature, "status": "queued", "progress": 0.0,
                "progress_basis": progress_basis,
                "message": "Waiting for simulation worker", "created": time.monotonic(), "started": None,
                "finished": None, "result": None, "error": None, "cancel": threading.Event(),
                "project_snapshot": snapshot, "project_sha256": project_hash,
                "cfd_source": cfd_source,
                "submitted_at": datetime.now(timezone.utc).isoformat()}
            self.executor.submit(self._execute, identity, project.model_copy(deep=True), kind,
                                 conditions.model_copy(deep=True), configuration_id, copy.deepcopy(options or {}))
            return self.get(identity)

    def get(self, identity: str) -> dict:
        with self.lock:
            job = self.jobs.get(identity)
            if job is None:
                raise KeyError(identity)
            elapsed = (job["finished"] or time.monotonic()) - job["started"] if job["started"] else 0.0
            progress = job["progress"]
            eta = elapsed * (1 / progress - 1) if job["status"] == "running" and progress > 0.01 and job["progress_basis"] != "convergence_unknown" else None
            return {k: v for k, v in job.items() if k not in {"cancel", "created", "started", "finished", "project_snapshot"}} | {
                "elapsed_seconds": max(0, elapsed), "eta_seconds": eta}

    def input_project(self, identity: str) -> Project:
        with self.lock:
            if identity not in self.jobs:
                raise KeyError(identity)
            return self.jobs[identity]["project_snapshot"].model_copy(deep=True)

    def cancel(self, identity: str) -> dict:
        with self.lock:
            if identity not in self.jobs:
                raise KeyError(identity)
            self.jobs[identity]["cancel"].set()
            if self.jobs[identity]["status"] == "queued":
                self.jobs[identity].update(status="cancelled", message="Cancelled before starting", finished=time.monotonic())
        return self.get(identity)

    def shutdown(self):
        with self.lock:
            self.closed = True
            for job in self.jobs.values():
                job["cancel"].set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _execute(self, identity, project, kind, conditions, configuration_id, options):
        with self.lock:
            # A cancelled queued job may have been pruned before its future
            # reaches the worker. Never dereference an expired registry entry.
            job = self.jobs.get(identity)
            if job is None or job["cancel"].is_set():
                return
            job.update(status="running", started=time.monotonic(), message="Preparing simulation")

        def progress(fraction, message):
            with self.lock:
                job.update(progress=float(np.clip(fraction, 0, 0.999)), message=str(message))

        def cancelled():
            return job["cancel"].is_set()

        try:
            if kind == "flight":
                from .solvers.flight import simulate
                result = simulate(project, conditions, configuration_id, progress, cancelled)
            elif kind == "cfd":
                from .solvers.cfd import solve
                result = solve(project, conditions, configuration_id, options, progress, cancelled)
            elif kind == "fea":
                from .solvers.structure import solve_fea
                component_id = options.get("component_id")
                if not component_id:
                    raise ValueError("Select a component for finite element analysis.")
                result = solve_fea(project, component_id, conditions, options, progress, cancelled)
            elif kind == "comparison":
                result = compare(project, conditions, configuration_id, options, progress, cancelled)
            else:
                result = study(project, conditions, configuration_id, kind, options, progress, cancelled)
            result["inputs"] = {"project_id": project.id, "project_name": project.name,
                "configuration_id": configuration_id or project.active_configuration_id,
                "geometry_signature": job["geometry_signature"],
                "application_version": __version__, "project_sha256": job["project_sha256"],
                "submitted_at": job["submitted_at"],
                "conditions": conditions.model_dump(), "options": {k: v for k, v in options.items() if k != "cfd_surface"}}
            if job["cfd_source"] is not None:
                result["inputs"]["cfd_source"] = copy.deepcopy(job["cfd_source"])
            with self.lock:
                was_cancelled = cancelled()
                # CFD explicitly returns its actual transient fields on cancel.
                # Retain those outputs and provenance for inspection/export,
                # without upgrading the job status or pressure-transfer eligibility.
                retained = result if not was_cancelled or kind == "cfd" else None
                job.update(status="cancelled" if was_cancelled else "completed", result=retained,
                    progress=1.0 if not was_cancelled else self.jobs[identity]["progress"], message="Cancelled; partial CFD fields retained" if was_cancelled and kind == "cfd" else "Cancelled" if was_cancelled else "Simulation completed",
                    finished=time.monotonic())
        except Exception as exc:
            with self.lock:
                job.update(status="cancelled" if cancelled() else "failed", error=str(exc),
                    message="Cancelled" if cancelled() else "Simulation failed", finished=time.monotonic())


def compare(project, conditions, configuration_id=None, options=None, progress=None, cancelled=None):
    from .solvers.aero import analyze
    from .solvers.structure import analyze as structural
    options = options or {}
    original = project.model_copy(deep=True)
    for component in original.components:
        component.geometry_mode = "original"
    result = {"original": {"aero": analyze(original, conditions, configuration_id), "structure": structural(original, conditions, configuration_id)},
              "replacement": {"aero": analyze(project, conditions, configuration_id), "structure": structural(project, conditions, configuration_id)},
              "configurations": [], "fidelity": "Engineering estimates; detailed external CAD requires resolved flow analysis.", "warnings": []}
    fields = ["mass_kg", "cg_m", "cp_m", "stability_calibers", "cd", "drag_n", "normal_force_n"]
    result["deltas"] = {k: result["replacement"]["aero"].get(k, 0) - result["original"]["aero"].get(k, 0) for k in fields
                        if isinstance(result["replacement"]["aero"].get(k), (float, int)) and isinstance(result["original"]["aero"].get(k), (float, int))}
    for label in ["original", "replacement"]:
        result["warnings"].extend(f"{label}: {message}" for message in result[label]["aero"].get("warnings", []))
    for cfg in project.configurations:
        try:
            result["configurations"].append({"configuration_id": cfg.id, "name": cfg.name, "aero": analyze(project, conditions, cfg.id)})
        except (ValueError, RuntimeError) as exc:
            result["configurations"].append({"configuration_id": cfg.id, "name": cfg.name, "aero": None, "error": str(exc)})
    stages = 2 * int(bool(options.get("use_flight"))) + 2 * int(bool(options.get("use_cfd")))
    current_stage = 0
    if options.get("use_flight"):
        from .solvers.flight import simulate
        for label, model in [("original", original), ("replacement", project)]:
            callback = (lambda f, m, i=current_stage, l=label: progress((i + f) / stages, f"{l} flight: {m}")) if progress else None
            try:
                result[label]["flight"] = simulate(model, conditions, configuration_id, callback, cancelled)
                result["warnings"].extend(f"{label} flight: {message}" for message in result[label]["flight"].get("warnings", []))
            except ValueError as exc:
                result[label]["flight"] = None
                result[label]["flight_error"] = str(exc)
                result["warnings"].append(f"{label} flight was not run: {exc}")
            current_stage += 1
        original_summary = (result["original"]["flight"] or {}).get("summary", {})
        replacement_summary = (result["replacement"]["flight"] or {}).get("summary", {})
        result["flight_deltas"] = {key: replacement_summary[key] - value for key, value in original_summary.items()
            if isinstance(value, (float, int)) and not isinstance(value, bool) and isinstance(replacement_summary.get(key), (float, int))}
        result["fidelity"] += " Includes point-mass flight comparisons using each model's declared aerodynamic basis."
    if options.get("use_cfd"):
        from .solvers.cfd import solve
        for label, model in [("original", original), ("replacement", project)]:
            if cancelled and cancelled():
                raise RuntimeError("Comparison cancelled")
            callback = (lambda f, m, i=current_stage, l=label: progress((i + f) / stages, f"{l}: {m}")) if progress else None
            result[label]["cfd"] = solve(model, conditions, configuration_id, options, callback, cancelled)
            result["warnings"].extend(f"{label} CFD: {message}" for message in result[label]["cfd"].get("warnings", []))
            current_stage += 1
        result["fidelity"] = "Empirical mass/stability comparison plus experimental inviscid Euler geometry comparison."
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    return result


def study(project, conditions, configuration_id, kind, options, progress, cancelled):
    from .solvers.aero import analyze
    from .solvers.flight import simulate
    raw_count = options.get("count", 10)
    count = int(raw_count)
    if isinstance(raw_count, bool) or count != raw_count or not 2 <= count <= 200:
        raise ValueError("Study count must be between 2 and 200")
    parameter = options.get("parameter", "wind_speed" if kind == "monte_carlo" else "speed")
    allowed = {"speed", "mach", "altitude", "angle_of_attack", "wind_speed", "wind_direction", "turbulence",
               "launch_angle", "launch_azimuth", "rail_length", "temperature_delta"}
    if parameter not in allowed:
        raise ValueError("Choose a supported condition parameter")
    use_flight = bool(options.get("flight", kind == "monte_carlo"))
    if use_flight and parameter in {"speed", "mach"}:
        raise ValueError("Flight speed/Mach are integrated outputs. Sweep wind, launch altitude or other supported flight inputs instead.")
    if not use_flight and parameter in {"launch_angle", "launch_azimuth", "rail_length"}:
        raise ValueError("Rail/launch parameters require flight mode; static aerodynamics does not use launch orientation.")
    raw_seed = options.get("seed", conditions.seed)
    study_seed = int(raw_seed)
    if isinstance(raw_seed, bool) or study_seed != raw_seed or study_seed < 0:
        raise ValueError("Study seed must be a nonnegative integer.")
    rng = np.random.default_rng(study_seed)
    if kind == "monte_carlo":
        mean = float(options.get("mean", getattr(conditions, parameter) or 0))
        sigma = float(options.get("std", 1))
        if not np.isfinite(mean) or not np.isfinite(sigma) or sigma < 0:
            raise ValueError("Mean must be finite; standard deviation must be finite and nonnegative")
        values = rng.normal(mean, sigma, count)
    else:
        start, stop = float(options.get("start", 0)), float(options.get("stop", 200))
        if not np.isfinite(start) or not np.isfinite(stop):
            raise ValueError("Sweep endpoints must be finite.")
        values = np.linspace(start, stop, count)
    rows, failures, warnings = [], [], []
    if use_flight and parameter == "angle_of_attack":
        warnings.append("Angle-of-attack flight sweeps vary the fixed structural-load reference angle; the point-mass flight path does not integrate attitude/incidence.")
    for index, value in enumerate(values):
        if cancelled():
            raise RuntimeError("Study cancelled")
        update = conditions.model_dump() | {parameter: float(value)}
        if parameter == "speed":
            update["mach"] = None
        # A deterministic sweep changes one condition with a common gust
        # realization. Monte Carlo assigns distinct, reproducible gust seeds.
        update["seed"] = study_seed + index if kind == "monte_carlo" else conditions.seed
        try:
            sample = Conditions.model_validate(update)
            callback = (lambda fraction, message, i=index: progress((i + fraction) / count,
                f"Run {i + 1} of {count}: {message}")) if progress else None
            answer = simulate(project, sample, configuration_id, progress=callback, cancelled=cancelled) if use_flight else analyze(project, sample, configuration_id)
            metrics = answer.get("summary", answer)
            row = {"index": index, "parameter": parameter, "value": float(value), "gust_seed": sample.seed,
                "fidelity": answer.get("fidelity"), "warnings": answer.get("warnings", []),
                "validity": answer.get("validity", {key: answer[key] for key in
                    ["cp_valid", "within_mach_range", "within_small_angle_range", "cad_resolved"] if key in answer})}
            warnings.extend(answer.get("warnings", []))
            row.update({k: v for k, v in metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
            rows.append(row)
        except ValueError as exc:
            failures.append({"index": index, "value": float(value), "error": str(exc)})
        if progress:
            progress((index + 1) / count, f"Run {index + 1} of {count}")
    if not rows:
        raise ValueError("Every study run failed: " + str(failures[:1]))
    statistics = {}
    for key in rows[0]:
        if key in {"index", "parameter", "value", "gust_seed", "fidelity", "warnings", "validity"}:
            continue
        numbers = [row[key] for row in rows if key in row]
        statistics[key] = {"mean": float(np.mean(numbers)), "std": float(np.std(numbers)),
                           "p05": float(np.percentile(numbers, 5)), "p95": float(np.percentile(numbers, 95))}
    return {"rows": rows, "statistics": statistics, "failures": failures, "parameter": parameter, "seed": study_seed,
            "gust_seed_policy": "independent per sample" if kind == "monte_carlo" else "common across sweep",
            "fidelity": "Seeded engineering study, using the same approximations as the selected underlying solver.",
            "warnings": list(dict.fromkeys(warnings + ([f"{len(failures)} sampled inputs failed; statistics exclude them."] if failures else []))), "backend": "CPU"}
