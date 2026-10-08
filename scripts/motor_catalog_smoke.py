"""Read-only, live ThrustCurve.org integration check with a hard time limit.

Run with ``uv run --no-sync python scripts/motor_catalog_smoke.py --output
build/live-motor-smoke.json``. This contacts the real official API, downloads a
real ENG/RSE curve, and parses it through the application. It does not import a
motor into any project, assign a motor, or use a synthetic fallback. A blocked
network or unavailable provider produces a failed receipt and nonzero exit.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify_download(preview: dict, motor, provider_row: dict, motor_id: str, curve_id: str) -> dict:
    """Check downloaded bytes and physical data independently of the preview."""
    from rocket_workbench.motor_catalog import API_URL, BASE_URL, PROVIDER

    payload = base64.b64decode(provider_row["data"], validate=True)
    digest = hashlib.sha256(payload).hexdigest()
    provenance = preview["provenance"]
    if not payload or provenance.get("curve_sha256") != digest:
        raise ValueError("The preview hash does not identify the downloaded curve bytes.")
    expected = {"provider": PROVIDER, "motor_id": motor_id, "simfile_id": curve_id,
                "format": provider_row["format"], "curve_sha256": digest,
                "source_url": f"{BASE_URL}/simfiles/{curve_id}/",
                "retrieval_endpoint": API_URL + "download.json"}
    if any(provenance.get(key) != value for key, value in expected.items()):
        raise ValueError("Downloaded motor/curve identifiers or source provenance do not match.")
    if motor.provenance != provenance or not provenance.get("fetched_at"):
        raise ValueError("Reviewed curve lost its provider provenance.")
    if len(motor.curve) < 2 or any(len(point) != 2 or not all(math.isfinite(value) for value in point)
                                  or point[0] < 0 or point[1] < 0 for point in motor.curve):
        raise ValueError("Downloaded curve has missing, non-finite or negative time/thrust values.")
    if any(b[0] <= a[0] for a, b in zip(motor.curve, motor.curve[1:])):
        raise ValueError("Downloaded curve time values do not increase strictly.")
    # Independent trapezoidal integration checks the actual parsed samples.
    impulse = math.fsum((b[0] - a[0]) * (a[1] + b[1]) * 0.5
                        for a, b in zip(motor.curve, motor.curve[1:]))
    peak = max(point[1] for point in motor.curve)
    duration = motor.curve[-1][0]
    if not math.isfinite(impulse) or impulse <= 0 or peak <= 0 or duration <= 0:
        raise ValueError("Downloaded curve does not describe positive finite motor impulse.")
    summary = preview["summary"]
    for field, value in (("total_impulse_ns", impulse), ("max_thrust_n", peak), ("burn_time_s", duration)):
        if not math.isclose(summary[field], value, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError(f"Preview {field} differs from the downloaded samples.")
    if summary["samples"] != len(motor.curve):
        raise ValueError("Preview sample count differs from the downloaded curve.")
    if any(not math.isfinite(value) or value <= 0 for value in (motor.diameter, motor.length)):
        raise ValueError("Downloaded motor dimensions are not finite positive values.")
    if any(not math.isfinite(value) or value < 0 for value in (motor.dry_mass, motor.propellant_mass)):
        raise ValueError("Downloaded motor masses are invalid.")
    return {"motor_name": motor.name, "motor_id": motor_id, "simfile_id": curve_id,
            "file_format": provider_row["format"], "curve_bytes": len(payload),
            "curve_sha256": digest, "samples": len(motor.curve),
            "total_impulse_ns": impulse, "max_thrust_n": peak, "burn_time_s": duration,
            "diameter_m": motor.diameter, "length_m": motor.length,
            "dry_mass_kg": motor.dry_mass, "propellant_mass_kg": motor.propellant_mass,
            "provenance": provenance}


def live_check(query: str, manufacturer: str = "", transport=None) -> dict:
    """Use the production catalog client; the CLI never supplies a transport."""
    from rocket_workbench.motor_catalog import API_URL, PROVIDER, MotorCatalog, provider_request

    started = time.monotonic()
    receipt = {"status": "failed", "provider": PROVIDER, "started_at": datetime.now(timezone.utc).isoformat(),
               "query": query, "manufacturer": manufacturer, "actual_request": False,
               "project_modified": False, "synthetic_fallback": False, "requests": []}
    downloaded_rows = []
    actual_transport = transport or provider_request

    def audited_request(endpoint, criteria):
        receipt["actual_request"] = transport is None
        receipt["requests"].append({"endpoint": API_URL + endpoint, "criteria": criteria.copy()})
        response = actual_transport(endpoint, criteria)
        if endpoint == "download.json":
            downloaded_rows.extend(response.get("results", []))
        return response

    try:
        catalog = MotorCatalog(audited_request)
        search = catalog.search(query, manufacturer, limit=5)
        if not search["motors"]:
            raise ValueError("No real provider motor matched the requested designation/manufacturer.")
        motor_row = next((row for row in search["motors"] if row["data_files"] > 0), search["motors"][0])
        motor_id = motor_row["motor_id"]
        listing = catalog.curves(motor_id)
        if not listing["curves"]:
            raise ValueError("The real provider motor has no supported ENG/RSE files.")
        # Prefer manufacturer/certification curves, retaining the actual
        # reported attribution. A provider file can be malformed; reviewing up
        # to three downloaded files adds no network calls due to the cache.
        candidates = sorted(listing["curves"], key=lambda row:
                            (row["source"] not in {"mfr", "cert"}, row["format"] != "RockSim"))
        failures = []
        for row in candidates[:3]:
            try:
                preview = catalog.preview(motor_id, row["simfile_id"])
                motor = catalog.reviewed_motor(preview["review_token"])
                provider_row = next(item for item in downloaded_rows
                                    if item.get("simfileId") == row["simfile_id"] and item.get("motorId") == motor_id)
                checked = verify_download(preview, motor, provider_row, motor_id, row["simfile_id"])
                receipt.update({"status": "ok", "matched_motor": motor_row,
                                "curve": checked, "warnings": preview["warnings"],
                                "provider_certification_independently_verified": False})
                break
            except (ValueError, KeyError, StopIteration) as exc:
                failures.append(type(exc).__name__)
            except Exception as exc:
                # Provider import failures are bounded friendly messages in
                # the production client. Never print downloaded file content.
                failures.append(type(exc).__name__)
        else:
            raise ValueError("None of the first three real provider files passed preview/integrity checks (" + ", ".join(failures) + ").")
    except Exception as exc:
        # Fixed-provider client exceptions contain no credentials or arbitrary
        # response bodies. Keep the receipt bounded for CI diagnostics.
        receipt["error"] = str(exc)[:600]
        receipt["error_type"] = type(exc).__name__
    receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
    receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="J350W", help="Real motor designation; default: J350W")
    parser.add_argument("--manufacturer", default="", help="Optional provider manufacturer filter")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "live-motor-smoke.json")
    parser.add_argument("--timeout", type=float, default=60, help="Hard overall time limit, 10–60 seconds")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 10 <= args.timeout <= 60:
        parser.error("--timeout must be between 10 and 60 seconds")
    if args.worker:
        sys.path.insert(0, str(ROOT))
        receipt = live_check(args.query, args.manufacturer)
        print(json.dumps(receipt, allow_nan=False))
        return 0 if receipt["status"] == "ok" else 1

    started = time.monotonic()
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--query", args.query,
               "--manufacturer", args.manufacturer, "--timeout", str(args.timeout)]
    try:
        # A subprocess makes DNS, TLS, socket and parser time bounded together.
        # It is killed/reaped by subprocess.run on timeout, including Windows.
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf8", errors="replace",
                                 timeout=args.timeout, cwd=ROOT, check=False)
        receipt = json.loads(process.stdout)
        if not isinstance(receipt, dict) or receipt.get("status") not in {"ok", "failed"}:
            raise ValueError("Unexpected live-check worker receipt.")
        if process.returncode != 0:
            receipt["status"] = "failed"
        receipt["hard_timeout_seconds"] = args.timeout
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        receipt = {"status": "failed", "provider": "ThrustCurve.org", "actual_request": None,
                   "project_modified": False, "synthetic_fallback": False,
                   "error_type": type(exc).__name__,
                   "error": "Live motor verification exceeded its hard time limit." if isinstance(exc, subprocess.TimeoutExpired)
                            else "Live motor verification could not produce a valid receipt.",
                   "hard_timeout_seconds": args.timeout,
                   "elapsed_seconds": round(time.monotonic() - started, 3),
                   "completed_at": datetime.now(timezone.utc).isoformat()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf8")
    print(json.dumps({"status": receipt["status"], "actual_request": receipt["actual_request"],
                      "output": str(args.output), "error": receipt.get("error")}, allow_nan=False))
    return 0 if receipt["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
