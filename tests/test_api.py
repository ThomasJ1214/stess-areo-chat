"""API integration, persistence, worker outcomes and desktop-session protection."""
import time

from fastapi.testclient import TestClient

from rocket_workbench.api import create_app
from rocket_workbench.demo import demo_project
from rocket_workbench.models import Conditions, Project


def wait(client, identity, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = client.get(f"/api/jobs/{identity}").json()
        if result["status"] in {"completed", "failed", "cancelled"}:
            return result
        time.sleep(0.02)
    raise AssertionError("Job did not finish within integration-test timeout")


def test_project_roundtrip_and_session_restore(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    value = demo_project().model_dump()
    value["name"] = "Integration test rocket"
    assert client.put("/api/project", json=value).status_code == 200
    saved = client.get("/api/project/download")
    assert saved.status_code == 200
    restored = TestClient(create_app(data_dir=tmp_path))
    assert restored.get("/api/project").json()["name"] == value["name"]
    loaded = client.post("/api/project/load", files={"file": ("rocket.json", saved.content)})
    assert loaded.status_code == 200
    assert Project.model_validate(loaded.json()).motors[0].curve == demo_project().motors[0].curve


def test_token_and_foreign_origin_protection():
    client = TestClient(create_app(token="integration-session"))
    assert client.get("/api/project").status_code == 403
    headers = {"X-Rocket-Session": "integration-session"}
    assert client.get("/api/project", headers=headers).status_code == 200
    assert client.post("/api/project/demo", headers=headers | {"Origin": "https://foreign.example"}).status_code == 403
    assert client.get("/api/project", headers=headers | {"Host": "foreign.example"}).status_code == 403


def test_actual_aerodynamic_analysis_and_mesh():
    client = TestClient(create_app())
    response = client.post("/api/analyze", json={"conditions": Conditions().model_dump()})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["aero"]["mass_kg"] > 0
    assert result["aero"]["drag_n"] > 0
    assert result["structure"]["components"]
    mesh = client.get("/api/mesh")
    assert mesh.status_code == 200, mesh.text
    assert any(len(component["vertices"]) > 20 for component in mesh.json()["components"])


def test_flight_job_export_and_failed_motor_configuration():
    client = TestClient(create_app())
    response = client.post("/api/jobs", json={"kind": "flight", "conditions": {"dt": 0.05}})
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    completed = wait(client, identity)
    assert completed["status"] == "completed", completed["error"]
    assert len(completed["result"]["trajectory"]) > 20
    csv = client.get(f"/api/jobs/{identity}/export?format=csv")
    assert csv.status_code == 200 and "time" in csv.text.splitlines()[0]
    html = client.get(f"/api/jobs/{identity}/export?format=html")
    assert html.status_code == 200
    assert "fidelity" in html.text
    value = client.get("/api/project").json()
    value["configurations"][0]["motor_id"] = None
    client.put("/api/project", json=value)
    identity = client.post("/api/jobs", json={"kind": "flight", "conditions": {}}).json()["id"]
    assert wait(client, identity)["status"] == "failed"


def test_parameter_sweep_executes_different_conditions():
    client = TestClient(create_app())
    response = client.post("/api/jobs", json={"kind": "sweep", "conditions": {},
        "options": {"parameter": "speed", "start": 50, "stop": 150, "count": 3}})
    job = wait(client, response.json()["id"])
    assert job["status"] == "completed", job["error"]
    rows = job["result"]["rows"]
    assert len(rows) == 3 and rows[-1]["dynamic_pressure_pa"] > rows[0]["dynamic_pressure_pa"]
    assert job["result"]["failures"] == []


def test_cad_attachment_and_actual_background_fea():
    import trimesh
    client = TestClient(create_app())
    solid = trimesh.creation.box([0.1, 0.1, 0.1])
    imported = client.post("/api/import/geometry", data={"units": "m"}, files={"file": ("cube.stl", solid.export(file_type="stl"))})
    assert imported.status_code == 200, imported.text
    asset = imported.json()
    assert asset["watertight"] and abs(asset["volume"] - 0.001) < 1e-9
    attached = client.post("/api/geometry/attach", json={"component_id": "payload", "asset_id": asset["id"], "transform": {"translation": [0, 0, 0], "rotation": [0, 0, 0], "scale": 1}})
    assert attached.status_code == 200
    started = client.post("/api/jobs", json={"kind": "fea", "conditions": {}, "options": {
        "component_id": "payload", "mesh_size": 0.035, "max_elements": 3000,
        "load_mode": "traction", "traction_pa": [1000, 0, 0], "backend": "cpu"}})
    assert started.status_code == 200, started.text
    job = wait(client, started.json()["id"], timeout=60)
    assert job["status"] == "completed", job["error"]
    summary = job["result"]["summary"]
    assert summary["max_von_mises_pa"] > 500
    assert summary["force_balance_relative_error"] < 1e-7
    assert abs(summary["applied_force_n"][0] - 10) < 1e-5
    assert client.get(f'/api/jobs/{job["id"]}/export?format=csv').status_code == 200


def test_standalone_cad_polar_and_geometry_invalidation():
    import trimesh
    client = TestClient(create_app())
    solid = trimesh.creation.box([0.1, 0.1, 0.1])
    imported = client.post("/api/import/geometry", data={"units": "m"}, files={"file": ("cube.stl", solid.export(file_type="stl"))}).json()
    standalone = client.post("/api/geometry/standalone", json={"asset_id": imported["id"]})
    assert standalone.status_code == 200, standalone.text
    body = standalone.json()
    assert len(body["components"]) == 1 and body["motors"]
    before = client.post("/api/analyze", json={"conditions": {}})
    assert before.status_code == 200, before.text
    assert before.json()["aero"]["cp_m"] is None
    csv = b"mach,cd,cna,cp_m,source\n0,0.25,4,0.08,Integration fixture\n2,0.5,3,0.075,Integration fixture\n"
    attached = client.post("/api/import/polar", files={"file": ("test-polar.csv", csv)})
    assert attached.status_code == 200, attached.text
    after = client.post("/api/analyze", json={"conditions": {}}).json()["aero"]
    assert after["polar_applied"] and 0.075 < after["cp_m"] <= 0.08
    changed = attached.json()
    changed["components"][0]["transform"]["scale"] = 1.01
    client.put("/api/project", json=changed)
    stale = client.post("/api/analyze", json={"conditions": {}}).json()["aero"]
    assert not stale["polar_applied"] and stale["cp_m"] is None
