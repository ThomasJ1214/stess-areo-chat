"""FEA setup checks use actual solids and retain the solver's bending guard."""
import math

from fastapi.testclient import TestClient
import pytest
import trimesh

from rocket_workbench.api import create_app
from rocket_workbench.fea_setup import preflight
from rocket_workbench.models import Component, Conditions, GeometryAsset, Project
from rocket_workbench.solvers import structure


def solid_project():
    mesh = trimesh.creation.box(extents=[.03, .012, .012])
    asset = GeometryAsset(id="solid", name="Small bar", format="stl", watertight=True,
                          volume=float(mesh.volume), vertices=mesh.vertices.tolist(), faces=mesh.faces.tolist())
    component = Component(id="bar", asset_id="solid", geometry_mode="replacement", x=.5,
                          transform={"translation": [0, .02, 0], "scale": 1})
    return Project(components=[component], assets=[asset])


def test_thin_fin_recommendation_preserves_bending_resolution_and_solves_real_solid():
    fin = Component(id="fin", kind="trapezoidfinset", radius=.01, root_chord=.03,
                    tip_chord=.02, span=.015, sweep=.005, thickness=.003, fin_count=3)
    project = Project(components=[fin])
    original = project.model_dump_json()
    coarse = preflight(project, fin.id, {"mesh_size": .015})
    assert coarse["geometry_valid"] and not coarse["can_run"]
    assert coarse["maximum_bending_mesh_size_m"] == pytest.approx(.0015)
    assert coarse["recommended_mesh_size_m"] <= .0015
    assert coarse["recommended_within_budget"]
    assert coarse["beam_estimate_available"]
    assert coarse["recommended_clamp_type"] == "radial_root"
    # Known trapezoidal planform volume, not a bounding-box solid.
    actual_volume = 3 * ((.03 + .02) / 2) * .015 * .003
    assert coarse["material_volume_m3"] == pytest.approx(actual_volume, rel=1e-12)
    recommended = {"mesh_size": coarse["recommended_mesh_size_m"], "max_elements": 100000,
                   "clamp_type": "radial_root", "backend": "cpu"}
    assert preflight(project, fin.id, recommended)["can_run"]
    result = structure.solve_fea(project, fin.id, Conditions(speed=100, wind_speed=0), recommended)
    assert result["summary"]["elements"] > 0
    assert result["summary"]["max_von_mises_pa"] > 0
    assert result["summary"]["force_balance_relative_error"] < 1e-7
    assert project.model_dump_json() == original


def test_long_thin_tube_reports_impossible_whole_part_budget_without_coarsening():
    tube = Component(id="tube", length=3, radius=.08, thickness=.002)
    project = Project(components=[tube])
    result = preflight(project, tube.id, {"mesh_size": .015, "max_elements": 300000})
    assert result["geometry_valid"] and not result["can_run"]
    assert result["recommended_mesh_size_m"] == pytest.approx(.001)
    assert not result["recommended_within_maximum_budget"]
    assert result["recommended_max_elements"] is None
    assert result["beam_estimate_available"]
    # The revolution's 64 flat facets closely approximate the annular material.
    annular_volume = math.pi * (.08**2 - .078**2) * 3
    assert result["material_volume_m3"] == pytest.approx(annular_volume, rel=.002)
    assert any("not included" in error for error in result["errors"])
    with pytest.raises(ValueError, match="thickness/2"):
        structure.solve_fea(project, tube.id, Conditions(), {"mesh_size": .015, "max_elements": 300000})
    with pytest.raises(ValueError, match="budget"):
        structure.solve_fea(project, tube.id, Conditions(), {"mesh_size": .001, "max_elements": 300000})


def test_switching_to_small_cad_part_recommends_its_actual_scale_without_inventing_thickness():
    project = solid_project()
    project.components.append(Component(id="tube", length=3, radius=.08, thickness=.002))
    assert not preflight(project, "tube")["recommended_within_maximum_budget"]
    result = preflight(project, "bar")
    assert result["can_run"] and result["recommended_within_budget"]
    assert result["recommended_mesh_size_m"] == pytest.approx(.03 / 12)
    assert result["maximum_bending_mesh_size_m"] is None
    assert result["procedural_thickness_m"] is None and result["cad_thickness_unknown"]
    assert not result["beam_estimate_available"]
    assert result["bounds_m"][0] == pytest.approx([.485, .014, -.006])
    assert any("thickness is unknown" in warning for warning in result["warnings"])
    solved = structure.solve_fea(project, "bar", Conditions(speed=0), {
        "mesh_size": result["recommended_mesh_size_m"], "load_mode": "traction",
        "traction_pa": [1000, 0, 0], "backend": "cpu"})
    # The known end area and traction must give the actual transmitted force.
    assert solved["summary"]["applied_force_n"][0] == pytest.approx(1000 * .012**2, rel=1e-6)
    assert solved["summary"]["max_von_mises_pa"] > 0


def test_preflight_api_is_read_only_and_does_not_invoke_native_meshing(monkeypatch):
    def unexpected_mesh(*args, **kwargs):
        pytest.fail("Preflight may not generate a volume mesh")
    monkeypatch.setattr(structure, "_volume_mesh", unexpected_mesh)
    with TestClient(create_app()) as client:
        project = solid_project()
        assert client.put("/api/project", json=project.model_dump()).status_code == 200
        before = client.get("/api/project").content
        result = client.post("/api/fea/preflight", json={"component_id": "bar", "options": {"mesh_size": .0025}})
        assert result.status_code == 200, result.text
        assert result.json()["can_run"]
        assert result.json()["material"]["youngs_modulus"] > 0
        assert client.get("/api/project").content == before
        invalid = client.post("/api/fea/preflight", json={"component_id": "missing"})
        assert invalid.status_code == 400


def test_invalid_material_volume_blocks_preflight_and_solver_consistently():
    project = solid_project()
    project.assets[0].watertight = False
    result = preflight(project, "bar")
    assert not result["geometry_valid"] and not result["can_run"]
    assert result["recommended_mesh_size_m"] is None
    assert "verified enclosed material volume" in result["errors"][0]
    with pytest.raises(ValueError, match="verified enclosed material volume"):
        structure.solve_fea(project, "bar", Conditions(), {})


@pytest.mark.parametrize("budget", [19, 300001, 100000.5, True, "100000"])
def test_invalid_element_budget_is_rejected_before_meshing(budget):
    with pytest.raises(ValueError, match="integer"):
        preflight(solid_project(), "bar", {"max_elements": budget})


def test_extremely_fine_preflight_is_json_safe_and_reports_budget_failure():
    with TestClient(create_app()) as client:
        client.put("/api/project", json=solid_project().model_dump())
        response = client.post("/api/fea/preflight", json={"component_id": "bar", "options": {"mesh_size": 1e-200}})
        assert response.status_code == 200, response.text
        result = response.json()
        assert not result["can_run"]
        assert result["estimated_elements"] is None
        assert any("budget" in error for error in result["errors"])
