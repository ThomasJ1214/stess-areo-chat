"""SI mesh geometry: CAD tessellation, original ORK parts and aligned replacements.

The saved project contains triangulated geometry rather than a STEP B-rep. CAD
vertices preserve their original origin, then users align them to a component.
"""
from __future__ import annotations

import io
import math
from pathlib import Path
import tempfile

import numpy as np
from scipy.spatial.transform import Rotation
import trimesh

from .models import Component, GeometryAsset, Project, active_components

UNIT_SCALE = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "inch": 0.0254, "ft": 0.3048}
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_VERTICES = 1_000_000
MAX_FACES = 2_000_000
ASSEMBLIES = {"rocket", "stage", "parallelstage", "podset"}
FINS = {"finset", "trapezoidfinset", "freeformfinset", "ellipticalfinset", "fin"}


def _empty() -> trimesh.Trimesh:
    return trimesh.Trimesh(vertices=np.empty((0, 3)), faces=np.empty((0, 3), dtype=np.int64), process=False)


def _validate_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError("The imported file contains no triangle geometry.")
    if len(mesh.vertices) > MAX_VERTICES or len(mesh.faces) > MAX_FACES:
        raise ValueError("Geometry exceeds the one million vertices/two million faces safety limit. Simplify the source model.")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError("Geometry contains non-finite vertices.")
    if (mesh.faces < 0).any() or mesh.faces.max() >= len(mesh.vertices):
        raise ValueError("Geometry contains invalid face indices.")
    mesh.remove_unreferenced_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.merge_vertices()
    if len(mesh.faces) == 0:
        raise ValueError("Geometry contains only degenerate triangles.")
    # Repair local winding without interpreting every disconnected shell as
    # additional solid material. An enclosed inward shell can be a genuine void.
    trimesh.repair.fix_winding(mesh)
    _orient_enclosed_shells(mesh)
    return mesh


def _point_inside_closed_shell(point: np.ndarray, triangles: np.ndarray) -> bool:
    """Generalized winding number from triangle solid angles; no spatial-index dependency.

    Van Oosterom & Strackee, IEEE Trans. Biomed. Eng. 30(2), 1983,
    doi:10.1109/TBME.1983.325207. Only used on bounded closed-shell candidates.
    """
    vectors = triangles - point
    a, b, c = vectors[:, 0], vectors[:, 1], vectors[:, 2]
    la, lb, lc = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1), np.linalg.norm(c, axis=1)
    numerator = np.einsum("ij,ij->i", a, np.cross(b, c))
    denominator = (la * lb * lc + np.einsum("ij,ij->i", a, b) * lc
                   + np.einsum("ij,ij->i", b, c) * la + np.einsum("ij,ij->i", c, a) * lb)
    winding = float(np.sum(2 * np.arctan2(numerator, denominator)))
    return abs(winding) > 2 * math.pi


