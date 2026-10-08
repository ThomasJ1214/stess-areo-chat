import { useMemo } from "react";
import { Chart } from "./Controls";
import { displayValue, unitLabel } from "./units";
import type { Quantity } from "./units";
import type { Units } from "./types";

const plots: { key: string; title: string; kind: Quantity; color: string }[] = [
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

/** Keep full-resolution plot inputs stable while the playback cursor advances. */
export default function FlightCharts({
  trajectory,
  units,
  time,
}: {
  trajectory: Record<string, number | null>[];
  units: Units;
  time: number;
}) {
  const data = useMemo(
    () =>
      trajectory.map((row) =>
        Object.fromEntries([
          ["time", row.time],
          ...plots.map(({ key, kind }) => [
            key,
            typeof row[key] === "number" && Number.isFinite(row[key])
              ? displayValue(row[key], kind, units)
              : null,
          ]),
        ]),
      ),
    [trajectory, units],
  );
  const series = useMemo(
    () =>
      plots.map((plot) => [
        {
          key: plot.key,
          label: `${plot.title} · ${unitLabel(plot.kind, units)}`,
          color: plot.color,
        },
      ]),
    [units],
  );
  return (
    <div className="flight-charts">
      {plots.map((plot, index) => (
        <div className="chart-card" key={plot.key}>
          <h4>{series[index][0].label}</h4>
          <Chart data={data} series={series[index]} time={time} />
        </div>
      ))}
    </div>
  );
}
