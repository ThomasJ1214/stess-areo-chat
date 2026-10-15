import { useMemo, useState } from "react";
import { Chart } from "./Controls";
import HelpTip from "./HelpTip";
import { displayValue, unitLabel } from "./units";
import type { Quantity } from "./units";
import type { Units } from "./types";

type Plot = {
  key: string;
  title: string;
  kind: Quantity | null;
  color: string;
  unit?: string;
};
const overview: Plot[] = [
  { key: "altitude", title: "Altitude", kind: "length", color: "#77c9c0" },
  { key: "velocity", title: "Velocity", kind: "speed", color: "#e0b176" },
  {
    key: "dynamic_pressure",
    title: "Dynamic pressure",
    kind: "pressure",
    color: "#92aee4",
  },
  {
    key: "stress",
    title: "Beam stress estimate",
    kind: "stress",
    color: "#c498da",
  },
];
const plotGroups: Record<string, Plot[]> = {
  Overview: overview,
  "Loads & stress": [
    { key: "thrust", title: "Thrust", kind: "force", color: "#77c9c0" },
    {
      key: "drag",
      title: "Total aerodynamic drag",
      kind: "force",
      color: "#e0b176",
    },
    {
      key: "specific_acceleration",
      title: "Specific acceleration",
      kind: "acceleration",
      color: "#92aee4",
    },
    overview[3],
  ],
  "Wind & air": [
    {
      key: "air_relative_speed",
      title: "Air-relative speed",
      kind: "speed",
      color: "#77c9c0",
    },
    {
      key: "wind_speed_magnitude",
      title: "Local wind and modeled gust speed",
      kind: "speed",
      color: "#e0b176",
    },
    { key: "mach", title: "Mach", kind: null, color: "#92aee4" },
    overview[2],
  ],
  "Attitude & recovery": [
    {
      key: "angle_of_attack_deg",
      title: "Calculated angle of attack",
      kind: null,
      unit: "°",
      color: "#77c9c0",
    },
    {
      key: "angular_rate_magnitude",
      title: "Body angular rate magnitude",
      kind: null,
      unit: "rad/s",
      color: "#e0b176",
    },
    {
      key: "normal_force_magnitude",
      title: "Aerodynamic normal force",
      kind: "force",
      color: "#92aee4",
    },
    {
      key: "canopy_opening_load_n",
      title: "Lumped recovery load",
      kind: "force",
      color: "#c498da",
    },
  ],
  "Dynamic fin FEA": [
    {
      key: "dynamic_stress",
      title: "Dynamic fin bending stress",
      kind: "stress",
      color: "#77c9c0",
    },
    {
      key: "dynamic_fin_deflection",
      title: "Dynamic fin deflection",
      kind: "length",
      color: "#e0b176",
    },
    {
      key: "dynamic_fin_safety_factor",
      title: "Dynamic fin yield safety factor",
      kind: null,
      color: "#92aee4",
    },
    overview[3],
  ],
};
const plotDefinitions: Record<string, string> = {
  altitude:
    "Height above the launch ground level (AGL), calculated from the trajectory.",
  velocity:
    "Rocket speed relative to the ground. Aerodynamic loads instead use air-relative speed after subtracting the wind.",
  specific_acceleration:
    "Acceleration excluding gravitational freefall. This measures applied force per unit mass; ideal ballistic freefall is zero. Instantaneous canopy deployment is not a resolved opening-shock model.",
  air_relative_speed:
    "Magnitude of rocket velocity minus the actual ambient wind vector. This speed drives Mach, dynamic pressure and drag.",
  wind_speed_magnitude:
    "Magnitude of the calculated local wind vector, including the selected modeled gusts, mean wind shear and scheduled environment changes. Gusts are an atmospheric disturbance model, not resolved turbulent CFD.",
  stress:
    "Maximum supported quasi-static beam/fin stress estimate for this flight sample, including supported inertial loads. Missing values mean unavailable, not zero stress; this is not transient FEA or recovery opening shock.",
  drag: "Combined body and deployed-recovery aerodynamic drag magnitude from the flight model. Body and canopy force vectors are separately available in the exported flight data.",
  thrust:
    "Force interpolated from the assigned motor's actual thrust curve, with ignition and burnout timing. Synthetic demonstration motors are labeled examples.",
  angle_of_attack_deg:
    "Actual incidence between the calculated nose axis and rocket air-relative velocity, in degrees. Large angles exceed the simplified aerodynamic model's useful range; inspect the run's warnings.",
  angular_rate_magnitude:
    "Magnitude of the computed body angular-velocity vector in radians per second. Available for the rigid-body solver; missing point-mass values are unavailable, not zero rotation.",
  normal_force_magnitude:
    "Magnitude of the actual computed aerodynamic normal-force vector, perpendicular to the nose axis. This uses engineering coefficients, not a CFD solution.",
  canopy_opening_load_n:
    "Calculated q × effective recovery drag area during prescribed inflation. This is a lumped force estimate, not line shock, canopy FEA or parachute suspension dynamics.",
  dynamic_stress:
    "Actual time-integrated one-dimensional Euler–Bernoulli fin beam FEA bending stress under the saved flight loads. It ends at recovery and omits unsupported geometry or aerodynamic incidence. This is not full vehicle transient solid FEA.",
  dynamic_fin_deflection:
    "Maximum absolute supported fin beam deflection from the time-integrated structural solution. Null samples preserve gaps where loads or supported geometry are unavailable.",
  dynamic_fin_safety_factor:
    "Minimum reported yield safety factor across the supported dynamic fin beam solutions. Scalar isotropic composite approximations do not establish laminate failure strength.",
};

