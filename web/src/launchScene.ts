import * as THREE from "three";
import type { Conditions, Vec3 } from "./types";

export interface FlightEvent {
  name: string;
  time: number;
  index?: number;
}
export interface FlightSample {
  time?: number;
  east?: number;
  north?: number;
  altitude?: number;
  cg?: number;
  phase?: string;
  velocity_vector?: number[];
  wind_vector?: number[];
}

/** The flight solver stores east/north/up; Three.js uses east/up/north. */
export function inertialToScene(v: number[]): Vec3 {
  return [v[0] || 0, v[2] || 0, v[1] || 0];
}

/** Launch tilt is from vertical, azimuth is toward north (0) / east (90). */
export function railDirection(
  conditions: Pick<Conditions, "launch_angle" | "launch_azimuth">,
): Vec3 {
  const tilt = (conditions.launch_angle * Math.PI) / 180;
  const azimuth = (conditions.launch_azimuth * Math.PI) / 180;
  return [
    Math.sin(tilt) * Math.sin(azimuth),
    Math.cos(tilt),
    Math.sin(tilt) * Math.cos(azimuth),
  ];
}

export function samplePosition(row?: FlightSample | null): Vec3 {
  return [row?.east || 0, row?.altitude || 0, row?.north || 0];
}

/** Rendering only: the backend does not solve attitude or weathercocking. */
export function flightPose(
  row: FlightSample | null | undefined,
  conditions: Conditions,
  events: FlightEvent[],
  tailX: number,
  cgX: number,
) {
  const rail = new THREE.Vector3(...railDirection(conditions));
  const point = new THREE.Vector3(...samplePosition(row));
  const railExit = events.find((event) => event.name === "rail_exit");
  const onRail =
    !row ||
    (railExit
      ? (row.time || 0) < railExit.time
      : point.length() < conditions.rail_length);
  const velocity = new THREE.Vector3(
    ...inertialToScene(row?.velocity_vector || [0, 0, 0]),
  );
  const noseDirection =
    onRail || velocity.lengthSq() < 1e-8 ? rail : velocity.normalize();
  const quaternion = new THREE.Quaternion().setFromUnitVectors(
    new THREE.Vector3(1, 0, 0),
    noseDirection.clone().negate(),
  );
  // The solver starts its point at the pad (zero AGL). A fixed display-origin
  // offset puts the actual rocket tail on the pad at t=0 without altering data.
  const originOffset = rail.clone().multiplyScalar(tailX - cgX);
  return {
    point,
    position: point.clone().add(originOffset),
    quaternion,
    noseDirection,
    onRail,
  };
}

export function flightLocalDrag(
  row: FlightSample,
  quaternion: THREE.Quaternion,
): Vec3 {
  const velocity = row.velocity_vector || [0, 0, 0];
  const wind = row.wind_vector || [0, 0, 0];
  const worldDrag = new THREE.Vector3(
    ...inertialToScene(velocity.map((value, i) => -(value - (wind[i] || 0)))),
  );
  return worldDrag
    .applyQuaternion(quaternion.clone().invert())
    .toArray() as Vec3;
}

export function ambientWind(
  row: FlightSample | null | undefined,
  conditions: Conditions,
): Vec3 {
  if (row?.wind_vector?.length === 3) return inertialToScene(row.wind_vector);
  const angle = (conditions.wind_direction * Math.PI) / 180;
  return [
    conditions.wind_speed * Math.sin(angle),
    0,
    conditions.wind_speed * Math.cos(angle),
  ];
}

/** Preserve endpoints, coordinate extrema and real events when drawing long runs. */
export function trajectoryPoints(
  rows: FlightSample[],
  events: FlightEvent[] = [],
  limit = 1600,
): Vec3[] {
  if (!rows.length) return [];
  const selected = new Set<number>([0, rows.length - 1]);
  const stride = Math.max(
    1,
    Math.ceil(rows.length / Math.max(2, limit - events.length - 8)),
  );
  for (let i = 0; i < rows.length; i += stride) selected.add(i);
  for (const key of ["east", "north", "altitude"] as const) {
    let min = 0,
      max = 0;
    rows.forEach((row, i) => {
      if ((row[key] || 0) < (rows[min][key] || 0)) min = i;
      if ((row[key] || 0) > (rows[max][key] || 0)) max = i;
    });
    selected.add(min);
    selected.add(max);
  }
  for (const event of events) {
    if (event.index != null && event.index >= 0 && event.index < rows.length)
      selected.add(event.index);
    else {
      let nearest = 0;
      rows.forEach((row, i) => {
        if (
          Math.abs((row.time || 0) - event.time) <
          Math.abs((rows[nearest].time || 0) - event.time)
        )
          nearest = i;
      });
      selected.add(nearest);
    }
  }
  return [...selected]
    .sort((a, b) => a - b)
    .map((i) => samplePosition(rows[i]));
}

export function followCameraDistance(
  rocketSize: number,
  altitude: number,
  railLength: number,
) {
  const padSize = Math.max(rocketSize, railLength, 1);
  // Reveal a local segment of the path without reducing the rocket to a pixel.
  // Full-path framing is available separately through the Overview camera.
  const zoom = Math.sqrt(Math.max(0, altitude) * padSize) * 0.65;
  return padSize * 3.2 + Math.min(zoom, Math.max(rocketSize, 0.1) * 16);
}
