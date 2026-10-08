import { describe, it, expect } from "vitest";
import {
  displayValue,
  fromDisplay,
  nearestRow,
  csv,
  fmt,
  quantity,
  fitSphereDistance,
} from "./units";
describe("engineering presentation", () => {
  it("round trips SI quantities without modifying physics inputs", () => {
    for (const kind of [
      "length",
      "speed",
      "mass",
      "pressure",
      "stress",
      "area",
      "force",
      "density",
      "acceleration",
      "energy",
    ] as const)
      for (const units of ["metric", "us"] as const)
        expect(
          fromDisplay(displayValue(1234.5, kind, units), kind, units),
        ).toBeCloseTo(1234.5, 6);
  });
  it("preserves small nonzero engineering results instead of displaying apparent zero", () => {
    expect(fmt(1.234e-8)).toBe("1.23e-8");
    expect(fmt(-1e-9)).toBe("-1.00e-9");
    expect(fmt(0.0012, 2)).toBe("1.20e-3");
    expect(fmt(0.0000001, 5)).toBe("1.00000e-7");
    expect(quantity(1e-8, "length", "metric")).toBe("1.00e-8 m");
    expect(quantity(0.001, "pressure", "metric")).toBe("1.00e-6 kPa");
    expect(Number.parseFloat(quantity(1e-8, "length", "us"))).toBeGreaterThan(
      0,
    );
  });
  it("keeps true zero distinct from unavailable or nonfinite results", () => {
    expect(fmt(0)).toBe(
      (0).toLocaleString(undefined, {
        minimumFractionDigits: 1,
        maximumFractionDigits: 2,
      }),
    );
    expect(fmt(-0)).toBe(fmt(0));
    for (const absent of [null, undefined, NaN, Infinity, -Infinity]) {
      expect(fmt(absent)).toBe("—");
      expect(quantity(absent, "length", "metric")).toBe("—");
    }
  });
  it("fits a cube bounding sphere in both camera cones including narrow viewports", () => {
    const radius = Math.sqrt(3) * 0.05;
    for (const aspect of [0.5, 1, 2.4]) {
      const distance = fitSphereDistance(radius, 42, aspect);
      const vHalf = (42 * Math.PI) / 360,
        hHalf = Math.atan(Math.tan(vHalf) * aspect);
      expect(distance * Math.sin(vHalf)).toBeGreaterThanOrEqual(radius * 1.119);
      expect(distance * Math.sin(hHalf)).toBeGreaterThanOrEqual(radius * 1.119);
    }
    expect(fitSphereDistance(1, 60, 2, 1)).toBeCloseTo(2, 12);
    expect(fitSphereDistance(radius, 42, 0.5)).toBeGreaterThan(
      fitSphereDistance(radius, 42, 2),
    );
  });
  it("selects nearest timeline sample at edges and between samples", () => {
    const rows = [{ time: 0 }, { time: 1 }, { time: 3 }];
    expect(nearestRow(rows, -1)).toEqual(rows[0]);
    expect(nearestRow(rows, 1.1)).toEqual(rows[1]);
    expect(nearestRow(rows, 10)).toEqual(rows[2]);
    expect(nearestRow([], 2)).toBeNull();
  });
  it("escapes exported CSV fields", () =>
    expect(csv([{ name: 'fin, "A"', value: 3 }])).toBe(
      '"name","value"\r\n"fin, ""A""","3"',
    ));
});
