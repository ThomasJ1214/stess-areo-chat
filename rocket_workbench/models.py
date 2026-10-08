"""Serializable project model. All stored quantities use SI units; angles are degrees."""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


def uid() -> str:
    return uuid4().hex


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class Material(Model):
    id: str = Field(default_factory=uid)
    name: str = "Fiberglass"
    density: float = Field(default=1850, gt=0)
    youngs_modulus: float = Field(default=25e9, gt=0)
    poisson_ratio: float = Field(default=0.25, gt=-1, lt=0.5)
    yield_strength: float = Field(default=200e6, gt=0)
    # Isotropic surrogate properties must be identified as such for composites.
    description: str = "Isotropic engineering surrogate; verify laminate properties."


class Transform(Model):
    translation: list[float] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    rotation: list[float] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    scale: float = Field(default=1.0, gt=0)


class GeometryAsset(Model):
    id: str = Field(default_factory=uid)
    name: str
    format: str
    vertices: list[list[float]] = Field(default_factory=list)
    faces: list[list[int]] = Field(default_factory=list)
    volume: float = Field(default=0, ge=0)
    watertight: bool = False
    source_file: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mesh(self):
        if any(len(vertex) != 3 for vertex in self.vertices):
            raise ValueError("Geometry vertices must each contain three coordinates")
        if any(len(face) != 3 or any(index < 0 or index >= len(self.vertices) for index in face) for face in self.faces):
            raise ValueError("Geometry faces must contain three valid vertex indices")
        if self.faces and not self.vertices:
            raise ValueError("Geometry faces require vertices")
        return self


class Component(Model):
    id: str = Field(default_factory=uid)
    name: str = "Component"
    kind: str = "bodytube"
    parent_id: str | None = None
    x: float = 0
    length: float = Field(default=0.1, ge=0)
    radius: float = Field(default=0.05, ge=0)
    radius_end: float | None = Field(default=None, ge=0)
    thickness: float = Field(default=0.002, ge=0)
    fin_count: int = Field(default=3, ge=1, le=16)
    root_chord: float = Field(default=0.25, ge=0)
    tip_chord: float = Field(default=0.10, ge=0)
    span: float = Field(default=0.12, ge=0)
    sweep: float = 0.1
    mass_override: float | None = Field(default=None, ge=0)
    cg_override: float | None = None
    material_id: str | None = None
    asset_id: str | None = None
    transform: Transform = Field(default_factory=Transform)
    geometry_mode: Literal["original", "replacement"] = "original"
    enabled: bool = True
    external: bool = True
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Motor(Model):
    id: str = Field(default_factory=uid)
    name: str = "Motor"
    diameter: float = Field(default=0.054, gt=0)
    length: float = Field(default=0.25, gt=0)
    dry_mass: float = Field(default=0.3, ge=0)
    propellant_mass: float = Field(default=0.5, ge=0)
    curve: list[list[float]] = Field(default_factory=list)
    source: str = "User supplied"
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_curve(self):
        if self.curve:
            if len(self.curve) < 2 or any(len(point) != 2 or point[0] < 0 or point[1] < 0 for point in self.curve):
                raise ValueError("A motor curve requires at least two nonnegative time/thrust pairs")
            if any(b[0] <= a[0] for a, b in zip(self.curve, self.curve[1:])):
                raise ValueError("Motor curve times must increase strictly")
        return self


class FlightConfiguration(Model):
    id: str = Field(default_factory=uid)
    name: str = "Default"
    active_component_ids: list[str] | None = None
    motor_id: str | None = None
    motor_mount_id: str | None = None
    motor_position: float | None = None
    deployment: Literal["single", "dual"] = "dual"
    recovery_defined: bool = True
    drogue_cd_area: float = Field(default=0.35, gt=0)
    main_cd_area: float = Field(default=3.5, gt=0)
    main_deploy_altitude: float = Field(default=250, ge=0)
    apogee_delay: float = Field(default=0.5, ge=0)
    ignition_delay: float = Field(default=0, ge=0)
    primary_deploy_event: Literal["apogee", "motor_ejection"] = "apogee"
    motor_ejection_delay: float | None = Field(default=None, ge=0)


class Conditions(Model):
    speed: float = Field(default=100, ge=0, le=1000)
    mach: float | None = Field(default=None, ge=0, le=2)
    altitude: float = Field(default=0, ge=-500, le=50000)
    angle_of_attack: float = Field(default=2, ge=-45, le=45)
    sideslip: float = Field(default=0, ge=-45, le=45)
    wind_speed: float = Field(default=5, ge=0, le=150)
    wind_direction: float = Field(default=90, ge=0, le=360)
    turbulence: float = Field(default=0, ge=0, le=1)
    temperature_delta: float = Field(default=0, ge=-80, le=80)
    rail_length: float = Field(default=3, gt=0)
    launch_angle: float = Field(default=5, ge=0, le=30)
    launch_azimuth: float = Field(default=0, ge=0, le=360)
    dt: float = Field(default=0.025, ge=0.001, le=0.2)
    max_time: float = Field(default=300, gt=0, le=1200)
    seed: int = Field(default=42, ge=0)


