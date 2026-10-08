/** Drag direction in the displayed local frame (+X nose to tail).
 * The launch viewer rotates that frame -90 degrees around Z, with an illustrative
 * vertical rocket. Convert actual inertial east/north/up relative velocity rather
 * than leaving drag pointed downward throughout parachute descent.
 */
export function flightDragDirection(row: {
  velocity_vector?: number[];
  wind_vector?: number[];
}): number[] {
  const velocity = row.velocity_vector || [0, 0, 0];
  const wind = row.wind_vector || [0, 0, 0];
  const relative = velocity.map((value, axis) => value - (wind[axis] || 0));
  return [relative[2], -relative[0], -relative[1]];
}

export function fieldRange(values: number[]): [number, number] {
  return values.reduce<[number, number]>(
    ([min, max], value) =>
      Number.isFinite(value)
        ? [Math.min(min, value), Math.max(max, value)]
        : [min, max],
    [Infinity, -Infinity],
  );
}
