"""Physical CAD placement references, not just generated proposal snapshots."""
import math

from fastapi.testclient import TestClient
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
import trimesh

from rocket_workbench.alignment import AlignmentOptions, propose_alignment
from rocket_workbench.api import create_app
from rocket_workbench.geometry import component_mesh
from rocket_workbench.models import Component, GeometryAsset, Material, Project, Transform
from rocket_workbench.solvers.aero import mass_properties


def asset_of(mesh):
    return GeometryAsset(name="actual CAD", format="stl", vertices=mesh.vertices.tolist(),
                         faces=mesh.faces.tolist(), watertight=bool(mesh.is_watertight), volume=abs(mesh.volume))


def test_auto_alignment_of_rotated_translated_bar_preserves_physics_and_source():
    dimensions = [.7, .08, .05]
    mesh = trimesh.creation.box(dimensions)
    rotation = Rotation.from_euler("xyz", [23, -41, 37], degrees=True)
    mesh.vertices = rotation.apply(mesh.vertices) + [180, -35, 70]
    asset = asset_of(mesh)
    component = Component(id="selected", x=1.2, length=.7, radius=.04, material_id="steel")
    neighbor = Component(id="neighbor", x=1.9, length=.8, radius=.04, material_id="steel")
    project = Project(components=[component, neighbor], assets=[asset],
                      materials=[Material(id="steel", density=7800)])
    before = project.model_dump_json()
    neighbor_before = component_mesh(project, neighbor).vertices.copy()
    proposal = propose_alignment(project, component, asset)
    assert abs(np.dot(proposal["source_axis"], rotation.apply([1, 0, 0]))) == pytest.approx(1, abs=1e-12)
    placed = component.model_copy(deep=True)
    placed.asset_id, placed.geometry_mode = asset.id, "replacement"
    placed.transform = Transform.model_validate(proposal["transform"])
    aligned = component_mesh(project, placed)
    assert aligned.bounds[:, 0] == pytest.approx([1.2, 1.9], abs=1e-12)
    assert aligned.bounds.mean(axis=0)[1:] == pytest.approx([0, 0], abs=1e-12)
    assert aligned.volume == pytest.approx(math.prod(dimensions), rel=1e-11)
    # An independently invariant reference: every original vertex-pair distance
    # and therefore actual shape/volume survives the rigid placement.
    pairs = np.array([[0, 1], [1, 6], [3, 4], [4, 7]])
    original_distances = np.linalg.norm(mesh.vertices[pairs[:, 0]] - mesh.vertices[pairs[:, 1]], axis=1)
    aligned_distances = np.linalg.norm(aligned.vertices[pairs[:, 0]] - aligned.vertices[pairs[:, 1]], axis=1)
    assert aligned_distances == pytest.approx(original_distances, abs=1e-12)
    assert np.linalg.det(Rotation.from_euler("xyz", placed.transform.rotation, degrees=True).as_matrix()) == pytest.approx(1)
    assert project.model_dump_json() == before
    assert component_mesh(project, neighbor).vertices == pytest.approx(neighbor_before)
    assert proposal["interfaces"][0]["status"] == "aligned"
    assert proposal["source_mesh_modified"] is False


def test_explicit_uniform_fit_has_cubic_mass_scaling_and_center_anchor():
    mesh = trimesh.creation.box([.08, .1, .2])
    mesh.apply_translation([15, 9, -22])
    asset = asset_of(mesh)
    component = Component(id="part", x=2, length=.6, radius=.15, material_id="material")
    project = Project(components=[component], assets=[asset], materials=[Material(id="material", density=500)])
    options = AlignmentOptions(axis="z", fit_length=True, anchor="center")
    proposal = propose_alignment(project, component, asset, options)
    assert proposal["scale"] == pytest.approx(3)
    component.geometry_mode, component.asset_id = "replacement", asset.id
    component.transform = Transform.model_validate(proposal["transform"])
    transformed = component_mesh(project, component)
    assert transformed.bounds.mean(axis=0) == pytest.approx([2.3, 0, 0], abs=1e-12)
    assert transformed.extents == pytest.approx([.6, .08 * 3, .1 * 3])
    assert mass_properties(project)["mass_kg"] == pytest.approx(500 * .08 * .1 * .2 * 3**3)
    assert any("scale³" in warning for warning in proposal["warnings"])


def test_auto_axis_does_not_depend_on_triangle_subdivision():
    mesh = trimesh.creation.box([.7, .08, .05])
    rotation = Rotation.from_euler("xyz", [20, 35, 77], degrees=True)
    mesh.vertices = rotation.apply(mesh.vertices) + [2, 3, 5]
    refined = mesh.subdivide()
    component = Component(length=.7)
    project = Project(components=[component])
    original = propose_alignment(project, component, asset_of(mesh))
    subdivided = propose_alignment(project, component, asset_of(refined))
    assert original["source_axis"] == pytest.approx(subdivided["source_axis"], abs=1e-12)
    assert original["transform"]["rotation"] == pytest.approx(subdivided["transform"]["rotation"], abs=1e-10)


