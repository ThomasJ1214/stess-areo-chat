import type { Conditions, WindEvent } from "./types";

export function appendFlightWindEvent(
  source: Conditions,
  event: WindEvent,
): Conditions {
  const finite = [
    event.time_s,
    event.wind_speed,
    event.wind_direction,
    event.turbulence,
    event.transition_s,
  ];
  if (
    !finite.every(Number.isFinite) ||
    (event.temperature_delta !== null &&
      !Number.isFinite(event.temperature_delta))
  )
    throw new Error(
      "Enter finite environment values before applying a change.",
    );
  if (event.time_s < 0 || event.time_s > source.max_time)
    throw new Error("Select a time within the calculated flight duration.");
  if (
    event.wind_speed < 0 ||
    event.wind_speed > 150 ||
    event.wind_direction < 0 ||
    event.wind_direction > 360 ||
    event.turbulence < 0 ||
    event.turbulence > 1 ||
    event.transition_s < 0 ||
    event.transition_s > 60
  )
    throw new Error(
      "Wind must be 0–150 m/s, direction 0–360°, turbulence 0–100%, and transition time 0–60 s.",
    );
  if (
    event.temperature_delta !== null &&
    (event.temperature_delta < -80 || event.temperature_delta > 80)
  )
    throw new Error("Temperature deviation must be between −80 and 80 K.");
  const events = source.wind_events || [];
  if (events.length >= 1000)
    throw new Error(
      "The schedule supports at most 1,000 environment changes. Clear the schedule for a new launch.",
    );
  const previous = events.at(-1);
  if (
    previous &&
    (event.time_s <= previous.time_s ||
      event.time_s < previous.time_s + previous.transition_s)
  )
    throw new Error(
      `Select a time after the last change at ${previous.time_s} s and at or after its transition ends at ${previous.time_s + previous.transition_s} s. To replace earlier changes, clear the schedule and recalculate a new launch.`,
    );
  return {
    ...structuredClone(source),
    wind_events: [...structuredClone(events), structuredClone(event)],
  };
}
