import type { Vec3 } from "./types";
import { followCameraDistance } from "./launchScene";
import { fitSphereDistance } from "./units";

export interface FollowCameraSample {
  position: Vec3;
  velocity: Vec3;
  railDirection: Vec3;
  onRail: boolean;
  time: number | null;
}

export interface FollowCameraFraming {
  position: Vec3;
  focus: Vec3;
  distance: number;
}

export interface FollowCameraState {
  position: Vec3;
  focus: Vec3;
  anchor: Vec3;
  time: number | null;
  automatic: boolean;
  initialized: boolean;
}

const add = (a: Vec3, b: Vec3): Vec3 => a.map((n, i) => n + b[i]) as Vec3;
const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));
const mix = (a: Vec3, b: Vec3, amount: number): Vec3 =>
  a.map((n, i) => n + (b[i] - n) * amount) as Vec3;

/** A bounded side/chase view of the solved path, never a rocket attitude solver. */
export function followCameraFraming(
  sample: FollowCameraSample,
  rocketSize: number,
  railLength: number,
  fov: number,
  aspect: number,
): FollowCameraFraming {
  const size = Math.max(0.1, rocketSize);
  const padSize = Math.max(size, railLength, 1);
  const projection =
    fitSphereDistance(1, fov, Math.max(0.1, aspect)) /
    fitSphereDistance(1, 42, 1.5);
  const distance =
    followCameraDistance(size, sample.position[1], railLength) * projection;
  const railHeading = Math.atan2(
    sample.railDirection[0],
    sample.railDirection[2],
  );
  const horizontalSpeed = Math.hypot(sample.velocity[0], sample.velocity[2]);
  const speed = Math.hypot(...sample.velocity);
  const velocityHeading = Math.atan2(sample.velocity[0], sample.velocity[2]);
  const headingDifference = Math.atan2(
    Math.sin(velocityHeading - railHeading),
    Math.cos(velocityHeading - railHeading),
  );
  // Limit the heading change: reversal under recovery must not spin the camera
  // around the rocket. Near-vertical velocity cannot define a useful heading.
  const headingBlend = sample.onRail
    ? 0
    : clamp(horizontalSpeed / Math.max(5, speed * 0.25), 0, 1);
  const viewHeading =
    railHeading +
    (110 * Math.PI) / 180 +
    clamp(headingDifference, -Math.PI / 5, Math.PI / 5) * headingBlend * 0.6;
  const ascent = clamp(Math.max(0, sample.position[1]) / (padSize * 12), 0, 1);
  const elevation = 0.17 + 0.17 * ascent;
  const horizontalDistance = distance * Math.cos(elevation);
  const offset: Vec3 = [
    Math.sin(viewHeading) * horizontalDistance,
    Math.sin(elevation) * distance,
    Math.cos(viewHeading) * horizontalDistance,
  ];
  const lookAheadLength = sample.onRail
    ? size * 0.08
    : Math.min(size * 0.65, speed * 0.08);
  const direction =
    sample.onRail || speed < 1e-8
      ? sample.railDirection
      : (sample.velocity.map((n) => n / speed) as Vec3);
  const lookAhead = direction.map((n) => n * lookAheadLength) as Vec3;
  const position = add(sample.position, offset);
  // Stay above the flat launch/landing plane even when the selected sample has
  // a tail-origin display offset, or a recovery velocity points downwards.
  position[1] = Math.max(position[1], size * 0.15);
  return { position, focus: add(sample.position, lookAhead), distance };
}

/** Scrubbing/replay should display the requested frame, not traverse old space. */
export function cameraSampleJump(
  previousTime: number | null,
  time: number | null,
  playing: boolean,
) {
  if (previousTime == null || time == null) return previousTime !== time;
  const elapsed = time - previousTime;
  return (
    elapsed < -1e-7 || (!playing && Math.abs(elapsed) > 1e-7) || elapsed > 1.5
  );
}

/**
 * Smooth the relative view, while carrying it by the actual rocket movement.
 * Lerp of world positions alone trails a fast rocket by hundreds of metres.
 * Manual view changes are passed through verbatim; resumption eases back in.
 */
export function stepFollowCamera(
  previous: FollowCameraState,
  sample: FollowCameraSample,
  desired: FollowCameraFraming,
  delta: number,
  automatic: boolean,
  playing: boolean,
): FollowCameraState {
  const next = {
    ...previous,
    anchor: sample.position,
    time: sample.time,
    automatic,
  };
  if (!automatic) return next;
  if (
    !previous.initialized ||
    cameraSampleJump(previous.time, sample.time, playing)
  )
    return {
      ...next,
      position: desired.position,
      focus: desired.focus,
      initialized: true,
    };
  const movement = sample.position.map(
    (n, i) => n - previous.anchor[i],
  ) as Vec3;
  const position = previous.automatic
    ? add(previous.position, movement)
    : previous.position;
  const focus = previous.automatic
    ? add(previous.focus, movement)
    : previous.focus;
  const step = Math.max(0, Math.min(delta, 0.1));
  return {
    ...next,
    position: mix(position, desired.position, 1 - Math.exp(-step * 3.5)),
    focus: mix(focus, desired.focus, 1 - Math.exp(-step * 5)),
    initialized: true,
  };
}
