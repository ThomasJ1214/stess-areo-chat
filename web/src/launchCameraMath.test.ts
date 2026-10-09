import { describe, expect, it } from "vitest";
import * as THREE from "three";
import type { Vec3 } from "./types";
import {
  cameraSampleJump,
  followCameraFraming,
  stepFollowCamera,
  type FollowCameraSample,
  type FollowCameraState,
} from "./launchCameraMath";

const sample = (
  overrides: Partial<FollowCameraSample> = {},
): FollowCameraSample => ({
  position: [0, 1, 0],
  velocity: [0, 0, 0],
  railDirection: [0, 1, 0],
  onRail: true,
  time: 0,
  ...overrides,
});
const stateAt = (row: FollowCameraSample, aspect = 1.5): FollowCameraState => {
  const framing = followCameraFraming(row, 2, 3, 42, aspect);
  return {
    ...framing,
    anchor: row.position,
    time: row.time,
    automatic: true,
    initialized: true,
  };
};
const projectedRocket = (
  row: FollowCameraSample,
  view: Pick<FollowCameraState, "position" | "focus">,
  aspect = 1.5,
) => {
  const camera = new THREE.PerspectiveCamera(42, aspect, 0.001, 100000);
  camera.position.fromArray(view.position);
  camera.lookAt(new THREE.Vector3(...view.focus));
  camera.updateMatrixWorld();
  return new THREE.Vector3(...row.position).project(camera);
};

