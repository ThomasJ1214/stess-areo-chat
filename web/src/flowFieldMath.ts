/** Snapshot streamlines through the solver's actual Cartesian velocity field.
 * Nothing outside the exported field or inside its nonflow mask is extrapolated.
 * Display coarsening is conservative: interpolation requires fluid support at
 * every corner that contributes a nonzero weight.
 */
export type FlowPoint = [number, number, number];
export interface FlowGrid {
  shape: FlowPoint;
  origin: FlowPoint;
  spacing: FlowPoint;
  upper: FlowPoint;
  velocity: Float64Array;
  fluid: Uint8Array;
  speedRange: [number, number];
}
export interface Streamline {
  points: FlowPoint[];
  speeds: number[];
  travelTimes: number[];
}
export interface CfdFlowSettings {
  density: number;
  length: number;
  colorBy: "speed" | "uniform";
  animate: boolean;
}
export const defaultCfdFlowSettings: CfdFlowSettings = {
  density: 160,
  length: 1.3,
  colorBy: "speed",
  animate: true,
};

const vector = (value: unknown): value is FlowPoint =>
  Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
const magnitude = (v: FlowPoint) => Math.hypot(...v);
const add = (a: FlowPoint, b: FlowPoint, scale: number): FlowPoint =>
  a.map((value, i) => value + b[i] * scale) as FlowPoint;
const index = (grid: FlowGrid, i: number, j: number, k: number) =>
  (i * grid.shape[1] + j) * grid.shape[2] + k;

export function readFlowGrid(raw: any): FlowGrid | null {
  if (
    !raw || !vector(raw.shape) || !vector(raw.origin_m) ||
    !vector(raw.spacing_m) || raw.shape.some((n: number) => n < 2 || !Number.isInteger(n)) ||
    raw.spacing_m.some((n: number) => n <= 0)
  ) return null;
  const count = raw.shape.reduce((total: number, n: number) => total * n, 1);
  if (count > 2_000_000 || !Array.isArray(raw.fluid_mask) || raw.fluid_mask.length !== count ||
      !Array.isArray(raw.velocity_m_s) || raw.velocity_m_s.length !== count * 3) return null;
  const fluid = new Uint8Array(count);
  const velocity = new Float64Array(count * 3);
  let minimum = Infinity;
  let maximum = -Infinity;
  for (let n = 0; n < count; n++) {
    if (raw.fluid_mask[n] !== 0 && raw.fluid_mask[n] !== 1) return null;
    fluid[n] = raw.fluid_mask[n];
    for (let axis = 0; axis < 3; axis++) {
      const v = raw.velocity_m_s[n * 3 + axis];
      if (!Number.isFinite(v)) return null;
      velocity[n * 3 + axis] = v;
    }
    if (fluid[n]) {
      const speed = Math.hypot(velocity[n * 3], velocity[n * 3 + 1], velocity[n * 3 + 2]);
      minimum = Math.min(minimum, speed);
      maximum = Math.max(maximum, speed);
    }
  }
  if (!Number.isFinite(minimum)) return null;
  const origin = [...raw.origin_m] as FlowPoint;
  const spacing = [...raw.spacing_m] as FlowPoint;
  return {
    shape: [...raw.shape] as FlowPoint, origin, spacing,
    upper: origin.map((v, axis) => v + spacing[axis] * (raw.shape[axis] - 1)) as FlowPoint,
    fluid, velocity, speedRange: [minimum, maximum],
  };
}

export function sampleVelocity(grid: FlowGrid, point: FlowPoint): FlowPoint | null {
  const base: number[] = [];
  const fraction: number[] = [];
  for (let axis = 0; axis < 3; axis++) {
    const coordinate = (point[axis] - grid.origin[axis]) / grid.spacing[axis];
    if (coordinate < -1e-9 || coordinate > grid.shape[axis] - 1 + 1e-9) return null;
    const bounded = Math.max(0, Math.min(grid.shape[axis] - 1, coordinate));
    base[axis] = Math.min(Math.floor(bounded), grid.shape[axis] - 2);
    fraction[axis] = bounded - base[axis];
  }
  const result: FlowPoint = [0, 0, 0];
  for (let di = 0; di <= 1; di++) for (let dj = 0; dj <= 1; dj++) for (let dk = 0; dk <= 1; dk++) {
    const weight = (di ? fraction[0] : 1 - fraction[0]) *
      (dj ? fraction[1] : 1 - fraction[1]) * (dk ? fraction[2] : 1 - fraction[2]);
    if (weight <= 1e-14) continue;
    const n = index(grid, base[0] + di, base[1] + dj, base[2] + dk);
    if (!grid.fluid[n]) return null;
    for (let axis = 0; axis < 3; axis++) result[axis] += grid.velocity[n * 3 + axis] * weight;
  }
  return result;
}

function direction(grid: FlowGrid, point: FlowPoint, sign: number): FlowPoint | null {
  const velocity = sampleVelocity(grid, point);
  if (!velocity) return null;
  const speed = magnitude(velocity);
  if (speed <= Math.max(1e-8, grid.speedRange[1] * 1e-9)) return null;
  return velocity.map((v) => sign * v / speed) as FlowPoint;
}

function edgeDistance(grid: FlowGrid, point: FlowPoint, dir: FlowPoint) {
  let distance = Infinity;
  for (let axis = 0; axis < 3; axis++) {
    if (dir[axis] > 1e-14) distance = Math.min(distance, (grid.upper[axis] - point[axis]) / dir[axis]);
    if (dir[axis] < -1e-14) distance = Math.min(distance, (grid.origin[axis] - point[axis]) / dir[axis]);
  }
  return Math.max(0, distance);
}

