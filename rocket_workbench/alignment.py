"""Rigid CAD placement proposals, without editing imported or neighboring meshes.

The rocket frame is nose-to-tail +X. An automatic principal axis is a placement
guess, not an inference of CAD assembly connections or of its physical nose.
"""
from __future__ import annotations

import warnings as python_warnings
from typing import Literal

import numpy as np
from scipy.spatial.transform import Rotation
import trimesh

from .geometry import ASSEMBLIES, FINS, MAX_FACES, MAX_VERTICES, component_mesh
from .models import Component, GeometryAsset, Model, Project, Transform, active_components


class AlignmentOptions(Model):
    axis: Literal["auto", "x", "y", "z"] = "auto"
    reverse: bool = False
    fit_length: bool = False
    anchor: Literal["start", "center"] = "start"


def _signed_axis(axis: np.ndarray) -> np.ndarray:
    """Remove eigensolver sign ambiguity using its largest Cartesian projection."""
    axis = axis / np.linalg.norm(axis)
    if axis[int(np.argmax(np.abs(axis)))] < 0:
        axis = -axis
    return axis


def _surface_axis(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, str, bool]:
    """Principal axis of uniform surface area, independent of triangle subdivision.

    A triangle's uniform barycentric second moments are E[lambda_i²]=1/6,
    E[lambda_i lambda_j]=1/12. Work near the asset origin to avoid cancellation.
    Symmetric/equal principal moments cannot identify a longitudinal direction;
    in that case retain a deterministic Cartesian longest-bound axis.
    """
    bounds = np.array([vertices.min(axis=0), vertices.max(axis=0)])
    origin = bounds.mean(axis=0)
    triangles = vertices[faces] - origin
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                   triangles[:, 2] - triangles[:, 0]), axis=1) / 2
    total = float(area.sum())
    if not np.isfinite(total) or total <= 0:
        raise ValueError("CAD geometry has no nondegenerate triangle surface to align.")
    sums = triangles.sum(axis=1)
    mean = np.einsum("n,ni->i", area, sums) / (3 * total)
    second = (np.einsum("n,nki,nkj->ij", area, triangles, triangles)
              + np.einsum("n,ni,nj->ij", area, sums, sums)) / (12 * total)
    covariance = second - np.outer(mean, mean)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    ambiguous = eigenvalues[-1] <= 0 or eigenvalues[-1] - eigenvalues[-2] <= eigenvalues[-1] * .08
    if ambiguous:
        axis = np.eye(3)[int(np.argmax(bounds[1] - bounds[0]))]
        return axis, "longest Cartesian bound (ambiguous principal axis)", True
    return _signed_axis(eigenvectors[:, -1]), "surface-area principal axis", False


def _rotation_for_axis(axis: np.ndarray) -> Rotation:
    # Preserve source +Z as the roll reference unless it lies along the axis.
    # The rows form a proper right-handed basis and map source axis to rocket X.
    up = np.array([0., 0., 1.])
    if abs(float(axis @ up)) > .95:
        up = np.array([0., 1., 0.])
    z_axis = up - axis * float(axis @ up)
    z_axis /= np.linalg.norm(z_axis)
    y_axis = np.cross(z_axis, axis)
    return Rotation.from_matrix(np.vstack([axis, y_axis, z_axis]))


def _nose_direction(vertices: np.ndarray, axis: np.ndarray, flipped: bool) -> tuple[np.ndarray, str]:
    """Orient a visibly tapered nose using its actual end surface envelopes.

    CAD carries no semantic nose/tail labels. This bounded shape heuristic is
    restricted to a selected reference nose; payloads are never guessed from a
    taper. Reverse is applied after this proposal and remains the user override.
    """
    origin = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    projected = _rotation_for_axis(axis).apply(vertices - origin)
    lower, upper = projected.min(axis=0), projected.max(axis=0)
    length = float(upper[0] - lower[0])
    if length <= 0:
        return axis, "deterministic Cartesian sign"
    radial_center = (lower[1:] + upper[1:]) / 2
    radii = np.linalg.norm(projected[:, 1:] - radial_center, axis=1)
    front = float(radii[projected[:, 0] <= lower[0] + length * .15].max())
    aft = float(radii[projected[:, 0] >= upper[0] - length * .15].max())
    if abs(front - aft) <= max(front, aft, 1e-12) * .05:
        return axis, "deterministic Cartesian sign (nose taper ambiguous)"
    # A flipped OpenRocket nose has the narrow end tailward.
    if (front > aft) != flipped:
        axis = -axis
    return axis, "narrower CAD end tailward for flipped nose" if flipped else "narrower CAD end noseward"


