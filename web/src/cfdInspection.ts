import type { CfdFlowSettings, FlowPoint } from "./flowFieldMath";

/** Viewer-only local plane; no mesh editing, cavity opening or solver masking. */
export function cfdCutawayPlane(
  minimum: FlowPoint,
  maximum: FlowPoint,
  settings?: CfdFlowSettings,
): { normal: FlowPoint; constant: number } | null {
  if (
    !settings?.cutaway ||
    !minimum.every(Number.isFinite) ||
    !maximum.every(Number.isFinite)
  )
    return null;
  const axis =
    settings.cutawayAxis === "x" ? 0 : settings.cutawayAxis === "y" ? 1 : 2;
  const fraction = Number.isFinite(settings.cutawayPosition)
    ? Math.max(0, Math.min(1, settings.cutawayPosition!))
    : 0.5;
  const position = minimum[axis] + (maximum[axis] - minimum[axis]) * fraction;
  const sign = settings.cutawayReverse ? -1 : 1;
  const normal: FlowPoint = [0, 0, 0];
  normal[axis] = sign;
  return { normal, constant: -position * sign };
}