describe("launch chase camera with actual trajectory coordinates", () => {
  it("frames both a tall launch rail and a high-altitude rocket in wide and narrow viewports", () => {
    for (const aspect of [0.7, 1.5, 2.4]) {
      for (const row of [
        sample(),
        sample({
          position: [600, 10000, -200],
          velocity: [80, 680, -20],
          onRail: false,
          time: 22,
        }),
      ]) {
        const framing = followCameraFraming(row, 2, 3, 42, aspect);
        const ndc = projectedRocket(row, framing, aspect);
        expect(Math.abs(ndc.x)).toBeLessThan(0.2);
        expect(Math.abs(ndc.y)).toBeLessThan(0.2);
        expect(ndc.z).toBeGreaterThan(-1);
        expect(ndc.z).toBeLessThan(1);
        const rocketDirection = new THREE.Vector3(
          ...(row.onRail ? row.railDirection : row.velocity),
        ).normalize();
        const camera = new THREE.PerspectiveCamera(42, aspect, 0.001, 100000);
        camera.position.fromArray(framing.position);
        camera.lookAt(new THREE.Vector3(...framing.focus));
        camera.updateMatrixWorld();
        const tip = new THREE.Vector3(...row.position)
          .addScaledVector(rocketDirection, 1)
          .project(camera);
        const tail = new THREE.Vector3(...row.position)
          .addScaledVector(rocketDirection, -1)
          .project(camera);
        expect(tip.distanceTo(tail)).toBeGreaterThan(0.07); // At least 3.5% of the screen, without scale exaggeration.
      }
    }
  });

  it("carries the camera with a Mach-2-speed rocket at 10× playback instead of lagging its world position", () => {
    let row = sample({
      position: [0, 1000, 0],
      velocity: [680, 0, 0],
      onRail: false,
      time: 1,
    });
    let state = stateAt(row);
    const initialOffset = state.position.map((n, i) => n - row.position[i]);
    for (let i = 1; i <= 60; i++) {
      row = {
        ...row,
        position: [(680 * 10 * i) / 60, 1000, 0],
        time: 1 + (10 * i) / 60,
      };
      state = stepFollowCamera(
        state,
        row,
        followCameraFraming(row, 2, 3, 42, 1.5),
        1 / 60,
        true,
        true,
      );
      state.position.forEach((n, axis) =>
        expect(n - row.position[axis]).toBeCloseTo(initialOffset[axis], 8),
      );
      const ndc = projectedRocket(row, state);
      expect(Math.abs(ndc.x)).toBeLessThan(0.2);
      expect(Math.abs(ndc.y)).toBeLessThan(0.2);
    }
  });

  it("has frame-rate-independent exponential framing rather than a per-frame lerp", () => {
    const row = sample();
    const desired = followCameraFraming(row, 2, 3, 42, 1.5);
    const advance = (fps: number) => {
      let state = {
        ...stateAt(row),
        position: [100, 30, 70] as Vec3,
        focus: [20, 10, 3] as Vec3,
      };
      for (let i = 0; i < fps; i++)
        state = stepFollowCamera(state, row, desired, 1 / fps, true, true);
      return state;
    };
    const thirty = advance(30),
      oneTwenty = advance(120);
    thirty.position.forEach((n, i) =>
      expect(n).toBeCloseTo(oneTwenty.position[i], 9),
    );
    thirty.focus.forEach((n, i) =>
      expect(n).toBeCloseTo(oneTwenty.focus[i], 9),
    );
    expect(thirty.position[0] - desired.position[0]).toBeCloseTo(
      (100 - desired.position[0]) * Math.exp(-3.5),
      9,
    );
  });

  it("shows a scrubbed or restarted frame immediately and accepts normal fast playback samples", () => {
    const previous = stateAt(
      sample({ time: 60, position: [0, 5000, 0], onRail: false }),
    );
    const requested = sample({
      time: 70,
      position: [900, 100, 40],
      onRail: false,
    });
    const framing = followCameraFraming(requested, 2, 3, 42, 1.5);
    expect(
      stepFollowCamera(previous, requested, framing, 1 / 60, true, false)
        .position,
    ).toEqual(framing.position);
    const replay = sample();
    const replayFraming = followCameraFraming(replay, 2, 3, 42, 1.5);
    expect(
      stepFollowCamera(previous, replay, replayFraming, 1 / 60, true, true)
        .position,
    ).toEqual(replayFraming.position);
    expect(cameraSampleJump(10, 10.4, true)).toBe(false);
    expect(cameraSampleJump(10, 10.025, false)).toBe(true);
  });

  it("leaves a manual view unchanged through motion and scrubbing, then eases toward follow", () => {
    const manual: FollowCameraState = {
      ...stateAt(sample()),
      position: [20, 30, 40],
      focus: [0, 3, 0],
    };
    const moved = sample({
      time: 30,
      position: [500, 900, 50],
      velocity: [60, -30, 0],
      onRail: false,
    });
    const desired = followCameraFraming(moved, 2, 3, 42, 1.5);
    const held = stepFollowCamera(manual, moved, desired, 1 / 60, false, false);
    expect(held.position).toEqual(manual.position);
    expect(held.focus).toEqual(manual.focus);
    const resumed = stepFollowCamera(held, moved, desired, 1 / 60, true, false);
    const distance = (a: Vec3, b: Vec3) =>
      new THREE.Vector3(...a).distanceTo(new THREE.Vector3(...b));
    expect(distance(resumed.position, desired.position)).toBeLessThan(
      distance(held.position, desired.position),
    );
    expect(distance(resumed.position, held.position)).toBeLessThan(
      distance(held.position, desired.position) * 0.1,
    );
  });

  it("keeps a bounded horizontal camera heading through apogee and recovery reversal", () => {
    const ascent = sample({
      position: [0, 500, 0],
      velocity: [20, 1, 0],
      onRail: false,
    });
    const descending = { ...ascent, velocity: [-20, -1, 0] as Vec3 };
    const a = followCameraFraming(ascent, 2, 3, 42, 1.5);
    const b = followCameraFraming(descending, 2, 3, 42, 1.5);
    const heading = (view: typeof a) =>
      new THREE.Vector2(
        view.position[0] - ascent.position[0],
        view.position[2] - ascent.position[2],
      ).normalize();
    expect(Math.acos(heading(a).dot(heading(b)))).toBeLessThan(Math.PI / 4);
    const rest = followCameraFraming(
      { ...descending, position: [0, 0, 0], velocity: [0, 0, 0] },
      2,
      3,
      42,
      1.5,
    );
    expect(rest.position.every(Number.isFinite)).toBe(true);
    expect(rest.position[1]).toBeGreaterThan(0);
  });
});