def _orient_enclosed_shells(mesh: trimesh.Trimesh) -> None:
    """Orient actual material boundaries: exterior outward, nested void inward.

    STEP face orientation carries solid/void semantics. For a unitless boundary
    mesh nested shells follow even/odd material containment; this interpretation
    is reported to users rather than silently adding a cavity as solid mass.
    """
    groups = trimesh.graph.connected_components(mesh.face_adjacency,
        nodes=np.arange(len(mesh.faces)), min_len=1, engine="scipy")
    if len(groups) == 1:
        if mesh.is_watertight and mesh.volume < 0:
            mesh.invert()
        return
    if len(groups) > 4096:
        mesh.metadata["volume_ambiguous"] = "More than 4,096 shells: nested material topology cannot be verified."
        return
    shells = [mesh.submesh([indices], append=True, repair=False) for indices in groups]
    closed = [i for i, shell in enumerate(shells) if shell.is_watertight]
    bounds = [shell.bounds for shell in shells]
    depths = {i: 0 for i in closed}
    nested = False
    trusted = mesh.metadata.get("trusted_step_winding", False)
    # Separate closed shells need not be separate material. Bounding boxes
    # crossing without containment can hide an intersecting assembly; summing
    # signed volumes would count the overlap twice. Surface import cannot prove
    # a CAD Boolean union, so preserve inspection geometry and require measured
    # mass (or a unioned source) for these conservatively ambiguous cases.
    scale_tolerance = max(float(np.max(mesh.extents)), 1e-12) * 1e-10
    for ii, i in enumerate(closed):
        for j in closed[ii + 1:]:
            overlap = np.minimum(bounds[i][1], bounds[j][1]) - np.maximum(bounds[i][0], bounds[j][0])
            contains_i = np.all(bounds[i][0] <= bounds[j][0]) and np.all(bounds[i][1] >= bounds[j][1])
            contains_j = np.all(bounds[j][0] <= bounds[i][0]) and np.all(bounds[j][1] >= bounds[i][1])
            if np.all(overlap > scale_tolerance) and not (contains_i or contains_j):
                mesh.metadata["volume_ambiguous"] = "Closed shells have intersecting bounds without containment; overlapping assembly material volume cannot be verified. Use measured mass or a CAD union."
    for i in closed:
        candidates = [j for j in closed if i != j
                      and np.all(bounds[j][0] <= bounds[i][0])
                      and np.all(bounds[j][1] >= bounds[i][1])
                      and abs(shells[j].volume) > abs(shells[i].volume)]
        for j in candidates:
            samples = shells[i].vertices[np.linspace(0, len(shells[i].vertices) - 1, min(5, len(shells[i].vertices))).astype(int)]
            contained = [_point_inside_closed_shell(point, shells[j].triangles) for point in samples]
            if all(contained):
                nested = True
                depths[i] += 1
            elif any(contained):
                mesh.metadata["volume_ambiguous"] = "Intersecting or partially overlapping nested shells do not define an unambiguous material volume."
    if nested:
        mesh.metadata["nested_shells"] = True
    # A STEP internal positive shell can be a separate solid overlapping a
    # container. Do not turn that B-rep solid into an invented void.
    if trusted and any(depths[i] % 2 == 1 and shells[i].volume >= 0 for i in closed):
        mesh.metadata["volume_ambiguous"] = "STEP contains a positive solid enclosed by another solid; overlapping/assembly material volume requires measured mass or a CAD union."
        return
    faces = mesh.faces.copy()
    for i in closed:
        expected_positive = depths[i] % 2 == 0
        if (shells[i].volume > 0) != expected_positive:
            faces[groups[i]] = faces[groups[i]][:, ::-1]
    mesh.faces = faces


def _step_mesh(data: bytes) -> trimesh.Trimesh:
    """Read STEP using Open CASCADE. Its internal length unit is millimetres.

    STEP's encoded units are handled by OCCT. Unlike unitless mesh formats,
    changing the UI units cannot reinterpret an explicitly dimensioned STEP.
    """
    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        from OCP.TopLoc import TopLoc_Location
    except ImportError as exc:
        raise RuntimeError("STEP support requires the bundled Open CASCADE (cadquery-ocp) package.") from exc
    with tempfile.TemporaryDirectory(prefix="rocket-step-") as d:
        path = Path(d) / "geometry.step"
        path.write_bytes(data)
        reader = STEPControl_Reader()
        if reader.ReadFile(str(path)) != IFSelect_RetDone:
            raise ValueError("Open CASCADE could not read this STEP document.")
        if reader.TransferRoots() == 0:
            raise ValueError("STEP document contains no transferable solid/surface geometry.")
        shape = reader.OneShape()
        if shape.IsNull():
            raise ValueError("STEP document contains no shapes.")
        # 0.05 mm chord tolerance; Angular tolerance 0.3 radians. Adaptive OCCT
        # tessellation is a viewing/solver surface approximation, not exact CAD.
        BRepMesh_IncrementalMesh(shape, 0.05, False, 0.3, False).Perform()
        vertices, faces = [], []
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = TopoDS.Face_s(explorer.Current())
            location = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(face, location)
            if tri is not None:
                offset = len(vertices)
                tr = location.Transformation()
                for i in range(1, tri.NbNodes() + 1):
                    p = tri.Node(i).Transformed(tr)
                    vertices.append([p.X() * 0.001, p.Y() * 0.001, p.Z() * 0.001])
                reverse = face.Orientation() == TopAbs_REVERSED
                for i in range(1, tri.NbTriangles() + 1):
                    a, b, c = tri.Triangle(i).Get()
                    indices = [offset + a - 1, offset + b - 1, offset + c - 1]
                    faces.append(indices[::-1] if reverse else indices)
                if len(vertices) > MAX_VERTICES or len(faces) > MAX_FACES:
                    raise ValueError("STEP tessellation exceeds geometry safety limits. Simplify the CAD model.")
            explorer.Next()
    result = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    result.metadata["trusted_step_winding"] = True
    return result