class AnalysisSettings(Model):
    """Portable solver inputs; optional option dictionaries preserve solver extensibility."""
    conditions: Conditions = Field(default_factory=Conditions)
    cfd_options: dict[str, JsonValue] = Field(default_factory=dict)
    fea_options: dict[str, JsonValue] = Field(default_factory=dict)
    study_options: dict[str, JsonValue] = Field(default_factory=dict)
    study_mode: Literal["sweep", "monte_carlo", "comparison"] = "sweep"


class Project(Model):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=uid)
    name: str = "Untitled rocket"
    components: list[Component] = Field(default_factory=list)
    configurations: list[FlightConfiguration] = Field(default_factory=lambda: [FlightConfiguration()])
    active_configuration_id: str | None = None
    materials: list[Material] = Field(default_factory=lambda: [Material(id="fiberglass")])
    motors: list[Motor] = Field(default_factory=list)
    assets: list[GeometryAsset] = Field(default_factory=list)
    unit_system: Literal["metric", "us"] = "metric"
    analysis_settings: AnalysisSettings = Field(default_factory=AnalysisSettings)
    import_warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_references(self):
        if self.active_configuration_id is None and self.configurations:
            object.__setattr__(self, "active_configuration_id", self.configurations[0].id)
        return self




def active_components(project: Project, configuration_id: str | None = None) -> list[Component]:
    target = configuration_id or project.active_configuration_id
    cfg = next((c for c in project.configurations if c.id == target), None)
    if cfg is None:
        raise ValueError("Select an existing flight configuration.")
    by_id = {c.id: c for c in project.components}
    selected = None if cfg.active_component_ids is None else set(cfg.active_component_ids)
    included: dict[str, bool] = {}
    visiting: set[str] = set()

    def is_included(component: Component) -> bool:
        if component.id in included:
            return included[component.id]
        if component.id in visiting:
            raise ValueError("Component parent links contain a cycle.")
        visiting.add(component.id)
        active = component.enabled and (selected is None or component.id in selected)
        if active and component.parent_id is not None:
            parent = by_id.get(component.parent_id)
            if parent is None:
                raise ValueError(f"Component {component.name} has a missing parent.")
            active = is_included(parent)
        visiting.remove(component.id)
        included[component.id] = active
        return active

    # Enable/configuration selection applies to an entire subtree. A still-enabled
    # payload inside a disabled stage must not survive as a detached mass/mesh.
    return [component for component in project.components if is_included(component)]


def configuration(project: Project, configuration_id: str | None = None) -> FlightConfiguration:
    target = configuration_id or project.active_configuration_id
    cfg = next((c for c in project.configurations if c.id == target), None)
    if cfg is None:
        raise ValueError("Select an existing flight configuration.")
    return cfg


def validate_project_references(value: Project) -> None:
    """Validate complete project boundaries, without constraining incremental imports."""
    if not value.id.strip():
        raise ValueError("Project identifier must be nonempty.")
    for collection in [value.components, value.configurations, value.materials, value.motors, value.assets]:
        identities = [item.id for item in collection]
        if any(not identity.strip() for identity in identities) or len(set(identities)) != len(identities):
            raise ValueError("Project identifiers must be nonempty and unique within each collection.")
    components = {item.id: item for item in value.components}
    materials, motors, assets = ({item.id for item in collection} for collection in [value.materials, value.motors, value.assets])
    if not value.configurations or value.active_configuration_id not in {cfg.id for cfg in value.configurations}:
        raise ValueError("Project must contain the selected flight configuration.")
    for item in value.components:
        if item.parent_id is not None and item.parent_id not in components:
            raise ValueError(f"{item.name}: parent component does not exist.")
        if item.material_id is not None and item.material_id not in materials:
            raise ValueError(f"{item.name}: material does not exist.")
        if item.asset_id is not None and item.asset_id not in assets:
            raise ValueError(f"{item.name}: imported geometry asset does not exist.")
        if item.geometry_mode == "replacement" and not item.asset_id:
            raise ValueError(f"{item.name}: replacement geometry requires an imported asset.")
    # Check all immediate references first: an invalid grandparent must give a
    # useful validation error rather than a KeyError dependent on component order.
    checked = set()
    for item in value.components:
        seen, parent = set(), item.id
        while parent and parent not in checked:
            if parent in seen:
                raise ValueError("Component hierarchy contains a cycle.")
            seen.add(parent)
            parent = components[parent].parent_id
        checked.update(seen)
    for cfg in value.configurations:
        if cfg.motor_id is not None and cfg.motor_id not in motors:
            raise ValueError(f"{cfg.name}: assigned motor does not exist.")
        if cfg.motor_mount_id is not None and cfg.motor_mount_id not in components:
            raise ValueError(f"{cfg.name}: motor mount does not exist.")
        if cfg.active_component_ids is not None:
            if any(identity not in components for identity in cfg.active_component_ids):
                raise ValueError(f"{cfg.name}: enabled component does not exist.")
            if len(set(cfg.active_component_ids)) != len(cfg.active_component_ids):
                raise ValueError(f"{cfg.name}: enabled component identifiers must be unique.")
