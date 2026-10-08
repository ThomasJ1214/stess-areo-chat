import { describe, expect, it } from "vitest";
import { defaultConditions } from "./types";
import {
  flightMapBounds,
  flightMapEvents,
  flightMapPoints,
  mapScaleDistance,
  mapWind,
  parseMapLandmarks,
  railMapEnd,
  sampleFlightMapPoints,
} from "./flightMapData";
import { displayValue } from "./units";

describe("local flight map uses actual solver coordinates", () => {
  it("keeps negative east/north coordinates and rejects unavailable positions", () => {
    expect(
      flightMapPoints([
        { time: 0, east: 0, north: 0, altitude: 0 },
        { time: 1, east: -42, north: -16, altitude: 30 },
        { time: 2, east: undefined, north: 10 },
        { time: 3, east: NaN, north: 10 },
      ]),
    ).toEqual([
      { time: 0, east: 0, north: 0, altitude: 0, rowIndex: 0 },
      { time: 1, east: -42, north: -16, altitude: 30, rowIndex: 1 },
    ]);
  });

  it("fits every coordinate, the origin and rail without clipping negative drift", () => {
    const points = flightMapPoints([
      { time: 0, east: 0, north: 0 },
      { time: 1, east: -1200, north: 2800 },
      { time: 2, east: 650, north: -2300 },
    ]);
    const fit = flightMapBounds(points, [0, 3], 16 / 9);
    for (const [east, north] of [
      ...points.map((point) => [point.east, point.north]),
      [0, 0],
      [0, 3],
    ]) {
      expect(Math.abs(east - fit.east)).toBeLessThan(fit.span / 2);
      expect(Math.abs(north - fit.north)).toBeLessThan(
        fit.span / ((2 * 16) / 9),
      );
    }
    const empty = flightMapBounds([], [0, 0], 16 / 9);
    expect(empty).toEqual({ east: 0, north: 0, span: 24.8 });
    expect(
      flightMapBounds(
        flightMapPoints([{ time: 0, east: 0, north: 0 }]),
        [0, 0],
        16 / 9,
      ),
    ).toEqual(empty);
  });

  it("uses north/east azimuth conventions for rail projection and toward wind", () => {
    const north = {
      ...defaultConditions,
      rail_length: 4,
      launch_angle: 30,
      launch_azimuth: 0,
      wind_speed: 10,
      wind_direction: 0,
    };
    expect(railMapEnd(north)[0]).toBeCloseTo(0);
    expect(railMapEnd(north)[1]).toBeCloseTo(2);
    expect(mapWind(null, north)).toEqual([0, 10]);
    const east = { ...north, launch_azimuth: 90, wind_direction: 90 };
    expect(railMapEnd(east)[0]).toBeCloseTo(2);
    expect(railMapEnd(east)[1]).toBeCloseTo(0);
    expect(mapWind(null, east)[0]).toBeCloseTo(10);
    expect(mapWind(null, east)[1]).toBeCloseTo(0);
    expect(mapWind({ wind_vector: [-3, 4, 5] }, east)).toEqual([-3, 4]);
    expect(railMapEnd({ ...east, launch_angle: 0 })).toEqual([0, 0]);
  });

  it("creates ground contact only from an actual event and a recorded ground sample", () => {
    const rows = [
      { time: 0, east: 0, north: 0, altitude: 0 },
      { time: 2, east: 10, north: -5, altitude: 50 },
      { time: 8, east: 80, north: -40, altitude: 0 },
    ];
    expect(
      flightMapEvents(rows, [{ name: "apogee", time: 2, index: 1 }])[0],
    ).toMatchObject({ name: "apogee", time: 2, east: 10, north: -5 });
    // A last row at zero, without an event, is not evidence of landing.
    expect(flightMapEvents(rows, [])).toEqual([]);
    expect(flightMapEvents(rows, [{ name: "recovery", time: -10 }])).toEqual(
      [],
    );
    expect(flightMapEvents(rows, [{ name: "recovery", time: 20 }])).toEqual([]);
    expect(
      flightMapEvents(rows, [{ name: "recovery", time: 2, index: 1 }]),
    ).toEqual([]);
    expect(
      flightMapEvents(rows, [{ name: "recovery", time: 8, index: 2 }])[0],
    ).toMatchObject({
      name: "recovery",
      time: 8,
      east: 80,
      north: -40,
      altitude: 0,
    });
    // Missing event indices resolve to a real sample, not array position zero.
    expect(
      flightMapEvents(rows, [{ name: "burnout", time: 2 }])[0],
    ).toMatchObject({ name: "burnout", east: 10, north: -5 });
  });

  it("preserves the final landing, event samples and plan-view extrema when drawing a long flight", () => {
    const rows = Array.from({ length: 50001 }, (_, index) => ({
      time: index / 20,
      east: index,
      north: index % 300,
      altitude: 100,
    }));
    rows[17319].north = -800;
    rows[22317].north = 1000;
    const points = flightMapPoints(rows);
    const sampled = sampleFlightMapPoints(points, [12003], 50);
    expect(sampled[0]).toBe(points[0]);
    expect(sampled.at(-1)).toBe(points.at(-1));
    for (const index of [12003, 17319, 22317])
      expect(sampled).toContain(points[index]);
    expect(sampled.length).toBeLessThanOrEqual(57);
    expect(
      sampled.every(
        (point, index) => index === 0 || point.time > sampled[index - 1].time,
      ),
    ).toBe(true);
    expect(points.length).toBe(50001);
  });

  it("shows an honest readable scale in metres or feet without changing SI positions", () => {
    expect(mapScaleDistance(123, "metric")).toBe(100);
    expect(
      displayValue(mapScaleDistance(123, "us"), "length", "us"),
    ).toBeCloseTo(200);
    expect(mapScaleDistance(0.0007, "metric")).toBeCloseTo(0.0005);
    expect(Number.isFinite(mapScaleDistance(0, "us"))).toBe(true);
  });

  it("loads only bounded, finite local landmarks without trusting broken browser storage", () => {
    expect(parseMapLandmarks("not JSON")).toEqual([]);
    expect(parseMapLandmarks('{"east":1}')).toEqual([]);
    expect(
      parseMapLandmarks(
        JSON.stringify([
          { id: "p1", name: "  Target field  ", east: -12, north: 40 },
          { id: "p1", name: "Duplicate", east: 0, north: 0 },
          { id: "p2", name: "Broken", east: null, north: 0 },
          { id: "p3", name: "", east: 1, north: 1 },
        ]),
      ),
    ).toEqual([{ id: "p1", name: "Target field", east: -12, north: 40 }]);
    expect(
      parseMapLandmarks(
        JSON.stringify(
          Array.from({ length: 60 }, (_, index) => ({
            id: `p${index}`,
            name: "A",
            east: index,
            north: 0,
          })),
        ),
      ),
    ).toHaveLength(50);
  });
});
