import { describe, expect, it } from "vitest";
import { defaultConditions } from "./types";
import {
  defaultCfdOptions,
  restoreCfdOptions,
  cfdRequestOptions,
  defaultFeaOptions,
  feaRequestOptions,
  mergeOptions,
  restoreSettings,
} from "./workspaceSettings";

describe("portable analysis setup", () => {
  it("opens older projects with documented defaults and preserves saved conditions", () => {
    expect(restoreSettings().conditions).toEqual(defaultConditions);
    const saved = restoreSettings({
      conditions: {
        ...defaultConditions,
        speed: 123,
        wind_speed: 7.25,
        mach: null,
      },
      cfd_options: { grid_resolution: 64, cfl: 0.2, domain_padding: 1.25 },
      fea_options: { mesh_size: 0.002, component_id: "payload" },
      study_options: { count: 24, seed: 2468 },
      study_mode: "comparison",
    });
    expect(saved.conditions.speed).toBe(123);
    expect(saved.conditions.wind_speed).toBe(7.25);
    expect(saved.cfd_options.grid_resolution).toBe(64);
    expect(saved.cfd_options.max_cells).toBe(defaultCfdOptions.max_cells);
    expect(saved.cfd_options.domain_padding).toBe(1.25);
    expect(saved.fea_options.component_id).toBe("payload");
    expect(saved.study_options.seed).toBe(2468);
    expect(saved.study_mode).toBe("comparison");
  });
  it("does not install incorrectly typed or nonfinite saved controls", () => {
    const restored = mergeOptions(defaultFeaOptions, {
      mesh_size: "small",
      max_elements: Infinity,
      traction_pa: [1000, 0, NaN],
      acceleration_m_s2: [1, 2],
      load_mode: "traction",
      unrelated: true,
    });
    expect(restored.mesh_size).toBe(defaultFeaOptions.mesh_size);
    expect(restored.max_elements).toBe(defaultFeaOptions.max_elements);
    expect(restored.traction_pa).toEqual([1000, 0, 0]);
    expect(restored.acceleration_m_s2).toEqual([0, 0, 0]);
    expect(restored.load_mode).toBe("traction");
    expect(restored).toHaveProperty("unrelated", true);
    expect(
      mergeOptions(defaultFeaOptions, {
        clamp_tolerance: 0.0001,
        custom_solver: { mesh_order: 1 },
      }),
    ).toHaveProperty("clamp_tolerance", 0.0001);
  });
  it("preserves explicit zero pressure while preventing a hidden zero aerodynamic load", () => {
    const uniform = feaRequestOptions({
      ...defaultFeaOptions,
      load_mode: "uniform_pressure",
      load_pressure_pa: 0,
    });
    expect(uniform.load_pressure_pa).toBe(0);
    for (const load_mode of ["aero_pressure", "cfd_pressure", "traction"]) {
      expect(
        feaRequestOptions({ ...defaultFeaOptions, load_mode }),
      ).not.toHaveProperty("load_pressure_pa");
    }
    expect(defaultFeaOptions.load_pressure_pa).toBe(0);
  });
  it("migrates legacy CFD budgets without binding reopened projects to stale jobs", () => {
    const restored = restoreCfdOptions({
      max_steps: 1,
      max_wall_seconds: 1,
      max_physical_time: 1,
      flow_through_times: 0.1,
      run_until_converged: false,
      flight_job_id: "expired-job",
      mode: "transient",
      transient_source: "launch",
      flight_window: "interval",
      flight_start_s: 2,
      flight_end_s: 2.01,
      domain_padding: 1.5,
      future_solver_extension: true,
    });
    for (const key of [
      "max_steps",
      "max_wall_seconds",
      "max_physical_time",
      "flow_through_times",
      "run_until_converged",
      "flight_job_id",
    ])
      expect(restored).not.toHaveProperty(key);
    expect(restored.mode).toBe("transient");
    expect(restored.flight_start_s).toBe(2);
    expect(restored.domain_padding).toBe(1.5);
    expect(restored).toHaveProperty("future_solver_extension", true);
    expect(
      restoreCfdOptions({
        mode: "transient",
        transient_source: "launch",
        flight_start_s: 1,
        flight_end_s: 1.01,
      }).flight_window,
    ).toBe("interval");
    const malformed = restoreCfdOptions({
      mode: "pretend-cfd",
      transient_source: "synthetic",
      flight_window: "yesterday",
    });
    expect(malformed.mode).toBe("steady");
    expect(malformed.transient_source).toBe("launch");
    expect(malformed.flight_window).toBe("whole");
  });
  it("sends launch intervals only when requested and preserves fixed-flow duration", () => {
    const whole = cfdRequestOptions(
      {
        ...defaultCfdOptions,
        mode: "transient",
        flight_start_s: 20,
        flight_end_s: 30,
      },
      "current-flight",
    );
    expect(whole).toHaveProperty("flight_job_id", "current-flight");
    expect(whole).not.toHaveProperty("flight_start_s");
    expect(whole).not.toHaveProperty("flight_end_s");
    expect(whole).not.toHaveProperty("duration_s");
    const interval = cfdRequestOptions({
      ...defaultCfdOptions,
      mode: "transient",
      flight_window: "interval",
      flight_start_s: 2,
      flight_end_s: 2.01,
    });
    expect(interval.flight_start_s).toBe(2);
    expect(interval.flight_end_s).toBe(2.01);
    expect(interval).not.toHaveProperty("flight_job_id");
    const fixed = cfdRequestOptions(
      {
        ...defaultCfdOptions,
        mode: "transient",
        transient_source: "fixed",
        flight_window: "interval",
        duration_s: 0.05,
        flight_job_id: "stale",
      },
      "current-flight",
    );
    expect(fixed.duration_s).toBe(0.05);
    expect(fixed).not.toHaveProperty("flight_job_id");
    expect(fixed).not.toHaveProperty("flight_start_s");
    expect(
      cfdRequestOptions(defaultCfdOptions, "current-flight"),
    ).not.toHaveProperty("flight_job_id");
  });
});
