import type { Units } from "./types";
export type Quantity =
  | "length"
  | "speed"
  | "mass"
  | "force"
  | "pressure"
  | "stress"
  | "area"
  | "density"
  | "energy"
  | "acceleration";
const definitions: Record<
  Quantity,
  { metric: string; us: string; factor: number }
> = {
  length: { metric: "m", us: "ft", factor: 3.280839895 },
  speed: { metric: "m/s", us: "ft/s", factor: 3.280839895 },
  mass: { metric: "kg", us: "lb", factor: 2.2046226218 },
  force: { metric: "N", us: "lbf", factor: 0.2248089431 },
  pressure: { metric: "kPa", us: "psi", factor: 0.000145037738 },
  stress: { metric: "MPa", us: "ksi", factor: 0.000000145037738 },
  area: { metric: "m²", us: "ft²", factor: 10.76391042 },
  density: { metric: "kg/m³", us: "lb/ft³", factor: 0.06242796 },
  energy: { metric: "J", us: "ft·lbf", factor: 0.7375621493 },
  acceleration: { metric: "m/s²", us: "ft/s²", factor: 3.280839895 },
};
export function displayValue(
  value: number,
  kind: Quantity,
  units: Units,
): number {
  return units === "us"
    ? value * definitions[kind].factor
    : value / (kind === "pressure" ? 1000 : kind === "stress" ? 1e6 : 1);
}
export function fromDisplay(
  value: number,
  kind: Quantity,
  units: Units,
): number {
  return units === "us"
    ? value / definitions[kind].factor
    : value * (kind === "pressure" ? 1000 : kind === "stress" ? 1e6 : 1);
}
export function unitLabel(kind: Quantity, units: Units): string {
  return definitions[kind][units];
}
export function fmt(value: unknown, digits = 2): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  // Do not turn a computed displacement, elapsed flow time, or load into apparent zero.
  if (value !== 0 && Math.abs(value) < 10 ** -digits)
    return value.toExponential(Math.max(1, digits));
  return (Object.is(value, -0) ? 0 : value).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: Math.min(digits, 1),
  });
}
export function quantity(
  value: unknown,
  kind: Quantity,
  units: Units,
  digits = 2,
): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${fmt(displayValue(value, kind, units), digits)} ${unitLabel(kind, units)}`
    : "—";
}
export function nearestRow(rows: any[], time: number): any {
  if (!rows.length) return null;
  let lo = 0,
    hi = rows.length - 1;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (rows[mid].time < time) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 &&
    Math.abs(rows[lo - 1].time - time) < Math.abs(rows[lo].time - time)
    ? rows[lo - 1]
    : rows[lo];
}
export function csv(rows: Record<string, unknown>[]): string {
  if (!rows.length) return "";
  const keys = Array.from(new Set(rows.flatMap(Object.keys)));
  const cell = (x: unknown) => `"${String(x ?? "").replaceAll('"', '""')}"`;
  return [
    keys.map(cell).join(","),
    ...rows.map((r) => keys.map((k) => cell(r[k])).join(",")),
  ].join("\r\n");
}

/** Distance that keeps an entire sphere inside both perspective field-of-view cones. */
export function fitSphereDistance(
  radius: number,
  verticalFovDegrees: number,
  aspect: number,
  margin = 1.12,
): number {
  const verticalHalf = (verticalFovDegrees * Math.PI) / 360;
  const horizontalHalf = Math.atan(Math.tan(verticalHalf) * aspect);
  return (
    (Math.max(radius, 1e-9) * margin) /
    Math.sin(Math.min(verticalHalf, horizontalHalf))
  );
}
