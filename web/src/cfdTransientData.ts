/** Reconstruct a single saved, accepted CFD state. Never interpolate in time. */
export interface CfdTransientFrame {
  time_s: number;
  step: number;
  flow_velocity_m_s: number[];
  sample_pressure_pa: number[];
  sample_velocity_m_s: number[][];
  sample_density_kg_m3: number[];
  sample_mach: number[];
  surface_pressure_pa: number[];
  force_n: number[];
  moment_about_origin_nm: number[];
  pressure_drag_n: number;
  freestream_pressure_pa: number;
  dynamic_pressure_pa: number;
  freestream_velocity_m_s: number[];
  freestream_mach: number;
  pressure_coefficient_defined: boolean;
  altitude_msl_m: number | null;
  flight_time_s: number | null;
}

const finiteVector = (value: unknown): value is number[] =>
  Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
const scalarField = (value: unknown, count: number): value is number[] =>
  Array.isArray(value) &&
  value.length === count &&
  value.every(Number.isFinite);
const vectorField = (value: unknown, count: number): value is number[][] =>
  Array.isArray(value) && value.length === count && value.every(finiteVector);

export function cfdTransientFrames(data: any): CfdTransientFrame[] {
  const frames = data?.transient?.frames;
  if (!Array.isArray(frames) || !frames.length || frames.length > 32) return [];
  let previous = -Infinity;
  for (const frame of frames) {
    if (
      !Number.isFinite(frame?.time_s) ||
      frame.time_s < 0 ||
      frame.time_s <= previous
    )
      return [];
    previous = frame.time_s;
  }
  return frames;
}

export function boundedCfdFrameIndex(data: any, index: number): number {
  const count = cfdTransientFrames(data).length;
  return Math.max(
    0,
    Math.min(count - 1, Number.isFinite(index) ? Math.round(index) : 0),
  );
}

/** Select the last saved state at or before a playback clock, without blending. */
export function cfdFrameAtTime(
  frames: readonly CfdTransientFrame[],
  time: number,
): number {
  if (!frames.length || !Number.isFinite(time)) return 0;
  let low = 0;
  let high = frames.length;
  while (low + 1 < high) {
    const middle = Math.floor((low + high) / 2);
    if (frames[middle].time_s <= time) low = middle;
    else high = middle;
  }
  return low;
}

const views = new WeakMap<object, Map<number, any>>();

/** Steady results retain identity. Malformed transient fields return no view. */
export function selectCfdFrame(data: any, requestedIndex: number): any | null {
  if (!data?.transient) return data;
  const frames = cfdTransientFrames(data);
  const topology = data.transient.topology;
  if (!frames.length || !topology || !topology.flow_grid) return null;
  const index = boundedCfdFrameIndex(data, requestedIndex);
  const existing = views.get(data)?.get(index);
  if (existing) return existing;
  const frame = frames[index];
  const positions = topology.sample_positions_m;
  const surfacePositions = topology.surface_positions_m;
  const normals = topology.surface_normals;
  const shape = topology.flow_grid.shape;
  if (!finiteVector(shape) || shape.some((n) => !Number.isInteger(n) || n < 2))
    return null;
  const nodes = shape.reduce((total, n) => total * n, 1);
  if (
    nodes > 12000 ||
    !Array.isArray(positions) ||
    !positions.every(finiteVector) ||
    !Array.isArray(surfacePositions) ||
    !surfacePositions.every(finiteVector) ||
    !vectorField(normals, surfacePositions.length) ||
    !scalarField(frame.flow_velocity_m_s, nodes * 3) ||
    !scalarField(frame.sample_pressure_pa, positions.length) ||
    !vectorField(frame.sample_velocity_m_s, positions.length) ||
    !scalarField(frame.sample_density_kg_m3, positions.length) ||
    !scalarField(frame.sample_mach, positions.length) ||
    !scalarField(frame.surface_pressure_pa, surfacePositions.length) ||
    !finiteVector(frame.force_n) ||
    !finiteVector(frame.moment_about_origin_nm) ||
    !finiteVector(frame.freestream_velocity_m_s) ||
    ![
      frame.pressure_drag_n,
      frame.freestream_pressure_pa,
      frame.dynamic_pressure_pa,
      frame.freestream_mach,
      frame.step,
    ].every(Number.isFinite)
  )
    return null;
  const samples = positions.map((position: number[], i: number) => ({
    position,
    pressure_pa: frame.sample_pressure_pa[i],
    gauge_pressure_pa:
      frame.sample_pressure_pa[i] - frame.freestream_pressure_pa,
    velocity: frame.sample_velocity_m_s[i],
    density_kg_m3: frame.sample_density_kg_m3[i],
    mach: frame.sample_mach[i],
  }));
  const coefficientDefined =
    frame.pressure_coefficient_defined && frame.dynamic_pressure_pa > 0;
  const surface = surfacePositions.map((position: number[], i: number) => ({
    position,
    normal: normals[i],
    pressure_pa: frame.surface_pressure_pa[i],
    gauge_pressure_pa:
      frame.surface_pressure_pa[i] - frame.freestream_pressure_pa,
    pressure_coefficient: coefficientDefined
      ? (frame.surface_pressure_pa[i] - frame.freestream_pressure_pa) /
        frame.dynamic_pressure_pa
      : null,
  }));
  const selected = {
    ...data,
    samples,
    surface,
    flow_grid: { ...topology.flow_grid, velocity_m_s: frame.flow_velocity_m_s },
    summary: {
      ...data.summary,
      mode: "transient",
      converged: false,
      pressure_force_steady: false,
      cp_m: null,
      cp_fit_moment_residual_nm: null,
      physical_time_s: frame.time_s,
      steps: frame.step,
      force_n: frame.force_n,
      moment_about_origin_nm: frame.moment_about_origin_nm,
      pressure_drag_n: frame.pressure_drag_n,
      freestream_pressure_pa: frame.freestream_pressure_pa,
      dynamic_pressure_pa: frame.dynamic_pressure_pa,
      freestream_velocity_m_s: frame.freestream_velocity_m_s,
      freestream_mach: frame.freestream_mach,
      altitude_msl_m: frame.altitude_msl_m,
      flight_time_s: frame.flight_time_s,
      min_pressure_pa: frame.sample_pressure_pa.reduce(
        (a, b) => Math.min(a, b),
        Infinity,
      ),
      max_mach: frame.sample_mach.reduce((a, b) => Math.max(a, b), -Infinity),
      flow_visualization_nodes: nodes,
      flow_visualization_stride: topology.flow_grid.stride,
      pressure_output_kind:
        "Saved transient instantaneous pressure resultant; not a steady drag prediction",
    },
    transient_snapshot: {
      index,
      count: frames.length,
      time_s: frame.time_s,
      flight_time_s: frame.flight_time_s,
      step: frame.step,
      final: index === frames.length - 1,
      run_completed: data.transient.completed === true,
    },
  };
  if (!views.has(data)) views.set(data, new Map());
  views.get(data)!.set(index, selected);
  return selected;
}
