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
from .cfd_progress import CfdProgress


def _physical_project_hash(project: Project) -> str:
    """Bind flight history to saved motor, material, recovery and geometry inputs.

    Analysis panel settings, display units and the project title may change while
    inspecting an existing launch. Other saved project inputs remain bound.
    """
    encoded = json.dumps(project.model_dump(mode="json", exclude={"analysis_settings", "unit_system", "name"}),
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


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
        uses_cfd = kind == "cfd" or kind == "comparison" and bool(options.get("use_cfd"))
        if uses_cfd:
            mode = options.get("mode", "steady")
            if mode not in {"steady", "transient"}:
                raise ValueError("CFD mode must be steady or transient.")
            if kind == "comparison" and mode != "steady":
                raise ValueError("CFD geometry comparisons require steady mode. Run each launch-driven transient separately to inspect its actual history.")
            options["mode"] = mode
            progress_basis = "physical_time" if mode == "transient" and kind == "cfd" else "convergence_unknown"
        cfd_source = None
        flight_source = None
        flight_result = None
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
        if kind == "cfd" and options.get("mode") == "transient":
            source = options.get("transient_source", "fixed")
            if source not in {"fixed", "launch"}:
                raise ValueError("Transient CFD source must be fixed or launch.")
            if source == "launch" and options.get("flight_job_id"):
                try:
                    prior = self.get(str(options["flight_job_id"]))
                except KeyError as exc:
                    raise ValueError("The selected launch history is unavailable. Rerun launch or use a new calculated launch.") from exc
                if prior["kind"] != "flight" or prior["status"] != "completed" or not prior.get("result"):
                    raise ValueError("Launch-driven CFD requires a completed flight job.")
                source_project = self.input_project(prior["id"])
                if prior.get("geometry_signature") != signature or _physical_project_hash(source_project) != _physical_project_hash(snapshot):
                    raise ValueError("Rocket configuration, motor, recovery or geometry changed after this launch. Recompute the launch before using its history.")
                source_conditions = prior["result"].get("inputs", {}).get("conditions", {})
                launch_fields = ("altitude", "wind_speed", "wind_direction", "turbulence", "temperature_delta",
                                 "rail_length", "launch_angle", "launch_azimuth", "dt", "max_time", "seed")
                if any(source_conditions.get(name) != getattr(conditions, name) for name in launch_fields):
                    raise ValueError("Launch conditions changed after this flight. Recompute the launch to drive CFD with the current conditions.")
                flight_result = copy.deepcopy(prior["result"])
                flight_source = {"job_id": prior["id"], "generated_for_cfd": False,
                                 "inputs": copy.deepcopy(prior["result"].get("inputs", {}))}
        if kind == "fea" and options.get("load_mode") == "cfd_pressure":
            from .models import active_components
            component = next((c for c in active_components(project, configuration_id) if c.id == options.get("component_id")), None)
            if component is None or not component.external:
                raise ValueError("CFD pressures can only be transferred to a component included in the external flow geometry.")
            try:
                prior = self.get(str(options.get("cfd_job_id", "")))
            except KeyError as exc:
                raise ValueError("Select an available completed CFD job before transferring pressures.") from exc
            if (prior["kind"] != "cfd" or prior["status"] != "completed" or not prior["result"]["summary"]["converged"]
                    or prior["result"]["summary"].get("mode", "steady") != "steady"):
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
                "flight_source": flight_source, "flight_result": flight_result,
                "telemetry": None, "cfd_progress": CfdProgress() if uses_cfd else None,
                "eta_seconds": None, "eta_range_seconds": None,
                "eta_basis": None, "eta_confidence": None,
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
            if job["cfd_progress"] is not None:
                eta = job["eta_seconds"] if job["status"] == "running" else None
            else:
                eta = elapsed * (1 / progress - 1) if job["status"] == "running" and progress > 0.01 else None
            return {k: v for k, v in job.items() if k not in {
                "cancel", "created", "started", "finished", "project_snapshot", "cfd_progress", "flight_result", "flight_source"}} | {
                "elapsed_seconds": max(0, elapsed), "eta_seconds": eta,
                "eta_range_seconds": job["eta_range_seconds"] if job["status"] == "running" else None,
                "eta_basis": job["eta_basis"] if job["status"] == "running" else None,
                "eta_confidence": job["eta_confidence"] if job["status"] == "running" else None}

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
        requested_options = copy.deepcopy(options)
        with self.lock:
            # A cancelled queued job may have been pruned before its future
            # reaches the worker. Never dereference an expired registry entry.
            job = self.jobs.get(identity)
            if job is None or job["cancel"].is_set():
                return
            job.update(status="running", started=time.monotonic(), message="Preparing simulation")

        def progress(fraction, message):
            with self.lock:
                # A solver preparation percentage or a decaying residual is not
                # a numerical convergence/completion percentage.
                measured = float(np.clip(fraction, 0, 0.999)) if job["cfd_progress"] is None else job["progress"]
                job.update(progress=measured, message=str(message))

        def telemetry(event):
            with self.lock:
                event = copy.deepcopy(event)
                estimates = job["cfd_progress"].update(event)
                if event.get("eta_scope"):
                    estimates["eta_scope"] = event["eta_scope"]
                job.update(estimates, telemetry=event)
                if kind == "cfd" and event.get("mode") == "transient" and event.get("phase") == "integration":
                    target = event.get("target_physical_time_s")
                    value = event.get("physical_time_s")
                    if isinstance(target, (int, float)) and target > 0 and isinstance(value, (int, float)):
                        job["progress"] = float(np.clip(value / target, 0, .999))
                elif event.get("mode") != "transient" or kind == "comparison":
                    job["progress"] = 0.0

        def cancelled():
            return job["cancel"].is_set()

        try:
            if kind == "flight":
                from .solvers.flight import simulate
                result = simulate(project, conditions, configuration_id, progress, cancelled)
            elif kind == "cfd":
                from .solvers.cfd import solve
                profile = None
                if options.get("mode") == "transient" and options.get("transient_source", "fixed") == "launch":
                    from .solvers.flight_profile import build_flight_profile
                    source_result = job["flight_result"]
                    if source_result is None:
                        from .solvers.flight import simulate
                        telemetry({"mode": "transient", "phase": "flight_preparation"})
                        source_result = simulate(project, conditions, configuration_id,
                            lambda fraction, message: progress(0, "Preparing launch history: " + message), cancelled)
                        job["flight_source"] = {"generated_for_cfd": True, "job_id": None,
                            "inputs": {"configuration_id": configuration_id or project.active_configuration_id,
                                "conditions": conditions.model_dump(), "project_sha256": job["project_sha256"],
                                "geometry_signature": job["geometry_signature"], "application_version": __version__}}
                    window = options.get("flight_window", "interval" if "flight_start_s" in options or "flight_end_s" in options else "whole")
                    if window not in {"whole", "interval"}:
                        raise ValueError("Choose the whole launch or a selected flight interval.")
                    profile = build_flight_profile(source_result,
                        start_s=options.get("flight_start_s") if window == "interval" else None,
                        end_s=options.get("flight_end_s") if window == "interval" else None,
                        temperature_delta=conditions.temperature_delta)
                    options["duration_s"] = profile.duration_s
                    options["flight_start_s"], options["flight_end_s"] = profile.start_s, profile.end_s
                    job["flight_source"].update(profile.metadata)
                    job["flight_source"]["profile"] = profile.to_dict()
                    job["flight_source"]["fidelity"] = source_result.get("fidelity")
                    job["flight_source"]["warnings"] = source_result.get("warnings", [])
                    with self.lock:
                        job["flight_result"] = None
                result = solve(project, conditions, configuration_id, options, progress, cancelled,
                               telemetry=telemetry, freestream_provider=profile)
                if profile is not None:
                    result["warnings"] = list(dict.fromkeys(result.get("warnings", []) + list(profile.warnings)))
            elif kind == "fea":
                from .solvers.structure import solve_fea
                component_id = options.get("component_id")
                if not component_id:
                    raise ValueError("Select a component for finite element analysis.")
                result = solve_fea(project, component_id, conditions, options, progress, cancelled)
            elif kind == "comparison":
                result = compare(project, conditions, configuration_id, options, progress, cancelled,
                                 telemetry=telemetry if job["cfd_progress"] is not None else None)
            else:
                result = study(project, conditions, configuration_id, kind, options, progress, cancelled)
            result["inputs"] = {"project_id": project.id, "project_name": project.name,
                "configuration_id": configuration_id or project.active_configuration_id,
                "geometry_signature": job["geometry_signature"],
                "application_version": __version__, "project_sha256": job["project_sha256"],
                "submitted_at": job["submitted_at"],
                "conditions": conditions.model_dump(), "options": {k: v for k, v in requested_options.items() if k != "cfd_surface"}}
            if options != requested_options:
                result["inputs"]["effective_options"] = {k: v for k, v in options.items() if k != "cfd_surface"}
            if job["cfd_source"] is not None:
                result["inputs"]["cfd_source"] = copy.deepcopy(job["cfd_source"])
            if job["flight_source"] is not None:
                result["inputs"]["flight_source"] = copy.deepcopy(job["flight_source"])
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


def compare(project, conditions, configuration_id=None, options=None, progress=None, cancelled=None, telemetry=None):
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
            stage_telemetry = (lambda event, l=label: telemetry(event | {"comparison_stage": l,
                "eta_scope": f"{l} CFD integration only; whole comparison ETA unknown"})) if telemetry else None
            result[label]["cfd"] = solve(model, conditions, configuration_id, options, callback, cancelled,
                                        telemetry=stage_telemetry)
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
