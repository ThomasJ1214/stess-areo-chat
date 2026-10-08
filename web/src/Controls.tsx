import { useState, useRef, useEffect, useId } from "react";
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
import { numberInputIssue, parseNumberInput } from "./numericInput";
import HelpTip, { getTermDefinition } from "./HelpTip";
export function NumberField({
  label,
  value,
  onChange,
  unit = "",
  min,
  max,
  step = "any",
  hint,
  normalize,
  disabled = false,
}: {
  label: string;
  value: number | null;
  onChange: (n: number | null) => void;
  unit?: string;
  min?: number;
  max?: number;
  step?: number | string;
  hint?: string;
  normalize?: (n: number) => number;
  disabled?: boolean;
}) {
  // Keep partial decimal/scientific/negative text editable; persist only finite numbers.
  const [text, setText] = useState(value === null ? "" : String(value));
  const focused = useRef(false);
  const lastEmitted = useRef<number | null | undefined>(undefined);
  const fieldId = useId();
  const issue = numberInputIssue(text, min, max);
  useEffect(() => {
    // Preserve an in-progress edit only when this field caused the update.
    // Project/settings loads must also replace a currently focused field.
    if (!focused.current || value !== lastEmitted.current)
      setText(value === null ? "" : String(value));
    lastEmitted.current = undefined;
  }, [value]);
  const commit = (raw: string) => {
    setText(raw);
    if (!raw.trim()) {
      lastEmitted.current = null;
      onChange(null);
    } else {
      const parsed = parseNumberInput(raw);
      if (parsed !== null) {
        lastEmitted.current = normalize ? normalize(parsed) : parsed;
        onChange(parsed);
      }
    }
  };
  return (
    <div className={`field ${issue ? "invalid-field" : ""}`}>
      <span>
        {label}
        <HelpTip
          term={label}
          definition={
            hint
              ? [getTermDefinition(label), hint].filter(Boolean).join(" ")
              : undefined
          }
        />
      </span>
      <div className="input-unit">
        <input
          disabled={disabled}
          type="text"
          inputMode="decimal"
          role="spinbutton"
          id={fieldId}
          aria-label={label}
          aria-valuenow={value ?? undefined}
          aria-valuemin={min}
          aria-valuemax={max}
          aria-invalid={!!issue}
          aria-describedby={
            issue ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined
          }
          value={text}
          onFocus={() => {
            focused.current = true;
          }}
          onBlur={() => {
            focused.current = false;
            // Keep malformed nonempty edits visible: clicking Run must not
            // silently revert them and simulate an older valid value.
            if (!text.trim() || parseNumberInput(text) !== null)
              setText(value === null ? "" : String(value));
          }}
          onChange={(e) => commit(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowUp" || e.key === "ArrowDown") {
              e.preventDefault();
              const base = parseNumberInput(text) ?? value ?? 0;
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
      {hint && (
        <small id={`${fieldId}-hint`} className="sr-only">
          {hint}
        </small>
      )}
      {issue && (
        <small id={`${fieldId}-error`} className="field-error">
          {issue}
        </small>
      )}
    </div>
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
  const present = (n: number) =>
    Number(displayValue(n, kind, units).toPrecision(8));
  const min = props.min === undefined ? undefined : present(props.min);
  const max = props.max === undefined ? undefined : present(props.max);
  return (
    <NumberField
      {...props}
      value={props.value === null ? null : present(props.value)}
      onChange={(n) =>
        props.onChange(
          n === null
            ? null
            : n === min
              ? props.min!
              : n === max
                ? props.max!
                : fromDisplay(n, kind, units),
        )
      }
      unit={unitLabel(kind, units)}
      min={min}
      max={max}
      normalize={(n) => Number(n.toPrecision(8))}
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
    <span className="toggle-with-help">
      <button
        className={`toggle ${value ? "enabled" : ""}`}
        disabled={disabled}
        onClick={onChange}
        aria-pressed={value}
      >
        <span>{value && <Check size={10} />}</span>
        {label}
      </button>
      <HelpTip term={label} />
    </span>
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
      <span>
        {label}
        <HelpTip term={label} />
      </span>
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
  currentConditions,
  currentOptions,
}: {
  data: any;
  compact?: boolean;
  currentConditions?: object;
  currentOptions?: object;
}) {
  if (!data) return null;
  const differs = (current: object | undefined, original: any) =>
    current &&
    original &&
    Object.entries(current).some(
      ([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key]),
    );
  const changed =
    differs(currentConditions, data.inputs?.conditions) ||
    differs(currentOptions, data.inputs?.options);
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
        {!compact && data.inputs?.application_version && (
          <div className="result-provenance">
            Engine {data.inputs.application_version}
            {data.inputs.submitted_at && (
              <span>
                {" "}
                · {new Date(data.inputs.submitted_at).toLocaleString()}
              </span>
            )}
            {typeof data.inputs.project_sha256 === "string" && (
              <span
                title={`Input project SHA-256: ${data.inputs.project_sha256}`}
              >
                · Input {data.inputs.project_sha256.slice(0, 12)}
              </span>
            )}
          </div>
        )}
        {!compact && changed && (
          <p className="field-error">
            Setup changed since this run. Rerun the solver to calculate the new
            setup.
          </p>
        )}
        {!compact && data.inputs && (
          <details className="run-inputs">
            <summary>Inspect run inputs · SI units</summary>
            <p>Configuration: {data.inputs.configuration_id || "default"}</p>
            <pre>
              {JSON.stringify(
                {
                  conditions: data.inputs.conditions,
                  options: data.inputs.options,
                },
                null,
                2,
              )}
            </pre>
            {data.inputs.cfd_source && (
              <p>
                Pressure-transfer source fields belong to the recorded CFD run.
                Download its solution JSON or rerun CFD before reproducing the
                coupled load.
              </p>
            )}
          </details>
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
    <div className="field">
      <span>
        {label}
        <HelpTip term={label} />
      </span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {children}
      </select>
    </div>
  );
}
