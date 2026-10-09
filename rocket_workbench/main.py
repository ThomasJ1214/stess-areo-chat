"""Desktop entry point, also providing a headless local development API."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path


def _public_https_external_url(value: str, session_token: str | None = None) -> bool:
    """External source links must never send a desktop session URL to a browser."""
    import ipaddress
    from urllib.parse import parse_qsl, unquote, urlsplit

    if not value or any(character.isspace() or ord(character) < 32 for character in value):
        return False
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme.lower() != "https" or not host or url.username or url.password:
            return False
        # Reading port also rejects malformed/non-numeric port declarations.
        if url.port is not None and not 1 <= url.port <= 65535:
            return False
    except ValueError:
        return False
    if session_token and session_token.lower() in unquote(value).lower():
        return False
    if any("token" in key.lower() for section in (url.query, url.fragment)
           for key, _ in parse_qsl(section, keep_blank_values=True)):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Reject local names and alternate numeric IPv4 notation browsers may
        # normalize to loopback (for example 127.1 or 0x7f000001).
        return ("." in host and not host.endswith((".localhost", ".local", ".internal"))
                and not host.startswith("0x")
                and not all(character.isdecimal() or character == "." for character in host))
    return address.is_global and not address.is_multicast


def _connect_external_links(page, session_token: str | None = None):
    """Open explicitly clicked HTTPS source links outside the authenticated view."""
    from PySide6.QtGui import QDesktopServices

    def open_external(request):
        if not request.isUserInitiated():
            return
        url = request.requestedUrl()
        if url.isValid() and _public_https_external_url(url.toString(), session_token):
            QDesktopServices.openUrl(url)

    page.newWindowRequested.connect(open_external)
    return open_external


def _start_local_service(app, timeout_seconds: float = 20):
    """Keep the selected loopback port reserved until Uvicorn owns the listener."""
    import logging
    import uvicorn

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
    except BaseException:
        listener.close()
        raise
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
        log_level="warning", log_config=None, access_log=False,
        timeout_graceful_shutdown=3))

    def run_server():
        try:
            server.run(sockets=[listener])
        except BaseException:
            # Uvicorn may use SystemExit for startup errors; record those too.
            logging.getLogger(__name__).exception("Local application service failed")

    worker = threading.Thread(target=run_server, daemon=True, name="rocket-local-api")
    worker.start()
    deadline = time.monotonic() + timeout_seconds
    while not server.started and worker.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        _stop_local_service(server, worker, listener)
        raise RuntimeError("The local application service could not start.")
    return server, worker, listener, port


def _stop_local_service(server, worker, listener):
    server.should_exit = True
    worker.join(timeout=5)
    listener.close()


def smoke_test(output_path: Path | None = None) -> int:
    from .api import capabilities
    from .demo import demo_project
    from .models import Conditions
    from .solvers.aero import analyze
    from .solvers.flight import simulate
    from .geometry import project_mesh
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from .models import Component, GeometryAsset, Project
    from .solvers.structure import solve_fea
    import trimesh
    import gmsh
    if BRepPrimAPI_MakeBox(1, 1, 1).Shape().IsNull():
        raise RuntimeError("Packaged OpenCASCADE solid kernel failed")
    gmsh.initialize(interruptible=False)
    gmsh.finalize()
    model = demo_project()
    aero = analyze(model, Conditions())
    flight = simulate(model, Conditions(dt=0.05, max_time=300))
    mesh = project_mesh(model)
    if not len(mesh.vertices) or aero["mass_kg"] <= 0 or not flight["trajectory"]:
        raise RuntimeError("Packaged application smoke check failed")
    # Exercise the actual isolated mesher and sparse solve in frozen builds.
    solid = trimesh.creation.box([0.04, 0.02, 0.02])
    asset = GeometryAsset(id="smoke-solid", name="Smoke-test solid", format="stl", vertices=solid.vertices.tolist(), faces=solid.faces.tolist(), watertight=True, volume=float(solid.volume))
    fea_project = Project(components=[Component(id="smoke-component", asset_id=asset.id, geometry_mode="replacement", material_id="fiberglass")], assets=[asset])
    fea = solve_fea(fea_project, "smoke-component", Conditions(wind_speed=0), {
        "mesh_size": 0.01, "max_elements": 2000, "backend": "cpu", "load_mode": "traction", "traction_pa": [1000, 0, 0]})
    if fea["summary"]["force_balance_relative_error"] > 1e-7 or abs(fea["summary"]["applied_force_n"][0] - 0.4) > 1e-5:
        raise RuntimeError("Packaged FEA mesher/worker/solve smoke check failed")
    from . import __version__
    evidence = {"status": "ok", "application_version": __version__, "capabilities": capabilities(), "vertices": len(mesh.vertices),
                      "flight_samples": len(flight["trajectory"]), "summary": flight["summary"],
                      "fea_elements": fea["summary"]["elements"], "fea_equilibrium_error": fea["summary"]["force_balance_relative_error"]}
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(evidence, indent=2, allow_nan=False), "utf8")
    print(json.dumps(evidence, allow_nan=False))
    return 0


def main(argv=None) -> int:
    # Required for the isolated Gmsh mesher in frozen Windows executables.
    import multiprocessing
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Rocket Workbench desktop engineering application")
    from . import __version__
    parser.add_argument("--version", action="version", version=f"Rocket Workbench {__version__}")
    parser.add_argument("--headless", action="store_true", help="Run local API without a desktop window")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--data-dir", type=Path, help="Optional session storage directory")
    parser.add_argument("--smoke-test", "--bundle-smoke-test", dest="smoke", action="store_true")
    parser.add_argument("--smoke-output", type=Path, help="Write the engineering smoke receipt to a JSON file")
    parser.add_argument("--desktop-smoke-test", action="store_true", help="Launch the actual desktop and verify its UI/WebGL, then exit")
    parser.add_argument("--desktop-preferences-smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--preferences-smoke-phase", type=int, choices=(1, 2), help=argparse.SUPPRESS)
    parser.add_argument("--preferences-smoke-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--preferences-smoke-window-width", type=int, choices=range(640, 1921), help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if options.desktop_preferences_smoke_test and (not options.preferences_smoke_phase or not options.preferences_smoke_output):
        parser.error("Desktop preferences smoke requires its phase and output path")
    if options.smoke_output and not options.smoke:
        parser.error("--smoke-output requires --smoke-test")
    if options.smoke:
        if options.smoke_output:
            options.smoke_output.unlink(missing_ok=True)
        return smoke_test(options.smoke_output)
    from .api import create_app
    import uvicorn
    if options.headless:
        # Windowed Windows executables have no stdout/stderr; Uvicorn's default
        # colour formatter must not attempt .isatty() on those missing streams.
        configuration = {} if sys.stdout is not None and sys.stderr is not None else {"log_config": None, "access_log": False}
        uvicorn.run(create_app(data_dir=options.data_dir), host=options.host, port=options.port, **configuration)
        return 0
    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError as exc:
        raise RuntimeError("Desktop dependencies missing. Install the desktop extra: uv sync --extra desktop") from exc
    application = QApplication(sys.argv)
    application.setApplicationName("Rocket Workbench")
    application.setOrganizationName("Rocket Workbench")
    # PyInstaller's data root preserves the source checkout's assets layout.
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    application.setWindowIcon(QIcon(str(resource_root / "assets" / "rocket-workbench.ico")))
    smoke_directory = None
    if (options.desktop_smoke_test or options.desktop_preferences_smoke_test) and options.data_dir is None:
        import tempfile
        smoke_directory = tempfile.TemporaryDirectory(prefix="rocket-desktop-smoke-")
    data_dir = options.data_dir or (Path(smoke_directory.name) if smoke_directory else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "RocketWorkbench")
    data_dir.mkdir(parents=True, exist_ok=True)
    import logging
    from logging.handlers import RotatingFileHandler
    log_path = data_dir / "application.log"
    handler = RotatingFileHandler(log_path, maxBytes=3 * 1024 * 1024, backupCount=2, encoding="utf8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    previous_log_level = logging.getLogger().level
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger(__name__).info("Starting Rocket Workbench %s; Python %s; session directory %s", __version__, sys.version.split()[0], data_dir)
    token = secrets.token_hex(32)
    try:
        server, worker, listener, port = _start_local_service(create_app(token=token, data_dir=data_dir))
    except Exception:
        logging.getLogger(__name__).exception("Desktop startup failed")
        if not (options.desktop_smoke_test or options.desktop_preferences_smoke_test):
            QMessageBox.critical(None, "Rocket Workbench startup failed", f"The local application service could not start. Details: {log_path}")
        else:
            logging.getLogger(__name__).error("Desktop smoke: local service startup failed")
        logging.getLogger().removeHandler(handler)
        logging.getLogger().setLevel(previous_log_level)
        handler.close()
        if smoke_directory:
            smoke_directory.cleanup()
        return 1
    window = QMainWindow()
    window.setWindowIcon(application.windowIcon())
    window.setWindowTitle("Rocket Workbench — aerodynamic, flight and structural analysis")
    window.resize(1440, 960)
    if options.desktop_preferences_smoke_test and options.preferences_smoke_window_width:
        window.resize(options.preferences_smoke_window_width, 760)
    view = QWebEngineView(window)
    # Project/session state lives in the backend. Keep the browser profile in
    # memory, so packaging and restricted development hosts need no browser cache.
    profile = QWebEngineProfile(application)
    view.setPage(QWebEnginePage(profile, view))
    _connect_external_links(view.page(), token)
    from .desktop_preferences import install_desktop_preferences
    desktop_preferences = install_desktop_preferences(window, view, data_dir, f"http://127.0.0.1:{port}")
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
    # Native save dialogs make browser downloads work in the embedded desktop.
    def download_requested(item):
        from PySide6.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(window, "Save Rocket Workbench export", item.downloadFileName())
        if filename:
            target = Path(filename)
            item.setDownloadDirectory(str(target.parent))
            item.setDownloadFileName(target.name)
            item.accept()
        else:
            item.cancel()
    view.page().profile().downloadRequested.connect(download_requested)
    preferences_smoke_finish = None
    if options.desktop_preferences_smoke_test:
        from .desktop_preferences_smoke import start_preferences_smoke
        preferences_smoke_finish = start_preferences_smoke(application, window, view, data_dir,
            options.preferences_smoke_phase, options.preferences_smoke_output, port)
    # Register the smoke document callback before navigation can finish.
    view.setUrl(QUrl(f"http://127.0.0.1:{port}/?token={token}"))
    window.setCentralWidget(view)
    window.show()
    if options.desktop_smoke_test:
        smoke_done = False
        def check_ui():
            def checked(value):
                nonlocal smoke_done
                if smoke_done:
                    return
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except ValueError:
                        value = None
                if isinstance(value, dict) and all(value.get(key) for key in ("shell", "webgl", "api", "project")):
                    smoke_done = True
                    logging.getLogger(__name__).info("Desktop smoke passed: %s", value)
                    application.exit(0)
                else:
                    QTimer.singleShot(500, check_ui)
            view.page().runJavaScript("""JSON.stringify((() => {
                if (!window.__rocketSmokeApi) {
                    window.__rocketSmokeApi = {pending:true};
                    const headers = {'X-Rocket-Session':new URLSearchParams(location.search).get('token') || ''};
                    Promise.all(['/api/health','/api/project'].map(async url => {
                        const response = await fetch(url,{headers});
                        if (!response.ok) throw new Error('API status '+response.status);
                        return response.json();
                    })).then(([health,project]) => {
                        window.__rocketSmokeApi = {api:health.status==='ok',project:project.components.length>0};
                    }).catch(() => {window.__rocketSmokeApi = {api:false,project:false};});
                }
                const c=document.querySelector('canvas');
                const g=c && (c.getContext('webgl2') || c.getContext('webgl'));
                return {shell:!!document.querySelector('.app-shell'),webgl:!!g,
                    api:!!window.__rocketSmokeApi.api,project:!!window.__rocketSmokeApi.project,title:document.title};
            })())""", checked)
        def timed_out():
            nonlocal smoke_done
            if not smoke_done:
                smoke_done = True
                logging.getLogger(__name__).error("Desktop smoke failed: UI, authenticated API/project or WebGL unavailable within 30 seconds")
                application.exit(1)
        QTimer.singleShot(500, check_ui)
        QTimer.singleShot(30000, timed_out)
    try:
        exit_code = application.exec()
        if preferences_smoke_finish:
            exit_code = preferences_smoke_finish(exit_code)
    finally:
        desktop_preferences.timer.stop()
        _stop_local_service(server, worker, listener)
        view.close()
        logging.getLogger().removeHandler(handler)
        logging.getLogger().setLevel(previous_log_level)
        handler.close()
        if smoke_directory:
            smoke_directory.cleanup()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
