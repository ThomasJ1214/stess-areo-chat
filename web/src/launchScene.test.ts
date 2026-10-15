import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { defaultConditions } from "./types";
import {
  ambientWind,
  flightLocalDrag,
  flightPose,
  railDirection,
  trajectoryPoints,
  inertialToScene,
  solvedGeometryQuaternion,
} from "./launchScene";

describe("launch scene coordinates and truthful result playback", () => {
  it("uses the solver's north/east launch convention for a tilted rail", () => {
    const north = railDirection({ launch_angle: 30, launch_azimuth: 0 });
    expect(north[0]).toBeCloseTo(0);
    expect(north[1]).toBeCloseTo(Math.sqrt(3) / 2);
    expect(north[2]).toBeCloseTo(-0.5);
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
    ).toEqual([2, 0.4, -3]);
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
  it("preserves all CAD axes when converting a solved nose-body quaternion from right-handed ENU", () => {
    const world = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(0.7, -1.1, 0.3),
    );
    const geometry = solvedGeometryQuaternion([
      world.w,
      world.x,
      world.y,
      world.z,
    ])!;
    expect(geometry.length()).toBeCloseTo(1);
    expect(
      new THREE.Matrix4().makeRotationFromQuaternion(geometry).determinant(),
    ).toBeCloseTo(1);
    for (const local of [
      new THREE.Vector3(-1, 0, 0),
      new THREE.Vector3(0, 1, 0),
      new THREE.Vector3(0, 0, 1),
    ]) {
      const body = new THREE.Vector3(
        -local.x,
        local.y,
        -local.z,
      ).applyQuaternion(world);
      const expected = new THREE.Vector3(...inertialToScene(body.toArray()));
      expect(
        local.clone().applyQuaternion(geometry).distanceTo(expected),
      ).toBeLessThan(1e-12);
    }
  });
  it("renders solved attitude and roll instead of substituting flight velocity", () => {
    const body = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(1, 0, 0),
      Math.PI / 3,
    );
    const pose = flightPose(
      {
        time: 1,
        altitude: 30,
        velocity_vector: [0, 0, 100],
        body_quaternion_world: [body.w, body.x, body.y, body.z],
      },
      defaultConditions,
      [{ name: "rail_exit", time: 0.2 }],
      2,
      1,
    );
    expect(pose.attitudeSource).toBe("solved");
    expect(pose.noseDirection.x).toBeCloseTo(1);
    expect(pose.noseDirection.y).toBeCloseTo(0);
    const cadY = new THREE.Vector3(0, 1, 0).applyQuaternion(pose.quaternion);
    expect(cadY.y).toBeCloseTo(Math.sqrt(3) / 2);
    expect(cadY.z).toBeCloseTo(-0.5);
    const drag = flightLocalDrag(
      { velocity_vector: [3, 4, 5], wind_vector: [1, 2, 3] },
      pose.quaternion,
    );
    const recovered = new THREE.Vector3(...drag).applyQuaternion(
      pose.quaternion,
    );
    expect(recovered.distanceTo(new THREE.Vector3(-2, -2, 2))).toBeLessThan(
      1e-12,
    );
  });
  it("rejects invalid attitudes and retains a labelled point-mass fallback", () => {
    for (const invalid of [
      [0, 0, 0, 0],
      [1, NaN, 0, 0],
      [1, 0, 0],
    ])
      expect(solvedGeometryQuaternion(invalid)).toBeNull();
    expect(flightPose(null, defaultConditions, [], 2, 1).attitudeSource).toBe(
      "illustrative",
    );
  });
  it("keeps the initial display origin fixed during CG change and places an off-axis CAD tail on the pad", () => {
    const initial = {
      time: 0,
      cg: 0.7,
      cg_geometry_m: [0.7, 0.03, -0.02],
      body_quaternion_world: [1, 0, 0, 0],
    };
    const pad = flightPose(initial, defaultConditions, [], 2, 0.7, initial);
    const tail = new THREE.Vector3(2 - 0.7, -0.03, 0.02)
      .applyQuaternion(pad.quaternion)
      .add(pad.position);
    expect(tail.length()).toBeLessThan(1e-12);
    const later = flightPose(
      {
        time: 10,
        cg: 0.5,
        east: 20,
        north: 7,
        altitude: 30,
        body_quaternion_world: [Math.SQRT1_2, 0, 0, Math.SQRT1_2],
      },
      defaultConditions,
      [{ name: "rail_exit", time: 0.2 }],
      2,
      0.5,
      initial,
    );
    expect(
      later.position.clone().sub(later.point).distanceTo(pad.position),
    ).toBeLessThan(1e-12);
  });
});
