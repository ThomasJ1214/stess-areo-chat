import * as THREE from "three";
import type { FlightSample } from "./launchScene";

/** Interpolation is exclusively a display operation. The numerical inspector,
 * exports, events, loads and CFD continue to use stored solver samples. */
export interface FlightPresentationSample extends FlightSample {
  presentation_interpolated: boolean;
  actual_sample_index: number;
  actual_sample_time: number;
  [key: string]: unknown;
}

const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const vector = (value: unknown, length = 3): value is number[] =>
  Array.isArray(value) && value.length === length && value.every(finite);
const blend = (a: number, b: number, t: number) => a + (b - a) * t;

/** Find the enclosing actual timestamps in O(log N). Duplicate event timestamps
 * use the later stored state, making deployment and burnout deterministic. */
export function interpolateFlightSample(
  rows: FlightSample[],
  time: number,
): FlightPresentationSample | null {
  if (!rows.length) return null;
  const firstTime = finite(rows[0].time) ? rows[0].time : 0;
  const lastTime = finite(rows[rows.length - 1].time)
    ? rows[rows.length - 1].time!
    : firstTime;
  const selectedTime = finite(time)
    ? Math.max(firstTime, Math.min(lastTime, time))
    : firstTime;
  let lo = 0,
    hi = rows.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((rows[mid].time ?? firstTime) <= selectedTime) lo = mid + 1;
    else hi = mid;
  }
  const leftIndex = Math.max(0, lo - 1);
  const rightIndex = Math.min(rows.length - 1, lo);
  const left = rows[leftIndex],
    right = rows[rightIndex];
  const start = left.time ?? firstTime,
    end = right.time ?? start;
  const amount = end > start ? (selectedTime - start) / (end - start) : 0;
  const actualIndex = amount <= 0.5 ? leftIndex : rightIndex;
  const actual = rows[actualIndex];
  const result: FlightPresentationSample = {
    ...actual,
    time: selectedTime,
    presentation_interpolated: amount > 0 && amount < 1,
    actual_sample_index: actualIndex,
    actual_sample_time: actual.time ?? firstTime,
  };
  // These quantities affect visual placement, never interpolated force/stress
  // or engineering values. CG only shifts the CAD origin during propellant loss.
  for (const key of [
    "east",
    "north",
    "altitude",
    "cg",
    "inflation_fraction",
    "recovery_inflation_fraction",
  ] as const) {
    if (finite(left[key]) && finite(right[key]))
      result[key] = blend(left[key], right[key], amount);
  }
  for (const key of [
    "velocity_vector",
    "wind_vector",
    "body_axis_world",
    "cg_geometry_m",
  ] as const) {
    if (vector(left[key]) && vector(right[key]))
      result[key] = left[key].map((n, i) => blend(n, right[key]![i], amount));
  }
  if (
    vector(left.body_quaternion_world, 4) &&
    vector(right.body_quaternion_world, 4)
  ) {
    const a = new THREE.Quaternion(
      ...(left.body_quaternion_world.slice(1) as [number, number, number]),
      left.body_quaternion_world[0],
    );
    const b = new THREE.Quaternion(
      ...(right.body_quaternion_world.slice(1) as [number, number, number]),
      right.body_quaternion_world[0],
    );
    // Reject a corrupt zero quaternion rather than inventing an attitude.
    if (a.lengthSq() > 1e-20 && b.lengthSq() > 1e-20) {
      a.normalize().slerp(b.normalize(), amount);
      result.body_quaternion_world = [a.w, a.x, a.y, a.z];
      result.body_axis_world = new THREE.Vector3(1, 0, 0)
        .applyQuaternion(a)
        .toArray();
    }
  }
  return result;
}
