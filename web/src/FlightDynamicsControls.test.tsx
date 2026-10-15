import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FlightDynamicsControls, {
  FlightConfigurationDynamics,
} from "./FlightDynamicsControls";
import { defaultConditions } from "./types";
import type { Configuration } from "./types";
import { defaultFlightOptions } from "./workspaceSettings";
import LiveFlightEnvironment from "./LiveFlightEnvironment";
import { flightChartValues } from "./FlightCharts";
import FlightStructureCoverage from "./FlightStructureCoverage";

describe("flight model controls and truthful results", () => {
  it("shows structural work exhaustion and unsupported recovery gaps independently of flight completion", () => {
    const html = renderToStaticMarkup(
      <FlightStructureCoverage
        analysis={{
          summary: {
            status: "work_budget",
            supported_components: 1,
            unavailable_components: 2,
            rows_with_available_results: 3,
            unavailable_rows: 12,
            substeps: 1000,
            coverage: "Pre-recovery load intervals only",
          },
          warnings: ["No laminate layup analysis"],
        }}
        row={{
          dynamic_structural_components: [
            {
              component_id: "cad-fin",
              name: "Detailed fin",
              supported: false,
              reason: "CAD replacement fin is unsupported",
            },
          ],
        }}
      />,
    );
    expect(html).toContain("Partial structural analysis · work budget");
    expect(html).toContain("12 unavailable samples");
    expect(html).toContain("CAD replacement fin is unsupported");
    expect(html).toContain(
      "Whole-vehicle stress remains a separate quasi-static estimate.",
    );
  });
  it("exposes actual rigid-body, Dryden and dynamic fin options with their input limits", () => {
    const html = renderToStaticMarkup(
      <FlightDynamicsControls
        conditions={{
          ...defaultConditions,
          flight_model: "rigid_body",
          wind_model: "dryden",
        }}
        onConditions={() => {}}
        options={{ ...defaultFlightOptions, structural_mode: "dynamic_fins" }}
        onOptions={() => {}}
        units="us"
      />,
    );
    for (const label of [
      "Flight dynamics model",
      "Wind model",
      "Turbulence length scale",
      "Initial roll rate",
      "Wind shear exponent",
      "Fin modal damping ratio",
      "Fin beam elements",
    ])
      expect(html).toContain(`aria-label="${label}"`);
    expect(html).toContain('value="rigid_body" selected=""');
    expect(html).toContain('value="dryden" selected=""');
    expect(html).toContain('value="dynamic_fins" selected=""');
    expect(html).toContain('aria-valuemin="2"');
    expect(html).toContain('aria-valuemax="64"');
    expect(html).toContain("Allow isotropic composite approximation");
    expect(html).toContain("not evaluate laminate ply directions");
    expect(html).toContain("ft");
  });
  it("requires source provenance for an explicit dry inertia override and exposes inflation times", () => {
    const configuration = {
      deployment: "dual",
      inertia_override_kg_m2: [
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
      ],
      inertia_override_source: "",
      main_inflation_time: 0.4,
      drogue_inflation_time: 0.2,
    } as unknown as Configuration;
    const html = renderToStaticMarkup(
      <FlightConfigurationDynamics
        configuration={configuration}
        onChange={() => {}}
        units="metric"
      />,
    );
    expect(html).toContain('aria-label="Inertia source"');
    expect(html).toContain(
      "Enter the inertia calculation or measurement source before applying.",
    );
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain('aria-label="Main chute inflation time"');
    expect(html).toContain('aria-label="Drogue inflation time"');
    expect(html).toContain("Complete dry rocket");
  });
  it("disables live environment application to stale geometry rather than changing replay physics", () => {
    const html = renderToStaticMarkup(
      <LiveFlightEnvironment
        sourceConditions={defaultConditions}
        selectedTime={4.2}
        stale
        disabled={false}
        units="metric"
        onApply={() => {}}
        onClear={() => {}}
      />,
    );
    expect(html).toMatch(
      /<button[^>]*disabled=""[^>]*aria-label="Apply environment from selected time"/,
    );
    expect(html).toContain("Recalculate the changed setup first.");
    expect(html).toContain("4.2");
    expect(html).toContain("solver recalculates the launch");
  });
  it("derives graph scalars from actual vectors and leaves unsupported dynamic intervals empty", () => {
    expect(
      flightChartValues({
        time: 2,
        wind_vector: [3, 4, 0],
        angular_velocity_body_rad_s: [0, 0.2, 0],
        force_vectors_n: { aerodynamic_normal: [0, 6, 8] },
        dynamic_structural_components: [
          { deflection_m: -0.003, safety_factor: 2 },
          { deflection_m: 0.001, safety_factor: 3 },
        ],
      }),
    ).toMatchObject({
      wind_speed_magnitude: 5,
      angular_rate_magnitude: 0.2,
      normal_force_magnitude: 10,
      dynamic_fin_deflection: 0.003,
      dynamic_fin_safety_factor: 2,
    });
    const gap = flightChartValues({
      time: 3,
      angular_velocity_body_rad_s: [NaN, 0, 0],
      dynamic_structural_components: [
        { status: "unavailable", deflection_m: null },
      ],
    });
    expect(gap.angular_rate_magnitude).toBeNull();
    expect(gap.normal_force_magnitude).toBeNull();
    expect(gap.dynamic_fin_deflection).toBeNull();
  });
});
