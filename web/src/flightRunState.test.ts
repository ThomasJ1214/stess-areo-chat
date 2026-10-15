import { describe, expect, it } from "vitest";
import { defaultConditions } from "./types";
import type { Project } from "./types";
import { flightInputKey, flightRunIsStale } from "./flightRunState";

const project = {
  id: "vehicle",
  name: "Original name",
  unit_system: "metric",
  components: [{ id: "fin", span: 0.1, transform: { translation: [0, 0, 0] } }],
  materials: [{ id: "material", youngs_modulus: 10 }],
  assets: [{ id: "cad", vertices: [[0, 0, 0]], faces: [] }],
  motors: [
    {
      id: "motor",
      curve: [
        [0, 0],
        [1, 100],
      ],
    },
  ],
  configurations: [{ id: "config", main_cd_area: 0.5 }],
  active_configuration_id: "config",
} as unknown as Project;
const options = { structural_mode: "quasi_static", damping_ratio: 0.01 };

describe("immutable flight replay identity", () => {
  it("marks physical, launch, turbulence and structural edits as stale", () => {
    const saved = flightInputKey(project, defaultConditions, options);
    for (const changed of [
      { ...project, active_configuration_id: "other" },
      { ...project, components: [{ ...project.components[0], span: 0.2 }] },
      {
        ...project,
        motors: [
          {
            ...project.motors[0],
            curve: [
              [0, 0],
              [1, 200],
            ],
          },
        ],
      },
      {
        ...project,
        configurations: [
          { ...project.configurations[0], main_inflation_time: 1 },
        ],
      },
      {
        ...project,
        materials: [{ ...project.materials[0], youngs_modulus: 20 }],
      },
      { ...project, assets: [{ ...project.assets[0], vertices: [[1, 0, 0]] }] },
    ])
      expect(
        flightRunIsStale(
          saved,
          flightInputKey(changed, defaultConditions, options),
        ),
      ).toBe(true);
    expect(
      flightRunIsStale(
        saved,
        flightInputKey(
          project,
          { ...defaultConditions, wind_model: "dryden" },
          options,
        ),
      ),
    ).toBe(true);
    expect(
      flightRunIsStale(
        saved,
        flightInputKey(
          project,
          { ...defaultConditions, flight_model: "rigid_body" },
          options,
        ),
      ),
    ).toBe(true);
    expect(
      flightRunIsStale(
        saved,
        flightInputKey(project, defaultConditions, {
          ...options,
          structural_mode: "dynamic_fins",
        }),
      ),
    ).toBe(true);
  });
  it("ignores units, project title and saved page settings while preserving source inputs", () => {
    const before = structuredClone(project);
    const saved = flightInputKey(project, defaultConditions, options);
    const changed = {
      ...project,
      name: "Renamed",
      unit_system: "us",
      analysis_settings: { cfd_options: { grid_resolution: 96 } },
    } as unknown as Project;
    expect(
      flightRunIsStale(
        saved,
        flightInputKey(changed, defaultConditions, options),
      ),
    ).toBe(false);
    expect(project).toEqual(before);
    expect(flightRunIsStale(null, saved)).toBe(false);
  });
  it("does not treat JSON object-key ordering as a physics edit", () => {
    const key = flightInputKey(project, defaultConditions, options);
    expect(
      flightInputKey(project, defaultConditions, {
        damping_ratio: 0.01,
        structural_mode: "quasi_static",
      }),
    ).toBe(key);
  });
});
