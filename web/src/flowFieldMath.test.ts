import { describe, expect, it } from "vitest";
import {
  defaultCfdFlowSettings,
  generateStreamlines,
  integrateStreamline,
  readFlowGrid,
  sampleVelocity,
  streamlinePosition,
} from "./flowFieldMath";
import type { FlowPoint } from "./flowFieldMath";

function field(
  shape: FlowPoint,
  origin: FlowPoint,
  spacing: FlowPoint,
  velocity: (point: FlowPoint) => FlowPoint,
  fluid: (point: FlowPoint) => boolean = () => true,
) {
  const velocity_m_s: number[] = [];
  const fluid_mask: number[] = [];
  for (let i = 0; i < shape[0]; i++)
    for (let j = 0; j < shape[1]; j++)
      for (let k = 0; k < shape[2]; k++) {
        const point = [
          origin[0] + i * spacing[0],
          origin[1] + j * spacing[1],
          origin[2] + k * spacing[2],
        ] as FlowPoint;
        velocity_m_s.push(...velocity(point));
        fluid_mask.push(Number(fluid(point)));
      }
  return {
    shape,
    origin_m: origin,
    spacing_m: spacing,
    velocity_m_s,
    fluid_mask,
  };
}

describe("streamlines through actual CFD grid values", () => {
  it("interpolates a linear, oblique vector field against its analytic value", () => {
    const actual = (p: FlowPoint): FlowPoint => [
      2 + p[0] - 3 * p[1],
      p[1] + p[2],
      0.5 * p[0],
    ];
    const grid = readFlowGrid(
      field([5, 6, 4], [-1, -2, 0], [0.5, 0.4, 0.8], actual),
    )!;
    const point: FlowPoint = [0.17, -0.23, 1.19];
    sampleVelocity(grid, point)!.forEach((value, axis) =>
      expect(value).toBeCloseTo(actual(point)[axis], 12),
    );
  });

  it("renders full straight streamlines only inside the sampled domain", () => {
    const grid = readFlowGrid(
      field([21, 5, 5], [0, -1, -1], [0.1, 0.5, 0.5], () => [10, 0, 0]),
    )!;
    const path = integrateStreamline(grid, [0.6, 0.13, -0.4])!;
    expect(path.points[0][0]).toBeCloseTo(0, 12);
    expect(path.points.at(-1)![0]).toBeCloseTo(2, 12);
    path.points.forEach((point) => {
      expect(point[1]).toBeCloseTo(0.13, 12);
      expect(point[2]).toBeCloseTo(-0.4, 12);
      expect(point[0]).toBeGreaterThanOrEqual(0);
      expect(point[0]).toBeLessThanOrEqual(2);
    });
    expect(path.travelTimes.at(-1)).toBeCloseTo(0.2, 12);
    expect(streamlinePosition(path, 0.1)[0]).toBeCloseTo(1, 12);
  });

  it("does not interpolate through a thin solid barrier or bridge it with a segment", () => {
    const grid = readFlowGrid(
      field(
        [21, 5, 5],
        [0, 0, 0],
        [0.1, 0.1, 0.1],
        () => [100, 0, 0],
        (point) => Math.abs(point[0] - 1) > 1e-8,
      ),
    )!;
    expect(sampleVelocity(grid, [0.95, 0.2, 0.2])).toBeNull();
    expect(sampleVelocity(grid, [1, 0.2, 0.2])).toBeNull();
    const path = integrateStreamline(grid, [0.2, 0.2, 0.2])!;
    expect(
      Math.max(...path.points.map((point) => point[0])),
    ).toBeLessThanOrEqual(0.9 + 1e-12);
    expect(
      path.points.every((point) => sampleVelocity(grid, point) !== null),
    ).toBe(true);
  });

  it("tracks circular streamlines against the exact radius and quarter-turn endpoint", () => {
    const grid = readFlowGrid(
      field([41, 41, 3], [-2, -2, -0.1], [0.1, 0.1, 0.1], (point) => [
        -point[1],
        point[0],
        0,
      ]),
    )!;
    const path = integrateStreamline(grid, [1, 0, 0], Math.PI / 2)!;
    path.points.forEach((point) =>
      expect(Math.hypot(point[0], point[1])).toBeCloseTo(1, 6),
    );
    expect(path.points.at(-1)![0]).toBeCloseTo(0, 4);
    expect(path.points.at(-1)![1]).toBeCloseTo(1, 6);
    expect(path.points[0][1]).toBeCloseTo(-1, 6);
  });

  it("seeds dense reverse-flow paths that retain the actual velocity direction", () => {
    const grid = readFlowGrid(
      field([21, 5, 5], [0, -1, -1], [0.1, 0.5, 0.5], () => [-4, 0, 0]),
    )!;
    const paths = generateStreamlines(grid, [-4, 0, 0], {
      ...defaultCfdFlowSettings,
      density: 64,
    });
    expect(paths).toHaveLength(64);
    paths.forEach((path) => {
      expect(path.points[0][0]).toBeCloseTo(2, 12);
      expect(path.points.at(-1)![0]).toBeCloseTo(0, 12);
      path.speeds.forEach((speed) => expect(speed).toBeCloseTo(4, 12));
    });
  });

  it("does not manufacture streamlines for missing data, masked space or stagnation", () => {
    expect(
      readFlowGrid({
        samples: [{ position: [0, 0, 0], velocity: [100, 0, 0] }],
      }),
    ).toBeNull();
    const raw = field(
      [3, 3, 3],
      [0, 0, 0],
      [1, 1, 1],
      () => [0, 0, 0],
      (point) => point.join() !== "1,1,1",
    );
    const grid = readFlowGrid(raw)!;
    expect(sampleVelocity(grid, [1, 1, 1])).toBeNull();
    expect(integrateStreamline(grid, [0, 0, 0])).toBeNull();
    expect(sampleVelocity(grid, [-0.1, 0, 0])).toBeNull();
    raw.velocity_m_s[0] = NaN;
    expect(readFlowGrid(raw)).toBeNull();
  });

  it("excludes masked zero placeholders from the physical speed legend", () => {
    const grid = readFlowGrid(
      field(
        [3, 3, 3],
        [0, 0, 0],
        [1, 1, 1],
        (point) => (point.join() === "1,1,1" ? [0, 0, 0] : [3, 4, 0]),
        (point) => point.join() !== "1,1,1",
      ),
    )!;
    expect(grid.speedRange).toEqual([5, 5]);
  });

  it("improves curved-path integration with high display quality against a circular reference", () => {
    const grid = readFlowGrid(
      field([21, 21, 3], [-2, -2, -0.2], [0.2, 0.2, 0.2], (point) => [
        -point[1],
        point[0],
        0,
      ]),
    )!;
    const draft = integrateStreamline(grid, [1, 0, 0], Math.PI / 2, "draft")!;
    const high = integrateStreamline(grid, [1, 0, 0], Math.PI / 2, "high")!;
    const endpointError = (path: typeof high) =>
      Math.hypot(path.points.at(-1)![0], path.points.at(-1)![1] - 1);
    expect(endpointError(high)).toBeLessThan(endpointError(draft));
    expect(endpointError(high)).toBeLessThan(2e-7);
    expect(high.points.length).toBeGreaterThan(draft.points.length);
    expect(
      high.points.every((point) => sampleVelocity(grid, point) !== null),
    ).toBe(true);
  });
  it("seeds genuine transient motion with stationary farfield while leaving a quiescent field empty", () => {
    const still = readFlowGrid(
      field([11, 5, 5], [0, -1, -1], [0.2, 0.5, 0.5], () => [0, 0, 0]),
    )!;
    expect(
      generateStreamlines(still, [0, 0, 0], defaultCfdFlowSettings),
    ).toEqual([]);
    const moving = readFlowGrid(
      field(
        [21, 5, 5],
        [0, 0, 0],
        [0.1, 0.1, 0.1],
        () => [0.02, 0, 0],
        (point) => Math.abs(point[0] - 1) > 1e-8,
      ),
    )!;
    const paths = generateStreamlines(moving, [0, 0, 0], {
      ...defaultCfdFlowSettings,
      density: 24,
    });
    expect(paths.length).toBeGreaterThan(0);
    paths.forEach((path) => {
      const side = path.points[0][0] < 1;
      path.points.forEach((point) => {
        expect(sampleVelocity(moving, point)).not.toBeNull();
        expect(point[0] < 1).toBe(side);
      });
      path.speeds.forEach((speed) => expect(speed).toBeCloseTo(0.02, 12));
    });
  });

  it("crosses a continuous piecewise-affine velocity kink without shortening a high-quality path", () => {
    // dy/dx = 0.2 |x| gives an independent exact streamline. The derivative
    // jumps at x=0, as happens at a trilinear interpolation cell interface.
    const grid = readFlowGrid(
      field([21, 5, 3], [-1, -2, -0.1], [0.1, 1, 0.1], (point) => [
        1,
        0.2 * Math.abs(point[0]),
        0,
      ]),
    )!;
    const seed: FlowPoint = [-0.995, -0.5, 0];
    const high = integrateStreamline(grid, seed, 5, "high")!;
    const standard = integrateStreamline(grid, seed, 5, "standard")!;
    expect(high.points[0][0]).toBeCloseTo(-1, 12);
    expect(high.points.at(-1)![0]).toBeCloseTo(1, 12);
    expect(high.points.length).toBeGreaterThan(standard.points.length);
    high.points.forEach((point, index) => {
      const expectedY =
        -0.5 + 0.1 * (point[0] * Math.abs(point[0]) + seed[0] ** 2);
      // The first endpoint uses the existing domain-edge tangent clip; the
      // interior, kink crossing and forward endpoint retain RK4 accuracy.
      expect(point[1]).toBeCloseTo(expectedY, index === 0 ? 5 : 6);
      expect(sampleVelocity(grid, point)).not.toBeNull();
    });
  });
});
