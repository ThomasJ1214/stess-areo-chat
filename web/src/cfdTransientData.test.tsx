import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  boundedCfdFrameIndex,
  cfdFrameAtTime,
  cfdTransientFrames,
  selectCfdFrame,
} from "./cfdTransientData";
import CfdTransientPlayer from "./CfdTransientPlayer";
import { readFlowGrid, sampleVelocity } from "./flowFieldMath";

function result() {
  const frame = (
    time: number,
    speed: number,
    pressure: number,
    incomingPressure: number,
  ) => ({
    time_s: time,
    step: Math.round(time * 100),
    flow_velocity_m_s: Array.from({ length: 8 }, () => [speed, 0, 0]).flat(),
    sample_pressure_pa: [pressure, pressure + 10],
    sample_velocity_m_s: [
      [speed, 0, 0],
      [speed + 3, 4, 0],
    ],
    sample_density_kg_m3: [1, 0.9],
    sample_mach: [speed / 330, (speed + 5) / 330],
    surface_pressure_pa: [pressure + 100],
    force_n: [speed * 2, 5, 0],
    moment_about_origin_nm: [0, 0, 5],
    pressure_drag_n: speed * 2,
    freestream_pressure_pa: incomingPressure,
    dynamic_pressure_pa: 0.5 * speed ** 2,
    freestream_velocity_m_s: [speed, 0, 0],
    freestream_mach: speed / 330,
    pressure_coefficient_defined: speed > 0,
    altitude_msl_m: 100 + time * 20,
    flight_time_s: 2 + time,
  });
  return {
    backend: "numpy-cpu",
    fidelity: "experimental inviscid Euler",
    warnings: ["unvalidated"],
    summary: {
      mode: "transient",
      converged: false,
      completed: true,
      pressure_drag_n: 9999,
      freestream_pressure_pa: 50000,
      dynamic_pressure_pa: 10000,
      cp_m: 0.4,
      physical_time_s: 0.7,
      flow_visualization_nodes: 50000,
    },
    samples: [{ pressure_pa: 999999 }],
    surface: [{ pressure_pa: 999999 }],
    transient: {
      completed: true,
      duration_s: 0.7,
      topology: {
        flow_grid: {
          shape: [2, 2, 2],
          origin_m: [0, 0, 0],
          spacing_m: [1, 1, 1],
          fluid_mask: Array(8).fill(1),
          stride: 2,
          node_count: 8,
        },
        sample_positions_m: [
          [0, 0, 0],
          [1, 1, 1],
        ],
        surface_positions_m: [[0.5, 0.5, 0.5]],
        surface_normals: [[-1, 0, 0]],
      },
      frames: [
        frame(0, 0, 100000, 100000),
        frame(0.2, 10, 99000, 98000),
        frame(0.7, 20, 98000, 96000),
      ],
    },
  };
}

describe("actual transient CFD snapshot selection", () => {
  it("selects stored pressure, force, atmosphere and velocity without the final-field values", () => {
    const source = result();
    const before = JSON.stringify(source);
    const selected = selectCfdFrame(source, 1);
    expect(selected.samples[0].pressure_pa).toBe(99000);
    expect(selected.samples[0].gauge_pressure_pa).toBe(1000);
    expect(selected.surface[0].pressure_pa).toBe(99100);
    expect(selected.surface[0].pressure_coefficient).toBe(22);
    expect(selected.summary.pressure_drag_n).toBe(20);
    expect(selected.summary.freestream_pressure_pa).toBe(98000);
    expect(selected.summary.dynamic_pressure_pa).toBe(50);
    expect(selected.summary.flight_time_s).toBe(2.2);
    expect(selected.summary.altitude_msl_m).toBe(104);
    expect(selected.summary.cp_m).toBeNull();
    expect(selected.summary.pressure_force_steady).toBe(false);
    const grid = readFlowGrid(selected.flow_grid)!;
    sampleVelocity(grid, [0.4, 0.3, 0.6])!.forEach((value, axis) =>
      expect(value).toBeCloseTo(axis === 0 ? 10 : 0, 12),
    );
    expect(grid.speedRange).toEqual([10, 10]);
    expect(
      readFlowGrid(selectCfdFrame(source, 2).flow_grid)!.speedRange,
    ).toEqual([20, 20]);
    expect(JSON.stringify(source)).toBe(before);
    expect(selectCfdFrame(source, 1)).toBe(selected);
  });

  it("leaves zero-dynamic-pressure coefficients undefined and keeps density/Mach genuine", () => {
    const selected = selectCfdFrame(result(), 0);
    expect(selected.surface[0].pressure_coefficient).toBeNull();
    expect(selected.samples[1].density_kg_m3).toBe(0.9);
    expect(selected.samples[1].mach).toBeCloseTo(5 / 330);
    expect(selected.summary.max_mach).toBeCloseTo(5 / 330);
  });

  it("holds accepted states on irregular saved times instead of inventing an intermediate field", () => {
    const data = result();
    const frames = cfdTransientFrames(data);
    expect(cfdFrameAtTime(frames, -1)).toBe(0);
    expect(cfdFrameAtTime(frames, 0.19999)).toBe(0);
    expect(cfdFrameAtTime(frames, 0.2)).toBe(1);
    expect(cfdFrameAtTime(frames, 0.69)).toBe(1);
    expect(cfdFrameAtTime(frames, 99)).toBe(2);
    expect(boundedCfdFrameIndex(data, 500)).toBe(2);
    expect(boundedCfdFrameIndex(data, NaN)).toBe(0);
  });

  it("rejects malformed stored data instead of silently displaying final fields", () => {
    const data = result();
    data.transient.frames[1].sample_pressure_pa.pop();
    expect(selectCfdFrame(data, 1)).toBeNull();
    data.transient.frames[1].time_s = -1;
    expect(cfdTransientFrames(data)).toEqual([]);
    const steady = { summary: { converged: true } };
    expect(selectCfdFrame(steady, 4)).toBe(steady);
  });

  it("offers accessible real-frame playback and exposes both CFD and launch timestamps", () => {
    const html = renderToStaticMarkup(
      <CfdTransientPlayer
        data={result()}
        frameIndex={1}
        onFrameChange={() => {}}
        units="us"
      />,
    );
    expect(html).toContain('aria-label="CFD snapshot timeline"');
    expect(html).toContain('data-cfd-time="0.2"');
    expect(html).toContain('data-cfd-flight-time="2.2"');
    expect(html).toContain('aria-label="Play CFD playback"');
    expect(html).toContain("32.81 ft/s");
    expect(html).toContain(
      "Saved accepted states only; no interpolation in time",
    );
    expect(html).toContain("not particle trajectories");
  });
});
