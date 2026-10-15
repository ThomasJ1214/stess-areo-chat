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
  cg_geometry_m?: number[];
  phase?: string;
  velocity_vector?: number[];
  wind_vector?: number[];
  body_quaternion_world?: number[];
  body_axis_world?: number[];
  thrust?: number;
  inflation_fraction?: number;
  recovery_inflation_fraction?: number;
  recovery_cd_area_m2?: number;
}

/** Proper right-handed transform: ENU becomes east/up/south in Three.js.
 * Using positive north for scene Z would mirror the imported CAD geometry. */
export function inertialToScene(v: number[]): Vec3 {
  return [v[0] || 0, v[2] || 0, -(v[1] || 0) || 0];
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
    -Math.sin(tilt) * Math.cos(azimuth) || 0,
  ];
}

export function samplePosition(row?: FlightSample | null): Vec3 {
  return [row?.east || 0, row?.altitude || 0, -(row?.north || 0) || 0];
}

/** Convert solved nose-body axes to original CAD axes without reflecting either
 * coordinate system. Both transforms are proper rotations (determinant +1). */
export function solvedGeometryQuaternion(
  values?: number[],
): THREE.Quaternion | null {
  if (!values || values.length !== 4 || !values.every(Number.isFinite))
    return null;
  const [w, x, y, z] = values;
  const bodyWorld = new THREE.Quaternion(x, y, z, w);
  if (bodyWorld.lengthSq() < 1e-20) return null;
  // World ENU → scene E/U/S: rotate −90° around east.
  const enuScene = new THREE.Quaternion(-Math.SQRT1_2, 0, 0, Math.SQRT1_2);
  // CAD (+X tail,+Y,+Z) → nose body (+X nose,+Y,−Z): 180° about Y.
  const geometryBody = new THREE.Quaternion(0, 1, 0, 0);
  return enuScene
    .multiply(bodyWorld.normalize())
    .multiply(geometryBody)
    .normalize();
}

/** Six-DOF playback uses actual attitude. Legacy point-mass orientation is
 * explicitly illustrative: rail first, then the velocity direction. */
export function flightPose(
  row: FlightSample | null | undefined,
  conditions: Conditions,
  events: FlightEvent[],
  tailX: number,
  cgX: number,
  initialSample?: FlightSample | null,
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
  const illustrativeDirection =
    onRail || velocity.lengthSq() < 1e-8 ? rail : velocity.normalize();
  const solved = solvedGeometryQuaternion(row?.body_quaternion_world);
  const quaternion =
    solved ||
    new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(1, 0, 0),
      illustrativeDirection.clone().negate(),
    );
  const noseDirection = solved
    ? new THREE.Vector3(-1, 0, 0).applyQuaternion(solved)
    : illustrativeDirection;
  // The solver starts its point at the pad (zero AGL). A fixed display-origin
  // offset puts the actual rocket tail on the pad at t=0 without altering data.
  const initialGeometryRotation =
    solvedGeometryQuaternion(initialSample?.body_quaternion_world) ||
    new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(1, 0, 0),
      rail.clone().negate(),
    );
  const initialCg =
    initialSample?.cg_geometry_m?.length === 3 &&
    initialSample.cg_geometry_m.every(Number.isFinite)
      ? initialSample.cg_geometry_m
      : [initialSample?.cg ?? cgX, 0, 0];
  const originOffset = new THREE.Vector3(
    initialCg[0] - tailX,
    initialCg[1],
    initialCg[2],
  ).applyQuaternion(initialGeometryRotation);
  return {
    point,
    position: point.clone().add(originOffset),
    quaternion,
    noseDirection,
    onRail,
    attitudeSource: solved ? ("solved" as const) : ("illustrative" as const),
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
    -conditions.wind_speed * Math.cos(angle),
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
