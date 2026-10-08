"""Inspect solid FEA geometry and sizing without starting the native mesher.

The same sizing screen is used by the solver. It is a rough resource check,
not a promised element count or a bending-convergence demonstration.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .geometry import component_mesh
from .models import Component, Material, Project

_FINS = {"trapezoidfinset", "freeformfinset", "ellipticalfinset", "finset", "fin"}
_TUBES = {"bodytube", "innertube", "tube", "launchlug"}


def validate_solid_surface(project: Project, component: Component, surface) -> None:
    """Keep the solver and preflight's actual-material admission checks identical."""
    if component.geometry_mode == "replacement":
        asset = next((asset for asset in project.assets if asset.id == component.asset_id), None)
        if asset is not None and not asset.watertight:
            raise ValueError("Solid FEA requires a replacement asset with verified enclosed material volume. Repair open/overlapping CAD geometry or provide a valid unioned solid before meshing.")
    if (not len(surface.faces) or not surface.is_watertight or not surface.is_winding_consistent or
            not math.isfinite(float(surface.volume)) or surface.volume <= 0 or surface.metadata.get("volume_ambiguous")):
        raise ValueError("Solid FEA requires watertight outward-oriented solid geometry; open STL surfaces and zero-thickness shells are unsupported.")


def _count_estimate(volume: float, mesh_size: float, multiplier: float) -> int | None:
    # Ordinary sizes yield a useful integer. Extremely fine requests must not
    # overflow JSON or the resource check before they can be rejected.
    logarithm = math.log(volume) + math.log(multiplier) - 3 * math.log(mesh_size)
    if logarithm > math.log(1e15):
        return None
    return max(1, math.ceil(math.exp(logarithm)))


@dataclass(frozen=True)
class MeshSizing:
    mesh_size: float
    max_elements: int
    recommended_mesh_size: float
    maximum_bending_mesh_size: float | None
    minimum_budget_mesh_size: float
    volume: float

    @property
    def thickness_satisfied(self) -> bool:
        return self.maximum_bending_mesh_size is None or self.mesh_size <= self.maximum_bending_mesh_size * 1.001

    @property
    def budget_satisfied(self) -> bool:
        return self.mesh_size >= self.minimum_budget_mesh_size

    @property
    def recommendation_within_budget(self) -> bool:
        return self.recommended_mesh_size >= self.minimum_budget_mesh_size

    def errors(self) -> list[str]:
        result = []
        if not self.thickness_satisfied:
            result.append(
                f"Solid bending FEA requires mesh_size <= thickness/2 ({self.maximum_bending_mesh_size:g} m) for this procedural component; "
                "a coarse solid mesh would give misleading stiffness. Use the recommended mesh if it fits the element budget. "
                "Otherwise use the separate beam/fin estimates where supported, or import a smaller physical CAD part prepared outside the app. "
                "A shell solver and region-cutting tool are not included."
            )
        if not self.budget_satisfied:
            result.append(
                f"Estimated solid mesh is too large for the {self.max_elements:,}-element budget. "
                "Use a higher budget within the 300,000-element limit if the recommendation permits it, "
                "or import a smaller physical CAD part prepared outside the app. "
                "The separate beam/fin estimates support original tubes/fins; a shell solver and region-cutting tool are not included."
            )
        return result

    def require_admissible(self) -> None:
        issues = self.errors()
        if issues:
            raise ValueError(issues[0])


def mesh_sizing(surface, component: Component, options: dict) -> MeshSizing:
    """Return the unchanged thickness cap and volume-based solver budget screen."""
    scale = float(surface.extents.max())
    replacement = bool(component.asset_id and component.geometry_mode == "replacement")
    thickness_cap = None if replacement else component.thickness / 2
    recommendation = scale / 12
    if thickness_cap is not None:
        recommendation = min(recommendation, thickness_cap)
    if recommendation <= 0:
        raise ValueError("A positive procedural thickness is required for solid bending FEA. Supply measured thickness or use a verified imported solid.")
    try:
        size = float(options.get("mesh_size", recommendation))
        raw_budget = options.get("max_elements", 100000)
        budget = int(raw_budget)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("mesh_size must be positive; max_elements must be an integer between 20 and 300000.") from None
    if (not math.isfinite(size) or size <= 0 or isinstance(raw_budget, bool) or
            budget != raw_budget or not 20 <= budget <= 300000):
        raise ValueError("mesh_size must be positive; max_elements must be an integer between 20 and 300000.")
    volume = float(surface.volume)
    # Original guard: nominal six-tet/cube estimate may be up to 4x the budget
    # at this coarse screening stage. Gmsh's actual count remains a hard limit.
    minimum = (volume * 6 / (budget * 4)) ** (1 / 3)
    return MeshSizing(size, budget, recommendation, thickness_cap, minimum, volume)


