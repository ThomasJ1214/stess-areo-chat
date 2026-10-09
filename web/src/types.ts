export type Vec3 = [number, number, number];
export type Units = "metric" | "us";
export interface Transform {
  translation: number[];
  rotation: number[];
  scale: number;
}
export interface Material {
  id: string;
  name: string;
  density: number;
  youngs_modulus: number;
  poisson_ratio: number;
  yield_strength: number;
  description: string;
}
export interface Component {
  id: string;
  name: string;
  kind: string;
  parent_id: string | null;
  x: number;
  length: number;
  radius: number;
  radius_end: number | null;
  thickness: number;
  fin_count: number;
  root_chord: number;
  tip_chord: number;
  span: number;
  sweep: number;
  mass_override: number | null;
  cg_override: number | null;
  material_id: string | null;
  asset_id: string | null;
  transform: Transform;
  geometry_mode: "original" | "replacement";
  enabled: boolean;
  external: boolean;
  metadata: Record<string, unknown>;
}
export interface Configuration {
  id: string;
  name: string;
  active_component_ids: string[] | null;
  motor_id: string | null;
  motor_mount_id: string | null;
  motor_position: number | null;
  deployment: "single" | "dual";
  recovery_defined: boolean;
  primary_deploy_event: "apogee" | "motor_ejection";
  motor_ejection_delay: number | null;
  drogue_cd_area: number;
  main_cd_area: number;
  main_deploy_altitude: number;
  apogee_delay: number;
  ignition_delay: number;
}
export interface Motor {
  id: string;
  name: string;
  diameter: number;
  length: number;
  dry_mass: number;
  propellant_mass: number;
  curve: number[][];
  source: string;
  provenance?: Record<string, unknown>;
}
export interface Asset {
  id: string;
  name: string;
  format: string;
  vertices: number[][];
  faces: number[][];
  volume: number;
  watertight: boolean;
  source_file: string | null;
  warnings: string[];
}
export interface Project {
  schema_version: number;
  id: string;
  name: string;
  components: Component[];
  configurations: Configuration[];
  active_configuration_id: string | null;
  materials: Material[];
  motors: Motor[];
  assets: Asset[];
  unit_system: Units;
  import_warnings: string[];
  metadata: Record<string, unknown>;
  analysis_settings?: AnalysisSettings;
}
export interface AnalysisSettings {
  conditions: Conditions;
  cfd_options: Record<string, unknown>;
  fea_options: Record<string, unknown>;
  study_options: Record<string, unknown>;
  study_mode: "sweep" | "monte_carlo" | "comparison";
}
export interface Conditions {
  speed: number;
  mach: number | null;
  altitude: number;
  angle_of_attack: number;
  sideslip: number;
  wind_speed: number;
  wind_direction: number;
  turbulence: number;
  temperature_delta: number;
  rail_length: number;
  launch_angle: number;
  launch_azimuth: number;
  dt: number;
  max_time: number;
  seed: number;
}
export interface MeshResponse {
  components: {
    id: string;
    name: string;
    vertices: number[][];
    faces: number[][];
  }[];
}
export interface Job {
  id: string;
  status: string;
  progress: number;
  progress_basis?:
    | "completion_fraction"
    | "budget_usage"
    | "convergence_unknown"
    | "physical_time";
  message: string;
  elapsed_seconds: number;
  eta_seconds: number | null;
  eta_range_seconds?: [number, number] | null;
  eta_basis?: "physical_time_throughput" | "convergence_trend" | null;
  eta_confidence?: "measured" | "tentative" | null;
  telemetry?: {
    phase?: string;
    integration_steps?: number;
    physical_time_s?: number;
    target_physical_time_s?: number;
    flight_time_s?: number;
    freestream_mach?: number;
    altitude_msl_m?: number;
    residuals?: Record<string, number>;
    [key: string]: unknown;
  } | null;
  result: any;
  error: string | null;
}
export type Workspace =
  "design" | "aero" | "flight" | "structure" | "cfd" | "studies";
export interface Overlays {
  forces: boolean;
  markers: boolean;
  wireframe: boolean;
  original: boolean;
  deformation: boolean;
  pressure: boolean;
  flow: boolean;
  stress: boolean;
}
export const defaultConditions: Conditions = {
  speed: 100,
  mach: null,
  altitude: 0,
  angle_of_attack: 2,
  sideslip: 0,
  wind_speed: 5,
  wind_direction: 90,
  turbulence: 0,
  temperature_delta: 0,
  rail_length: 3,
  launch_angle: 5,
  launch_azimuth: 0,
  dt: 0.025,
  max_time: 300,
  seed: 42,
};
