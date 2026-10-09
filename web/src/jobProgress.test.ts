import { describe, expect, it } from "vitest";
import type { Job } from "./types";
import {
  etaDescription,
  progressDescription,
  formatElapsed,
} from "./jobProgress";
const job: Job = {
  id: "job",
  status: "running",
  progress: 0.5,
  message: "",
  elapsed_seconds: 120,
  eta_seconds: null,
  result: null,
  error: null,
};

describe("honest simulation progress", () => {
  it("never turns steady residual settling into a completion fraction", () => {
    const steady = { ...job, progress_basis: "convergence_unknown" as const };
    expect(progressDescription(steady)).toContain("completion percent unknown");
    expect(etaDescription(steady)).toBe("ETA unknown");
    const tentative = {
      ...steady,
      eta_seconds: 100,
      eta_range_seconds: [75, 125] as [number, number],
      eta_basis: "convergence_trend" as const,
    };
    expect(etaDescription(tentative)).toBe(
      "Tentative convergence ETA 1m 15s–2m 5s",
    );
    expect(progressDescription(tentative)).toContain("percent unknown");
  });
  it("labels physical-time progress and measured integration ETA separately", () => {
    const transient = {
      ...job,
      progress_basis: "physical_time" as const,
      eta_seconds: 3660,
      eta_basis: "physical_time_throughput" as const,
      eta_confidence: "measured" as const,
    };
    expect(progressDescription(transient)).toBe("50% of physical interval");
    expect(etaDescription(transient)).toBe("Integration ETA 1h 1m");
    expect(etaDescription({ ...transient, eta_seconds: NaN })).toBe(
      "ETA calculating…",
    );
    expect(
      etaDescription({ ...transient, eta_range_seconds: [200, 100] }),
    ).toBe("Integration ETA 1h 1m");
  });
  it("clamps stale percentages and makes long elapsed times readable", () => {
    expect(progressDescription({ ...job, progress: 1.2 })).toBe(
      "100% complete",
    );
    expect(progressDescription({ ...job, progress: -1 })).toBe("0% complete");
    expect(formatElapsed(90061)).toBe("25h 1m");
  });
});
