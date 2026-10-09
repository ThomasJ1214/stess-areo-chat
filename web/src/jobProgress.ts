import type { Job } from "./types";

export function formatElapsed(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0s";
  const rounded = Math.round(seconds);
  if (rounded < 60) return `${rounded}s`;
  if (rounded < 3600) return `${Math.floor(rounded / 60)}m ${rounded % 60}s`;
  return `${Math.floor(rounded / 3600)}h ${Math.floor((rounded % 3600) / 60)}m`;
}

export function progressDescription(job: Job): string {
  if (job.progress_basis === "convergence_unknown")
    return "Convergence pending · completion percent unknown";
  const fraction = Math.max(
    0,
    Math.min(1, Number.isFinite(job.progress) ? job.progress : 0),
  );
  const percent = Math.round(fraction * 100);
  if (job.progress_basis === "physical_time")
    return `${percent}% of physical interval`;
  if (job.progress_basis === "budget_usage") return `${percent}% budget used`;
  return `${percent}% complete`;
}

export function etaDescription(job: Job): string {
  if (
    job.eta_seconds == null ||
    !Number.isFinite(job.eta_seconds) ||
    job.eta_seconds < 0
  )
    return job.progress_basis === "convergence_unknown"
      ? "ETA unknown"
      : "ETA calculating…";
  const tentative =
    job.eta_basis === "convergence_trend" || job.eta_confidence === "tentative";
  const range = job.eta_range_seconds;
  const validRange =
    range?.length === 2 &&
    range.every((n) => Number.isFinite(n) && n >= 0) &&
    range[1] >= range[0];
  const estimate = validRange
    ? `${formatElapsed(range![0])}–${formatElapsed(range![1])}`
    : formatElapsed(job.eta_seconds);
  return `${tentative ? "Tentative convergence ETA" : job.eta_basis === "physical_time_throughput" ? "Integration ETA" : job.progress_basis === "budget_usage" ? "Budget ETA" : "ETA"} ${estimate}`;
}
