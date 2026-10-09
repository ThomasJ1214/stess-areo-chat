"""UI-only storage, restart durability, and safe failure behavior."""
import json

from rocket_workbench.desktop_preferences import (
    DesktopPreferences, LAYOUT_KEY, TUTORIAL_KEY, MAP_PREFIX, MAX_BYTES, clean_preferences,
)


def test_restart_preserves_only_owned_ui_fields_and_supports_deletion(tmp_path):
    store = DesktopPreferences(tmp_path)
    project = "141a67e9-d0cb-46ed-bbe2-dbb82ecdbd67"
    snapshot = {
        "X-Rocket-Session": "secret-session-token",
        "foreign-origin-cache": "private-cache",
        LAYOUT_KEY: json.dumps({"assemblyWidth": 291, "setup": False, "token": "nested-secret"}),
        TUTORIAL_KEY: json.dumps({"app": {"step": 3, "completed": False, "auth": "hidden"}, "foreign": {"step": 1, "completed": True}}),
        MAP_PREFIX + project: json.dumps([{"id": "poi-1", "name": "Landing field", "east": 12.4, "north": -5.2, "password": "hidden"}]),
    }
    assert store.update(snapshot)
    saved = store.path.read_text("utf8")
    assert all(word not in saved for word in ("secret", "hidden", "foreign", "password", "auth"))
    restarted = DesktopPreferences(tmp_path)
    assert json.loads(restarted.values[LAYOUT_KEY]) == {"assemblyWidth": 291, "setup": False}
    assert json.loads(restarted.values[TUTORIAL_KEY]) == {"app": {"step": 3, "completed": False}}
    assert json.loads(restarted.values[MAP_PREFIX + project])[0]["east"] == 12.4
    assert restarted.update({})
    assert DesktopPreferences(tmp_path).values == {}


def test_corrupt_or_oversized_preferences_do_not_prevent_startup(tmp_path, caplog):
    target = tmp_path / "desktop-preferences.json"
    for content in (b"not-json", b"x" * (MAX_BYTES + 1), b'{"version":99,"values":{}}'):
        target.write_bytes(content)
        assert DesktopPreferences(tmp_path).values == {}
        assert target.read_bytes() == content
    assert "using default UI settings" in caplog.text


def test_failed_atomic_replace_retains_last_good_preferences(tmp_path, monkeypatch, caplog):
    import rocket_workbench.desktop_preferences as preferences
    store = DesktopPreferences(tmp_path)
    assert store.update({LAYOUT_KEY: '{"assemblyWidth":240}'})
    before = store.path.read_bytes()
    def failure(*_args):
        raise PermissionError("denied")
    monkeypatch.setattr(preferences.os, "replace", failure)
    assert not store.update({LAYOUT_KEY: '{"assemblyWidth":320}'})
    assert store.path.read_bytes() == before
    assert json.loads(store.values[LAYOUT_KEY])["assemblyWidth"] == 240
    assert not list(tmp_path.glob("*.tmp"))
    assert "check write access" in caplog.text


def test_bounds_and_nonfinite_or_malformed_data_are_safe():
    cleaned = clean_preferences({
        LAYOUT_KEY: '{"assemblyWidth":9999,"setupWidth":NaN,"sceneRatio":-1}',
        TUTORIAL_KEY: '{"app":{"step":false,"completed":true},"structure":{"step":2,"completed":false}}',
        MAP_PREFIX + "project": '[{"id":"a","name":"x","east":Infinity,"north":1}]',
        MAP_PREFIX + "../../token": "[]",
    })
    assert json.loads(cleaned[LAYOUT_KEY]) == {"assemblyWidth": 380, "sceneRatio": 0.6}
    assert json.loads(cleaned[TUTORIAL_KEY]) == {"structure": {"step": 2, "completed": False}}
    assert json.loads(cleaned[MAP_PREFIX + "project"]) == []
    assert MAP_PREFIX + "../../token" not in cleaned
