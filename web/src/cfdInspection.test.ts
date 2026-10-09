import { describe, expect, it } from "vitest";
import { cfdCutawayPlane } from "./cfdInspection";
import { defaultCfdFlowSettings } from "./flowFieldMath";

describe("viewer-only CAD/CFD cutaway", () => {
  it("clips in original SI coordinates and reverses only the display side", () => {
    const minimum: [number, number, number] = [2, -0.1, -0.2];
    const maximum: [number, number, number] = [5, 0.3, 0.6];
    const before = JSON.stringify([minimum, maximum]);
    const settings = {
      ...defaultCfdFlowSettings,
      cutaway: true,
      cutawayAxis: "z" as const,
      cutawayPosition: 0.25,
    };
    expect(cfdCutawayPlane(minimum, maximum, settings)).toEqual({
      normal: [0, 0, 1],
      constant: -0,
    });
    expect(
      cfdCutawayPlane(minimum, maximum, { ...settings, cutawayReverse: true }),
    ).toEqual({ normal: [0, 0, -1], constant: 0 });
    expect(
      cfdCutawayPlane(minimum, maximum, {
        ...settings,
        cutawayAxis: "x",
        cutawayPosition: 0.5,
      }),
    ).toEqual({ normal: [1, 0, 0], constant: -3.5 });
    expect(JSON.stringify([minimum, maximum])).toBe(before);
  });
  it("does not create a plane without an explicit cutaway request", () => {
    expect(
      cfdCutawayPlane([0, 0, 0], [1, 1, 1], defaultCfdFlowSettings),
    ).toBeNull();
  });
});
