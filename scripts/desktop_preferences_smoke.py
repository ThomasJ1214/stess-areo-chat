"""Check real Qt/frontend preferences across fresh processes and loopback ports.

Run with the desktop extra and a display. Uses isolated temporary project/UI
storage, an in-memory WebEngine profile, and the production persistence adapter.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def phase(data_dir: Path, index: int, avoid_port: int | None):
    import secrets
    import socket
    import time
    from PySide6.QtCore import QUrl, qVersion, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from rocket_workbench.api import create_app
    from rocket_workbench.desktop_preferences import install_desktop_preferences
    from rocket_workbench.main import _start_local_service, _stop_local_service

    reservation = None
    if avoid_port:
        reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            reservation.bind(("127.0.0.1", avoid_port))
        except OSError as exc:
            # TCP TIME_WAIT may already reserve the old origin after process exit.
            if exc.errno not in (98, 48, 10048):
                raise
            reservation.close()
            reservation = None
    token = secrets.token_hex(32)
    server, worker, listener, port = _start_local_service(create_app(token=token, data_dir=data_dir))
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = QMainWindow()
    window.resize(1440, 960)
    view = QWebEngineView(window)
    profile = QWebEngineProfile(app)
    page = QWebEnginePage(profile, view)
    view.setPage(page)
    window.setCentralWidget(view)
    persistence = install_desktop_preferences(window, view, data_dir, f"http://127.0.0.1:{port}")
    window.show()
    page.setUrl(QUrl(f"http://127.0.0.1:{port}/?token={token}"))

    def until(predicate, seconds=25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            QTest.qWait(20)
        raise AssertionError("Native preferences smoke timed out")

    def js(expression):
        result = []
        page.runJavaScript(f"JSON.stringify({expression})", result.append)
        until(lambda: bool(result), 5)
        return json.loads(result[0]) if result[0] else None

    def click(text=None, aria=None, selector="button"):
        expression = f"(() => {{const b=[...document.querySelectorAll({json.dumps(selector)})].find(b => "
        expression += f"b.getAttribute('aria-label')==={json.dumps(aria)}" if aria else f"b.textContent.trim()==={json.dumps(text)}"
        expression += "); if(!b) return false; b.click(); return true;})()"
        assert js(expression), f"Missing native frontend control: {aria or text}"
        QTest.qWait(120)
        app.processEvents()

    until(lambda: js("!!document.querySelector('.app-shell') && !!document.querySelector('.workspace-nav')"))
    if index == 1:
        click(aria="Hide assembly")
        click(text="Getting started")
        click(text="Next step")
        click(text="Next step")
        tutorial_title = js("document.getElementById('tutorial-step-title').textContent")
        click(aria="Close tutorial")
        # A saved capture must also refresh the injected script for this process.
        from rocket_workbench.desktop_preferences import DesktopPreferences, TUTORIAL_KEY
        until(lambda: json.loads(DesktopPreferences(data_dir).values.get(TUTORIAL_KEY, "{}" )).get("app", {}).get("step") == 2)
        loaded = []
        page.loadFinished.connect(loaded.append)
        page.triggerAction(QWebEnginePage.WebAction.Reload)
        until(lambda: bool(loaded))
        assert loaded[-1]
        until(lambda: js("!!document.querySelector('.workspace-nav')"))
        assert js("!!document.querySelector('button[aria-label=\"Show assembly\"]')"), "Reload restored stale layout"
        click(text="Getting started")
        assert js("document.getElementById('tutorial-step-title').textContent") == tutorial_title, "Reload restored stale tutorial progress"
        click(aria="Close tutorial")
    else:
        assert js("!!document.querySelector('button[aria-label=\"Show assembly\"]')"), "Saved layout was not applied by frontend initialization"
        click(text="Getting started")
        tutorial_title = js("document.getElementById('tutorial-step-title').textContent")
        click(aria="Close tutorial")
    click(text="Flight", selector=".workspace-nav button")
    until(lambda: js("!!document.querySelector('button[aria-label=\"Expand flight map\"]')"))
    click(aria="Expand flight map")
    if index == 1:
        # Prove a final edit is flushed on close, even before the next poll.
        persistence.timer.stop()
        click(aria="Add a map point", selector="dialog button")
        assert js("(() => {const map=document.querySelector('dialog .flight-map-svg');map.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));return true;})()")
        until(lambda: js("!!document.querySelector('[data-testid=map-point-name]')"))
        js("(() => {document.querySelector('[data-testid=map-point-name]').focus();return true;})()")
        QTest.keyClick(view.focusProxy(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(view.focusProxy(), "Restart smoke POI")
        click(text="Save point", selector="dialog button")
    until(lambda: js("[...document.querySelectorAll('dialog .flight-map-landmarks li span')].some(e=>e.textContent==='Restart smoke POI')"))
    # A session key must never be copied to the preferences file.
    js("(() => {localStorage.setItem('X-Rocket-Session','forbidden-secret-sentinel'); return true;})()")
    receipt = {"phase": index, "port": port, "qt_version": qVersion(),
               "tutorial_title": tutorial_title, "layout_restored": index == 2,
               "in_session_reload_preserved_latest_preferences": index == 1,
               "map_point_visible": True, "profile_off_the_record": profile.isOffTheRecord()}
    window.close()
    until(lambda: not window.isVisible(), 5)
    assert persistence.close_ready
    assert "forbidden-secret-sentinel" not in (data_dir / "desktop-preferences.json").read_text("utf8")
    _stop_local_service(server, worker, listener)
    view.setPage(QWebEnginePage(view))
    page.deleteLater()
    app.processEvents()
    if reservation:
        reservation.close()
    print(json.dumps(receipt))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/native-preferences-smoke.json"))
    parser.add_argument("--phase", type=int, choices=(1, 2))
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--avoid-port", type=int)
    parser.add_argument("--executable", type=Path, help="Verify an installed/frozen executable instead of the source Qt host")
    options = parser.parse_args()
    if options.phase:
        return phase(options.data_dir, options.phase, options.avoid_port)
    options.output.unlink(missing_ok=True)
    from rocket_workbench.demo import demo_project
    with tempfile.TemporaryDirectory(prefix="rocket-native-preferences-") as directory:
        data_dir = Path(directory)
        (data_dir / "last-project.json").write_text(demo_project().model_dump_json(), "utf8")
        phases = []
        for index in (1, 2):
            reservation = None
            if options.executable:
                phase_output = data_dir / f"phase-{index}.json"
                command = [str(options.executable.resolve()), "--desktop-preferences-smoke-test", "--preferences-smoke-phase", str(index),
                           "--preferences-smoke-output", str(phase_output), "--data-dir", directory]
                if phases:
                    import socket
                    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        reservation.bind(("127.0.0.1", phases[0]["port"]))
                    except OSError as exc:
                        reservation.close()
                        reservation = None
                        if exc.errno not in (98, 48, 10048):
                            raise
            else:
                command = [sys.executable, str(Path(__file__).resolve()), "--phase", str(index), "--data-dir", directory]
                if phases:
                    command += ["--avoid-port", str(phases[0]["port"])]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=90, env=os.environ.copy())
            finally:
                if reservation:
                    reservation.close()
            if result.returncode:
                failure = {"status": "failed", "phase": index, "exit_code": result.returncode}
                if options.executable and phase_output.exists():
                    failure["native_receipt"] = json.loads(phase_output.read_text("utf8"))
                options.output.parent.mkdir(parents=True, exist_ok=True)
                options.output.write_text(json.dumps(failure, indent=2) + "\n", "utf8")
                raise RuntimeError(f"Native preferences phase {index} failed:\n{result.stderr}\n{result.stdout}")
            phases.append(json.loads(phase_output.read_text("utf8")) if options.executable else json.loads(result.stdout.strip().splitlines()[-1]))
            assert phases[-1].get("status", "ok") == "ok"
        assert phases[0]["port"] != phases[1]["port"]
        assert phases[0]["tutorial_title"] == phases[1]["tutorial_title"]
        saved = json.loads((data_dir / "desktop-preferences.json").read_text("utf8"))
        receipt = {"status": "ok", "fresh_processes": 2, "different_loopback_origins": True,
                   "restored_before_frontend_state_initialization": True,
                   "final_edit_saved_on_close_before_poll": True,
                   "foreign_session_key_excluded": True, "saved_ui_keys": len(saved["values"]), "installed_executable": bool(options.executable), "phases": phases}
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(receipt, indent=2) + "\n", "utf8")
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
