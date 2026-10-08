import { describe, expect, it } from "vitest";
import { defaultConditions } from "./types";
import {
  defaultCfdOptions,
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
});
