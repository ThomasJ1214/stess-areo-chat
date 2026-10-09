"""Persist a bounded whitelist of desktop UI preferences across session origins.

Projects remain in the project store. The WebEngine profile remains in memory;
session cookies, credentials and arbitrary browser storage never enter this file.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
from pathlib import Path

LAYOUT_KEY = "rocket-workbench.workspace-layout.v1"
TUTORIAL_KEY = "rocket-workbench-tutorials-v1"
MAP_PREFIX = "rocket-workbench:map-points:"
MAX_BYTES = 1024 * 1024
MAX_KEYS = 128
_MAP_KEY = re.compile(r"rocket-workbench:map-points:[A-Za-z0-9_-]{1,128}\Z")
_TOURS = {"app", "design", "aero", "flight", "structure", "cfd", "studies"}
_LOG = logging.getLogger(__name__)


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _clean_value(key: str, value):
    if not isinstance(value, str) or len(value) > 65536:
        return None
    try:
        data = json.loads(value)
    except (ValueError, TypeError, RecursionError):
        return None
    if key == LAYOUT_KEY and isinstance(data, dict):
        result = {name: data[name] for name in ("assembly", "setup", "focus") if isinstance(data.get(name), bool)}
        for name, lower, upper in (("assemblyWidth", 190, 380), ("setupWidth", 280, 480), ("sceneRatio", 0.6, 3)):
            if _number(data.get(name)):
                result[name] = max(lower, min(upper, data[name]))
        return result
    if key == TUTORIAL_KEY and isinstance(data, dict):
        return {name: {"step": item["step"], "completed": item["completed"]}
                for name, item in data.items() if name in _TOURS and isinstance(item, dict)
                and isinstance(item.get("step"), int) and not isinstance(item["step"], bool)
                and 0 <= item["step"] < 1000 and isinstance(item.get("completed"), bool)}
    if _MAP_KEY.fullmatch(key) and isinstance(data, list):
        result, ids = [], set()
        for item in data[:50]:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not 1 <= len(item["id"]) <= 100 or item["id"] in ids
                    or not isinstance(item.get("name"), str) or not item["name"].strip()
                    or not _number(item.get("east")) or not _number(item.get("north"))):
                continue
            ids.add(item["id"])
            result.append({"id": item["id"], "name": item["name"].strip()[:80],
                           "east": item["east"], "north": item["north"]})
        return result
    return None


def clean_preferences(snapshot) -> dict[str, str]:
    """Keep only schema-checked UI fields, even inside otherwise allowed keys."""
    if not isinstance(snapshot, dict):
        return {}
    result = {}
    for key, value in snapshot.items():
        if not isinstance(key, str) or len(result) >= MAX_KEYS:
            continue
        if key not in (LAYOUT_KEY, TUTORIAL_KEY) and not _MAP_KEY.fullmatch(key):
            continue
        cleaned = _clean_value(key, value)
        if cleaned is not None:
            result[key] = json.dumps(cleaned, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return result


class DesktopPreferences:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "desktop-preferences.json"
        self.values: dict[str, str] = {}
        try:
            if self.path.exists():
                with self.path.open("rb") as stream:
                    raw = stream.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("preferences file exceeds size limit")
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("version") != 1:
                    raise ValueError("unknown preferences format")
                self.values = clean_preferences(data.get("values"))
        except (OSError, ValueError, UnicodeError, RecursionError):
            _LOG.warning("Desktop preferences could not be read; using default UI settings. File: %s", self.path)

    def update(self, snapshot) -> bool:
        cleaned = clean_preferences(snapshot)
        if cleaned == self.values:
            return True
        raw = json.dumps({"version": 1, "values": cleaned}, ensure_ascii=True, allow_nan=False).encode("utf8")
        if len(raw) > MAX_BYTES:
            _LOG.warning("Desktop preferences exceeded their size limit; previous settings retained.")
            return False
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".desktop-preferences-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self.values = cleaned
            return True
        except OSError:
            _LOG.warning("Desktop preferences could not be saved; check write access to %s", self.path.parent)
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def restore_script(origin: str, preferences: dict[str, str]) -> str:
    values = json.dumps(clean_preferences(preferences), ensure_ascii=True)
    return f"""(() => {{
      if (location.origin !== {json.dumps(origin)}) return;
      try {{ for (const [key,value] of Object.entries({values})) localStorage.setItem(key,value); }} catch (_) {{}}
    }})()"""


def snapshot_script(origin: str) -> str:
    return f"""(() => {{
      if (location.origin !== {json.dumps(origin)}) return null;
      try {{
        const result = {{}};
        const exact = {json.dumps([LAYOUT_KEY, TUTORIAL_KEY])};
        for (let i=0;i<localStorage.length && Object.keys(result).length<{MAX_KEYS};i++) {{
          const key=localStorage.key(i);
          if (exact.includes(key) || /^rocket-workbench:map-points:[A-Za-z0-9_-]{{1,128}}$/.test(key)) {{
            const value=localStorage.getItem(key);
            if (value && value.length<=65536) result[key]=value;
          }}
        }}
        return JSON.stringify(result);
      }} catch (_) {{ return null; }}
    }})()"""


def install_desktop_preferences(window, view, data_dir: Path, origin: str):
    """Restore before React executes; flush the latest UI state before closing."""
    from PySide6.QtCore import QObject, QEvent, QTimer
    from PySide6.QtWebEngineCore import QWebEngineScript

    store = DesktopPreferences(data_dir)
    script = QWebEngineScript()
    script.setName("Rocket Workbench UI preferences")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(restore_script(origin, store.values))
    view.page().scripts().insert(script)

    class Persistence(QObject):
        def __init__(self):
            super().__init__(window)
            self.closing = False
            self.close_ready = False
            self.pending = False
            self.generation = 0
            self.applied_generation = 0
            self.timer = QTimer(self)
            self.timer.setInterval(500)
            self.timer.timeout.connect(self.capture)
            self.timer.start()
            window.installEventFilter(self)

        def capture(self, done=None):
            if self.pending and done is None:
                return
            self.pending = True
            self.generation += 1
            generation = self.generation

            def captured(value):
                self.pending = False
                if isinstance(value, str) and value and generation >= self.applied_generation:
                    try:
                        if len(value) > MAX_BYTES * 2:
                            raise ValueError("snapshot exceeds size limit")
                        previous = store.values
                        if store.update(json.loads(value)) and store.values != previous:
                            # Script collections hold copies. Refresh the injected
                            # copy so an in-session reload restores the latest UI.
                            collection = view.page().scripts()
                            for existing in collection.find(script.name()):
                                collection.remove(existing)
                            script.setSourceCode(restore_script(origin, store.values))
                            collection.insert(script)
                        self.applied_generation = generation
                    except (ValueError, UnicodeError, RecursionError):
                        _LOG.warning("Desktop preferences snapshot could not be read; previous settings retained.")
                if done:
                    done()

            view.page().runJavaScript(snapshot_script(origin), captured)

        def finish_close(self):
            if self.close_ready:
                return
            self.close_ready = True
            window.close()

        def eventFilter(self, watched, event):
            if watched is window and event.type() == QEvent.Type.Close and not self.close_ready:
                event.ignore()
                if not self.closing:
                    self.closing = True
                    self.timer.stop()
                    self.capture(self.finish_close)
                    # A failed renderer must not trap the user in the window.
                    QTimer.singleShot(1500, self.finish_close)
                return True
            return super().eventFilter(watched, event)

    persistence = Persistence()
    # Retain Python's callback owner for the entire native window lifetime.
    window._rocket_preferences = persistence
    return persistence
