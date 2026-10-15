import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { interpolateFlightSample } from "./flightPlaybackMath";

describe("flight presentation interpolation, separate from numerical results", () => {
  it("interpolates only pose/wind and retains actual nearest-sample engineering data", () => {
    const a = {
      time: 0,
      east: 0,
      altitude: 1,
      north: 2,
      cg: 0.6,
      velocity_vector: [0, 1, 2],
      wind_vector: [1, 0, 0],
      thrust: 500,
      stress_pa: 12,
      mach: 0.1,
      acceleration: 10,
      recovery_inflation_fraction: 0,
    };
    const b = {
      time: 1,
      east: 10,
      altitude: 21,
      north: 12,
      cg: 0.5,
      velocity_vector: [10, 11, 12],
      wind_vector: [3, 2, 2],
      thrust: 1000,
      stress_pa: 80,
      mach: 0.4,
      acceleration: 25,
      recovery_inflation_fraction: 0.8,
    };
    const serialized = JSON.stringify([a, b]);
    const frame = interpolateFlightSample([a, b], 0.25)!;
    expect(frame).toMatchObject({
      time: 0.25,
      east: 2.5,
      altitude: 6,
      north: 4.5,
      cg: 0.575,
      thrust: 500,
      stress_pa: 12,
      mach: 0.1,
      acceleration: 10,
      actual_sample_index: 0,
      actual_sample_time: 0,
      presentation_interpolated: true,
      recovery_inflation_fraction: 0.2,
    });
    expect(frame.velocity_vector).toEqual([2.5, 3.5, 4.5]);
    expect(frame.wind_vector).toEqual([1.5, 0.5, 0.5]);
    expect(interpolateFlightSample([a, b], 0.75)!.thrust).toBe(1000);
    expect(JSON.stringify([a, b])).toBe(serialized);
  });
  it("uses quaternion SLERP and the same interpolated body axis through a sharp turn", () => {
    const turn = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 0, 1),
      Math.PI * 0.95,
    );
    const frame = interpolateFlightSample(
      [
        { time: 0, body_quaternion_world: [1, 0, 0, 0] },
        { time: 1, body_quaternion_world: [turn.w, turn.x, turn.y, turn.z] },
      ],
      0.5,
    )!;
    const [w, x, y, z] = frame.body_quaternion_world!;
    const attitude = new THREE.Quaternion(x, y, z, w);
    expect(attitude.length()).toBeCloseTo(1);
    expect(attitude.angleTo(new THREE.Quaternion())).toBeCloseTo(
      Math.PI * 0.475,
    );
    expect(
      new THREE.Vector3(
        ...(frame.body_axis_world! as [number, number, number]),
      ).distanceTo(new THREE.Vector3(1, 0, 0).applyQuaternion(attitude)),
    ).toBeLessThan(1e-12);
  });
  it("takes the shortest quaternion path for antipodal encodings", () => {
    const frame = interpolateFlightSample(
      [
        { time: 0, body_quaternion_world: [1, 0, 0, 0] },
        { time: 1, body_quaternion_world: [-1, 0, 0, 0] },
      ],
      0.5,
    )!;
    expect(Math.abs(frame.body_quaternion_world![0])).toBeCloseTo(1);
    expect(frame.body_axis_world).toEqual([1, 0, 0]);
  });
  it("clamps outside the saved flight and handles one-row/empty flights", () => {
    expect(interpolateFlightSample([], 1)).toBeNull();
    const rows = [
      { time: 3, east: 10 },
      { time: 5, east: 20 },
    ];
    expect(interpolateFlightSample(rows, -10)).toMatchObject({
      time: 3,
      east: 10,
      presentation_interpolated: false,
    });
    expect(interpolateFlightSample(rows, 100)).toMatchObject({
      time: 5,
      east: 20,
      presentation_interpolated: false,
    });
    expect(interpolateFlightSample(rows, NaN)!.time).toBe(3);
    expect(interpolateFlightSample([rows[0]], 20)!.time).toBe(3);
  });
  it("uses the later event state at duplicate timestamps without inventing attitude", () => {
    const rows = [
      { time: 1, phase: "coast", thrust: 0 },
      { time: 1, phase: "main", thrust: 0 },
      { time: 2, phase: "main", thrust: 0 },
    ];
    expect(interpolateFlightSample(rows, 1)).toMatchObject({
      phase: "main",
      actual_sample_index: 1,
    });
    expect(
      interpolateFlightSample(rows, 1.5)!.body_quaternion_world,
    ).toBeUndefined();
    const corrupt = [
      { time: 0, body_quaternion_world: [0, 0, 0, 0] },
      { time: 1, body_quaternion_world: [1, 0, 0, 0] },
    ];
    expect(
      interpolateFlightSample(corrupt, 0.2)!.body_quaternion_world,
    ).toEqual([0, 0, 0, 0]);
  });
});