def _target_mesh(project: Project, component: Component) -> trimesh.Trimesh:
    # Original bounds must describe one selected part, not the full span of
    # repeated copies. Attachment already replicates the placed asset afterward.
    single = component.model_copy(deep=True)
    single.metadata["instance_count"] = 1
    mesh = component_mesh(project, single, original=True)
    if not len(mesh.vertices) or not len(mesh.faces):
        raise ValueError("Select a physical component with reference geometry; an assembly cannot receive CAD alignment.")
    return mesh


def _interfaces(project: Project, component: Component, reference: np.ndarray,
                aligned: np.ndarray) -> list[dict]:
    """Axial endpoint diagnostics for adjacent main body parts, not contact claims."""
    kinds = {"nosecone", "bodytube", "transition", "boattail"}
    if component.kind not in kinds:
        return []
    candidates = [item for item in active_components(project)
                  if item.id != component.id and item.external and item.kind in kinds
                  and item.length > 0]
    result = []
    for side, endpoint in [("noseward", 0), ("tailward", 1)]:
        # Pick by nominal reference placement, so an unusually long replacement
        # does not change which original assembly interface we are inspecting.
        eligible = [item for item in candidates
                    if (item.x + item.length <= reference[0, 0] + 1e-8 if side == "noseward"
                        else item.x >= reference[1, 0] - 1e-8)]
        if not eligible:
            continue
        neighbor = min(eligible, key=lambda item: abs((item.x + item.length if side == "noseward" else item.x)
                                                    - reference[endpoint, 0]))
        neighbor_mesh = component_mesh(project, neighbor)
        if not len(neighbor_mesh.vertices):
            continue
        neighbor_endpoint = float(neighbor_mesh.bounds[1 if side == "noseward" else 0, 0])
        separation = (float(aligned[0, 0]) - neighbor_endpoint if side == "noseward"
                      else neighbor_endpoint - float(aligned[1, 0]))
        result.append({"side": side, "neighbor_component_id": neighbor.id,
                       "neighbor_name": neighbor.name, "axial_separation_m": separation,
                       "status": "gap" if separation > 1e-6 else "overlap" if separation < -1e-6 else "aligned"})
    return result


def _preview_mesh(project: Project, component: Component, asset: GeometryAsset,
                  transform: Transform) -> dict:
    count = 1
    if component.kind not in FINS and component.kind != "tubefinset":
        raw_count = component.metadata.get("instance_count", 1)
        if isinstance(raw_count, bool) or not isinstance(raw_count, (int, float)) or not float(raw_count).is_integer() or raw_count < 1:
            raise ValueError("CAD preview requires a positive integer component instance count.")
        count = int(raw_count)
    # Bound the replicated output before allocating it. Preview must not turn a
    # bounded asset into an unbounded JSON/Three.js mesh through instance_count.
    if len(asset.vertices) * count > MAX_VERTICES or len(asset.faces) * count > MAX_FACES:
        raise ValueError("The aligned preview exceeds the one million vertices/two million faces limit after replication. Simplify the CAD or preview one instance.")
    placed = component.model_copy(deep=True)
    placed.asset_id = asset.id
    placed.geometry_mode = "replacement"
    placed.transform = transform.model_copy(deep=True)
    mesh = component_mesh(project, placed)
    return {"components": [{"id": component.id, "name": component.name,
                             "vertices": mesh.vertices.tolist(), "faces": mesh.faces.tolist()}]}


