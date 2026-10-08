import type { Conditions, Units } from "./types";
import { displayValue, fromDisplay } from "./units";

export interface FlightMapPoint {
  east: number;
  north: number;
  time: number;
  altitude: number | null;
  rowIndex: number;
}

export interface FlightMapEvent extends FlightMapPoint {
  name: string;
  label: string;
  color: string;
}

export interface FlightMapBounds {
  east: number;
  north: number;
  /** Horizontal extent in metres, including the fit margin. */
  span: number;
}

export interface MapLandmark {
  id: string;
  name: string;
  east: number;
  north: number;
}

/** Local UI markers only; these are never engineering/project coordinates. */
export function parseMapLandmarks(value: string | null): MapLandmark[] {
  if (!value) return [];
  try {
    const data: unknown = JSON.parse(value);
    if (!Array.isArray(data)) return [];
    const ids = new Set<string>();
    return data.slice(0, 50).flatMap((entry) => {
      if (
        !entry ||
        typeof entry !== "object" ||
        typeof entry.id !== "string" ||
        !entry.id ||
        entry.id.length > 100 ||
        ids.has(entry.id) ||
        typeof entry.name !== "string" ||
        !entry.name.trim() ||
        !finite(entry.east) ||
        !finite(entry.north)
      )
        return [];
      ids.add(entry.id);
      return [
        {
          id: entry.id,
          name: entry.name.trim().slice(0, 80),
          east: entry.east,
          north: entry.north,
        },
      ];
    });
  } catch {
    return [];
  }
}

const eventStyles: Record<string, { label: string; color: string }> = {
  rail_exit: { label: "Rail exit", color: "#6bcfdf" },
  burnout: { label: "Motor burnout", color: "#efa967" },
  max_q: { label: "Maximum dynamic pressure (Max Q)", color: "#edc46b" },
  max_acceleration: { label: "Maximum acceleration", color: "#f89983" },
  max_velocity: { label: "Maximum speed", color: "#8fc8ed" },
  apogee: { label: "Apogee / highest point", color: "#c2a1ed" },
  drogue_deployment: { label: "Drogue parachute opens", color: "#72d5aa" },
  main_deployment: { label: "Main parachute opens", color: "#92df86" },
  recovery: { label: "Ground contact", color: "#f5cc70" },
};

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Only solver coordinates are positions; missing values never become the pad. */
export function flightMapPoint(
  row: Record<string, unknown> | null | undefined,
  rowIndex = -1,
): FlightMapPoint | null {
  if (!row || !finite(row.east) || !finite(row.north) || !finite(row.time))
    return null;
  return {
    east: row.east,
    north: row.north,
    time: row.time,
    altitude: finite(row.altitude) ? row.altitude : null,
    rowIndex,
  };
}

export function flightMapPoints(
  rows: Record<string, unknown>[],
): FlightMapPoint[] {
  return rows.flatMap((row, index) => {
    const point = flightMapPoint(row, index);
    return point ? [point] : [];
  });
}

export function flightMapEvents(
  rows: Record<string, unknown>[],
  events: Record<string, unknown>[],
): FlightMapEvent[] {
  const points = flightMapPoints(rows);
  if (!points.length) return [];
  return events.flatMap((event) => {
    if (
      typeof event.name !== "string" ||
      !eventStyles[event.name] ||
      !finite(event.time) ||
      event.time < points[0].time - 1e-5 ||
      event.time > points.at(-1)!.time + 1e-5
    )
      return [];
    // The solver inserts exact event samples. Its index is preferred; old files
    // without an index use the closest recorded sample, never a fabricated point.
    const indexed =
      finite(event.index) && Number.isInteger(event.index)
        ? flightMapPoint(rows[event.index], event.index)
        : null;
    const point =
      indexed && Math.abs(indexed.time - event.time) < 1e-5
        ? indexed
        : points.reduce((nearest, value) =>
            Math.abs(value.time - (event.time as number)) <
            Math.abs(nearest.time - (event.time as number))
              ? value
              : nearest,
          );
    // A time-limited trajectory is not a landing. Ground contact needs the
    // actual solver event and a recorded position on the ground plane.
    if (
      event.name === "recovery" &&
      (point.altitude === null ||
        Math.abs(point.altitude) > 1e-4 ||
        Math.abs(point.time - event.time) > 1e-5)
    )
      return [];
    return [
      {
        ...point,
        time: event.time,
        name: event.name,
        ...eventStyles[event.name],
      },
    ];
  });
}

