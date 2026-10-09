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
    "Magnitude of the calculated local wind vector, including seeded smooth gust perturbations when enabled. These gusts are a sensitivity model, not resolved turbulent CFD.",
  stress:
    "Maximum supported quasi-static beam/fin stress estimate for this flight sample, including supported inertial loads. Missing values mean unavailable, not zero stress; this is not transient FEA or recovery opening shock.",
  drag: "Combined body and deployed-recovery aerodynamic drag magnitude from the flight model. Body and canopy force vectors are separately available in the exported flight data.",
  thrust:
    "Force interpolated from the assigned motor's actual thrust curve, with ignition and burnout timing. Synthetic demonstration motors are labeled examples.",
};

/** Keep full-resolution plot inputs stable while the playback cursor advances. */
export default function FlightCharts({
  trajectory,
  units,
  time,
}: {
  trajectory: Record<string, unknown>[];
  units: Units;
  time: number;
}) {
  const [group, setGroup] = useState("Overview");
  const plots = plotGroups[group];
  const data = useMemo(
    () =>
      trajectory.map((row) => {
        const wind = row.wind_vector;
        const values: Record<string, unknown> = {
          ...row,
          wind_speed_magnitude:
            Array.isArray(wind) &&
            wind.length === 3 &&
            wind.every((v) => typeof v === "number" && Number.isFinite(v))
              ? Math.hypot(...wind)
              : null,
        };
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
          label: `${plot.title}${plot.kind ? ` · ${unitLabel(plot.kind, units)}` : ""}`,
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
          Graphs follow the saved flight samples. Gusts are modeled wind
          variations; stress is a quasi-static beam/fin estimate, including
          supported inertial loads. Specific acceleration excludes gravitational
          freefall.
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