def propose_alignment(project: Project, component: Component, asset: GeometryAsset,
                      options: AlignmentOptions | None = None, *, include_mesh: bool = False) -> dict:
    """Return a component-local rigid transform and SI preview diagnostics.

    Physical dimensions are retained by default. Optional fit is a single
    isotropic scale; it never squeezes a part to the tube diameter or edits CAD.
    """
    options = options or AlignmentOptions()
    if component.kind in ASSEMBLIES:
        raise ValueError("Choose a physical rocket part rather than an assembly for CAD alignment.")
    vertices = np.asarray(asset.vertices, dtype=float)
    faces = np.asarray(asset.faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1:] != (3,) or not len(vertices) or not len(faces):
        raise ValueError("Imported CAD must contain triangle geometry before alignment.")
    if not np.isfinite(vertices).all():
        raise ValueError("CAD vertices must be finite for alignment.")
    reference_mesh = _target_mesh(project, component)
    reference = reference_mesh.bounds.copy()
    target = reference.copy()
    # Main body length excludes bookkeeping shoulders: preserve a tip/front
    # attachment anchor rather than aligning a nose's shoulder to the nose tip.
    if component.kind in {"nosecone", "bodytube", "innertube", "transition", "boattail"} and component.length > 0:
        target[:, 0] = [component.x, component.x + component.length]
    messages = []
    if options.axis == "auto":
        axis, method, ambiguous = _surface_axis(vertices, faces)
        if ambiguous:
            messages.append("The CAD has no distinct longest principal axis. Check the preview and choose X, Y or Z manually if needed.")
    else:
        axis = np.eye(3)[{"x": 0, "y": 1, "z": 2}[options.axis]]
        method = "explicit source " + options.axis.upper() + " axis"
    direction_method = "deterministic Cartesian sign" if options.axis == "auto" else "explicit source axis direction"
    if options.axis == "auto" and component.kind == "nosecone":
        axis, direction_method = _nose_direction(vertices, axis, bool(component.metadata.get("isflipped")))
        messages.append("Nose direction uses a narrower-end surface-envelope guess. Check the actual tip and shoulder in the preview; Reverse overrides this guess.")
    if options.reverse:
        axis = -axis
        direction_method += "; reversed by user"
    rotation = _rotation_for_axis(axis)
    # Subtracting a local integration origin also keeps bounds robust for CAD
    # made far from its origin. Reconstruct the final affine translation below.
    source_bounds = np.array([vertices.min(axis=0), vertices.max(axis=0)])
    origin = source_bounds.mean(axis=0)
    rotated = rotation.apply(vertices - origin)
    rotated_bounds = np.array([rotated.min(axis=0), rotated.max(axis=0)])
    source_length = float(rotated_bounds[1, 0] - rotated_bounds[0, 0])
    target_length = float(target[1, 0] - target[0, 0])
    if source_length <= 1e-12 or target_length <= 1e-12:
        raise ValueError("Source CAD and selected part need nonzero axial dimensions to align.")
    scale = target_length / source_length if options.fit_length else 1.0
    scaled_bounds = rotated_bounds * scale
    source_anchor = scaled_bounds.mean(axis=0)
    target_anchor = target.mean(axis=0)
    if options.anchor == "start":
        source_anchor[0] = scaled_bounds[0, 0]
        target_anchor[0] = target[0, 0]
    offset = target_anchor - source_anchor
    world_translation = offset - rotation.apply(origin) * scale
    local_translation = world_translation - np.array([component.x, 0., 0.])
    with python_warnings.catch_warnings():
        python_warnings.filterwarnings("ignore", message="Gimbal lock detected")
        euler = rotation.as_euler("xyz", degrees=True)
    transform = Transform(translation=local_translation.tolist(), rotation=euler.tolist(), scale=scale)
    aligned_bounds = scaled_bounds + offset
    if not options.fit_length and abs(source_length - target_length) > max(1e-5, target_length * .01):
        messages.append("Physical CAD dimensions are preserved. Its length differs from the selected part; use explicit uniform Fit length only if resizing is intended.")
    if options.fit_length and abs(scale - 1) > 1e-8:
        messages.append("Fit length uniformly scales all CAD dimensions. Volume/mass scale by scale³; this changes the physical design.")
    messages.append("Axis direction and roll are placement guesses: check the preview and use Reverse or manual adjustments to put the correct end toward the nose.")
    if component.kind in FINS or component.kind == "tubefinset":
        messages.append("This asset replaces the entire selected fin set, not one individual fin. Axial PCA may be ambiguous for wide fins; inspect its orientation and radial placement.")
    if any(float(component.metadata.get(key, 0) or 0) > 0 for key in ["aftshoulderlength", "foreshoulderlength"]):
        messages.append("The axial target is the main part length; source shoulders remain part of the CAD and may need a manual axial adjustment.")
    interfaces = _interfaces(project, component, target, aligned_bounds)
    for item in interfaces:
        if item["status"] != "aligned":
            messages.append(f"{item['side'].capitalize()} interface with {item['neighbor_name']}: {item['status']} of {abs(item['axial_separation_m']):.6g} m. Inspect the joint; no material connection or Boolean union is inferred.")
    messages.append("Only the selected component is replaced. Exterior CFD uses the assembled exterior flow mask; CAD vertices, neighboring parts, cavities and structural connections are not merged or modified.")
    proposal = {"component_id": component.id, "asset_id": asset.id,
            "transform": transform.model_dump(), "axis_method": method,
            "axis_direction_method": direction_method,
            "source_axis": axis.tolist(), "anchor": options.anchor,
            "source_bounds_m": source_bounds.tolist(), "target_bounds_m": target.tolist(),
            "aligned_bounds_m": aligned_bounds.tolist(),
            "source_dimensions_m": (source_bounds[1] - source_bounds[0]).tolist(),
            "oriented_dimensions_m": (rotated_bounds[1] - rotated_bounds[0]).tolist(),
            "target_dimensions_m": (target[1] - target[0]).tolist(),
            "aligned_dimensions_m": (aligned_bounds[1] - aligned_bounds[0]).tolist(),
            "scale": scale, "fit_length": options.fit_length, "interfaces": interfaces,
            "warnings": messages, "source_mesh_modified": False, "neighbors_modified": False}
    if include_mesh:
        proposal["preview_mesh"] = _preview_mesh(project, component, asset, transform)
    return proposal
