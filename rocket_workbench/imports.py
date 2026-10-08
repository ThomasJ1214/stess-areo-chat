"""Bounded, non-extracting OpenRocket and thrust-curve readers.

OpenRocket schema is based on its upstream XML saver implementations, not on
saved simulation output. Motor references alone never become invented curves.
"""
from __future__ import annotations

import gzip
import io
import math
from pathlib import PurePosixPath
import zipfile

import numpy as np
from defusedxml import ElementTree as ET

from .models import Component, FlightConfiguration, Material, Motor, Project

MAX_XML_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4096
SUPPORTED_COMPONENTS = {
    "rocket", "stage", "nosecone", "bodytube", "transition", "trapezoidfinset",
    "ellipticalfinset", "freeformfinset", "innertube", "tubecoupler",
    "centeringring", "bulkhead", "engineblock", "masscomponent", "parachute",
    "streamer", "shockcord", "launchlug", "railbutton", "tubefinset",
    "parallelstage", "podset",
}
ASSEMBLIES = {"rocket", "stage", "parallelstage", "podset"}
AXIAL_COMPONENTS = {"nosecone", "bodytube", "transition", "stage"}
EXTERNAL_COMPONENTS = {
    "nosecone", "bodytube", "transition", "trapezoidfinset", "ellipticalfinset",
    "freeformfinset", "tubefinset", "launchlug", "railbutton",
}


def _xml(data: bytes):
    if len(data) > MAX_XML_BYTES:
        raise ValueError("XML exceeds the 16 MiB safety limit.")
    try:
        root = ET.fromstring(data)
    except Exception as exc:
        raise ValueError(f"Invalid or unsafe XML: {exc}") from exc
    count = 0
    pending = [(root, 0)]
    while pending:
        el, depth = pending.pop()
        count += 1
        if count > 100_000 or depth > 96:
            raise ValueError("XML component count or nesting exceeds the safety limit.")
        # OpenRocket itself uses no namespace; allow a default XML namespace.
        el.tag = el.tag.rsplit("}", 1)[-1].lower()
        pending.extend((c, depth + 1) for c in el)
    return root


def _text(el, tag: str, default: str = "") -> str:
    found = el.find(tag)
    return (found.text or "").strip() if found is not None else default


def _number_text(text: str, default: float | None = None) -> float:
    """OpenRocket writes both `auto` and `auto <resolved value>`."""
    text = text.strip()
    if text.startswith("auto"):
        text = text[4:].strip()
    if not text:
        if default is not None:
            return default
        raise ValueError("Required numeric value is missing.")
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value: {text[:80]!r}") from exc
    if not math.isfinite(value):
        raise ValueError("Non-finite numeric values are not supported.")
    return value


def _number(el, tag: str, default: float = 0.0) -> float:
    return _number_text(_text(el, tag), default)


def _boolean(el, tag: str, default: bool = False) -> bool:
    value = _text(el, tag, str(default)).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"Invalid Boolean for {tag}: {value}")
    return value == "true"


def _nonnegative(value: float, label: str) -> float:
    if value < 0:
        raise ValueError(f"{label} cannot be negative.")
    return value


def _curve(points: list[list[float]], name: str) -> list[list[float]]:
    if len(points) < 2:
        raise ValueError(f"Motor {name} needs at least two thrust samples.")
    a = np.asarray(points, dtype=float)
    if not np.isfinite(a).all() or (a < 0).any():
        raise ValueError(f"Motor {name} contains negative or non-finite time/thrust.")
    if (np.diff(a[:, 0]) <= 0).any():
        raise ValueError(f"Motor {name} sample times must strictly increase.")
    if not (a[:, 1] > 0).any():
        raise ValueError(f"Motor {name} has no positive thrust.")
    # A zero sample at t=0 is the physical convention for a curve beginning later.
    if a[0, 0] > 0:
        points = [[0.0, 0.0], *points]
    return points


