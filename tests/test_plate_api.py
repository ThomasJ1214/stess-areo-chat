import csv, io, json
from fastapi.testclient import TestClient
from rocket_workbench.api import create_app
from rocket_workbench.demo import demo_project
from test_api import wait


def test_real_plate_job_exports_and_immutable_source_geometry():
    p = demo_project()
    original = p.model_dump(mode="json")
    options = {
        "element_model": "plate",
        "component_id": "fins",
        "mesh_size": 0.04,
        "max_elements": 20000,
        "plate_allow_isotropic_surrogate": True,
        "plate_pressure_pa": -100,
    }
    with TestClient(create_app()) as c:
        assert c.put("/api/project", json=original).status_code == 200
        ready = c.post(
            "/api/fea/preflight", json={"component_id": "fins", "options": options}
        ).json()
        assert ready["can_run"] and ready["element_model"] == "plate"
        identity = c.post(
            "/api/jobs", json={"kind": "fea", "conditions": {}, "options": options}
        ).json()["id"]
        job = wait(c, identity)
        assert job["status"] == "completed", job.get("error")
        r = job["result"]
        assert len(r["plate_quads"]) == ready["estimated_elements"]
        assert r["inputs"]["options"]["element_model"] == "plate"
        rows = list(
            csv.DictReader(
                io.StringIO(c.get(f"/api/jobs/{identity}/export?format=csv").text)
            )
        )
        assert (
            len(rows) == len(r["vertices"])
            and json.loads(rows[0]["_result_summary"])["load_mode"] == "plate_pressure"
        )
        html = c.get(f"/api/jobs/{identity}/export?format=html").text
        assert "MITC4" in html and "Individual fin loads and equilibrium" in html
        after = c.get("/api/project").json()
        assert (
            after["components"] == original["components"]
            and after["assets"] == original["assets"]
        )
        assert (
            c.get(f"/api/jobs/{identity}/export?format=json").json()["mesh_kind"]
            == "plate_midsurface"
        )