const vectorMagnitude = (value: unknown) =>
  Array.isArray(value) &&
  value.length === 3 &&
  value.every((v) => typeof v === "number" && Number.isFinite(v))
    ? Math.hypot(...value)
    : null;
/** Derive presentation scalars solely from actual emitted vectors/results. */
export function flightChartValues(
  row: Record<string, unknown>,
): Record<string, unknown> {
  const forces = row.force_vectors_n as Record<string, unknown> | undefined;
  const fins = Array.isArray(row.dynamic_structural_components)
    ? (row.dynamic_structural_components as Record<string, unknown>[])
    : [];
  const finite = (key: string) =>
    fins
      .map((fin) => fin[key])
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const deflections = finite("deflection_m");
  const safety = finite("safety_factor");
  return {
    ...row,
    wind_speed_magnitude: vectorMagnitude(row.wind_vector),
    angular_rate_magnitude: vectorMagnitude(row.angular_velocity_body_rad_s),
    normal_force_magnitude: vectorMagnitude(forces?.aerodynamic_normal),
    dynamic_fin_deflection: deflections.length
      ? Math.max(...deflections.map(Math.abs))
      : null,
    dynamic_fin_safety_factor: safety.length ? Math.min(...safety) : null,
  };
}

/** Keep full-resolution plot inputs stable while the playback cursor advances. */
export default function FlightCharts({
  trajectory,
  units,
  time,
  flightModel,
  windModel,
  structuralMode,
}: {
  trajectory: Record<string, unknown>[];
  units: Units;
  time: number;
  flightModel?: string;
  windModel?: string;
  structuralMode?: string;
}) {
  const [group, setGroup] = useState("Overview");
  const plots = plotGroups[group];
  const data = useMemo(
    () =>
      trajectory.map((row) => {
        const values = flightChartValues(row);
        return Object.fromEntries([
          ["time", row.time],
          ...plots.map(({ key, kind }) => {
            const value = values[key];
            return [
              key,
              typeof value === "number" && Number.isFinite(value)
                ? kind
                  ? displayValue(value, kind, units)
                  : value
                : null,
            ];
          }),
        ]);
      }),
    [trajectory, units, plots],
  );
  const series = useMemo(
    () =>
      plots.map((plot) => [
        {
          key: plot.key,
          label: `${plot.title}${plot.kind ? ` · ${unitLabel(plot.kind, units)}` : plot.unit ? ` · ${plot.unit}` : ""}`,
          color: plot.color,
        },
      ]),
    [units, plots],
  );
  return (
    <div className="flight-charts">
      <label style={{ gridColumn: "1 / -1" }}>
        Flight graph group{" "}
        <select
          aria-label="Flight graph group"
          value={group}
          onChange={(e) => setGroup(e.target.value)}
        >
          {Object.keys(plotGroups).map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
        <p className="solver-note">
          Saved samples ·{" "}
          {flightModel === "rigid_body"
            ? "rigid-body 6DOF"
            : "point-mass flight"}{" "}
          ·{" "}
          {windModel === "dryden"
            ? "Dryden modeled gusts"
            : "smooth modeled gusts"}
          .{" "}
          {structuralMode === "dynamic_fins"
            ? "Dynamic fin plots use actual 1D beam FEA; whole-vehicle stress remains an estimate."
            : "Stress uses quasi-static beam/fin estimates."}{" "}
          Missing fields and unsupported intervals appear as gaps. Specific
          acceleration excludes gravitational freefall.
        </p>
      </label>
      {plots.map((plot, index) => (
        <div className="chart-card" key={plot.key}>
          <h4>
            {series[index][0].label}{" "}
            <HelpTip term={plot.title} definition={plotDefinitions[plot.key]} />
          </h4>
          <Chart data={data} series={series[index]} time={time} />
        </div>
      ))}
    </div>
  );
}