def import_motor(data: bytes, filename: str) -> list[Motor]:
    """Read RASP .eng (mm/kg) or RockSim .rse (mm/g) thrust curves."""
    if not data or len(data) > MAX_XML_BYTES:
        raise ValueError("Motor data is empty or exceeds the 16 MiB limit.")
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if suffix == ".rse":
        root = _xml(data)
        engines = list(root.iter("engine"))
        if not engines:
            raise ValueError("RSE file contains no engines.")
        motors = []
        for eng in engines:
            a = eng.attrib
            name = a.get("code", "Unnamed motor")
            total = _number_text(a.get("initWt", "")) / 1000
            prop = _number_text(a.get("propWt", "")) / 1000
            if total < prop:
                raise ValueError(f"Motor {name}: initial mass is less than propellant mass.")
            samples = [[_number_text(p.attrib.get("t", "")), _number_text(p.attrib.get("f", ""))]
                       for p in eng.iter("eng-data")]
            motors.append(Motor(
                name=name, diameter=_number_text(a.get("dia", "")) / 1000,
                length=_number_text(a.get("len", "")) / 1000,
                dry_mass=_nonnegative(total - prop, "Dry motor mass"),
                propellant_mass=_nonnegative(prop, "Propellant mass"),
                curve=_curve(samples, name), source=f"RSE: {a.get('mfg', '')}; {filename}",
            ))
        return motors
    if suffix != ".eng":
        raise ValueError("Motor format must be .eng or .rse.")
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        source = data.decode("latin-1")
    motors: list[Motor] = []
    header: list[str] | None = None
    points: list[list[float]] = []

    def finish():
        if header is None:
            return
        name, diameter, length, _delays, prop, total, manufacturer = header
        prop_kg, total_kg = _number_text(prop), _number_text(total)
        if prop_kg > total_kg:
            raise ValueError(f"Motor {name}: initial mass is less than propellant mass.")
        motors.append(Motor(
            name=name, diameter=_number_text(diameter) / 1000,
            length=_number_text(length) / 1000, propellant_mass=prop_kg,
            dry_mass=total_kg - prop_kg, curve=_curve(points, name),
            source=f"RASP: {manufacturer}; {filename}",
        ))

    for line_number, raw in enumerate(source.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) >= 7:
            finish()
            header = [*fields[:6], " ".join(fields[6:])]
            points = []
        elif len(fields) == 2 and header is not None:
            points.append([_number_text(fields[0]), _number_text(fields[1])])
        else:
            raise ValueError(f"Invalid RASP record on line {line_number}.")
    finish()
    if not motors:
        raise ValueError("RASP file contains no motors.")
    return motors


