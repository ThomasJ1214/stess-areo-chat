import { describe, expect, it } from "vitest";
import { defaultConditions } from "./types";
import { appendFlightWindEvent } from "./flightWindEvents";

const change = {
  time_s: 3.5,
  wind_speed: 12,
  wind_direction: 70,
  turbulence: 0.2,
  transition_s: 1,
  temperature_delta: null,
};
describe("causal reactive environment requests", () => {
  it("appends actual solver inputs without changing initial conditions or prior events", () => {
    const original = structuredClone(defaultConditions);
    const first = appendFlightWindEvent(original, change);
    const next = appendFlightWindEvent(first, {
      ...change,
      time_s: 5,
      wind_speed: 20,
    });
    expect(original).toEqual(defaultConditions);
    expect(first.wind_events).toEqual([change]);
    expect(next.wind_events[0]).toEqual(change);
    expect(next.wind_speed).toBe(defaultConditions.wind_speed);
    expect(next.seed).toBe(defaultConditions.seed);
    next.wind_events[0].wind_speed = 90;
    expect(first.wind_events[0].wind_speed).toBe(12);
  });
  it("rejects edits to earlier history and overlapping transitions with actionable guidance", () => {
    const source = appendFlightWindEvent(defaultConditions, change);
    for (const time_s of [2, 3.5, 4])
      expect(() =>
        appendFlightWindEvent(source, { ...change, time_s }),
      ).toThrow("Select a time after the last change");
    expect(
      appendFlightWindEvent(source, { ...change, time_s: 4.5 }).wind_events,
    ).toHaveLength(2);
  });
  it("rejects nonfinite or out-of-range conditions instead of faking a visual change", () => {
    for (const event of [
      { ...change, wind_speed: NaN },
      { ...change, turbulence: 1.1 },
      { ...change, transition_s: -1 },
      { ...change, time_s: 500 },
      { ...change, temperature_delta: 100 },
    ])
      expect(() => appendFlightWindEvent(defaultConditions, event)).toThrow();
  });
});