def import_geometry(data: bytes, filename: str, units: str = "mm") -> GeometryAsset:
    """Read a unitless mesh using chosen units or an explicitly dimensioned STEP."""
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("CAD data is empty or exceeds the 128 MiB limit.")
    suffix = Path(filename).suffix.lower().lstrip(".")
    if units.lower() not in UNIT_SCALE:
        raise ValueError("Geometry units must be m, cm, mm, in or ft.")
    warnings = []
    if suffix in {"step", "stp"}:
        mesh = _step_mesh(data)
        warnings.append("STEP units are read from the document; the mesh-format unit selector does not rescale dimensioned STEP geometry.")
        warnings.append("STEP B-rep was tessellated at 0.05 mm chord tolerance; the project saves the mesh rather than parametric CAD history.")
    elif suffix in {"stl", "obj", "ply"}:
        try:
            # Skip OBJ material loading: never resolve untrusted external files.
            loaded = trimesh.load(io.BytesIO(data), file_type=suffix, force="scene",
                                  resolver=None, skip_materials=True, process=True)
            if isinstance(loaded, trimesh.Scene):
                mesh = loaded.to_mesh()
            elif isinstance(loaded, trimesh.Trimesh):
                mesh = loaded
            else:
                raise ValueError("Geometry does not contain triangle surfaces.")
            mesh.apply_scale(UNIT_SCALE[units.lower()])
        except (ValueError, TypeError, OSError, IndexError) as exc:
            raise ValueError(f"Could not read {suffix.upper()} geometry: {exc}") from exc
    else:
        raise ValueError("Supported geometry formats are STEP/STP, STL, OBJ and PLY.")
    mesh = _validate_mesh(mesh)
    watertight = bool(mesh.is_watertight and mesh.is_winding_consistent and not mesh.metadata.get("volume_ambiguous"))
    volume = float(abs(mesh.volume)) if watertight else 0.0
    if not watertight:
        if mesh.metadata.get("volume_ambiguous"):
            warnings.append("Enclosed material volume is ambiguous. Assign measured mass; solid FEA requires an unambiguous closed solid.")
        else:
            warnings.append("This mesh is open or inconsistently wound: its volume is unknown. Assign measured mass; solid FEA requires a closed mesh.")
    elif volume <= 1e-15:
        watertight = False
        volume = 0.0
        warnings.append("Geometry has negligible enclosed volume and cannot represent a solid mass or FEA solid.")
    if mesh.metadata.get("volume_ambiguous"):
        warnings.append(mesh.metadata["volume_ambiguous"])
    if mesh.metadata.get("nested_shells"):
        warnings.append("Nested closed shells represent material/void boundaries. Interior cavity volume is subtracted; overlapping solid assemblies require measured mass or a CAD union.")
    connected = trimesh.graph.connected_components(mesh.face_adjacency,
        nodes=np.arange(len(mesh.faces)), min_len=1, engine="scipy")
    if len(connected) > 1:
        warnings.append("Geometry contains disconnected shells. FEA contact/bonding is not inferred automatically.")
    if max(mesh.extents) > 10 or max(mesh.extents) < 1e-5:
        warnings.append("Model dimensions are unusual for a rocket component. Verify units and scale before analysis.")
    return GeometryAsset(name=Path(filename.replace("\\", "/")).name, format=suffix,
                         vertices=mesh.vertices.tolist(), faces=mesh.faces.tolist(),
                         volume=volume, watertight=watertight, source_file=Path(filename.replace("\\", "/")).name,
                         warnings=warnings)


