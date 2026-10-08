"""Verify actual native Qt source-link clicks without opening a browser or network.

Requires the desktop extra and a usable display. QTest sends real mouse events
through QWebEngine; only the final system-browser call is intercepted. This
script checks links independently of the application startup/WebGL smoke.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/native-external-link-smoke.json"))
    options = parser.parse_args(argv)
    options.output.unlink(missing_ok=True)
    import json
    import sys
    import time
    from unittest.mock import patch

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from rocket_workbench.main import _connect_external_links, _public_https_external_url
    from PySide6.QtCore import QUrl, Qt, QPoint, qVersion
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings, QWebEngineUrlRequestInterceptor
    from PySide6.QtWebEngineWidgets import QWebEngineView

    session_token = "native-test-session-private-value"
    allowed = ["https://www.thrustcurve.org/motors/AeroTech/J350W/", "https://github.com/ThomasJ1214/stess-areo-chat"]
    rejected = ["file:///tmp/private-project.rocket", "http://www.thrustcurve.org/motors/",
                "https://127.0.0.1/", "https://[::1]/", "https://localhost/", "https://127.1/",
                "https://0x7f000001/", "https://internal.local/", "https://10.0.0.1/",
                "https://www.thrustcurve.org/?token=private", "https://www.thrustcurve.org/#session_token=private",
                f"https://www.thrustcurve.org/{session_token}", "https://user:secret@www.thrustcurve.org/"]
    assert all(_public_https_external_url(value, session_token) for value in allowed)
    assert not any(_public_https_external_url(value, session_token) for value in rejected)

    app = QApplication([])
    view = QWebEngineView()
    profile = QWebEngineProfile(app)
    page = QWebEnginePage(profile, view)
    view.setPage(page)

    class NoNetwork(QWebEngineUrlRequestInterceptor):
        def __init__(self):
            super().__init__()
            self.requests = 0
        def interceptRequest(self, request):
            if request.requestUrl().scheme() in {"http", "https"}:
                self.requests += 1
                request.block(True)

    interceptor = NoNetwork()
    profile.setUrlRequestInterceptor(interceptor)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
    _connect_external_links(page, session_token)
    signal_requests = []
    page.newWindowRequested.connect(lambda request: signal_requests.append({"user_initiated": request.isUserInitiated(), "scheme": request.requestedUrl().scheme()}))
    view.resize(700, 450)
    view.show()

    def until(predicate, seconds=8):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(10)
        assert predicate(), "Qt signal/action did not complete before deadline"

    loaded = []
    page.loadFinished.connect(lambda ok: loaded.append(ok))
    links = [allowed[0], rejected[0], rejected[1], rejected[2], rejected[9]]
    page.setHtml('<html><head><link rel="icon" href="data:,"></head><body style="margin:20px;font-size:20px">' + ''.join(
        f'<p><a id="link-{i}" target="_blank" href="{url}">Native link {i}</a></p>'
        for i, url in enumerate(links)) + '</body></html>', QUrl("http://127.0.0.1:65534/?token=" + session_token))
    until(lambda: bool(loaded))
    assert loaded[-1]
    baseline = page.url().toString()

    with patch.object(QDesktopServices, "openUrl", return_value=True) as desktop_open:
        for i in range(len(links)):
            coordinates = []
            page.runJavaScript(f'(() => {{const r=document.getElementById("link-{i}").getBoundingClientRect(); return JSON.stringify([r.x+r.width/2,r.y+r.height/2]);}})()', coordinates.append)
            until(lambda: bool(coordinates))
            old_signals = len(signal_requests)
            QTest.mouseClick(view.focusProxy(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             QPoint(round(json.loads(coordinates[0])[0]), round(json.loads(coordinates[0])[1])))
            until(lambda: len(signal_requests) > old_signals)
            assert page.url().toString() == baseline, "External link replaced the desktop application page"
        assert desktop_open.call_count == 1
        assert desktop_open.call_args.args[0].toString() == allowed[0]
        assert all(request["user_initiated"] for request in signal_requests)
        before = len(signal_requests)
        page.runJavaScript('setTimeout(() => window.open("https://www.thrustcurve.org/", "_blank"), 300)')
        until(lambda: len(signal_requests) > before)
        assert not signal_requests[-1]["user_initiated"]
        assert desktop_open.call_count == 1

    assert interceptor.requests == 0, "Native link smoke attempted a network request"
    receipt = {"status": "ok", "qt_version": qVersion(), "real_webengine_signal": True,
               "qtest_user_clicks": len(links), "desktop_browser_open_calls": 1,
               "non_user_initiated_request_rejected": True, "desktop_page_preserved": True,
               "network_requests": interceptor.requests, "url_filter_cases": len(allowed) + len(rejected)}
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf8")
    print(json.dumps(receipt))
    view.close()
    view.setPage(QWebEnginePage(view))
    page.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