def _archive(data: bytes) -> tuple[bytes, list[tuple[str, bytes]]]:
    """Read members in memory; never trust paths or extract archive entries."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("ORK archive exceeds the 128 MiB limit.")
    embedded = []
    if data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                entries = z.infolist()
                if len(entries) > MAX_ARCHIVE_ENTRIES or sum(e.file_size for e in entries) > MAX_ARCHIVE_BYTES:
                    raise ValueError("ORK archive exceeds decompressed size or entry count limits.")
                names = set()
                for e in entries:
                    p = PurePosixPath(e.filename.replace("\\", "/"))
                    # Older genuine ORK files carry virtual absolute paths to
                    # stock textures. These are ignored, never read/extracted.
                    virtual_texture = (e.filename.startswith("/datafiles/textures/")
                                       and p.suffix.lower() in {".jpg", ".jpeg", ".png"})
                    if (p.is_absolute() and not virtual_texture) or ".." in p.parts or ":" in e.filename or e.flag_bits & 1:
                        raise ValueError("Unsafe or encrypted ORK archive member.")
                    if e.filename in names:
                        raise ValueError("Duplicate ORK archive member.")
                    names.add(e.filename)
                candidates = [e for e in entries if PurePosixPath(e.filename).name.lower() == "rocket.ork"]
                if not candidates:
                    candidates = [e for e in entries if e.filename.lower().endswith((".ork", ".xml"))]
                if len(candidates) != 1:
                    raise ValueError("ORK archive must contain one unambiguous rocket XML document.")
                main = candidates[0]
                if main.file_size > MAX_XML_BYTES:
                    raise ValueError("ORK XML exceeds the 16 MiB limit.")
                xml = z.read(main)
                for e in entries:
                    if e.filename.lower().endswith((".rse", ".eng")):
                        if e.file_size > MAX_XML_BYTES:
                            raise ValueError("Embedded motor data exceeds size limit.")
                        embedded.append((e.filename, z.read(e)))
                return xml, embedded
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise ValueError(f"Invalid ORK archive: {exc}") from exc
    if data.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                xml = g.read(MAX_XML_BYTES + 1)
            if len(xml) > MAX_XML_BYTES:
                raise ValueError("Compressed ORK XML exceeds the 16 MiB limit.")
            return xml, []
        except (OSError, EOFError) as exc:
            raise ValueError("Invalid gzip-compressed ORK document.") from exc
    return data, []


def import_ork(data: bytes, filename: str = "") -> Project:
    xml, embedded = _archive(data)
    root = _xml(xml)
    rocket = root if root.tag == "rocket" else root.find("rocket")
    if rocket is None:
        raise ValueError("The document contains no OpenRocket rocket element.")
    project = Project(name=_text(rocket, "name", PurePosixPath(filename).stem or "Imported rocket"),
                      components=[], configurations=[], materials=[])
    warnings = project.import_warnings
    unsupported: set[str] = set()
    project.metadata = {
        "source_format": "OpenRocket", "source_file": PurePosixPath(filename.replace("\\", "/")).name,
        "openrocket_version": root.attrib.get("version", "unknown"),
        "motor_assignments": [], "source_notes": _text(rocket, "comment"),
    }
    warnings.append("OpenRocket saved simulation results are not imported; all results are recalculated with the selected solver.")
    materials: dict[tuple[str, float, str], Material] = {}
    by_element: dict[int, Component] = {}
    stage_elements: list = []
    seen_ids: set[str] = set()

    def children(el):
        sub = el.find("subcomponents")
        return list(sub) if sub is not None else []

    source_parent = {id(child): el for el in rocket.iter() for child in children(el)}

    def radius_hint(el, default):
        """Use saved resolved auto radii; infer bare legacy auto from neighbours."""
        parent_el = source_parent.get(id(el))
        if parent_el is not None:
            siblings = children(parent_el)
            candidates = sorted(siblings, key=lambda other: abs(siblings.index(other) - siblings.index(el)))
            for other in candidates:
                if other is el:
                    continue
                for tag in ("radius", "aftradius", "foreradius", "outerradius"):
                    text = _text(other, tag)
                    value = _number_text(text, 0)
                    if value > 0:
                        return value
        return default

    def material(el, kind):
        m = el.find("material")
        if m is None:
            return None
        name = (m.text or "Imported material").strip()
        density = _number_text(m.attrib.get("density", "1850"))
        mat_type = m.attrib.get("type", "bulk")
        if density <= 0:
            raise ValueError(f"Material {name} density must be positive.")
        key = (name, density, mat_type)
        if key not in materials:
            # ORK stores density, not the Young modulus or tensile strength.
            # Those defaults must not masquerade as measured properties.
            bulk_density = density if mat_type == "bulk" else 1000.0
            materials[key] = Material(name=name, density=bulk_density,
                description=f"Imported ORK {mat_type} density {density:g}; stiffness and strength require user verification.")
            project.materials.append(materials[key])
            warnings.append(f"Material '{name}': ORK contains density but no verified elastic modulus/strength. Review structural properties.")
        return materials[key].id

    # Resolve assembly length first, because BOTTOM/MIDDLE positioning refers to it.
    lengths: dict[int, float] = {}

    def length(el):
        if id(el) in lengths:
            return lengths[id(el)]
        if el.tag in ASSEMBLIES:
            previous_end = 0.0
            extent = 0.0
            for child in children(el):
                child_len = length(child)
                pos = child.find("axialoffset")
                if pos is None:
                    pos = child.find("position")
                method = ((pos.attrib.get("method") or pos.attrib.get("type") or "top").lower()
                          if pos is not None else ("after" if child.tag in AXIAL_COMPONENTS else "top"))
                offset = _number_text(pos.text or "", 0) if pos is not None else 0
                start = previous_end + offset if method == "after" else offset
                if method in {"top", "front", "after", "absolute"}:
                    extent = max(extent, start + child_len)
                if child.tag in AXIAL_COMPONENTS:
                    previous_end = start + child_len
            result = max(0.0, extent)
        else:
            result = _number(el, "length", _number(el, "packedlength", 0))
            if el.tag == "railbutton":
                result = _number(el, "outerdiameter", result)
            if el.tag.endswith("finset") and el.tag != "tubefinset":
                result = _number(el, "rootchord", result)
                if el.tag == "freeformfinset":
                    points = el.findall("finpoints/point")
                    if points:
                        xs = [_number_text(p.attrib.get("x", "")) for p in points]
                        result = max(xs) - min(xs)
        lengths[id(el)] = _nonnegative(result, f"{el.tag} length")
        return result

    length(rocket)

    def walk(el, parent: Component | None, previous_end: float):
        kind = el.tag
        name = _text(el, "name", kind)
        if kind not in SUPPORTED_COMPONENTS:
            warnings.append(f"Unsupported component '{name}' ({kind}): retained for inspection but excluded from engineering calculations.")
            unsupported.add(f"component:{kind}")
        if kind in {"parallelstage", "podset", "tubefinset"}:
            unsupported.add(kind)
            warnings.append(f"{name}: {kind} geometry is shown, but its aerodynamic/interference physics is unsupported.")
        c_len = length(el)
        position = el.find("axialoffset")
        if position is None:
            position = el.find("position")
        method = (position.attrib.get("method", position.attrib.get("type", "top")).lower()
                  if position is not None else ("after" if kind in AXIAL_COMPONENTS and parent else "top"))
        offset = _number_text(position.text or "", 0.0) if position is not None else 0.0
        parent_x, parent_length = (parent.x, parent.length) if parent else (0.0, 0.0)
        if method in {"top", "front"}:
            x = parent_x + offset
        elif method in {"bottom", "end"}:
            x = parent_x + parent_length - c_len + offset
        elif method in {"middle", "center"}:
            x = parent_x + (parent_length - c_len) / 2 + offset
        elif method == "after":
            x = previous_end + offset
        elif method == "absolute":
            x = offset
        else:
            raise ValueError(f"Unknown axial position method '{method}' on {name}.")
        fallback_r = parent.radius if parent and parent.radius else radius_hint(el, 0.025)
        if kind in {"innertube", "tubecoupler", "centeringring", "bulkhead", "engineblock"} and parent:
            fallback_r = max(0.0, parent.radius - parent.thickness)
        radius = _number(el, "radius", _number(el, "outerradius", _number(el, "packedradius", fallback_r)))
        radius_end = None
        if kind in ASSEMBLIES:
            radius = 0.0
        if kind == "nosecone":
            radius = _number(el, "aftradius", fallback_r)
        elif kind == "transition":
            radius = _number(el, "foreradius", fallback_r)
            radius_end = _number(el, "aftradius", fallback_r)
        elif kind.endswith("finset") and kind != "tubefinset":
            radius = parent.radius if parent else 0.0
        elif kind == "railbutton":
            radius = _number(el, "outerdiameter", 0.01) / 2
        thickness_text = _text(el, "thickness", "0.002")
        filled = thickness_text == "filled"
        thickness = max(radius, 1e-6) if filled else _number_text(thickness_text)
        if thickness < 0:
            raise ValueError(f"{name} thickness cannot be negative.")
        zero_thickness = thickness == 0
        if zero_thickness:
            warnings.append(f"{name}: source has zero wall thickness; imported as a zero-mass surface/placeholder, unsuitable for solid FEA.")
        component_id = _text(el, "id") or f"ork-{len(project.components)}"
        if component_id in seen_ids:
            raise ValueError(f"Duplicate component ID: {component_id}")
        seen_ids.add(component_id)
        instance_count = _number(el, "instancecount", 1)
        if instance_count != int(instance_count):
            raise ValueError(f"{name}: instance count must be an integer.")
        metadata = {
            "source_kind": kind, "axial_method": method, "axial_offset": offset,
            "filled": filled, "finish": _text(el, "finish", "normal"),
            "zero_thickness": zero_thickness,
            "nose_shape": _text(el, "shape", "conical"),
            "shape_parameter": _number(el, "shapeparameter", 1.0 if _text(el, "shape") in {"ogive", "parabolic"} else 0.5 if _text(el, "shape") == "power" else 0.0),
            "shape_clipped": _boolean(el, "shapeclipped"),
            "mass_subcomponents_overridden": _boolean(el, "overridesubcomponentsmass", _boolean(el, "overridesubcomponents")),
            "cg_subcomponents_overridden": _boolean(el, "overridesubcomponentscg", _boolean(el, "overridesubcomponents")),
            "instance_count": int(instance_count),
        }
        for tag in ["aftshoulderradius", "aftshoulderlength", "aftshoulderthickness",
                    "foreshoulderradius", "foreshoulderlength", "foreshoulderthickness",
                    "tabheight", "tablength", "filletradius", "cant", "radialposition", "radialdirection",
                    "rotation", "angleoffset", "instanceseparation"]:
            if el.find(tag) is not None:
                metadata[tag] = _number(el, tag)
        if metadata["instance_count"] < 1 or metadata["instance_count"] > 128:
            raise ValueError(f"{name}: instance count exceeds supported bounds.")
        for tag in ("height", "baseheight", "flangeheight", "screwheight", "innerdiameter", "outerdiameter"):
            if kind == "railbutton" and el.find(tag) is not None:
                metadata[tag] = _number(el, tag)
        for tag in ("aftshouldercapped", "foreshouldercapped"):
            if el.find(tag) is not None:
                metadata[tag] = _boolean(el, tag)
        if el.find("innerradius") is not None:
            metadata["inner_radius"] = _number(el, "innerradius", max(0, radius - thickness))
            if metadata["inner_radius"] > radius:
                raise ValueError(f"{name}: inner radius exceeds outer radius.")
        elif kind == "bulkhead":
            metadata["inner_radius"] = 0.0
        if el.find("material") is not None:
            m = el.find("material")
            metadata["material_type"] = m.attrib.get("type", "bulk")
            metadata["material_density"] = _number_text(m.attrib.get("density", "1850"))
        if kind == "freeformfinset":
            metadata["fin_points"] = [[_number_text(p.attrib.get("x", "")), _number_text(p.attrib.get("y", ""))]
                                      for p in el.findall("finpoints/point")]
            if len(metadata["fin_points"]) < 3:
                raise ValueError(f"Freeform fin '{name}' requires at least three points.")
        if parent is not None:
            metadata["parent_radius"] = parent.radius
        if el.find("tabposition") is not None:
            tab = el.findall("tabposition")[-1]
            metadata["tab_position"] = _number_text(tab.text or "", 0)
            metadata["tab_position_method"] = tab.attrib.get("relativeto", "center")
        if kind in {"parachute", "streamer"}:
            metadata["diameter"] = _nonnegative(_number(el, "diameter"), f"{name} canopy diameter")
            metadata["cd"] = _nonnegative(_number(el, "cd", 0.8 if kind == "parachute" else 0.6), f"{name} recovery Cd")
            metadata["isdrogue"] = _boolean(el, "isdrogue")
            metadata["striplength"] = _nonnegative(_number(el, "striplength"), f"{name} streamer length")
            metadata["stripwidth"] = _nonnegative(_number(el, "stripwidth"), f"{name} streamer width")
        if el.find("overridecd") is not None:
            metadata["cd_override"] = _number(el, "overridecd")
            warnings.append(f"{name}: imported Cd override is recorded but solver-specific Cd calculation takes precedence.")
        if metadata.get("cant", 0) != 0:
            warnings.append(f"{name}: fin cant is shown geometrically; roll/6-DOF dynamics are unsupported.")
        if metadata.get("filletradius", 0) > 0:
            warnings.append(f"{name}: fin fillet geometry and its structural reinforcement are not modelled.")
        if _boolean(el, "isflipped"):
            metadata["isflipped"] = True
        cluster = _text(el, "clusterconfiguration", "single")
        if cluster not in {"single", "1", ""}:
            metadata["cluster_configuration"] = cluster
            unsupported.add("cluster")
            warnings.append(f"{name}: clustered motor configuration '{cluster}' needs a dedicated cluster flight solver.")
        if kind not in SUPPORTED_COMPONENTS:
            metadata["unsupported"] = True
        count_value = _number(el, "fincount", _number(el, "instancecount", 3)) if kind.endswith("finset") else 3
        if count_value != int(count_value):
            raise ValueError(f"{name}: fin count must be an integer.")
        fin_count = int(count_value)
        mass = _number(el, "overridemass") if el.find("overridemass") is not None else None
        if zero_thickness and mass is None:
            mass = 0.0
        if kind == "masscomponent" and mass is None:
            mass = _number(el, "mass")
        if kind == "shockcord" and mass is None:
            m = el.find("material")
            if m is not None and m.attrib.get("type") == "line":
                mass = _number(el, "cordlength") * _number_text(m.attrib.get("density", ""))
                if _text(el, "cordlength").strip() == "auto":
                    warnings.append(f"{name}: automatic shock cord length has no resolved value; enter its measured mass before analysis.")
        if kind in {"parachute", "streamer"} and mass is None:
            m = el.find("material")
            if m is not None and m.attrib.get("type") == "surface":
                area = (math.pi * (metadata["diameter"] / 2) ** 2 if kind == "parachute"
                        else metadata["striplength"] * metadata["stripwidth"])
                mass = area * _number_text(m.attrib.get("density", ""))
                line = el.find("linematerial")
                if line is not None:
                    mass += (_number(el, "linecount") * _number(el, "linelength", metadata["diameter"] * 1.5)
                             * _number_text(line.attrib.get("density", "")))
        if kind == "railbutton" and mass is None:
            base_h, flange_h = metadata.get("baseheight", 0), metadata.get("flangeheight", 0)
            neck_h = max(0, metadata.get("height", 0) - base_h - flange_h)
            neck_r = metadata.get("innerdiameter", 2 * radius) / 2
            volume = math.pi * (radius ** 2 * (base_h + flange_h) + neck_r ** 2 * neck_h)
            mat = el.find("material")
            if mat is not None:
                mass = volume * _number_text(mat.attrib.get("density", "1850"))
            if metadata.get("screwheight", 0):
                warnings.append(f"{name}: rail-button screw head is omitted; use a measured assembly mass for accurate mass properties.")
        cg = x + _number(el, "overridecg") if el.find("overridecg") is not None else None
        component = Component(
            id=component_id, name=name, kind=kind, parent_id=parent.id if parent else None,
            x=x, length=c_len, radius=_nonnegative(radius, f"{name} radius"),
            radius_end=radius_end, thickness=thickness, fin_count=fin_count,
            root_chord=_number(el, "rootchord", c_len if kind.endswith("finset") else 0.25),
            tip_chord=_number(el, "tipchord", 0.0 if kind == "ellipticalfinset" else 0.1),
            span=_number(el, "height", 0.12), sweep=_number(el, "sweeplength", 0),
            mass_override=mass, cg_override=cg, material_id=material(el, kind), metadata=metadata,
            external=kind in EXTERNAL_COMPONENTS,
            enabled=kind in SUPPORTED_COMPONENTS,
        )
        # Off-axis mass objects retain their true radial placement in the viewer.
        radial = metadata.get("radialposition", 0)
        angle = math.radians(metadata.get("radialdirection", 0))
        if radial:
            component.transform.translation = [0.0, radial * math.cos(angle), radial * math.sin(angle)]
        project.components.append(component)
        by_element[id(el)] = component
        if kind == "stage":
            stage_elements.append(el)
        cursor = x
        for child in children(el):
            child_comp = walk(child, component, cursor)
            if child.tag in AXIAL_COMPONENTS:
                cursor = child_comp.x + child_comp.length
        return component

    walk(rocket, None, 0.0)
    if len(stage_elements) > 1:
        unsupported.add("multistage")
        warnings.append("Multiple axial stages are imported for geometry/configuration comparison. Stage separation and sequential ignition are unsupported.")
    embedded_motors = []
    for motor_filename, payload in embedded:
        try:
            embedded_motors.extend(import_motor(payload, motor_filename))
        except ValueError as exc:
            warnings.append(f"Embedded motor '{motor_filename}' could not be loaded: {exc}")
    project.motors = embedded_motors
    cfg_elements = list(rocket.findall("motorconfiguration")) + list(rocket.findall("flightconfiguration"))
    cfg_ids = []
    cfg_sources = {}
    default_id = None
    for el in cfg_elements:
        cfg_id = el.attrib.get("configid", el.attrib.get("id", ""))
        if not cfg_id:
            continue
        if cfg_id in cfg_sources:
            raise ValueError(f"Duplicate flight configuration ID: {cfg_id}")
        cfg_ids.append(cfg_id)
        cfg_sources[cfg_id] = el
        if el.attrib.get("default", "false").lower() == "true":
            default_id = cfg_id
    for motor in rocket.findall(".//motormount/motor"):
        cfg_id = motor.attrib.get("configid", "default")
        if cfg_id not in cfg_ids:
            cfg_ids.append(cfg_id)
    if not cfg_ids:
        cfg_ids = ["default"]
    for cfg_id in cfg_ids:
        el = cfg_sources.get(cfg_id)
        cfg = FlightConfiguration(id=cfg_id, name=_text(el, "name", cfg_id) if el is not None else cfg_id,
                                  deployment="single")
        disabled_stage_ids = set()
        if el is not None:
            for stage in el.findall("stage"):
                if stage.attrib.get("active", "true").lower() == "false":
                    number = int(stage.attrib.get("number", "0"))
                    if 0 <= number < len(stage_elements):
                        disabled_stage_ids.add(by_element[id(stage_elements[number])].id)
        inactive = set(disabled_stage_ids)
        for c in project.components:
            if c.parent_id in inactive:
                inactive.add(c.id)
        cfg.active_component_ids = [c.id for c in project.components if c.id not in inactive]
        # Geometry/event limitations belong to the selected configuration. Keep
        # the overall union for import inspection, without blocking an unrelated
        # single-stage configuration because another one contains a cluster.
        active = [c for c in project.components if c.id not in inactive]
        cfg_unsupported = set()
        for c in active:
            if c.metadata.get("unsupported"):
                cfg_unsupported.add(f"component:{c.kind}")
            if c.kind in {"parallelstage", "podset", "tubefinset"}:
                cfg_unsupported.add(c.kind)
            if c.metadata.get("cluster_configuration"):
                cfg_unsupported.add("cluster")
        if sum(c.kind == "stage" for c in active) > 1:
            cfg_unsupported.add("multistage")
        assignments = []
        recovery = []
        for source_el in rocket.iter():
            c = by_element.get(id(source_el))
            if c is None or c.id in inactive:
                continue
            mount = source_el.find("motormount")
            if mount is not None:
                c.metadata["motor_overhang"] = _number(mount, "overhang")
                matching = [m for m in mount.findall("motor") if m.attrib.get("configid", "default") == cfg_id]
                for m in matching:
                    designation = _text(m, "designation")
                    assignment = {"config_id": cfg_id, "component_id": c.id, "designation": designation,
                                  "manufacturer": _text(m, "manufacturer"), "digest": _text(m, "digest"),
                                  "diameter": _number(m, "diameter", 0.054), "length": _number(m, "length", 0.25),
                                  "delay": _text(m, "delay", "none"), "overhang": _number(mount, "overhang")}
                    assignments.append(assignment)
                    project.metadata["motor_assignments"].append(assignment)
                    ignition = next((i for i in mount.findall("ignitionconfiguration") if i.attrib.get("configid") == cfg_id), mount)
                    event = _text(ignition, "ignitionevent", _text(mount, "ignitionevent", "launch"))
                    cfg.ignition_delay = _number(ignition, "ignitiondelay", _number(mount, "ignitiondelay"))
                    if event not in {"launch", "automatic"}:
                        unsupported.add("motor_ignition_event")
                        cfg_unsupported.add("motor_ignition_event")
                        warnings.append(f"Configuration {cfg.name}: ignition event '{event}' is unsupported.")
                    candidates = [motor for motor in embedded_motors if motor.name.casefold() == designation.casefold()
                                  and abs(motor.diameter - assignment["diameter"]) < 0.002]
                    if len(candidates) == 1:
                        cfg.motor_id = candidates[0].id
                    else:
                        warnings.append(f"Configuration {cfg.name}: import a matching .eng/.rse thrust curve for '{designation}' and assign it before launch simulation.")
                    cfg.motor_mount_id = c.id
                    cfg.motor_position = c.x + c.length - assignment["length"] / 2 + assignment["overhang"]
            if c.kind in {"parachute", "streamer"}:
                deploy = next((d for d in source_el.findall("deploymentconfiguration") if d.attrib.get("configid") == cfg_id), source_el)
                event = _text(deploy, "deployevent", _text(source_el, "deployevent", "apogee"))
                cd = c.metadata["cd"]
                area = math.pi * (c.metadata["diameter"] / 2) ** 2 if c.kind == "parachute" else c.metadata["striplength"] * c.metadata["stripwidth"]
                if event in {"never"}:
                    continue
                recovery.append({"component_id": c.id, "event": event, "cd_area": cd * area,
                                 "altitude": _nonnegative(_number(deploy, "deployaltitude", _number(source_el, "deployaltitude")), "Recovery deployment altitude"),
                                 "delay": _nonnegative(_number(deploy, "deploydelay", _number(source_el, "deploydelay")), "Recovery deployment delay")})
        if len(assignments) > 1:
            unsupported.add("cluster")
            cfg_unsupported.add("cluster")
            cfg.motor_id = None
            warnings.append(f"Configuration {cfg.name}: multiple motor assignments require cluster/staging support; launch simulation is blocked.")
        primary = [r for r in recovery if r["event"] in {"apogee", "ejection"}]
        altitude = [r for r in recovery if r["event"] == "altitude"]
        unsupported_recovery = [r for r in recovery if r["event"] not in {"apogee", "ejection", "altitude"}]
        if unsupported_recovery or len(primary) > 1 or len(altitude) > 1:
            unsupported.add("deployment_event")
            cfg_unsupported.add("deployment_event")
            warnings.append(f"Configuration {cfg.name}: recovery events cannot be represented by the single/dual apogee-altitude flight solver.")
        if primary:
            cfg.primary_deploy_event = "motor_ejection" if primary[0]["event"] == "ejection" else "apogee"
            cfg.apogee_delay = primary[0]["delay"]
            if cfg.primary_deploy_event == "motor_ejection":
                delay_text = assignments[0]["delay"].strip().lower() if len(assignments) == 1 else "none"
                if delay_text not in {"none", "plugged", "p", ""}:
                    cfg.motor_ejection_delay = _nonnegative(_number_text(delay_text), "Motor ejection delay")
                else:
                    warnings.append(f"Configuration {cfg.name}: motor-ejection recovery has no known ejection delay. Set the actual motor delay before flight simulation.")
        if primary and altitude:
            cfg.deployment = "dual"
            cfg.drogue_cd_area = max(primary[0]["cd_area"], 1e-9)
            cfg.main_cd_area = max(altitude[0]["cd_area"], 1e-9)
            cfg.main_deploy_altitude = max(0, altitude[0]["altitude"])
            if altitude[0]["delay"]:
                warnings.append(f"Configuration {cfg.name}: delayed altitude deployment is recorded but delay is not represented by this flight model.")
                unsupported.add("deployment_event")
                cfg_unsupported.add("deployment_event")
        elif primary:
            cfg.main_cd_area = max(primary[0]["cd_area"], 1e-9)
            cfg.drogue_cd_area = cfg.main_cd_area
        elif altitude:
            unsupported.add("deployment_event")
            cfg_unsupported.add("deployment_event")
            warnings.append(f"Configuration {cfg.name}: altitude-only recovery requires a dedicated event model; flight is blocked.")
        else:
            warnings.append(f"Configuration {cfg.name}: no supported active recovery device was found. Flight is blocked until recovery settings are explicitly defined.")
        cfg.recovery_defined = bool(primary and primary[0]["cd_area"] > 0
                                    and (not altitude or altitude[0]["cd_area"] > 0)
                                    and "deployment_event" not in cfg_unsupported)
        if primary and any(r["cd_area"] <= 0 for r in primary + altitude):
            warnings.append(f"Configuration {cfg.name}: recovery device has zero Cd×area. Enter usable recovery settings before flight simulation.")
        project.metadata.setdefault("recovery_assignments", {})[cfg_id] = recovery
        project.metadata.setdefault("unsupported_features_by_configuration", {})[cfg_id] = sorted(cfg_unsupported)
        project.configurations.append(cfg)
    project.active_configuration_id = default_id or project.configurations[0].id
    if not project.materials:
        project.materials = [Material(id="fiberglass")]
        warnings.append("No material definitions found. Assign verified component density and structural properties.")
    project.metadata["unsupported_features"] = sorted(unsupported)
    return project
