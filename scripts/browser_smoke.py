"""Exercise real browser workflows against an isolated local application instance.

Install the browser extra and Chromium first. The local APIs and numerical
engines run normally; the optional motor catalog uses an explicitly controlled
external-provider fixture. No fabricated solver results or live-network claims
are used. Hardware CUDA is a separate check.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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
CATALOG_MOTOR_ID = "a" * 24
CATALOG_CURVE_ID = "b" * 24
CATALOG_CURVE = b"; SYNTHETIC browser QA fixture, not measured motor data\nJ350-QA 54 295 P 0.235 0.567 WorkbenchQA\n0 0\n0.05 350\n1.0 350\n1.5 0\n"


@contextmanager
def capture_browser_failure(artifacts: Path, current_page):
    """Save UI evidence before Playwright's context closes on an exception."""
    try:
        yield
    except Exception:
        page = current_page()
        if page is not None and not page.is_closed():
            try:
                page.screenshot(path=str(artifacts / "failure.png"), full_page=True)
                (artifacts / "failure-aria.txt").write_text(page.locator("body").aria_snapshot(), encoding="utf8")
            except Exception:
                pass
        raise


def isolated_server_runner(port: int, path: Path) -> None:
    """Replace only the external provider transport, retaining the real API.

    The generated runner is saved with the receipt so the controlled fixture
    and lack of a live-provider validation remain explicit and reviewable.
    """
    path.write_text(f'''from __future__ import annotations
import base64
import sys
sys.path.insert(0, {str(ROOT)!r})
import uvicorn
from rocket_workbench.api import create_app
from rocket_workbench.motor_catalog import CatalogUnavailable, MotorCatalog

def catalog_transport(endpoint, criteria):
    if endpoint == "search.json":
        if criteria.get("designation") == "QA-OFFLINE":
            raise CatalogUnavailable("Synthetic QA provider unavailable. Import a local .eng/.rse file or retry later.")
        if criteria.get("designation") != "QA-J350":
            return {{"matches": 0, "results": []}}
        return {{"matches": 1, "results": [{{"motorId": {CATALOG_MOTOR_ID!r},
            "designation": "QA-J350", "manufacturer": "Synthetic Workbench QA",
            "diameter": 54, "length": 295, "dataFiles": 1, "type": "reload",
            "certOrg": "SYNTHETIC QA ONLY", "totImpulseNs": 428.75,
            "avgThrustN": 285.8333333333333, "maxThrustN": 350, "burnTimeS": 1.5}}]}}
    if endpoint == "download.json" and criteria.get("motorIds") == [{CATALOG_MOTOR_ID!r}]:
        return {{"results": [{{"motorId": {CATALOG_MOTOR_ID!r}, "simfileId": {CATALOG_CURVE_ID!r},
            "format": "RASP", "source": "user", "license": "PD",
            "data": base64.b64encode({CATALOG_CURVE!r}).decode("ascii")}}]}}
    raise AssertionError("Unexpected controlled provider request: " + repr((endpoint, criteria)))

app = create_app()
app.state.motor_catalog = MotorCatalog(transport=catalog_transport)
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port={port})
''', encoding="utf8")


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
    runner = args.artifacts / "isolated-catalog-server.py"
    isolated_server_runner(port, runner)
    process = subprocess.Popen([sys.executable, str(runner.resolve())],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    receipt = []
    external, errors = [], []
    started_at = datetime.now(timezone.utc).isoformat()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT).strip())
    page = None
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
        with sync_playwright() as playwright, capture_browser_failure(args.artifacts, lambda: page):
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
            expect(page).to_have_title("Rocket Workbench")
            icon_url = page.locator('link[rel="icon"]').evaluate("element => element.href")
            assert icon_url.startswith(base + "/"), "The app icon must be bundled locally"
            icon_response = context.request.get(icon_url)
            assert icon_response.status == 200 and "<svg" in icon_response.text()
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

            # Panels must free actual scene space and remain reachable without
            # depending on a screenshot or one particular large display size.
            assembly = page.locator(".project-sidebar")
            setup = page.locator(".inspector")
            expect(assembly).to_be_visible()
            expect(setup).to_be_visible()
            initial_scene_width = page.locator(".viewport").bounding_box()["width"]
            page.get_by_role("button", name="Hide assembly", exact=True).click()
            expect(assembly).to_be_hidden()
            expect(page.get_by_role("button", name="Show assembly", exact=True)).to_be_visible()
            assert page.locator(".viewport").bounding_box()["width"] > initial_scene_width
            page.get_by_role("button", name="Show assembly", exact=True).click()
            expect(assembly).to_be_visible()
            page.get_by_role("button", name="Hide setup", exact=True).click()
            expect(setup).to_be_hidden()
            page.get_by_role("button", name="Show setup", exact=True).click()
            expect(setup).to_be_visible()
            page.get_by_role("button", name="Focus 3D view", exact=True).click()
            expect(assembly).to_be_hidden()
            expect(setup).to_be_hidden()
            page.get_by_role("button", name="Reset layout", exact=True).click()
            expect(assembly).to_be_visible()
            expect(setup).to_be_visible()
            for label, panel in [("Resize assembly panel", assembly), ("Resize setup panel", setup)]:
                handle = page.get_by_role("separator", name=label, exact=True)
                before = panel.bounding_box()["width"]
                handle.focus()
                handle.press("ArrowRight")
                handle.press("ArrowRight")
                expect(handle).to_be_focused()
                assert abs(panel.bounding_box()["width"] - before) > 1, label
                before_drag = panel.bounding_box()["width"]
                handle_box = handle.bounding_box()
                start = (handle_box["x"] + handle_box["width"] / 2, handle_box["y"] + handle_box["height"] / 2)
                page.mouse.move(*start)
                page.mouse.down()
                page.mouse.move(start[0] + 20, start[1], steps=4)
                page.mouse.up()
                assert abs(panel.bounding_box()["width"] - before_drag) > 1, f"Pointer drag must resize {label}"
            scene_handle = page.get_by_role("separator", name="Resize 3D view", exact=True)
            scene_before = page.locator(".viewport").bounding_box()["height"]
            scene_handle.focus()
            scene_handle.press("ArrowDown")
            scene_handle.press("ArrowDown")
            assert abs(page.locator(".viewport").bounding_box()["height"] - scene_before) > 1
            page.get_by_role("button", name="Reset layout", exact=True).click()
            page.set_viewport_size({"width": 900, "height": 760})
            navigate("Flight")
            launch_control = page.get_by_role("button", name="Launch", exact=True)
            launch_control.scroll_into_view_if_needed()
            expect(launch_control).to_be_visible()
            expect(page.get_by_role("button", name="User guide", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "Small windows must not create body-wide horizontal overflow"
            window_bounds = page.locator(".main-layout").bounding_box()
            for selector in (".workspace-main", ".workspace-results", ".panel-divider-handle.horizontal"):
                panel_bounds = page.locator(selector).bounding_box()
                assert panel_bounds["y"] + panel_bounds["height"] <= window_bounds["y"] + window_bounds["height"] + 1, f"{selector} must stay inside the available window; results/playback cannot be clipped below it"
            expect(page.locator(".flight-map-overlay")).to_be_hidden()
            page.get_by_role("button", name="Flight map", exact=True).click()
            expect(page.get_by_role("dialog", name="Local flight map", exact=True)).to_be_visible()
            expect(page.get_by_test_id("local-flight-map")).to_be_visible()
            page.get_by_role("button", name="Close Local flight map", exact=True).click()
            page.screenshot(path=str(args.artifacts / "layout-900x760.png"), full_page=True)
            page.set_viewport_size({"width": 1600, "height": 1100})
            page.get_by_role("button", name="Reset layout", exact=True).click()
            receipt.append("Collapsible/focusable workspace panels, accessible keyboard resizing and reachable small-window launch controls")

            getting_started = page.get_by_role("button", name="Getting started", exact=True)
            getting_started.click()
            tutorial = page.get_by_role("dialog", name="Guided tutorials", exact=True)
            expect(tutorial).to_be_visible()
            topics = tutorial.get_by_role("navigation", name="Tutorial topics", exact=True)
            expect(topics.get_by_role("button", name=re.compile(r"^Start to finish"))).to_have_attribute("aria-current", "step")
            first_instruction = tutorial.locator("#tutorial-step-title").inner_text()
            tutorial.get_by_role("button", name="Next step", exact=True).click()
            expect(tutorial.locator("#tutorial-step-title")).not_to_have_text(first_instruction)
            resumed_instruction = tutorial.locator("#tutorial-step-title").inner_text()
            page.keyboard.press("Escape")
            expect(tutorial).to_have_count(0)
            expect(getting_started).to_be_focused()
            page.reload(wait_until="networkidle")
            page.get_by_role("button", name="Getting started", exact=True).click()
            expect(tutorial.locator("#tutorial-step-title")).to_have_text(resumed_instruction)
            page.keyboard.press("Escape")
            for workspace_name, topic_name in [
                ("Design", "Design & CAD"), ("Aerodynamics", "Aerodynamics"),
                ("Flight", "Launch & playback"), ("Structures", "Structures"),
                ("CFD", "CFD"), ("Studies", "Studies & comparisons"),
            ]:
                navigate(workspace_name)
                tutorial_button = page.get_by_role("button", name="Tutorial", exact=True)
                tutorial_button.click()
                expect(tutorial).to_be_visible()
                expect(topics.get_by_role("button", name=re.compile("^" + re.escape(topic_name)))).to_have_attribute("aria-current", "step")
                first_step = tutorial.locator("#tutorial-step-title").inner_text()
                assert tutorial.locator(".tutorial-instruction").inner_text().strip()
                assert tutorial.locator(".tutorial-check").inner_text().strip()
                tutorial.get_by_role("button", name="Next step", exact=True).click()
                expect(tutorial.locator("#tutorial-step-title")).not_to_have_text(first_step)
                continued_step = tutorial.locator("#tutorial-step-title").inner_text()
                page.keyboard.press("Escape")
                expect(tutorial_button).to_be_focused()
                tutorial_button.click()
                expect(tutorial.locator("#tutorial-step-title")).to_have_text(continued_step)
                if workspace_name == "Aerodynamics":
                    # Reading all the steps marks a tutorial complete; it never
                    # runs an analysis or mutates the current rocket by itself.
                    before_tutorial_jobs = len(job_requests)
                    for _ in range(20):
                        next_step = tutorial.get_by_role("button", name="Next step", exact=True)
                        if not next_step.count():
                            break
                        next_step.click()
                    tutorial.get_by_role("button", name="Finish tutorial", exact=True).click()
                    expect(tutorial.locator("#tutorial-step-title")).to_have_text("Tutorial complete")
                    expect(tutorial.get_by_role("progressbar")).to_have_attribute("value", "100")
                    assert len(job_requests) == before_tutorial_jobs
                    tutorial.get_by_role("button", name="Done", exact=True).click()
                else:
                    page.keyboard.press("Escape")
            receipt.append("Whole-app and all six page tutorials provide instructions/checks, retain progress after reopening/reload and complete without running solvers")

            navigate("Aerodynamics")
            definition_button = page.get_by_role("button", name="Definition of Mach override", exact=True)
            definition_button.click()
            expect(definition_button).to_have_attribute("aria-expanded", "true")
            definition = page.get_by_role("tooltip")
            expect(definition).to_contain_text("Air-relative speed divided by the local speed of sound")
            definition_box = definition.bounding_box()
            assert definition_box["x"] >= 0 and definition_box["x"] + definition_box["width"] <= 1601
            page.keyboard.press("Escape")
            expect(definition).to_have_count(0)
            expect(definition_button).to_be_focused()
            expect(definition_button).to_have_attribute("aria-expanded", "false")
            expect(page.get_by_label("Mach override", exact=True)).to_be_visible()
            receipt.append("Engineering question-mark definitions are clickable, stay on-screen and support keyboard dismissal/focus without changing input labels")

            # This is the real catalog API/curve parser/import transaction with
            # only its external transport controlled. Exercise an unavailable
            # provider and an explicit review before adding the synthetic motor.
            page.get_by_role("button", name="Import", exact=True).click()
            page.get_by_role("button", name="Find motor online", exact=True).first.click()
            motor_dialog = page.get_by_role("dialog", name="Find a motor curve", exact=True)
            expect(motor_dialog).to_be_visible()
            motor_dialog.get_by_label("Motor designation", exact=True).fill("QA-OFFLINE")
            with page.expect_response(lambda response: response.url.endswith("/api/motors/search")) as unavailable:
                motor_dialog.get_by_role("button", name="Search catalog", exact=True).click()
            assert unavailable.value.status == 503
            expect(motor_dialog.get_by_role("alert")).to_contain_text("Import a local .eng/.rse file")
            motor_dialog.get_by_label("Motor designation", exact=True).fill("QA-J350")
            with page.expect_response(lambda response: response.url.endswith("/api/motors/search")) as search_result:
                motor_dialog.get_by_role("button", name="Search catalog", exact=True).click()
            assert search_result.value.status == 200
            search_filters = search_result.value.request.post_data_json
            assert set(search_filters) == {"query", "manufacturer", "limit"}
            assert search_result.value.json()["motors"][0]["diameter_m"] == 0.054
            expect(motor_dialog.get_by_role("heading", name=re.compile("QA-J350"))).to_be_visible()
            with page.expect_response(lambda response: response.url.endswith("/curves")) as available_curves:
                motor_dialog.get_by_role("button", name="Review curves", exact=True).click()
            assert available_curves.value.status == 200
            with page.expect_response(lambda response: response.url.endswith("/api/motors/preview")) as previewed_curve:
                motor_dialog.get_by_role("button", name="Preview curve", exact=True).click()
            assert previewed_curve.value.status == 200
            preview = previewed_curve.value.json()
            assert preview["motor"]["curve"] == [[0.0, 0.0], [0.05, 350.0], [1.0, 350.0], [1.5, 0.0]]
            assert preview["summary"]["total_impulse_ns"] == 428.75
            assert preview["provenance"]["curve_sha256"] == hashlib.sha256(CATALOG_CURVE).hexdigest()
            assert preview["provenance"]["simfile_id"] == CATALOG_CURVE_ID
            expect(motor_dialog.get_by_test_id("motor-curve-plot")).to_be_visible()
            assert "L" in motor_dialog.get_by_test_id("motor-curve-plot").locator("path").get_attribute("d")
            expect(motor_dialog).to_contain_text(preview["provenance"]["curve_sha256"])
            expect(motor_dialog).to_contain_text("Contributor (provider reported)")
            latest_project = context.request.get(base + "/api/project").json()
            assert all(motor.get("provenance", {}).get("simfile_id") != CATALOG_CURVE_ID for motor in latest_project["motors"])
            latest_project["metadata"]["browser_motor_latest_state"] = "Design edited after curve preview"
            latest_project["name"] += " — reviewed motor QA"
            updated_project = context.request.put(base + "/api/project", data=latest_project)
            assert updated_project.status == 200, updated_project.text()
            with page.expect_response(lambda response: response.url.endswith("/api/motors/import")) as imported_curve:
                motor_dialog.get_by_role("button", name="Import reviewed motor", exact=True).click()
            assert imported_curve.value.status == 200
            imported_project = imported_curve.value.json()
            expect(motor_dialog).to_have_count(0)
            assert imported_project["metadata"]["browser_motor_latest_state"] == "Design edited after curve preview"
            assert imported_project["name"] == latest_project["name"]
            for key in ("components", "assets", "materials", "configurations", "analysis_settings"):
                assert imported_project[key] == latest_project[key], f"Motor import changed {key}"
            assert len(imported_project["motors"]) == len(latest_project["motors"]) + 1
            actual_motor = next(motor for motor in imported_project["motors"] if motor.get("provenance", {}).get("simfile_id") == CATALOG_CURVE_ID)
            assert actual_motor["curve"] == preview["motor"]["curve"]
            portable_motor_project = save_project("reviewed-motor.rocket.json")
            assert portable_motor_project["metadata"]["browser_motor_latest_state"] == "Design edited after curve preview"
            assert next(motor for motor in portable_motor_project["motors"] if motor["id"] == actual_motor["id"])["provenance"] == actual_motor["provenance"]
            no_errors()
            receipt.append("Controlled external-provider failure/recovery, real catalog preview/curve provenance and latest-project-preserving import; no live-network claim")
            navigate("Aerodynamics")
            with page.expect_response(lambda r: r.url.endswith("/api/analyze")) as analyzed:
                page.get_by_role("button", name="Run aerodynamic analysis", exact=True).click()
            aero = analyzed.value.json()["aero"]
            assert aero["mass_kg"] > 0 and aero["dynamic_pressure_pa"] > 0
            no_errors()
            receipt.append("GPU/WebGL viewport and real aerodynamic analysis")

            navigate("Flight")
            viewport = page.locator(".viewport")
            expect(viewport).to_have_attribute("data-scene", "launch")
            expect(viewport).to_have_attribute("data-launch-state", "pad")
            expect(viewport).to_have_attribute("data-ground-plane", "true")
            assert float(viewport.get_attribute("data-rail-length")) > 0
            local_map = page.get_by_test_id("local-flight-map")
            expect(local_map).to_have_attribute("data-ground-contact", "false")
            expect(page.get_by_test_id("flight-map-landing")).to_have_count(0)
            flight = job("Launch")
            assert flight["summary"]["complete"] and flight["summary"]["apogee_m"] > 100
            assert {"rail_exit", "burnout", "apogee", "main_deployment", "recovery"} <= {event["name"] for event in flight["events"]}
            timeline = page.get_by_label("Flight timeline")
            expect(timeline).to_be_visible()
            expect(page.get_by_role("button", name="Pause flight playback", exact=True)).to_be_visible()
            initial_play_time = float(timeline.input_value())
            page.wait_for_function("before => Number(document.querySelector('[aria-label=\"Flight timeline\"]').value) > before", arg=initial_play_time, timeout=4000)
            page.get_by_role("button", name="Pause flight playback", exact=True).click()
            expect(page.get_by_role("button", name="Play flight playback", exact=True)).to_be_visible()
            receipt.append("Real launch rail/flat ground scene and large Launch control start solved-flight playback automatically")
            timeline.evaluate("el => {Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'8');el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}")
            expect(page.locator(".timeline-label")).to_contain_text("8.0", timeout=3000)
            expect(page.get_by_role("button", name="Follow", exact=True)).to_be_visible()
            page.get_by_role("button", name="Expand flight map", exact=True).click()
            expect(page.get_by_role("dialog", name="Local flight map", exact=True)).to_be_visible()

            # Every map position comes from the solved east/north coordinates;
            # a finished timeline alone cannot manufacture a landing marker.
            expect(local_map).to_have_attribute("data-ground-contact", "true")
            recovery = next(event for event in flight["events"] if event["name"] == "recovery")
            landed_row = flight["trajectory"][recovery["index"]]
            landing = page.get_by_test_id("flight-map-landing")
            assert abs(landed_row["altitude"]) < 1e-4
            for key in ("east", "north", "time"):
                assert abs(float(landing.get_attribute("data-" + key)) - landed_row[key]) < 1e-6
            for event in flight["events"]:
                marker = local_map.locator(f'[data-map-event][data-event="{event["name"]}"]')
                if marker.count():
                    expected_row = flight["trajectory"][event["index"]]
                    for key in ("east", "north"):
                        assert abs(float(marker.get_attribute("data-" + key)) - expected_row[key]) < 1e-6
            current = page.get_by_test_id("flight-map-current")
            current_row = min(flight["trajectory"], key=lambda sample: abs(sample["time"] - 8))
            for key in ("east", "north", "time"):
                assert abs(float(current.get_attribute("data-" + key)) - current_row[key]) < 1e-6
            wind = page.get_by_test_id("flight-map-wind")
            wind_east, wind_north = [float(wind.get_attribute("data-" + key)) for key in ("east", "north")]
            assert abs(wind_east - current_row["wind_vector"][0]) < 1e-9
            assert abs(wind_north - current_row["wind_vector"][1]) < 1e-9
            if abs(wind_east) + abs(wind_north) > 1e-9:
                wind_line = wind.locator("line")
                assert float(wind_line.get_attribute("x2")) * wind_east >= 0
                assert float(wind_line.get_attribute("y2")) * wind_north <= 0, "North must point upward in SVG"
            assert page.get_by_test_id("flight-map-played-path").get_attribute("d").startswith("M")
            assert "L" in page.get_by_test_id("flight-map-future-path").get_attribute("d")
            map_svg = page.get_by_test_id("flight-map-svg")
            initial_span = float(map_svg.get_attribute("data-view-span"))
            initial_east_center = float(map_svg.get_attribute("data-east-center"))
            page.get_by_role("button", name="Zoom in on flight map", exact=True).click()
            assert float(map_svg.get_attribute("data-view-span")) < initial_span
            page.get_by_role("button", name="Zoom out of flight map", exact=True).click()
            assert abs(float(map_svg.get_attribute("data-view-span")) - initial_span) < 1e-6
            map_svg.focus()
            map_svg.press("ArrowRight")
            assert float(map_svg.get_attribute("data-east-center")) > initial_east_center
            page.get_by_role("button", name="Fit whole flight on map", exact=True).click()
            assert abs(float(map_svg.get_attribute("data-east-center")) - initial_east_center) < 1e-6
            apogee = next(event for event in flight["events"] if event["name"] == "apogee")
            page.get_by_test_id("map-event-apogee").click()
            assert abs(float(timeline.input_value()) - apogee["time"]) < 0.02
            engineering_before_points = context.request.get(base + "/api/project").json()
            point_east = float(map_svg.get_attribute("data-east-center"))
            point_north = float(map_svg.get_attribute("data-north-center"))
            page.get_by_role("button", name="Add a map point", exact=True).click()
            map_svg.focus()
            map_svg.press("Enter")
            page.get_by_test_id("map-point-name").fill("Launch observer QA")
            page.get_by_role("button", name="Save point", exact=True).click()
            marker = page.get_by_test_id("flight-map-landmark")
            expect(marker).to_have_count(1)
            map_marker_id = marker.get_attribute("data-point-id")
            assert abs(float(marker.get_attribute("data-east")) - point_east) < 1e-6
            assert abs(float(marker.get_attribute("data-north")) - point_north) < 1e-6
            page.get_by_role("button", name="Add a map point", exact=True).click()
            map_svg.focus()
            map_svg.press("Enter")
            page.get_by_test_id("map-point-name").fill("Delete me QA")
            page.get_by_role("button", name="Save point", exact=True).click()
            expect(page.get_by_test_id("flight-map-landmark")).to_have_count(2)
            page.get_by_role("button", name="Remove Delete me QA from map", exact=True).click()
            expect(page.get_by_test_id("flight-map-landmark")).to_have_count(1)
            assert context.request.get(base + "/api/project").json() == engineering_before_points, "Visual map markers must not change engineering project data"
            page.get_by_role("button", name="Close Local flight map", exact=True).click()
            expect(page.get_by_role("dialog", name="Local flight map", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="Play flight playback", exact=True)).to_be_visible()
            expect(page.get_by_test_id("flight-map-landmark")).to_have_attribute("data-point-id", map_marker_id)
            receipt.append("Top-down map preserves solved POI/landing/current positions and wind conventions; zoom/pan/reset and event seeking work")

            page.get_by_role("button", name="Follow", exact=True).click()
            expect(viewport).to_have_attribute("data-camera-mode", "follow")
            expect(viewport).to_have_attribute("data-auto-follow", "true")
            canvas = page.locator("canvas")
            canvas.scroll_into_view_if_needed()
            camera_before = viewport.get_attribute("data-camera-position")
            canvas_rect = canvas.bounding_box()
            drag_start = (canvas_rect["x"] + canvas_rect["width"] * 0.6, canvas_rect["y"] + canvas_rect["height"] * 0.55)
            page.mouse.move(*drag_start)
            page.mouse.down()
            page.mouse.move(drag_start[0] + 65, drag_start[1] + 28, steps=8)
            page.mouse.up()
            expect(viewport).to_have_attribute("data-auto-follow", "false")
            assert float(viewport.get_attribute("data-manual-until")) > page.evaluate("performance.now()")
            page.wait_for_function("before => document.querySelector('.viewport').dataset.cameraPosition !== before", arg=camera_before, timeout=3000)
            expect(page.get_by_role("button", name="Resume follow", exact=True)).to_be_visible()
            expect(viewport).to_have_attribute("data-auto-follow", "true", timeout=8000)
            page.mouse.move(*drag_start)
            page.mouse.wheel(0, 90)
            expect(viewport).to_have_attribute("data-auto-follow", "false")
            page.get_by_role("button", name="Resume follow", exact=True).click()
            expect(viewport).to_have_attribute("data-auto-follow", "true")
            page.get_by_role("button", name="Overview", exact=True).click()
            expect(viewport).to_have_attribute("data-camera-mode", "overview")
            page.get_by_role("button", name="Follow", exact=True).click()
            receipt.append("Actual camera responds to manual orbit/zoom, pauses follow for a grace period, resumes automatically and supports explicit resume/overview")
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
            page.get_by_role("button", name="Main airframe", exact=True).click()
            navigate("Structures")
            expect(page.get_by_role("button", name="Automatic mesh sizing", exact=True)).to_have_attribute("aria-pressed", "true")
            with page.expect_response(lambda r: r.url.endswith("/api/fea/preflight") and r.request.post_data_json["options"]["mesh_size"] == 0.02) as thin_checked:
                page.get_by_label("Target mesh size", exact=True).fill("0.02")
            assert thin_checked.value.status == 200, thin_checked.value.text()
            thin_check = thin_checked.value.json()
            thin_project = context.request.get(base + "/api/project").json()
            thin_component = next(c for c in thin_project["components"] if c["id"] == "airframe")
            assert thin_check["recommended_mesh_size_m"] <= thin_component["thickness"] / 2
            assert not thin_check["can_run"] and not thin_check["recommended_within_maximum_budget"]
            readiness = page.get_by_label("Mesh readiness", exact=True)
            expect(readiness).to_contain_text("supported budget")
            expect(page.get_by_role("button", name="Use recommended mesh", exact=True)).to_be_disabled()
            expect(page.get_by_role("button", name="Run finite element analysis", exact=True)).to_be_disabled()
            expect(page.get_by_role("button", name="Use beam/fin estimates", exact=True)).to_be_enabled()
            expect(page.get_by_role("button", name="Automatic mesh sizing", exact=True)).to_have_attribute("aria-pressed", "false")
            (args.artifacts / "thin-fea-preflight.json").write_text(json.dumps(thin_check, indent=2), "utf8")
            page.screenshot(path=str(args.artifacts / "thin-fea-guidance.png"), full_page=True)
            receipt.append("Thin original airframe has thickness-resolving mesh guidance, truthful whole-part budget limits and disabled misleading solid FEA")

            navigate("Design")
            page.get_by_role("button", name="Payload bay — replace with CAD", exact=True).click()
            page.get_by_role("button", name="Geometry", exact=True).click()
            asset = upload('input[accept=".step,.stp,.stl,.obj,.ply"]', ROOT / "examples" / "synthetic_payload.step", "import/geometry")
            assert asset["watertight"] and asset["volume"] > 0
            before_alignment = context.request.get(base + "/api/project").json()
            before_meshes = context.request.get(base + "/api/mesh").json()["components"]
            expect(page.get_by_role("button", name="Automatic alignment", exact=True)).to_have_attribute("aria-pressed", "true")
            preview_button = page.get_by_role("button", name="Preview automatic alignment", exact=True)
            expect(preview_button).to_be_enabled(timeout=10000)
            with page.expect_response(lambda r: r.url.endswith("/api/geometry/alignment")) as default_alignment:
                preview_button.click()
            assert default_alignment.value.status == 200, default_alignment.value.text()
            default_proposal = default_alignment.value.json()
            assert default_proposal["scale"] == 1 and not default_proposal["fit_length"]
            assert default_proposal["source_mesh_modified"] is False and default_proposal["neighbors_modified"] is False
            assert abs(default_proposal["aligned_bounds_m"][0][0] - default_proposal["target_bounds_m"][0][0]) < 1e-9
            unchanged_preview = context.request.get(base + "/api/project").json()
            assert unchanged_preview["components"] == before_alignment["components"]
            assert unchanged_preview["assets"] == before_alignment["assets"]
            expect(page.locator(".viewport")).to_have_attribute("data-alignment-preview", "true")
            with page.expect_response(lambda r: r.url.endswith("/api/geometry/attach")) as step_attached:
                page.get_by_role("button", name="Attach & use detailed geometry", exact=True).click()
            assert step_attached.value.status == 200, step_attached.value.text()
            first_attached = next(c for c in step_attached.value.json()["components"] if c["id"] == "payload")
            assert first_attached["asset_id"] == asset["id"] and first_attached["transform"] == default_proposal["transform"]
            expect(page.get_by_role("button", name="Automatic alignment", exact=True)).to_have_attribute("aria-pressed", "false")
            saved_step = save_project("step-default-aligned.rocket.json")
            upload('input[accept=".json,.rocket"]', args.artifacts / "step-default-aligned.rocket.json", "project/load")
            expect(page.get_by_role("button", name="Automatic alignment", exact=True)).to_have_attribute("aria-pressed", "false")
            assert next(c for c in saved_step["components"] if c["id"] == "payload")["transform"] == default_proposal["transform"]
            # A second real file is intentionally shorter, rotated and offset.
            # Importing it for the same part must re-enable a fresh placement
            # proposal without quietly moving the already attached STEP asset.
            offset_mesh = trimesh.Trimesh(vertices=asset["vertices"], faces=asset["faces"], process=False)
            offset_mesh.apply_scale(0.8)
            offset_mesh.apply_transform(trimesh.transformations.rotation_matrix(0.5, [0, 0, 1]))
            offset_mesh.apply_translation([0.8, -0.2, 0.35])
            offset_file = args.artifacts / "offset-rotated-payload.stl"
            offset_file.write_bytes(offset_mesh.export(file_type="stl"))
            page.get_by_label("Mesh file units", exact=True).select_option("m")
            asset = upload('input[accept=".step,.stp,.stl,.obj,.ply"]', offset_file, "import/geometry")
            before_alignment = context.request.get(base + "/api/project").json()
            before_meshes = context.request.get(base + "/api/mesh").json()["components"]
            assert next(c for c in before_alignment["components"] if c["id"] == "payload")["transform"] == default_proposal["transform"]
            expect(page.get_by_role("button", name="Automatic alignment", exact=True)).to_have_attribute("aria-pressed", "true")
            expect(page.get_by_role("button", name="Fit selected length", exact=True)).to_have_attribute("aria-pressed", "false")
            expect(preview_button).to_be_enabled(timeout=10000)
            with page.expect_response(lambda r: r.url.endswith("/api/geometry/alignment")) as fitted_alignment:
                page.get_by_role("button", name="Fit selected length", exact=True).click()
            assert fitted_alignment.value.status == 200, fitted_alignment.value.text()
            fitted_proposal = fitted_alignment.value.json()
            assert fitted_proposal["fit_length"] and fitted_proposal["scale"] > 0
            assert abs(fitted_proposal["scale"] - 1.25) < 1e-5
            assert abs(fitted_proposal["aligned_dimensions_m"][0] - fitted_proposal["target_dimensions_m"][0]) < 1e-9
            expect(page.get_by_label("CAD alignment preview", exact=True)).to_contain_text("uniformly")
            expect(page.get_by_role("button", name="Attach & use detailed geometry", exact=True)).to_be_enabled(timeout=10000)
            with page.expect_response(lambda r: r.url.endswith("/api/geometry/attach")) as attached:
                page.get_by_role("button", name="Attach & use detailed geometry", exact=True).click()
            assert attached.value.status == 200
            attached_project = attached.value.json()
            attached_component = next(c for c in attached_project["components"] if c["id"] == "payload")
            assert attached_component["asset_id"] == asset["id"]
            assert attached_component["transform"] == fitted_proposal["transform"]
            assert attached_project["assets"] == before_alignment["assets"]
            assert [c for c in attached_project["components"] if c["id"] != "payload"] == [c for c in before_alignment["components"] if c["id"] != "payload"]
            after_meshes = context.request.get(base + "/api/mesh").json()["components"]
            assert [m for m in after_meshes if m["id"] != "payload"] == [m for m in before_meshes if m["id"] != "payload"]
            selected_mesh = next(m for m in after_meshes if m["id"] == "payload")
            preview_mesh = fitted_proposal["preview_mesh"]["components"][0]
            assert selected_mesh["vertices"] == preview_mesh["vertices"] and selected_mesh["faces"] == preview_mesh["faces"]
            expect(page.locator(".viewport")).to_have_attribute("data-alignment-preview", "false")
            expect(page.get_by_role("button", name="Automatic alignment", exact=True)).to_have_attribute("aria-pressed", "false")
            no_errors()
            with page.expect_download() as saved:
                page.get_by_role("button", name="Save project", exact=True).click()
            saved.value.save_as(args.artifacts / "roundtrip.rocket.json")
            loaded = upload('input[accept=".json,.rocket"]', args.artifacts / "roundtrip.rocket.json", "project/load")
            assert any(saved_asset["id"] == asset["id"] for saved_asset in loaded["assets"])
            assert next(c for c in loaded["components"] if c["id"] == "payload")["transform"] == fitted_proposal["transform"]
            expect(page.get_by_role("button", name="Automatic alignment", exact=True)).to_have_attribute("aria-pressed", "false")
            receipt.append("Real STEP replacement and portable project save/reload")
            receipt.append("Automatic CAD preview preserves dimensions by default; explicit length fit matches attached world mesh and keeps source CAD, neighboring geometry and saved placement unchanged")

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
            navigate("Flight")
            expect(page.get_by_test_id("flight-map-landmark")).to_have_attribute("data-point-id", map_marker_id)
            expect(page.get_by_test_id("flight-map-landing")).to_have_count(0)
            expect(page.get_by_test_id("local-flight-map")).to_have_attribute("data-ground-contact", "false")

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
            navigate("Flight")
            expect(page.get_by_test_id("flight-map-landmark")).to_have_count(0)
            expect(page.get_by_test_id("flight-map-landing")).to_have_count(0)
            receipt.append("Named visual map points can be added/removed, persist for the same project and never change engineering data or leak to a different project")
            navigate("CFD")
            expect(page.get_by_label("Mach override", exact=True)).to_be_enabled()
            mach_input = page.get_by_label("Mach override", exact=True)
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
            cube_check = context.request.post(base + "/api/fea/preflight", data={"component_id": standalone["components"][0]["id"], "options": {"mesh_size": 0.035, "max_elements": 30000}}).json()
            assert cube_check["can_run"] and cube_check["cad_thickness_unknown"]
            assert abs(cube_check["recommended_mesh_size_m"] - 0.1 / 12) < 1e-9
            expect(page.get_by_label("Mesh readiness", exact=True)).to_contain_text("CAD wall thickness is unknown")
            page.get_by_role("button", name="Use recommended mesh", exact=True).click()
            expect(page.get_by_role("button", name="Automatic mesh sizing", exact=True)).to_have_attribute("aria-pressed", "true")
            page.wait_for_function("expected => Math.abs(Number(document.querySelector('[aria-label=\"Target mesh size\"]').value) - expected) < 1e-9", arg=cube_check["recommended_mesh_size_m"], timeout=10000)
            page.get_by_label("Target mesh size", exact=True).fill("0.035")
            expect(page.get_by_role("button", name="Automatic mesh sizing", exact=True)).to_have_attribute("aria-pressed", "false")
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
            receipt.append("CAD solid preflight supplies honest unknown-thickness guidance; recommended sizing and explicit manual override remain usable")

            navigate("CFD")
            health = context.request.get(base + "/api/health").json()
            diagnostics_button = page.get_by_role("button", name="GPU diagnostics", exact=True).first
            diagnostics_button.click()
            diagnostics_dialog = page.get_by_role("dialog", name="GPU diagnostics", exact=True)
            expect(diagnostics_dialog).to_be_visible()
            gpu = health["capabilities"]["gpu_diagnostics"]
            expect(diagnostics_dialog).to_contain_text(gpu["reason"])
            expect(diagnostics_dialog).to_contain_text("compiled float64 reduction")
            expect(diagnostics_dialog).to_contain_text("CUDA calculation available" if gpu["available"] else "CUDA calculation unavailable")
            page.screenshot(path=str(args.artifacts / "gpu-diagnostics.png"), full_page=True)
            page.keyboard.press("Escape")
            expect(diagnostics_dialog).to_have_count(0)
            expect(diagnostics_button).to_be_focused()
            receipt.append("GPU diagnostics displays the actual device/kernel probe and CPU fallback reason without claiming hardware acceleration")

            page.get_by_label("Maximum steps", exact=True).fill("1")
            page.get_by_label("Flow-through times", exact=True).fill("0.1")
            page.get_by_label("Wall time limit", exact=True).fill("0")
            page.get_by_role("button", name="Run until converged", exact=True).click()
            expect(page.get_by_label("Maximum steps", exact=True)).to_be_disabled()
            expect(page.get_by_label("Flow-through times", exact=True)).to_be_disabled()
            with page.expect_response(lambda r: r.url.endswith("/api/jobs") and r.request.method == "POST") as unlimited_started:
                page.get_by_role("button", name="Solve flow field", exact=True).click()
            assert unlimited_started.value.status == 200, unlimited_started.value.text()
            unlimited_id = unlimited_started.value.json()["id"]
            unlimited_options = unlimited_started.value.request.post_data_json["options"]
            assert unlimited_options["run_until_converged"] and unlimited_options["max_wall_seconds"] == 0
            assert unlimited_options["max_steps"] == 1 and unlimited_options["flow_through_times"] == 0.1
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                live_job = context.request.get(base + "/api/jobs/" + unlimited_id).json()
                assert live_job["status"] in {"queued", "running"}, live_job
                live_steps = re.search(r"Euler step (\d+); ([\d.]+) domain crossings", live_job["message"])
                if live_steps and int(live_steps.group(1)) > 1 and float(live_steps.group(2)) > 0.12:
                    break
                page.wait_for_timeout(150)
            else:
                raise AssertionError("Unbounded CFD did not advance beyond the disabled finite budgets")
            assert live_job["progress_basis"] == "convergence_unknown" and live_job["eta_seconds"] is None
            progressbar = page.get_by_role("progressbar", name="cfd progress", exact=True)
            expect(progressbar).to_be_visible()
            assert progressbar.get_attribute("aria-valuenow") is None
            expect(page.locator(".job-meta")).to_contain_text("completion time unknown")
            cancel_url = base + "/api/jobs/" + unlimited_id + "/cancel"

            def terminal_cancel_reply(route):
                # Delay the real cancel response until its actual terminal state.
                # This exercises response/poll ordering without fabricating fields.
                response = route.fetch()
                assert response.status == 200
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    terminal = context.request.get(base + "/api/jobs/" + unlimited_id).json()
                    if terminal["status"] == "cancelled":
                        assert terminal["result"], "Cancelled CFD must retain the actual integrated partial field"
                        route.fulfill(response=response, json=terminal)
                        return
                    time.sleep(0.05)
                raise AssertionError("The actual CFD worker did not finish cancellation")

            page.route(cancel_url, terminal_cancel_reply)
            with page.expect_response(lambda r: r.url == cancel_url) as cancelled_response:
                page.get_by_role("button", name="Cancel", exact=True).click()
            assert cancelled_response.value.status == 200
            assert cancelled_response.value.json()["status"] == "cancelled"
            page.unroute(cancel_url, terminal_cancel_reply)
            expect(page.locator(".job-progress")).to_have_count(0, timeout=15000)
            expect(page.get_by_text("Partial pressure force", exact=True)).to_be_visible()
            cancelled_job = context.request.get(base + "/api/jobs/" + unlimited_id).json()
            partial = cancelled_job["result"]
            assert cancelled_job["status"] == "cancelled" and not partial["summary"]["converged"]
            assert partial["summary"]["status"] == "cancelled" and partial["summary"]["steps"] > 1
            assert partial["summary"]["domain_crossings_completed"] > 0.1 and partial["samples"] and partial["surface"]
            with page.expect_download() as partial_download:
                page.get_by_role("button", name="Flow solution JSON", exact=True).click()
            partial_download.value.save_as(args.artifacts / "cancelled-cfd-export.json")
            exported_partial = json.loads((args.artifacts / "cancelled-cfd-export.json").read_text("utf8"))
            assert exported_partial["summary"] == partial["summary"] and exported_partial["inputs"] == partial["inputs"]
            assert any("partial" in warning.lower() for warning in exported_partial["warnings"])
            navigate("Structures")
            expect(page.get_by_role("button", name="Run finite element analysis", exact=True)).to_be_disabled()
            expect(page.locator('select[aria-label="Surface load"] option[value="cfd_pressure"]')).to_be_disabled()
            no_errors()
            receipt.append("Actual unlimited CFD exceeds disabled step/time ceilings, reports unknown convergence progress, survives a delayed terminal cancellation reply, exports partial fields and blocks pressure FEA")

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
            "graphics": "Chromium software WebGL; hardware GPU/CUDA not established",
            "motor_catalog": "Controlled synthetic external-provider transport; real local search/preview/import API; live provider/network availability not established",
            "external_requests": external}, indent=2), encoding="utf8")
        print(json.dumps({"status": "passed", "checks": receipt}, indent=2))
    except Exception as exc:
        (args.artifacts / "receipt.json").write_text(json.dumps({"status": "failed", "checks_completed": receipt,
            "error": str(exc), "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(),
            "source_commit": revision, "source_dirty": dirty, "external_requests": external,
            "motor_catalog": "Controlled synthetic external-provider transport; no live-network validation",
            "javascript_errors": errors}, indent=2), encoding="utf8")
        if page is not None and not page.is_closed():
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
