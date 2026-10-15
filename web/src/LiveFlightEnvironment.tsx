import { useEffect, useState } from "react";
import { Wind, RefreshCw, Trash2 } from "lucide-react";
import { NumberField, SIField } from "./Controls";
import HelpTip from "./HelpTip";
import type { Conditions, Units, WindEvent } from "./types";
import { appendFlightWindEvent } from "./flightWindEvents";
import { fmt, quantity } from "./units";

export default function LiveFlightEnvironment({
  sourceConditions,
  selectedTime,
  stale,
  disabled,
  units,
  onApply,
  onClear,
}: {
  sourceConditions: Conditions;
  selectedTime: number;
  stale: boolean;
  disabled: boolean;
  units: Units;
  onApply: (next: Conditions) => void;
  onClear: () => void;
}) {
  const [draft, setDraft] = useState({
    wind_speed: sourceConditions.wind_speed,
    wind_direction: sourceConditions.wind_direction,
    turbulence: sourceConditions.turbulence,
    transition_s: 1,
    temperature_delta: null as number | null,
  });
  const [error, setError] = useState("");
  useEffect(() => {
    const last = sourceConditions.wind_events?.at(-1);
    setDraft((current) => ({
      ...current,
      wind_speed: last?.wind_speed ?? sourceConditions.wind_speed,
      wind_direction: last?.wind_direction ?? sourceConditions.wind_direction,
      turbulence: last?.turbulence ?? sourceConditions.turbulence,
    }));
    setError("");
  }, [sourceConditions]);
  const set = (key: keyof typeof draft, value: number | null) =>
    setDraft((current) => ({
      ...current,
      [key]:
        value === null && key !== "temperature_delta" ? current[key] : value,
    }));
  return (
    <details className="flight-live-environment flight-advanced" open>
      <summary>
        <Wind size={14} /> Live environment · recalculate from a selected moment{" "}
        <HelpTip
          term="Live environment"
          definition="Appends a causal change to the saved launch conditions, reruns the actual simulation, and resumes viewing at your selected time. The wind history before the change stays unchanged. This controls atmospheric conditions, not rocket steering or throttle."
        />
      </summary>
      <p className="solver-note">
        Apply a wind or air change at <strong>{fmt(selectedTime, 3)} s</strong>.
        The solver recalculates the launch with the change scheduled at this
        time, then resumes playback here. Existing history before the event is
        preserved.
      </p>
      {stale && (
        <p className="field-error">
          Recalculate the changed setup first. A live environment change must
          use the saved flight's original geometry and launch inputs.
        </p>
      )}
      <div className="field-pair">
        <SIField
          label="Live lateral wind"
          kind="speed"
          units={units}
          value={draft.wind_speed}
          min={0}
          max={150}
          onChange={(n) => set("wind_speed", n)}
        />
        <NumberField
          label="Live wind direction"
          value={draft.wind_direction}
          unit="°"
          min={0}
          max={360}
          onChange={(n) => set("wind_direction", n)}
        />
        <NumberField
          label="Live turbulence intensity"
          value={draft.turbulence * 100}
          unit="%"
          min={0}
          max={100}
          onChange={(n) => n !== null && set("turbulence", n / 100)}
        />
        <NumberField
          label="Environment transition time"
          value={draft.transition_s}
          unit="s"
          min={0}
          max={60}
          onChange={(n) => set("transition_s", n)}
          hint="Duration over which this scheduled change grows from the previous environment. Zero is an abrupt change; this does not alter the flight integrator time step."
        />
        <NumberField
          label="Live temperature deviation"
          value={draft.temperature_delta}
          unit="K"
          min={-80}
          max={80}
          onChange={(n) => set("temperature_delta", n)}
          hint="Optional new temperature deviation from standard atmosphere. Leave blank to preserve the preceding temperature schedule."
        />
      </div>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <button
        className="secondary"
        disabled={disabled || stale}
        aria-label="Apply environment from selected time"
        onClick={() => {
          try {
            setError("");
            onApply(
              appendFlightWindEvent(sourceConditions, {
                ...draft,
                time_s: selectedTime,
              } satisfies WindEvent),
            );
          } catch (issue) {
            setError(issue instanceof Error ? issue.message : String(issue));
          }
        }}
      >
        <RefreshCw size={14} /> Apply from selected time
      </button>
      {(sourceConditions.wind_events?.length ?? 0) > 0 && (
        <div className="flight-wind-schedule">
          <h4>Scheduled environment changes</h4>
          <ol>
            {sourceConditions.wind_events.map((event, index) => (
              <li key={index}>
                {fmt(event.time_s, 3)} s ·{" "}
                {quantity(event.wind_speed, "speed", units)} ·{" "}
                {fmt(event.wind_direction, 1)}° ·{" "}
                {fmt(event.turbulence * 100, 1)}% gust intensity ·{" "}
                {fmt(event.transition_s)} s transition
              </li>
            ))}
          </ol>
          <button className="quiet-btn" disabled={disabled} onClick={onClear}>
            <Trash2 size={13} /> Clear schedule for next launch
          </button>
        </div>
      )}
    </details>
  );
}