def test_symmetric_axis_fallback_reverse_and_start_anchor_are_deterministic():
    asset = asset_of(trimesh.creation.box([.2, .2, .2]))
    component = Component(x=.5, length=.2, radius=.1)
    project = Project(components=[component], assets=[asset])
    guess = propose_alignment(project, component, asset)
    assert guess["source_axis"] == [1, 0, 0]
    assert "ambiguous" in guess["axis_method"]
    reverse = propose_alignment(project, component, asset, AlignmentOptions(reverse=True))
    assert reverse["source_axis"] == [-1, 0, 0]
    proper_rotation = Rotation.from_euler("xyz", reverse["transform"]["rotation"], degrees=True).as_matrix()
    assert np.linalg.det(proper_rotation) == pytest.approx(1)
    assert proper_rotation @ np.array([1, 0, 0]) == pytest.approx([-1, 0, 0], abs=1e-15)
    assert reverse["aligned_bounds_m"] == pytest.approx(np.array([[.5, -.1, -.1], [.7, .1, .1]]))


def test_repeated_part_fits_single_reference_and_preserves_radial_location():
    asset = asset_of(trimesh.creation.box([.2, .03, .03]))
    component = Component(x=.6, length=.2, radius=.03,
                          metadata={"instance_count": 3, "instance_separation": .5,
                                    "radialposition": .1, "radialdirection": 90})
    project = Project(components=[component], assets=[asset])
    before = project.model_dump_json()
    proposal = propose_alignment(project, component, asset, AlignmentOptions(axis="x", fit_length=True), include_mesh=True)
    assert project.model_dump_json() == before
    assert proposal["scale"] == pytest.approx(1)
    assert np.asarray(proposal["target_bounds_m"]).mean(axis=0) == pytest.approx([.7, 0, .1])
    component.geometry_mode, component.asset_id = "replacement", asset.id
    component.transform = Transform.model_validate(proposal["transform"])
    placed = component_mesh(project, component)
    assert placed.extents[0] == pytest.approx(1.2)
    assert placed.bounds.mean(axis=0)[1:] == pytest.approx([0, .1])
    assert placed.volume == pytest.approx(3 * .2 * .03**2)
    preview = proposal["preview_mesh"]["components"]
    assert len(preview) == 1
    assert preview[0]["id"] == component.id
    assert preview[0]["vertices"] == pytest.approx(placed.vertices)
    assert np.array_equal(preview[0]["faces"], placed.faces)


def test_preview_replication_budget_is_checked_before_allocating_replacement(monkeypatch):
    import rocket_workbench.alignment as alignment
    asset = asset_of(trimesh.creation.box([.2, .03, .03]))
    component = Component(length=.2, metadata={"instance_count": 3, "instance_separation": .5})
    project = Project(components=[component], assets=[asset])
    before = project.model_dump_json()
    original_mesh_function = alignment.component_mesh

    def reference_only(project, component, original=False):
        assert original, "A preview over budget must never allocate replacement geometry."
        return original_mesh_function(project, component, original)

    monkeypatch.setattr(alignment, "component_mesh", reference_only)
    monkeypatch.setattr(alignment, "MAX_FACES", len(asset.faces) * 3 - 1)
    with pytest.raises(ValueError, match="limit after replication"):
        propose_alignment(project, component, asset, include_mesh=True)
    assert "preview_mesh" not in propose_alignment(project, component, asset)
    assert project.model_dump_json() == before


def test_different_physical_length_reports_gap_without_extending_or_fusing_part():
    asset = asset_of(trimesh.creation.box([.3, .1, .1]))
    selected = Component(id="selected", x=.4, length=.6)
    neighbor = Component(id="neighbor", x=1, length=.7)
    project = Project(components=[selected, neighbor], assets=[asset])
    proposal = propose_alignment(project, selected, asset)
    assert proposal["scale"] == 1
    assert proposal["interfaces"][0]["status"] == "gap"
    assert proposal["interfaces"][0]["axial_separation_m"] == pytest.approx(.3)
    assert any("no material connection or Boolean union" in text for text in proposal["warnings"])


