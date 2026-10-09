"""Regression diagnostics stay reviewable after a windowed native failure."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "desktop_preferences_smoke.py"
spec = importlib.util.spec_from_file_location("native_preferences_driver", SCRIPT)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_windowed_failure_exposes_native_cause_and_preserves_logs(tmp_path, capsys):
    output = tmp_path / "build" / "installed-preferences-smoke.json"
    session = tmp_path / "temporary-session"
    session.mkdir()
    native = {"status": "failed", "stage": "click:Hide assembly", "viewport": {"width": 900, "height": 760},
              "error": "Control Hide assembly did not become available"}
    receipt = session / "phase-1.json"
    receipt.write_text(json.dumps(native), "utf8")
    log = session / "application.log"
    log.write_text("Native UI initialized; source failure recorded.\n", "utf8")
    diagnostics = driver.preserve_diagnostics(output, session, 1, SimpleNamespace(stdout="", stderr=""))
    receipt.unlink()
    log.unlink()
    session.rmdir()
    driver.record_failure(output, 1, "windowed executable failed", exit_code=1, native_receipt=native)
    annotation = capsys.readouterr().out
    assert "::error title=Desktop preferences verification::" in annotation
    assert "click:Hide assembly" in annotation and "Control Hide assembly did not become available" in annotation
    assert "900" in annotation
    assert json.loads(output.read_text("utf8"))["native_receipt"] == native
    assert json.loads((diagnostics / "phase-1-phase-1.json").read_text("utf8")) == native
    assert "Native UI initialized" in (diagnostics / "phase-1-application.log").read_text("utf8")


def test_failure_annotation_is_bounded_and_cannot_inject_workflow_commands(tmp_path, capsys):
    driver.record_failure(tmp_path / "receipt.json", 2, "x%\n::notice::injection\r" + "z" * 4000)
    annotation = capsys.readouterr().out
    assert annotation.count("\n") == 1
    assert "x%25%0A::notice::injection%0D" in annotation
    assert len(annotation) < 1500
