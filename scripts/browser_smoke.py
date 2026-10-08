"""Exercise real browser workflows against an isolated local application instance.

Install the browser extra and Chromium first. No external requests, mocked APIs,
or fabricated solver results are used. Hardware CUDA is a separate check.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import trimesh
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Existing Chromium executable; otherwise use Playwright's installed browser")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "build" / "browser-smoke")
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    (args.artifacts / "receipt.json").unlink(missing_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = (args.artifacts / "server.log").open("w", encoding="utf8")
    process = subprocess.Popen([sys.executable, "-m", "rocket_workbench.main", "--headless", "--port", str(port)],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    receipt = []
    external, errors = [], []
    started_at = datetime.now(timezone.utc).isoformat()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT).strip())
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Local API failed to start; inspect server.log")
            try:
                with urlopen(base + "/api/health", timeout=1) as response:
                    if json.load(response)["status"] == "ok":
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Local API did not become ready")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True,
                args=["--no-sandbox", "--enable-unsafe-swiftshader", "--use-angle=swiftshader"])
            context = browser.new_context(viewport={"width": 1600, "height": 1100}, accept_downloads=True)
            def local_only(route):
                if route.request.url.startswith(base + "/"):
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()
            context.route("**/*", local_only)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            job_requests = []
            page.on("request", lambda request: job_requests.append(request.url)
                    if request.method == "POST" and request.url.endswith("/api/jobs") else None)
            page.goto(base, wait_until="networkidle")
            expect(page.locator("canvas")).to_be_visible()
            assert page.evaluate("!!document.querySelector('canvas').getContext('webgl2')")
            guide_button = page.get_by_role("button", name="User guide", exact=True)
            guide_button.click()
            expect(page.get_by_role("dialog", name="Using Rocket Workbench")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog", name="Using Rocket Workbench")).to_have_count(0)
            expect(guide_button).to_be_focused()
            receipt.append("Offline user guide and accessible dialog focus/Escape")

            def no_errors():
                assert page.locator(".error-banner").count() == 0, page.locator(".error-banner").all_text_contents()
                assert not errors, errors

            def navigate(name):
                page.locator(".workspace-nav").get_by_role("button", name=name, exact=True).click()

            def upload(selector, path, endpoint):
                with page.expect_response(lambda r: r.url.endswith("/api/" + endpoint) and r.request.method == "POST") as response:
                    page.locator(selector).set_input_files(str(path))
                assert response.value.status == 200, response.value.text()
                expect(page.get_by_role("button", name="Save project", exact=True)).to_be_enabled(timeout=10000)
                no_errors()
                return response.value.json()

            def job(button, timeout=90):
                with page.expect_response(lambda r: r.url.endswith("/api/jobs") and r.request.method == "POST") as started:
                    page.get_by_role("button", name=button, exact=True).click()
                assert started.value.status == 200, started.value.text()
                identity = started.value.json()["id"]
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    answer = context.request.get(base + "/api/jobs/" + identity).json()
                    if answer["status"] not in {"running", "queued"}:
                        assert answer["status"] == "completed", answer.get("error")
                        expect(page.locator(".job-progress")).to_have_count(0, timeout=10000) if page.locator(".job-progress").count() else None
                        # Let the UI's own polling receive the completed result.
                        page.wait_for_timeout(900)
                        no_errors()
                        return answer["result"]
                    page.wait_for_timeout(150)
                raise AssertionError(f"{button} did not finish")

            def save_project(filename):
                with page.expect_download() as saved:
                    page.get_by_role("button", name="Save project", exact=True).click()
                saved.value.save_as(args.artifacts / filename)
                return json.loads((args.artifacts / filename).read_text("utf8"))

            navigate("Aerodynamics")
            with page.expect_response(lambda r: r.url.endswith("/api/analyze")) as analyzed:
                page.get_by_role("button", name="Run aerodynamic analysis", exact=True).click()
            aero = analyzed.value.json()["aero"]
            assert aero["mass_kg"] > 0 and aero["dynamic_pressure_pa"] > 0
            no_errors()
            receipt.append("GPU/WebGL viewport and real aerodynamic analysis")

            navigate("Flight")
            flight = job("Simulate full flight")
            assert flight["summary"]["complete"] and flight["summary"]["apogee_m"] > 100
            assert {"rail_exit", "burnout", "apogee", "main_deployment", "recovery"} <= {event["name"] for event in flight["events"]}
            timeline = page.get_by_label("Flight timeline")
            expect(timeline).to_be_visible()
            timeline.evaluate("el => {Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'8');el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}")
            expect(page.locator(".timeline-label")).to_contain_text("8.0", timeout=3000)
            expect(page.get_by_role("button", name="Follow", exact=True)).to_be_visible()
            with page.expect_download() as exported:
                page.get_by_role("button", name="Flight data CSV", exact=True).click()
            exported.value.save_as(args.artifacts / "flight.csv")
            assert "dynamic_pressure" in (args.artifacts / "flight.csv").read_text().splitlines()[0]
            with (args.artifacts / "flight.csv").open(newline="", encoding="utf8") as stream:
                first_row = next(csv.DictReader(stream))
            assert first_row["_result_fidelity"] and first_row["_result_backend"]
            assert json.loads(first_row["_result_inputs"])["project_sha256"] == flight["inputs"]["project_sha256"]
            with page.expect_download() as run_inputs:
                page.get_by_role("button", name="Run input project", exact=True).click()
            run_inputs.value.save_as(args.artifacts / "flight-inputs.rocket.json")
            snapshot = json.loads((args.artifacts / "flight-inputs.rocket.json").read_text("utf8"))
            assert snapshot["analysis_settings"]["conditions"] == flight["inputs"]["conditions"]
            digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            assert digest == flight["inputs"]["project_sha256"]
            assert flight["inputs"]["application_version"] and flight["inputs"]["submitted_at"]
            (args.artifacts / "flight-result.json").write_text(json.dumps(flight, indent=2, allow_nan=False), "utf8")
            page.screenshot(path=str(args.artifacts / "flight.png"), full_page=True)
            receipt.append("Complete dual-deployment flight, events, timeline, CSV and content-verified portable run inputs")

            navigate("Studies")
            page.get_by_label("Samples", exact=True).fill("3")
            sweep = job("Run parameter sweep")
            assert len(sweep["rows"]) == 3 and sweep["rows"][0]["value"] != sweep["rows"][-1]["value"]
            page.get_by_role("button", name="Compare", exact=True).click()
            compared = job("Compare flight performance")
            assert compared["original"]["flight"]["summary"]["complete"]
            expect(page.get_by_text("GEOMETRY FLIGHT PERFORMANCE", exact=True)).to_be_visible()
            receipt.append("Parameter sweep and original/current flight comparison")

            navigate("Design")
            page.get_by_role("button", name="Payload bay — replace with CAD", exact=True).click()
            page.get_by_role("button", name="Geometry", exact=True).click()
            asset = upload('input[accept=".step,.stp,.stl,.obj,.ply"]', ROOT / "examples" / "synthetic_payload.step", "import/geometry")
            assert asset["watertight"] and asset["volume"] > 0
            with page.expect_response(lambda r: r.url.endswith("/api/geometry/attach")) as attached:
                page.get_by_role("button", name="Attach & use detailed geometry", exact=True).click()
            assert attached.value.status == 200
            assert next(c for c in attached.value.json()["components"] if c["id"] == "payload")["asset_id"] == asset["id"]
            no_errors()
            with page.expect_download() as saved:
                page.get_by_role("button", name="Save project", exact=True).click()
            saved.value.save_as(args.artifacts / "roundtrip.rocket.json")
            loaded = upload('input[accept=".json,.rocket"]', args.artifacts / "roundtrip.rocket.json", "project/load")
            assert loaded["assets"][0]["id"] == asset["id"]
            receipt.append("Real STEP replacement and portable project save/reload")

            navigate("Aerodynamics")
            page.get_by_label("Primary stream speed", exact=True).fill("123")
            page.get_by_label("Lateral wind", exact=True).fill("7.25")
            saved_settings = save_project("analysis-settings.rocket.json")
            assert saved_settings["analysis_settings"]["conditions"]["speed"] == 123
            assert saved_settings["analysis_settings"]["conditions"]["wind_speed"] == 7.25
            page.get_by_label("Primary stream speed", exact=True).fill("99")
            page.get_by_label("Lateral wind", exact=True).fill("9")
            upload('input[accept=".json,.rocket"]', args.artifacts / "analysis-settings.rocket.json", "project/load")
            navigate("Aerodynamics")
            expect(page.get_by_label("Primary stream speed", exact=True)).to_have_value("123")
            expect(page.get_by_label("Lateral wind", exact=True)).to_have_value("7.25")
            # Reloading the same numeric value must also discard an unfinished
            # local edit; a primitive prop equality alone cannot signal reload.
            wind_input = page.get_by_label("Lateral wind", exact=True)
            wind_input.fill("7.25e")
            wind_input.blur()
            expect(wind_input).to_have_attribute("aria-invalid", "true")
            upload('input[accept=".json,.rocket"]', args.artifacts / "analysis-settings.rocket.json", "project/load")
            expect(page.get_by_label("Lateral wind", exact=True)).to_have_value("7.25")
            expect(page.get_by_label("Lateral wind", exact=True)).to_have_attribute("aria-invalid", "false")
            # A browser restart reads backend-persisted settings rather than
            # keeping those values only in the current React component.
            page.reload(wait_until="networkidle")
            navigate("Aerodynamics")
            expect(page.get_by_label("Primary stream speed", exact=True)).to_have_value("123")
            expect(page.get_by_label("Lateral wind", exact=True)).to_have_value("7.25")
            receipt.append("Edited analysis conditions persist in saved/reloaded projects and browser restarts")

            navigate("Design")
            page.get_by_role("button", name="Geometry", exact=True).click()
            page.get_by_label("Mesh file units", exact=True).select_option("m")
            cube_file = args.artifacts / "browser-box.stl"
            cube_file.write_bytes(trimesh.creation.box([0.1, 0.1, 0.1]).export(file_type="stl"))
            upload('input[accept=".step,.stp,.stl,.obj,.ply"]', cube_file, "import/geometry")
            with page.expect_download() as backup:
                with page.expect_response(lambda r: r.url.endswith("/api/geometry/standalone")) as created:
                    page.get_by_role("button", name="New project from CAD", exact=True).click()
            backup.value.save_as(args.artifacts / "before-standalone.json")
            standalone = created.value.json()
            assert standalone["metadata"]["cad_only"] and len(standalone["components"]) == 1
            navigate("CFD")
            expect(page.get_by_label("Mach override")).to_be_enabled()
            mach_input = page.get_by_label("Mach override")
            before_requests = len(job_requests)
            mach_input.fill("1e")
            page.get_by_role("button", name="Solve flow field", exact=True).click()
            expect(page.locator(".error-banner")).to_contain_text("Correct Mach override")
            expect(mach_input).to_have_value("1e")
            assert len(job_requests) == before_requests, "A malformed field must not submit stale solver inputs"
            page.get_by_role("button", name="Dismiss error", exact=True).click()
            mach_input.fill("")
            mach_input.press_sequentially("0.3")
            expect(mach_input).to_have_value("0.3")
            receipt.append("Malformed numeric edits block jobs; same-value project reload resets unfinished text")
            page.get_by_label("Angle of attack", exact=True).fill("5")
            page.get_by_label("Lateral wind", exact=True).fill("0")
            for label, value in [("Lengthwise grid cells", "12"), ("Maximum steps", "1500"), ("Flow-through times", "8"), ("CFL number", "0.7"), ("Convergence tolerance", "0.001")]:
                page.get_by_label(label, exact=True).fill(value)
            cfd_settings = save_project("cfd-settings.rocket.json")
            assert cfd_settings["analysis_settings"]["cfd_options"]["grid_resolution"] == 12
            assert cfd_settings["analysis_settings"]["cfd_options"]["max_steps"] == 1500
            assert cfd_settings["analysis_settings"]["cfd_options"]["convergence_tolerance"] == 0.001
            page.get_by_label("Lengthwise grid cells", exact=True).fill("16")
            upload('input[accept=".json,.rocket"]', args.artifacts / "cfd-settings.rocket.json", "project/load")
            navigate("CFD")
            expect(page.get_by_label("Lengthwise grid cells", exact=True)).to_have_value("12")
            expect(page.get_by_label("Maximum steps", exact=True)).to_have_value("1500")
            expect(page.get_by_label("Convergence tolerance", exact=True)).to_have_value("0.001")
            flow = job("Solve flow field", timeout=240)
            assert flow["summary"]["converged"] and flow["samples"] and flow["summary"]["min_pressure_pa"] > 0
            (args.artifacts / "cfd-result.json").write_text(json.dumps(flow, indent=2, allow_nan=False), "utf8")
            page.screenshot(path=str(args.artifacts / "cfd.png"), full_page=True)
            receipt.append("Standalone STL geometry, portable solver settings and genuinely converged nonzero CFD")

            navigate("Structures")
            page.get_by_label("Target mesh size", exact=True).fill("0.035")
            page.get_by_label("Clamp side", exact=True).select_option("max")
            page.get_by_label("Surface load", exact=True).select_option("cfd_pressure")
            structure = job("Run finite element analysis", timeout=120)
            assert structure["summary"]["cfd_pressure_transfer"]["mapped_surface_area_fraction"] > 0.5
            assert structure["summary"]["force_balance_relative_error"] < 1e-7
            assert structure["summary"]["max_von_mises_pa"] > 0
            cfd_source = structure["inputs"]["cfd_source"]
            assert cfd_source["inputs"]["project_sha256"] == flow["inputs"]["project_sha256"]
            surface_digest = hashlib.sha256(json.dumps(flow["surface"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            assert cfd_source["surface_sha256"] == surface_digest
            (args.artifacts / "fea-result.json").write_text(json.dumps(structure, indent=2, allow_nan=False), "utf8")
            page.get_by_role("button", name="Deformation", exact=True).click()
            expect(page.get_by_role("button", name="Deformation", exact=True)).to_have_attribute("aria-pressed", "true")
            page.screenshot(path=str(args.artifacts / "fea.png"), full_page=True)
            receipt.append("Geometry-matched CFD pressure transfer into actual solid FEA and deformation display")

            navigate("Design")
            ork = upload('input[accept=".ork"]', ROOT / "tests/fixtures/openrocket/dual-deployment.ork", "import/ork")
            assert len(ork["configurations"]) == 6 and all(c["motor_id"] is None for c in ork["configurations"])
            page.get_by_label("Flight configuration", exact=True).select_option(ork["configurations"][0]["id"])
            expect(page.locator("canvas")).to_be_visible()
            no_errors()
            receipt.append("Real upstream ORK import, all six configurations and explicit unresolved motors")
            assert not external, external
            browser.close()
        (args.artifacts / "receipt.json").write_text(json.dumps({"status": "passed", "checks": receipt,
            "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(),
            "source_commit": revision, "source_dirty": dirty,
            "graphics": "Chromium software WebGL; hardware GPU/CUDA not established", "external_requests": external}, indent=2), encoding="utf8")
        print(json.dumps({"status": "passed", "checks": receipt}, indent=2))
    except Exception as exc:
        (args.artifacts / "receipt.json").write_text(json.dumps({"status": "failed", "checks_completed": receipt,
            "error": str(exc), "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(),
            "source_commit": revision, "source_dirty": dirty, "external_requests": external,
            "javascript_errors": errors}, indent=2), encoding="utf8")
        if "page" in locals() and not page.is_closed():
            try:
                page.screenshot(path=str(args.artifacts / "failure.png"), full_page=True)
                (args.artifacts / "failure-aria.txt").write_text(page.locator("body").aria_snapshot(), encoding="utf8")
            except Exception:
                pass
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()


if __name__ == "__main__":
    main()
