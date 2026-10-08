import { describe, expect, it } from "vitest";
import { fieldRange, flightDragDirection } from "./viewerData";

describe("actual result visualization", () => {
  it("reverses displayed drag when a rocket descends and subtracts the actual wind", () => {
    expect(flightDragDirection({ velocity_vector: [0, 0, 100] })).toEqual([
      100, -0, -0,
    ]);
    expect(flightDragDirection({ velocity_vector: [0, 0, -10] })).toEqual([
      -10, -0, -0,
    ]);
    expect(
      flightDragDirection({
        velocity_vector: [7, 3, 50],
        wind_vector: [2, 1, 0],
      }),
    ).toEqual([50, -5, -2]);
  });
  it("computes a large result-field range without spread argument overflow", () => {
    expect(
      fieldRange(Array.from({ length: 150000 }, (_, i) => i - 100)),
    ).toEqual([-100, 149899]);
    expect(fieldRange([NaN, 2, Infinity, -3])).toEqual([-3, 2]);
  });
});