def preflight(project: Project, component_id: str, options: dict | None = None) -> dict:
    """Report actionable mesh sizing and geometry limits; never mesh or mutate."""
    component = next((part for part in project.components if part.id == component_id), None)
    if component is None:
        raise ValueError("Select an existing component for FEA.")
    options = options or {}
    material = next((m for m in project.materials if m.id == component.material_id), None)
    material = material or (project.materials[0] if project.materials else Material())
    replacement = bool(component.asset_id and component.geometry_mode == "replacement")
    beam_supported = not replacement and (
        (component.kind in _TUBES and 0 < component.thickness <= component.radius) or
        (component.kind in _FINS and component.thickness > 0 and component.span > 0 and
         component.root_chord + component.tip_chord > 0)
    )
    result = {
        "project_id": project.id, "component_id": component.id, "component_name": component.name,
        "geometry_mode": component.geometry_mode, "geometry_valid": False, "can_run": False,
        "bounds_m": None, "material": material.model_dump(), "material_volume_m3": None,
        "procedural_thickness_m": None if replacement else component.thickness,
        "cad_thickness_unknown": replacement, "recommended_mesh_size_m": None,
        "maximum_bending_mesh_size_m": None, "minimum_budget_mesh_size_m": None,
        "requested_mesh_size_m": options.get("mesh_size"), "max_elements": options.get("max_elements", 100000),
        "estimated_elements": None, "budget_screening_elements": None,
        "recommended_estimated_elements": None, "recommended_budget_screening_elements": None,
        "recommended_within_budget": False, "recommended_within_maximum_budget": False,
        "recommended_max_elements": None, "beam_estimate_available": beam_supported,
        "recommended_clamp_type": "radial_root" if component.kind in _FINS and not replacement else "plane",
        "scope": "Actual triangle solid and mesh-sizing checks; native volume mesh, supports, loads and convergence still require validation.",
        "errors": [], "warnings": [
            "Sizing is a starting point, not a convergence study. Verify the physical support, load direction and material before solving.",
            "Element estimates use material volume only. Thin features, surface detail and disconnected solids can increase the actual count; Gmsh enforces the hard element limit.",
        ],
    }
    if replacement:
        result["warnings"].append("Imported CAD wall thickness is unknown. The scale/12 suggestion cannot guarantee adequate bending resolution; measure thin features and refine the mesh to demonstrate convergence.")
    try:
        surface = component_mesh(project, component)
        if len(surface.vertices):
            result["bounds_m"] = surface.bounds.tolist()
        validate_solid_surface(project, component, surface)
    except ValueError as exc:
        result["errors"].append(str(exc))
        return result
    sizing = mesh_sizing(surface, component, options)
    recommended_screen = _count_estimate(sizing.volume, sizing.recommended_mesh_size, 1.5)
    maximum_budget_minimum = (sizing.volume * 6 / (300000 * 4)) ** (1 / 3)
    maximum_budget_satisfied = sizing.recommended_mesh_size >= maximum_budget_minimum
    result.update({
        "geometry_valid": True, "can_run": sizing.thickness_satisfied and sizing.budget_satisfied,
        "material_volume_m3": sizing.volume,
        "recommended_mesh_size_m": sizing.recommended_mesh_size,
        "maximum_bending_mesh_size_m": sizing.maximum_bending_mesh_size,
        "minimum_budget_mesh_size_m": sizing.minimum_budget_mesh_size,
        "requested_mesh_size_m": sizing.mesh_size, "max_elements": sizing.max_elements,
        "estimated_elements": _count_estimate(sizing.volume, sizing.mesh_size, 6),
        "budget_screening_elements": _count_estimate(sizing.volume, sizing.mesh_size, 1.5),
        "recommended_estimated_elements": _count_estimate(sizing.volume, sizing.recommended_mesh_size, 6),
        "recommended_budget_screening_elements": recommended_screen,
        "recommended_within_budget": sizing.recommendation_within_budget,
        "recommended_within_maximum_budget": maximum_budget_satisfied,
        # Count rounding near an exact budget boundary must not disagree with
        # the solver's cube-root inequality or suggest an invalid 300001 cap.
        "recommended_max_elements": min(300000, max(sizing.max_elements, recommended_screen or 300000)) if maximum_budget_satisfied else None,
        "errors": sizing.errors(),
    })
    if not result["recommended_within_maximum_budget"]:
        result["warnings"].append("The thickness-resolving whole-part recommendation exceeds even the maximum element-budget screen. Do not coarsen past the thickness guard to obtain a stress image; use supported beam/fin estimates or import a smaller separately prepared physical part.")
    return result
