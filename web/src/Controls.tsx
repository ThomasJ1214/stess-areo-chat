import { useState, useRef, useEffect } from "react";
import { Info, Check, ShieldCheck, Activity } from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Legend,
} from "recharts";
import { fmt, displayValue, fromDisplay, unitLabel } from "./units";
import type { Quantity } from "./units";
import type { Units } from "./types";
export function NumberField({
  label,
  value,
  onChange,
  unit = "",
  min,
  max,
  step = "any",
  hint,
}: {
  label: string;
  value: number | null;
  onChange: (n: number | null) => void;
  unit?: string;
  min?: number;
  max?: number;
  step?: number | string;
  hint?: string;
}) {
  // Keep partial decimal/scientific/negative text editable; persist only finite numbers.
  const [text, setText] = useState(value === null ? "" : String(value));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(value === null ? "" : String(value));
  }, [value]);
  const commit = (raw: string) => {
    setText(raw);
    if (!raw.trim()) onChange(null);
    else if (Number.isFinite(Number(raw))) onChange(Number(raw));
  };
  return (
    <label className="field">
      <span>
        {label}
        {hint && (
          <span title={hint}>
            <Info size={12} />
          </span>
        )}
      </span>
      <div className="input-unit">
        <input
          type="text"
          inputMode="decimal"
          role="spinbutton"
          aria-label={label}
          aria-valuenow={value ?? undefined}
          aria-valuemin={min}
          aria-valuemax={max}
          aria-invalid={!!text.trim() && !Number.isFinite(Number(text))}
          value={text}
          onFocus={() => {
            focused.current = true;
          }}
          onBlur={() => {
            focused.current = false;
            setText(
              text.trim() && Number.isFinite(Number(text))
                ? String(Number(text))
                : value === null
                  ? ""
                  : String(value),
            );
          }}
          onChange={(e) => commit(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowUp" || e.key === "ArrowDown") {
              e.preventDefault();
              const base = Number.isFinite(Number(text))
                ? Number(text)
                : (value ?? 0);
              const increment = typeof step === "number" ? step : 1;
              const next = Math.max(
                min ?? -Infinity,
                Math.min(
                  max ?? Infinity,
                  base + (e.key === "ArrowUp" ? increment : -increment),
                ),
              );
              commit(String(next));
            }
          }}
        />
        {unit && <small>{unit}</small>}
      </div>
    </label>
  );
}
export function SIField({
  kind,
  units,
  ...props
}: {
  kind: Quantity;
  units: Units;
  label: string;
  value: number | null;
  onChange: (n: number | null) => void;
  min?: number;
  max?: number;
  hint?: string;
}) {
  return (
    <NumberField
      {...props}
      value={
        props.value === null
          ? null
          : Number(displayValue(props.value, kind, units).toPrecision(8))
      }
      onChange={(n) =>
        props.onChange(n === null ? null : fromDisplay(n, kind, units))
      }
      unit={unitLabel(kind, units)}
    />
  );
}
export function Toggle({
  label,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  value: boolean;
  onChange: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      className={`toggle ${value ? "enabled" : ""}`}
      disabled={disabled}
      onClick={onChange}
      aria-pressed={value}
    >
      <span>{value && <Check size={10} />}</span>
      {label}
    </button>
  );
}
export function Metric({
  label,
  value,
  unit,
  color,
}: {
  label: string;
  value: unknown;
  unit?: string;
  color?: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong style={color ? { color } : undefined}>
        {typeof value === "number" ? fmt(value) : String(value ?? "—")}{" "}
        <small>{unit}</small>
      </strong>
    </div>
  );
}
export function Fidelity({
  data,
  compact = false,
}: {
  data: any;
  compact?: boolean;
}) {
  if (!data) return null;
  return (
    <div className={`fidelity ${compact ? "compact" : ""}`}>
      <ShieldCheck size={15} />
      <div>
        <strong>
          {typeof data.fidelity === "string"
            ? data.fidelity
            : "Engineering estimate"}
        </strong>
        {data.backend && <span className="backend-badge">{data.backend}</span>}
        {!compact && data.warnings?.length > 0 && (
          <ul>
            {data.warnings.map((w: string, i: number) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
export function Empty({
  icon: Icon = Activity,
  title,
  children,
}: {
  icon?: typeof Activity;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <Icon size={25} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Chart({
  data,
  x = "time",
  series,
  height = 150,
  time,
}: {
  data: any[];
  x?: string;
  series: { key: string; label: string; color: string }[];
  height?: number;
  time?: number;
}) {
  return (
    <div style={{ height, width: "100%" }}>
      <ResponsiveContainer>
        <LineChart
          data={data}
          margin={{ top: 10, right: 15, bottom: 0, left: 0 }}
        >
          <CartesianGrid
            stroke="#283444"
            strokeDasharray="3 4"
            vertical={false}
          />
          <XAxis
            dataKey={x}
            type="number"
            domain={["dataMin", "dataMax"]}
            tick={{ fill: "#8495a9", fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: "#283444" }}
            tickFormatter={(v) => fmt(v, 1)}
          />
          <YAxis
            width={46}
            tick={{ fill: "#8495a9", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => fmt(v, 0)}
          />
          <Tooltip
            contentStyle={{
              background: "#1c2837",
              border: "1px solid #394658",
              borderRadius: 8,
              fontSize: 11,
            }}
            labelFormatter={(v) =>
              `${x === "time" ? "Time " : ""}${fmt(Number(v), 2)}${x === "time" ? " s" : ""}`
            }
            formatter={(v: any) => fmt(Number(v), 3)}
          />
          {series.map((s) => (
            <Line
              key={s.key}
              type="linear"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={1.8}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
          ))}
          {time !== undefined && (
            <ReferenceLine x={time} stroke="#ddac70" strokeDasharray="3 3" />
          )}
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 10 }} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
export function FieldSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (s: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {children}
      </select>
    </label>
  );
}