def _revolve(xs: np.ndarray, outer: np.ndarray, inner: np.ndarray | None = None) -> trimesh.Trimesh:
    """Watertight revolution of a solid or hollow radial-thickness profile."""
    if inner is None:
        contour = [[0, xs[0]], *np.column_stack((outer, xs)).tolist(), [0, xs[-1]]]
    else:
        contour = [*np.column_stack((outer, xs)).tolist(),
                   *np.column_stack((inner[::-1], xs[::-1])).tolist()]
    profile = np.asarray(contour)
    # Consecutive coincident endpoints can arise at a hollow nose's closed tip.
    keep = np.r_[True, np.linalg.norm(np.diff(profile, axis=0), axis=1) > 1e-14]
    profile = profile[keep]
    if len(profile) < 3:
        return _empty()
    if np.linalg.norm(profile[0] - profile[-1]) > 1e-14:
        profile = np.vstack([profile, profile[0]])
    mesh = trimesh.creation.revolve(profile, sections=64)
    # Revolve generates (radial cosine, radial sine, axial). Rocket axial = X.
    mesh.vertices = mesh.vertices[:, [2, 0, 1]]
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals(multibody=True)
    return mesh


def _nose_radius(x, length, radius, shape, parameter):
    u = np.clip(np.asarray(x) / max(length, 1e-15), 0, 1)
    if radius <= 0:
        return np.zeros_like(u)
    if shape == "conical":
        return radius * u
    if shape == "ellipsoid":
        return radius * np.sqrt(np.maximum(0, 2 * u - u * u))
    if shape == "power":
        p = np.clip(parameter, 0, 1)
        return np.where(u <= 1e-5, 0, radius) if p <= 1e-5 else radius * u ** p
    if shape == "parabolic":
        k = np.clip(parameter, 0, 1)
        return radius * (2 * u - k * u * u) / (2 - k)
    if shape in {"haack", "vonkarman"}:
        theta = np.arccos(1 - 2 * u)
        return radius * np.sqrt(np.maximum(0, (theta - np.sin(2 * theta) / 2 + parameter * np.sin(theta) ** 3) / math.pi))
    if shape == "ogive":
        p = np.clip(parameter, 0, 1)
        if p < 1e-8:
            return radius * u
        effective_length = max(length, radius)
        xx = u * effective_length
        rr = math.sqrt((effective_length ** 2 + radius ** 2) * (((2 - p) * effective_length) ** 2 + (p * radius) ** 2) / (4 * (p * radius) ** 2))
        ll = effective_length / p
        y0 = math.sqrt(max(0, rr * rr - ll * ll))
        return np.sqrt(np.maximum(0, rr * rr - (ll - xx) ** 2)) - y0
    raise ValueError(f"Unsupported nose/transition profile '{shape}'.")


def _transition_radii(component: Component, xs: np.ndarray) -> np.ndarray:
    a = component.radius
    b = component.radius_end if component.radius_end is not None else a
    shape = component.metadata.get("nose_shape", "conical")
    p = component.metadata.get("shape_parameter", 1 if shape in {"ogive", "parabolic"} else 0.5 if shape == "power" else 0)
    xx = xs if a <= b else component.length - xs
    lo, hi = min(a, b), max(a, b)
    if component.metadata.get("shape_clipped") and lo > 0 and hi > lo:
        from scipy.optimize import brentq
        def difference(clip):
            return float(_nose_radius(np.array([clip]), clip + component.length, hi, shape, p)[0]) - lo
        upper = component.length
        while difference(upper) < 0 and upper < 1e7:
            upper *= 2
        clip = brentq(difference, 0, upper)
        return _nose_radius(xx + clip, component.length + clip, hi, shape, p)
    return lo + _nose_radius(xx, component.length, hi - lo, shape, p)


