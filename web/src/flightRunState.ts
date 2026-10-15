import type { Conditions, Project } from "./types";

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, canonical(item)]),
    );
  return value;
}

/** A local comparison key, not the backend SHA-256 receipt. Physical project
 * fields match the backend projection; display preferences do not stale a run. */
export function flightInputKey(
  project: Project | null,
  conditions: Conditions,
  options: Record<string, unknown>,
): string {
  if (!project) return "";
  const { analysis_settings, unit_system, name, ...physical } = project;
  void analysis_settings;
  void unit_system;
  void name;
  return JSON.stringify(canonical({ physical, conditions, options }));
}

export function flightRunIsStale(savedKey: string | null, currentKey: string) {
  return savedKey !== null && savedKey !== currentKey;
}
