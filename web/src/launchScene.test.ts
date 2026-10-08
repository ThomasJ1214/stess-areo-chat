import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { defaultConditions } from "./types";
import {
  ambientWind,
  flightLocalDrag,
  flightPose,
  railDirection,
  trajectoryPoints,
} from "./launchScene";

describe("launch scene coordinates and truthful result playback", () => {
  it("uses the solver's north/east launch convention for a tilted rail", () => {
    const north = railDirection({ launch_angle: 30, launch_azimuth: 0 });
    expect(north[0]).toBeCloseTo(0);
    expect(north[1]).toBeCloseTo(Math.sqrt(3) / 2);
    expect(north[2]).toBeCloseTo(0.5);
    const east = railDirection({ launch_angle: 30, launch_azimuth: 90 });
    expect(east[0]).toBeCloseTo(0.5);
    expect(east[2]).toBeCloseTo(0);
  });
  it("places the actual geometry tail on the pad with a noncentral CG", () => {
    const pose = flightPose(null, defaultConditions, [], 2, 0.7);
    const tail = new THREE.Vector3(2 - 0.7, 0, 0)
      .applyQuaternion(pose.quaternion)
      .add(pose.position);
    expect(tail.length()).toBeCloseTo(0);
    const nose = new THREE.Vector3(-0.7, 0, 0)
      .applyQuaternion(pose.quaternion)
      .add(pose.position);
    expect(nose.length()).toBeCloseTo(2);
    expect(nose.y).toBeGreaterThan(0);
  });
  it("keeps the nose on the rail until the actual rail-exit event and then follows inertial velocity", () => {
    const conditions = { ...defaultConditions, launch_angle: 0 };
    const row = { time: 0.3, altitude: 1, velocity_vector: [10, 0, 10] };
    const before = flightPose(
      row,
      conditions,
      [{ name: "rail_exit", time: 0.4 }],
      2,
      1,
    );
    expect(before.noseDirection.toArray()).toEqual([0, 1, 0]);
    const after = flightPose(
      { ...row, time: 0.5 },
      conditions,
      [{ name: "rail_exit", time: 0.4 }],
      2,
      1,
    );
    expect(after.noseDirection.x).toBeCloseTo(1 / Math.sqrt(2));
    expect(after.noseDirection.y).toBeCloseTo(1 / Math.sqrt(2));
    const localDrag = flightLocalDrag(
      { ...row, wind_vector: [2, 0, 0] },
      after.quaternion,
    );
    const backToWorld = new THREE.Vector3(...localDrag).applyQuaternion(
      after.quaternion,
    );
    expect(backToWorld.x).toBeCloseTo(-8);
    expect(backToWorld.y).toBeCloseTo(-10);
  });
  it("uses actual simulated wind during playback and entered wind before a result", () => {
    expect(
      ambientWind({ wind_vector: [2, 3, 0.4] }, defaultConditions),
    ).toEqual([2, 0.4, 3]);
    const entered = ambientWind(null, {
      ...defaultConditions,
      wind_speed: 5,
      wind_direction: 90,
    });
    expect(entered[0]).toBeCloseTo(5);
    expect(entered[2]).toBeCloseTo(0);
  });
  it("retains exact landing, apogee and event positions in a long rendered path", () => {
    const rows = Array.from({ length: 4000 }, (_, i) => ({
      time: i,
      east: i,
      north: 0,
      altitude: i === 1703 ? 10000 : 1,
    }));
    rows[3999].altitude = 0;
    const points = trajectoryPoints(
      rows,
      [{ name: "rail_exit", time: 27 }],
      100,
    );
    expect(points[0]).toEqual([0, 1, 0]);
    expect(points.at(-1)).toEqual([3999, 0, 0]);
    expect(points).toContainEqual([1703, 10000, 0]);
    expect(points).toContainEqual([27, 1, 0]);
    expect(points.length).toBeLessThan(110);
  });
});