def radius_profile(component: Component, x_array: np.ndarray) -> np.ndarray:
    """Canonical original radius at local axial X; shared by mass/CP and meshes."""
    xs = np.clip(np.asarray(x_array, dtype=float), 0, component.length)
    if component.kind == "nosecone":
        shape = component.metadata.get("nose_shape", "conical")
        parameter = component.metadata.get("shape_parameter", 1 if shape in {"ogive", "parabolic"} else .5 if shape == "power" else 0)
        if component.metadata.get("isflipped"):
            xs = component.length - xs
        return _nose_radius(xs, component.length, component.radius, shape, parameter)
    if component.kind in {"transition", "boattail"}:
        return _transition_radii(component, xs)
    return np.full_like(xs, component.radius)


def _signed_area(p):
    return float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]) / 2)


def _triangulate_polygon(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Ear clipping retains a concave freeform fin, without a convex hull surrogate."""
    p = np.asarray(points, dtype=float)
    if len(p) > 4096 or len(p) < 3 or not np.isfinite(p).all():
        raise ValueError("Invalid or excessively complex fin polygon.")
    if np.linalg.norm(p[0] - p[-1]) < 1e-12:
        p = p[:-1]
    area = _signed_area(p)
    if abs(area) < 1e-14:
        raise ValueError("Fin polygon has zero area.")
    if area < 0:
        p = p[::-1]
    indices, triangles = list(range(len(p))), []
    tol = 1e-14
    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]
    while len(indices) > 3:
        found = False
        for j in range(len(indices)):
            ia, ib, ic = indices[j - 1], indices[j], indices[(j + 1) % len(indices)]
            a, b, c = p[[ia, ib, ic]]
            if cross(b - a, c - b) <= tol:
                continue
            others = [k for k in indices if k not in {ia, ib, ic}]
            if any(cross(b - a, p[k] - a) >= -tol and cross(c - b, p[k] - b) >= -tol
                   and cross(a - c, p[k] - c) >= -tol for k in others):
                continue
            triangles.append([ia, ib, ic])
            indices.pop(j)
            found = True
            break
        if not found:
            raise ValueError("Fin polygon is self-intersecting or cannot be triangulated.")
    triangles.append(indices)
    return p, np.asarray(triangles, dtype=np.int64)


def _fin_mesh(c: Component) -> trimesh.Trimesh:
    if c.kind == "freeformfinset":
        polygon = np.asarray(c.metadata.get("fin_points", []), dtype=float)
    elif c.kind == "ellipticalfinset":
        theta = np.linspace(math.pi, 0, 33)
        polygon = np.column_stack((c.root_chord * (1 + np.cos(theta)) / 2, c.span * np.sin(theta)))
    else:
        polygon = np.array([[0, 0], [c.sweep, c.span], [c.sweep + c.tip_chord, c.span], [c.root_chord, 0]])
    points, faces = _triangulate_polygon(polygon)
    if c.metadata.get("zero_thickness"):
        base = trimesh.Trimesh(vertices=np.column_stack([points, np.zeros(len(points))]), faces=faces, process=False)
    else:
        base = trimesh.creation.extrude_triangulation(points, faces, c.thickness)
        base.vertices[:, 2] -= c.thickness / 2
    # Optional fin tab is real geometry but is not automatically bonded for FEA.
    tab_height, tab_length = c.metadata.get("tabheight", 0), c.metadata.get("tablength", 0)
    if tab_height > 0 and tab_length > 0:
        tab = trimesh.creation.box([tab_length, tab_height, c.thickness])
        method = c.metadata.get("tab_position_method", "middle")
        offset = c.metadata.get("tab_position", 0)
        tab_start = (c.root_chord - tab_length if method in {"bottom", "end"}
                     else (c.root_chord - tab_length) / 2 if method in {"middle", "center"} else 0) + offset
        tab.apply_translation([tab_start + tab_length / 2, -tab_height / 2, 0])
        base = trimesh.util.concatenate([base, tab])
    base.vertices[:, 1] += c.radius
    cant = float(c.metadata.get("cant", 0))
    if cant:
        # Cant about radial axis through the centre of the root chord.
        origin = np.array([c.root_chord / 2, c.radius, 0])
        base.vertices = Rotation.from_euler("y", cant, degrees=True).apply(base.vertices - origin) + origin
    rotation = c.metadata.get("angleoffset", c.metadata.get("rotation", 0))
    copies = []
    for index in range(c.fin_count):
        fin = base.copy()
        fin.vertices = Rotation.from_euler("x", rotation + 360 * index / c.fin_count, degrees=True).apply(fin.vertices)
        copies.append(fin)
    return trimesh.util.concatenate(copies)


def _original_mesh(c: Component) -> trimesh.Trimesh:
    if c.kind in ASSEMBLIES or c.metadata.get("unsupported"):
        return _empty()
    if c.kind in FINS:
        return _fin_mesh(c)
    if c.kind == "railbutton":
        base, flange = c.metadata.get("baseheight", 0), c.metadata.get("flangeheight", 0)
        height = c.metadata.get("height", 0)
        if height <= 0:
            return _empty()
        neck_r = c.metadata.get("innerdiameter", c.radius * 2) / 2
        xs = np.array([0, base, base, height - flange, height - flange, height])
        outer = np.array([c.radius, c.radius, neck_r, neck_r, c.radius, c.radius])
        mesh = _revolve(xs, outer)
        # A rail button's axis is radial, unlike the rocket's longitudinal axis.
        mesh.vertices = mesh.vertices[:, [1, 0, 2]]
        mesh.apply_translation([c.length / 2, c.metadata.get("parent_radius", 0), 0])
        return mesh
    if c.length <= 0 or c.radius <= 0:
        return _empty()
    if c.kind == "nosecone":
        xs = np.linspace(0, c.length, 97)
        outer = radius_profile(c, xs)
    elif c.kind in {"transition", "boattail"}:
        xs = np.linspace(0, c.length, 65)
        outer = radius_profile(c, xs)
    else:
        xs = np.array([0, c.length])
        outer = np.full(2, c.radius)
    solid = c.metadata.get("filled") or c.kind in {"bulkhead", "masscomponent", "parachute", "streamer", "shockcord", "railbutton"}
    inner = None if solid else np.full_like(outer, c.metadata["inner_radius"]) if "inner_radius" in c.metadata else np.maximum(outer - c.thickness, 0)
    if c.metadata.get("zero_thickness"):
        main = trimesh.creation.revolve(np.column_stack([outer, xs]), sections=64)
        main.vertices = main.vertices[:, [2, 0, 1]]
    else:
        main = _revolve(xs, outer, inner)
    pieces = [main]
    # Shoulders are independently watertight; overlap interfaces are not unioned.
    shoulder_positions = [("aft", c.length), ("fore", -c.metadata.get("foreshoulderlength", 0))]
    if c.kind == "nosecone" and c.metadata.get("isflipped"):
        shoulder_positions = [("aft", -c.metadata.get("aftshoulderlength", 0)), ("fore", c.length)]
    for prefix, position in shoulder_positions:
        shoulder_r = c.metadata.get(f"{prefix}shoulderradius", 0)
        shoulder_l = c.metadata.get(f"{prefix}shoulderlength", 0)
        shoulder_t = c.metadata.get(f"{prefix}shoulderthickness", c.thickness)
        if shoulder_r > 0 and shoulder_l > 0:
            shoulder = _revolve(np.array([position, position + shoulder_l]), np.full(2, shoulder_r),
                                np.full(2, max(0, shoulder_r - shoulder_t)))
            pieces.append(shoulder)
    if c.kind == "tubefinset":
        tube = main.copy()
        copies = []
        parent_r = c.metadata.get("parent_radius", c.radius)
        for i in range(c.fin_count):
            angle = math.radians(c.metadata.get("rotation", 0) + 360 * i / c.fin_count)
            copy = tube.copy()
            copy.apply_translation([0, (parent_r + c.radius) * math.cos(angle), (parent_r + c.radius) * math.sin(angle)])
            copies.append(copy)
        return trimesh.util.concatenate(copies)
    if c.kind == "launchlug":
        main.apply_translation([0, c.metadata.get("parent_radius", 0) + c.radius, 0])
        main.vertices = Rotation.from_euler("x", c.metadata.get("angleoffset", c.metadata.get("rotation", 0)), degrees=True).apply(main.vertices)
        return main
    return trimesh.util.concatenate(pieces)


def component_mesh(project: Project, component: Component, original: bool = False) -> trimesh.Trimesh:
    if not original and component.geometry_mode == "replacement":
        asset = next((a for a in project.assets if a.id == component.asset_id), None)
        if asset is None:
            raise ValueError(f"Replacement asset for {component.name} is missing.")
        mesh = trimesh.Trimesh(vertices=asset.vertices, faces=asset.faces, process=False)
        if not asset.watertight:
            # Retain the importer's material-volume decision when reconstructing
            # the portable asset. Closed triangle topology alone cannot turn an
            # ambiguous overlapping assembly into a verified physical solid.
            mesh.metadata["volume_ambiguous"] = "Imported asset has no reliable enclosed material volume."
        mesh.vertices *= component.transform.scale
        mesh.vertices = Rotation.from_euler("xyz", component.transform.rotation, degrees=True).apply(mesh.vertices)
        mesh.apply_translation(component.transform.translation)
    else:
        mesh = _original_mesh(component)
        # Internal original component radial placement is stored here. CAD
        # alignment scale/rotation never distorts the original ORK comparison.
        if component.kind not in ASSEMBLIES:
            radial = component.metadata.get("radialposition", 0)
            angle = math.radians(component.metadata.get("radialdirection", 0))
            mesh.apply_translation([0, radial * math.cos(angle), radial * math.sin(angle)])
    count = component.metadata.get("instance_count", 1)
    if count > 1 and component.kind not in FINS and component.kind != "tubefinset":
        instances = []
        for index in range(count):
            piece = mesh.copy()
            piece.apply_translation([index * component.metadata.get("instance_separation", component.metadata.get("instanceseparation", 0)), 0, 0])
            instances.append(piece)
        mesh = trimesh.util.concatenate(instances)
    mesh.apply_translation([component.x, 0, 0])
    return mesh


def project_mesh(project: Project, configuration_id: str | None = None, original: bool = False) -> trimesh.Trimesh:
    meshes = [component_mesh(project, c, original) for c in active_components(project, configuration_id) if c.external]
    meshes = [mesh for mesh in meshes if len(mesh.faces)]
    return trimesh.util.concatenate(meshes) if meshes else _empty()


def geometry_properties(project: Project, component: Component, original: bool = False) -> dict:
    """Physical bounds/volume for inspection, alignment and original/replacement comparisons."""
    mesh = component_mesh(project, component, original)
    if not len(mesh.faces):
        return {"bounds_m": None, "volume_m3": 0.0, "watertight": False, "centroid_m": None}
    watertight = bool(mesh.is_watertight and mesh.is_winding_consistent
                      and not mesh.metadata.get("volume_ambiguous"))
    return {"bounds_m": mesh.bounds.tolist(), "extents_m": mesh.extents.tolist(),
            "volume_m3": abs(float(mesh.volume)) if watertight else None,
            "watertight": watertight,
            "centroid_m": mesh.center_mass.tolist() if watertight else mesh.centroid.tolist(),
            "surface_area_m2": float(mesh.area)}