function safeSegment(grid: FlowGrid, start: FlowPoint, end: FlowPoint) {
  const subdivisions = Math.max(2, Math.ceil(Math.max(...end.map((v, axis) =>
    Math.abs(v - start[axis]) / grid.spacing[axis])) * 4));
  for (let i = 1; i <= subdivisions; i++) {
    const point = start.map((v, axis) => v + (end[axis] - v) * i / subdivisions) as FlowPoint;
    if (!sampleVelocity(grid, point)) return false;
  }
  return true;
}

function integrateDirection(grid: FlowGrid, seed: FlowPoint, sign: number, maximumLength: number) {
  const points: FlowPoint[] = [seed];
  let length = 0;
  // The cap bounds rendering work for looping fields or extremely anisotropic grids.
  for (let step = 0; step < 4096 && length < maximumLength; step++) {
    const previous = points[points.length - 1];
    const k1 = direction(grid, previous, sign);
    if (!k1) break;
    const cellStep = 0.45 / Math.max(...k1.map((v, axis) => Math.abs(v) / grid.spacing[axis]));
    const edge = edgeDistance(grid, previous, k1);
    const h = Math.min(cellStep, maximumLength - length, edge);
    if (h < Math.min(...grid.spacing) * 1e-8) break;
    let next: FlowPoint;
    if (h === edge) {
      next = add(previous, k1, h);
    } else {
      const k2 = direction(grid, add(previous, k1, h / 2), sign);
      const k3 = k2 && direction(grid, add(previous, k2, h / 2), sign);
      const k4 = k3 && direction(grid, add(previous, k3, h), sign);
      if (!k2 || !k3 || !k4) break;
      next = previous.map((v, axis) => v + h * (k1[axis] + 2 * k2[axis] + 2 * k3[axis] + k4[axis]) / 6) as FlowPoint;
    }
    if (!safeSegment(grid, previous, next)) break;
    const distance = magnitude(next.map((v, axis) => v - previous[axis]) as FlowPoint);
    if (distance <= 1e-12) break;
    // RK4 parameterizes the curve by arclength. Summing chords instead would
    // overshoot the requested extent on curved paths.
    length += h;
    points.push(next);
  }
  return points;
}

export function integrateStreamline(grid: FlowGrid, seed: FlowPoint, maximumLength?: number): Streamline | null {
  if (!sampleVelocity(grid, seed)) return null;
  const domainLength = magnitude(grid.upper.map((v, axis) => v - grid.origin[axis]) as FlowPoint);
  const limit = maximumLength ?? domainLength * 1.3;
  if (!Number.isFinite(limit) || limit <= 0) return null;
  const backward = integrateDirection(grid, seed, -1, limit).reverse();
  const forward = integrateDirection(grid, seed, 1, limit);
  const points = [...backward.slice(0, -1), ...forward];
  if (points.length < 2) return null;
  const speeds = points.map((point) => magnitude(sampleVelocity(grid, point)!));
  const travelTimes = [0];
  for (let i = 1; i < points.length; i++) {
    const distance = magnitude(points[i].map((v, axis) => v - points[i - 1][axis]) as FlowPoint);
    travelTimes.push(travelTimes[i - 1] + distance / Math.max((speeds[i] + speeds[i - 1]) / 2, 1e-12));
  }
  return { points, speeds, travelTimes };
}

const radicalInverse = (number: number, base: number) => {
  let result = 0;
  let factor = 1 / base;
  while (number > 0) {
    result += (number % base) * factor;
    number = Math.floor(number / base);
    factor /= base;
  }
  return result;
};

export function generateStreamlines(grid: FlowGrid, freestream: FlowPoint, settings: CfdFlowSettings): Streamline[] {
  if (!vector(freestream) || magnitude(freestream) <= 1e-8) return [];
  const axis = freestream.reduce((best, v, i) => Math.abs(v) > Math.abs(freestream[best]) ? i : best, 0);
  const transverse = [0, 1, 2].filter((i) => i !== axis);
  const count = Math.round(Math.max(16, Math.min(512, settings.density)));
  const domainLength = magnitude(grid.upper.map((v, i) => v - grid.origin[i]) as FlowPoint);
  const length = domainLength * Math.max(0.1, Math.min(3, settings.length));
  const paths: Streamline[] = [];
  for (let i = 1; i <= count * 3 && paths.length < count; i++) {
    const point = [...grid.origin] as FlowPoint;
    point[axis] = freestream[axis] >= 0 ? grid.origin[axis] + grid.spacing[axis] * 0.03 : grid.upper[axis] - grid.spacing[axis] * 0.03;
    for (let j = 0; j < 2; j++) {
      const a = transverse[j];
      const fraction = 0.015 + radicalInverse(i, j === 0 ? 2 : 3) * 0.97;
      point[a] += (grid.upper[a] - grid.origin[a]) * fraction;
    }
    const path = integrateStreamline(grid, point, length);
    if (path) paths.push(path);
  }
  return paths;
}

/** Position of a direction tracer on a frozen snapshot, in physical seconds.
 * This is deliberately not an unsteady pathline reconstruction.
 */
export function streamlinePosition(path: Streamline, time: number): FlowPoint {
  const duration = path.travelTimes[path.travelTimes.length - 1];
  const bounded = duration > 0 ? ((time % duration) + duration) % duration : 0;
  let low = 0;
  let high = path.travelTimes.length - 1;
  while (high - low > 1) {
    const middle = Math.floor((low + high) / 2);
    if (path.travelTimes[middle] <= bounded) low = middle;
    else high = middle;
  }
  const fraction = (bounded - path.travelTimes[low]) / Math.max(path.travelTimes[high] - path.travelTimes[low], 1e-12);
  return path.points[low].map((v, axis) => v + (path.points[high][axis] - v) * fraction) as FlowPoint;
}