def test_nose_target_starts_at_tip_and_fit_excludes_original_shoulder():
    component = Component(kind="nosecone", x=.25, length=.4, radius=.05,
                          metadata={"aftshoulderlength": .1, "aftshoulderradius": .04})
    asset = asset_of(trimesh.creation.box([.4, .1, .1]))
    project = Project(components=[component], assets=[asset])
    proposal = propose_alignment(project, component, asset, AlignmentOptions(fit_length=True))
    assert np.asarray(proposal["target_bounds_m"])[:, 0] == pytest.approx([.25, .65])
    assert proposal["scale"] == pytest.approx(1)
    assert any("source shoulders remain" in warning for warning in proposal["warnings"])


@pytest.mark.parametrize("flipped", [False, True])
def test_actual_nose_tip_orientation_is_inferred_before_user_reverse(flipped):
    mesh = trimesh.creation.cone(radius=.05, height=.4, sections=32)
    mesh.apply_translation([4, 7, 10])
    asset = asset_of(mesh)
    component = Component(kind="nosecone", x=.25, length=.4, radius=.05,
                          metadata={"isflipped": flipped})
    project = Project(components=[component], assets=[asset])
    proposal = propose_alignment(project, component, asset)
    placed = component.model_copy(update={"asset_id": asset.id, "geometry_mode": "replacement",
                                         "transform": Transform.model_validate(proposal["transform"])})
    transformed = component_mesh(project, placed)
    tip_index = int(np.argmax(mesh.vertices[:, 2]))
    assert transformed.vertices[tip_index, 0] == pytest.approx(.65 if flipped else .25)
    reversed_proposal = propose_alignment(project, component, asset, AlignmentOptions(reverse=True))
    placed.transform = Transform.model_validate(reversed_proposal["transform"])
    reversed_mesh = component_mesh(project, placed)
    assert reversed_mesh.vertices[tip_index, 0] == pytest.approx(.25 if flipped else .65)
    assert "narrower CAD end" in proposal["axis_direction_method"]


def test_alignment_preview_readonly_and_auto_attach_matches_preview_over_http(tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        mesh = trimesh.creation.box([.1, .65, .1])
        mesh.apply_translation([20, -15, 8])
        response = client.post("/api/import/geometry", data={"units": "m"},
                               files={"file": ("payload.stl", mesh.export(file_type="stl"))})
        assert response.status_code == 200, response.text
        asset = response.json()
        original_project = client.get("/api/project").json()
        request = {"component_id": "payload", "asset_id": asset["id"]}
        assert "preview_mesh" not in client.post("/api/geometry/alignment", json=request).json()
        preview_response = client.post("/api/geometry/alignment", json=request | {"include_mesh": True})
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert client.get("/api/project").json() == original_project
        attached = client.post("/api/geometry/attach", json=request | {"auto_align": True})
        assert attached.status_code == 200, attached.text
        saved_project = attached.json()
        selected = next(item for item in saved_project["components"] if item["id"] == "payload")
        assert selected["transform"] == preview["transform"]
        assert saved_project["assets"] == original_project["assets"]
        assert [item for item in saved_project["components"] if item["id"] != "payload"] == [
            item for item in original_project["components"] if item["id"] != "payload"]
        properties = client.get("/api/geometry/properties/payload").json()
        assert properties["replacement"]["bounds_m"] == pytest.approx(np.asarray(preview["aligned_bounds_m"]), abs=1e-6)
        assert selected["mass_override"] == 1.25
        actual_mesh = next(item for item in client.get("/api/mesh").json()["components"] if item["id"] == "payload")
        preview_mesh = preview["preview_mesh"]["components"][0]
        assert actual_mesh["id"] == preview_mesh["id"]
        assert actual_mesh["name"] == preview_mesh["name"]
        assert actual_mesh["vertices"] == preview_mesh["vertices"]
        assert actual_mesh["faces"] == preview_mesh["faces"]
        assert client.post("/api/geometry/alignment", json=request | {"axis": "q"}).status_code == 422
        assert client.post("/api/geometry/alignment", json=request | {"component_id": "missing"}).status_code == 400


def test_manual_attach_keeps_explicit_transform_and_empty_assembly_is_rejected():
    with TestClient(create_app()) as client:
        mesh = trimesh.creation.box([.2, .1, .1])
        asset = client.post("/api/import/geometry", data={"units": "m"},
                            files={"file": ("payload.stl", mesh.export(file_type="stl"))}).json()
        transform = {"translation": [3, 2, 1], "rotation": [25, 15, 5], "scale": 2}
        attached = client.post("/api/geometry/attach", json={"component_id": "payload", "asset_id": asset["id"],
                                                            "transform": transform}).json()
        assert next(item for item in attached["components"] if item["id"] == "payload")["transform"] == transform
    assembly = Component(kind="stage")
    with pytest.raises(ValueError, match="physical rocket part"):
        propose_alignment(Project(components=[assembly]), assembly, asset_of(mesh))
