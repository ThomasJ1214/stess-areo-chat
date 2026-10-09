import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "./api";
import { defaultConditions } from "./types";
import type { AnalysisSettings, Conditions, Project } from "./types";

export const defaultCfdOptions = {
  grid_resolution: 48,
  transverse_resolution: 24,
  max_cells: 300000,
  domain_padding: 0.5,
  cfl: 0.35,
  convergence_tolerance: 0.00001,
  backend: "auto",
  mode: "steady",
  transient_source: "launch",
  duration_s: 0.01,
  snapshot_count: 24,
  flight_window: "whole",
  flight_start_s: 0,
  flight_end_s: 1,
};
export const defaultFeaOptions = {
  component_id: "",
  mesh_size: 0.015,
  max_elements: 30000,
  clamp_axis: "x",
  clamp_side: "min",
  load_mode: "aero_pressure",
  backend: "auto",
  load_pressure_pa: 0,
  clamp_type: "plane",
  acceleration_m_s2: [0, 0, 0],
  traction_pa: [1000, 0, 0],
  auto_mesh: true,
};
export const defaultStudyOptions = {
  parameter: "wind_speed",
  count: 10,
  start: 0,
  stop: 20,
  mean: 5,
  std: 2,
  flight: false,
  seed: 42,
};
type WorkspaceSettings = {
  conditions: Conditions;
  cfd_options: typeof defaultCfdOptions;
  fea_options: typeof defaultFeaOptions;
  study_options: typeof defaultStudyOptions;
  study_mode: "sweep" | "monte_carlo" | "comparison";
};

/** Preserve solver extension fields while giving malformed known controls defaults. */
export function mergeOptions<T extends Record<string, unknown>>(
  defaults: T,
  saved: Record<string, unknown> | undefined,
): T {
  const merged = {
    ...structuredClone(saved || {}),
    ...structuredClone(defaults),
  } as T;
  for (const key of Object.keys(defaults) as (keyof T)[]) {
    const value = saved?.[String(key)];
    const original = defaults[key];
    if (
      (typeof original === "number" &&
        typeof value === "number" &&
        Number.isFinite(value)) ||
      (typeof original === "string" && typeof value === "string") ||
      (typeof original === "boolean" && typeof value === "boolean") ||
      (Array.isArray(original) &&
        Array.isArray(value) &&
        original.length === value.length &&
        value.every((n) => typeof n === "number" && Number.isFinite(n)))
    )
      merged[key] = value as T[keyof T];
  }
  return merged;
}

export function restoreSettings(saved?: AnalysisSettings): WorkspaceSettings {
  return {
    conditions: { ...defaultConditions, ...saved?.conditions },
    cfd_options: restoreCfdOptions(saved?.cfd_options),
    fea_options: mergeOptions(defaultFeaOptions, saved?.fea_options),
    study_options: mergeOptions(defaultStudyOptions, saved?.study_options),
    study_mode: ["sweep", "monte_carlo", "comparison"].includes(
      saved?.study_mode || "",
    )
      ? saved!.study_mode
      : "sweep",
  };
}

/** Restore older projects without retaining obsolete execution time ceilings. */
export function restoreCfdOptions(saved?: Record<string, unknown>) {
  const restored = mergeOptions(defaultCfdOptions, saved);
  for (const key of [
    "max_steps",
    "max_wall_seconds",
    "max_physical_time",
    "flow_through_times",
    "run_until_converged",
    "flight_job_id",
  ])
    delete (restored as Record<string, unknown>)[key];
  if (!["steady", "transient"].includes(restored.mode))
    restored.mode = "steady";
  if (!["launch", "fixed"].includes(restored.transient_source))
    restored.transient_source = "launch";
  if (
    !saved?.flight_window &&
    saved?.mode === "transient" &&
    saved?.transient_source === "launch" &&
    (saved.flight_start_s !== undefined || saved.flight_end_s !== undefined)
  )
    restored.flight_window = "interval";
  if (!["whole", "interval"].includes(restored.flight_window))
    restored.flight_window = "whole";
  return restored;
}

/** Flight job ids are session-bound; only attach a current completed launch. */
export function cfdRequestOptions(
  options: Record<string, unknown>,
  flightJobId?: string,
) {
  const result = { ...options };
  const launch =
    result.mode === "transient" && result.transient_source === "launch";
  const whole = result.flight_window !== "interval";
  delete result.flight_window;
  delete result.flight_job_id;
  if (!launch || whole) {
    delete result.flight_start_s;
    delete result.flight_end_s;
  }
  if (launch && flightJobId) result.flight_job_id = flightJobId;
  if (launch) delete result.duration_s;
  return result;
}