/** East/north horizontal rail projection; angle is measured from vertical. */
export function railMapEnd(conditions: Conditions): [number, number] {
  const radians = Math.PI / 180;
  const horizontal =
    conditions.rail_length * Math.sin(conditions.launch_angle * radians);
  return [
    horizontal * Math.sin(conditions.launch_azimuth * radians),
    horizontal * Math.cos(conditions.launch_azimuth * radians),
  ];
}

/** Actual current gust if available, otherwise the entered mean toward wind. */
export function mapWind(
  row: Record<string, unknown> | null | undefined,
  conditions: Conditions,
): [number, number] {
  if (
    Array.isArray(row?.wind_vector) &&
    finite(row.wind_vector[0]) &&
    finite(row.wind_vector[1])
  )
    return [row.wind_vector[0], row.wind_vector[1]];
  const direction = (conditions.wind_direction * Math.PI) / 180;
  return [
    conditions.wind_speed * Math.sin(direction),
    conditions.wind_speed * Math.cos(direction),
  ];
}

/** Always fit the complete path, pad and rail, including negative drift. */
export function flightMapBounds(
  points: FlightMapPoint[],
  railEnd: [number, number],
  aspect: number,
): FlightMapBounds {
  let minEast = Math.min(0, railEnd[0]),
    maxEast = Math.max(0, railEnd[0]);
  let minNorth = Math.min(0, railEnd[1]),
    maxNorth = Math.max(0, railEnd[1]);
  for (const point of points) {
    minEast = Math.min(minEast, point.east);
    maxEast = Math.max(maxEast, point.east);
    minNorth = Math.min(minNorth, point.north);
    maxNorth = Math.max(maxNorth, point.north);
  }
  return {
    east: (minEast + maxEast) / 2,
    north: (minNorth + maxNorth) / 2,
    span:
      Math.max(20, maxEast - minEast, (maxNorth - minNorth) * aspect) * 1.24,
  };
}

/** Bounded drawing work, while preserving endpoints, extrema and event samples. */
export function sampleFlightMapPoints(
  points: FlightMapPoint[],
  eventRowIndices: number[] = [],
  budget = 1200,
): FlightMapPoint[] {
  if (points.length <= Math.max(2, budget)) return points;
  const count = Math.max(2, Math.floor(budget));
  const indices = new Set<number>();
  for (let i = 0; i < count; i++)
    indices.add(Math.round((i * (points.length - 1)) / (count - 1)));
  const requested = new Set(eventRowIndices);
  let minEast = 0,
    maxEast = 0,
    minNorth = 0,
    maxNorth = 0;
  for (let i = 0; i < points.length; i++) {
    if (requested.has(points[i].rowIndex)) indices.add(i);
    if (points[i].east < points[minEast].east) minEast = i;
    if (points[i].east > points[maxEast].east) maxEast = i;
    if (points[i].north < points[minNorth].north) minNorth = i;
    if (points[i].north > points[maxNorth].north) maxNorth = i;
  }
  for (const index of [
    0,
    points.length - 1,
    minEast,
    maxEast,
    minNorth,
    maxNorth,
  ])
    indices.add(index);
  return [...indices].sort((a, b) => a - b).map((index) => points[index]);
}

/** A readable 1/2/5 distance no longer than the requested scale bar. */
export function mapScaleDistance(targetMetres: number, units: Units): number {
  const target = Math.max(1e-12, displayValue(targetMetres, "length", units));
  const power = 10 ** Math.floor(Math.log10(target));
  const ratio = target / power;
  const distance = (ratio >= 5 ? 5 : ratio >= 2 ? 2 : 1) * power;
  return fromDisplay(distance, "length", units);
}