/** Send an explicit pressure only when the selected load is uniform pressure. */
export function feaRequestOptions(options: Record<string, unknown>) {
  const result = { ...options };
  if (result.load_mode !== "uniform_pressure") delete result.load_pressure_pa;
  return result;
}

export function usePersistentSettings(
  onSaved: (project: Project) => void,
  onError: (message: string) => void,
) {
  const [settings, setSettings] = useState(restoreSettings);
  const [context, setContext] = useState<{
    id: string;
    generation: number;
  } | null>(null);
  const [status, setStatus] = useState<
    "saved" | "pending" | "saving" | "error"
  >("saved");
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const contextRef = useRef(context);
  const callbacks = useRef({ onSaved, onError });
  callbacks.current = { onSaved, onError };
  const savedKey = useRef("");
  const sequence = useRef(0);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const latestQueued = useRef<{
    generation: number;
    key: string;
    task: Promise<void>;
  } | null>(null);

  const restore = useCallback((project: Project) => {
    const next = restoreSettings(project.analysis_settings);
    const nextContext = { id: project.id, generation: ++sequence.current };
    contextRef.current = nextContext;
    settingsRef.current = next;
    savedKey.current = JSON.stringify(next);
    setSettings(next);
    setContext(nextContext);
    setStatus("saved");
  }, []);

  const flush = useCallback(async () => {
    const current = contextRef.current;
    if (!current) return;
    const snapshot = structuredClone(settingsRef.current);
    const key = JSON.stringify(snapshot);
    if (
      savedKey.current === key &&
      latestQueued.current?.generation !== current.generation
    )
      return;
    if (
      latestQueued.current?.generation === current.generation &&
      latestQueued.current.key === key
    )
      return latestQueued.current.task;
    setStatus("saving");
    const task = queue.current
      .catch(() => {})
      .then(async () => {
        if (contextRef.current?.generation !== current.generation) return;
        try {
          const updated = await request<Project>("/project/settings", {
            method: "PUT",
            body: JSON.stringify({
              project_id: current.id,
              settings: snapshot,
            }),
          });
          if (contextRef.current?.generation !== current.generation) return;
          savedKey.current = key;
          callbacks.current.onSaved(updated);
          setStatus(
            JSON.stringify(settingsRef.current) === key ? "saved" : "pending",
          );
        } catch (error) {
          if (contextRef.current?.generation === current.generation) {
            setStatus("error");
            callbacks.current.onError(
              `Analysis settings were not saved: ${error instanceof Error ? error.message : String(error)}`,
            );
          }
          throw error;
        }
      });
    queue.current = task;
    latestQueued.current = { generation: current.generation, key, task };
    task
      .finally(() => {
        if (latestQueued.current?.task === task) latestQueued.current = null;
      })
      .catch(() => {});
    return task;
  }, []);

  const key = JSON.stringify(settings);
  useEffect(() => {
    if (
      !context ||
      (savedKey.current === key &&
        latestQueued.current?.generation !== context.generation)
    )
      return;
    setStatus("pending");
    const timer = setTimeout(() => void flush().catch(() => {}), 600);
    return () => clearTimeout(timer);
  }, [key, context, flush]);

  const update = useCallback(
    <K extends keyof WorkspaceSettings>(
      key: K,
      value:
        | WorkspaceSettings[K]
        | ((previous: WorkspaceSettings[K]) => WorkspaceSettings[K]),
    ) =>
      setSettings((previous) => ({
        ...previous,
        [key]: typeof value === "function" ? value(previous[key]) : value,
      })),
    [],
  );

  return {
    conditions: settings.conditions,
    setConditions: (
      value: Conditions | ((previous: Conditions) => Conditions),
    ) => update("conditions", value),
    cfdOptions: settings.cfd_options,
    setCfdOptions: (value: WorkspaceSettings["cfd_options"]) =>
      update("cfd_options", value),
    feaOptions: settings.fea_options,
    setFeaOptions: (
      value:
        | WorkspaceSettings["fea_options"]
        | ((
            previous: WorkspaceSettings["fea_options"],
          ) => WorkspaceSettings["fea_options"]),
    ) => update("fea_options", value),
    studyOptions: settings.study_options,
    setStudyOptions: (value: WorkspaceSettings["study_options"]) =>
      update("study_options", value),
    studyMode: settings.study_mode,
    setStudyMode: (value: string) => {
      if (["sweep", "monte_carlo", "comparison"].includes(value))
        update("study_mode", value as WorkspaceSettings["study_mode"]);
    },
    getSettings: () => structuredClone(settingsRef.current),
    restore,
    flush,
    status,
    restoreGeneration: context?.generation ?? 0,
  };
}
