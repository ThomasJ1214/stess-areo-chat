import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { Units } from "./types";
import { quantity } from "./units";
import { fieldRange } from "./viewerData";
import {
  defaultCfdFlowSettings,
  generateStreamlines,
  readFlowGrid,
  streamlinePosition,
} from "./flowFieldMath";
import type { CfdFlowSettings, FlowGrid, FlowPoint, Streamline } from "./flowFieldMath";
import "./cfdFlowView.css";

const cache = new WeakMap<object, FlowGrid | null>();
const pathCache = new WeakMap<FlowGrid, Map<string, Streamline[]>>();
export function getCfdFlowGrid(data: any): FlowGrid | null {
  const raw = data?.flow_grid;
  if (!raw || typeof raw !== "object") return null;
  if (!cache.has(raw)) cache.set(raw, readFlowGrid(raw));
  return cache.get(raw) || null;
}

function solvedPaths(grid: FlowGrid, data: any, settings: CfdFlowSettings) {
  const freestream: FlowPoint = data.summary?.freestream_velocity_m_s || [0, 0, 0];
  const key = `${freestream.join(",")}/${settings.density}/${settings.length}`;
  let entries = pathCache.get(grid);
  if (!entries) {
    entries = new Map();
    pathCache.set(grid, entries);
  }
  if (!entries.has(key)) {
    entries.set(key, generateStreamlines(grid, freestream, settings));
    if (entries.size > 4) entries.delete(entries.keys().next().value!);
  }
  return entries.get(key)!;
}

const color = (value: number, min: number, max: number) => {
  const t = max > min ? Math.max(0, Math.min(1, (value - min) / (max - min))) : 0.45;
  return new THREE.Color().setHSL((1 - t) * 0.66, 0.85, 0.56);
};

function Streamlines({ grid, data, settings }: {
  grid: FlowGrid; data: any; settings: CfdFlowSettings;
}) {
  const freestream: FlowPoint = data.summary?.freestream_velocity_m_s || [0, 0, 0];
  const paths = useMemo(() => solvedPaths(grid, data, settings),
    [grid, freestream.join(","), settings.density, settings.length]);
  const lines = useMemo(() => {
    const positions: number[] = [];
    const colors: number[] = [];
    paths.forEach((path) => {
      for (let i = 1; i < path.points.length; i++) {
        positions.push(...path.points[i - 1], ...path.points[i]);
        for (const speed of [path.speeds[i - 1], path.speeds[i]]) {
          colors.push(...(settings.colorBy === "speed" ?
            color(speed, ...grid.speedRange).toArray() : new THREE.Color("#71e0dd").toArray()));
        }
      }
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    return geometry;
  }, [paths, settings.colorBy, grid]);
  useEffect(() => () => lines.dispose(), [lines]);
  return <>
    <lineSegments geometry={lines}>
      <lineBasicMaterial vertexColors transparent opacity={0.65} depthWrite={false} />
    </lineSegments>
    {settings.animate && <DirectionTracers paths={paths} />}
  </>;
}

function DirectionTracers({ paths }: { paths: Streamline[] }) {
  const clock = useRef(0);
  const representativeDuration = useMemo(() => {
    const durations = paths.map((path) => path.travelTimes[path.travelTimes.length - 1]).sort((a, b) => a - b);
    return durations[Math.floor(durations.length / 2)] || 0;
  }, [paths]);
  const traces = useMemo(() => {
    const positions = new Float32Array(paths.length * 2 * 3);
    const geometry = new THREE.BufferGeometry();
    const attribute = new THREE.BufferAttribute(positions, 3);
    attribute.setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute("position", attribute);
    return { geometry, positions, attribute };
  }, [paths]);
  useEffect(() => () => traces.geometry.dispose(), [traces]);
  useFrame((_, delta) => {
    // Normalize the visual slowdown by a representative crossing duration. A
    // frozen snapshot is not an unsteady pathline or a time-accurate CFD replay.
    clock.current += delta;
    paths.forEach((path, i) => {
      const duration = path.travelTimes[path.travelTimes.length - 1];
      for (let j = 0; j < 2; j++) {
        const point = streamlinePosition(path, clock.current * representativeDuration / 6 + duration * (j / 2 + i * 0.137));
        traces.positions.set(point, (i * 2 + j) * 3);
      }
    });
    traces.attribute.needsUpdate = true;
  });
  return <points geometry={traces.geometry} frustumCulled={false}>
    <pointsMaterial color="#d9ffff" size={2.6} sizeAttenuation={false}
      transparent opacity={0.84} depthWrite={false} />
  </points>;
}

function SparseVectors({ samples, size }: { samples: any[]; size: number }) {
  const lines = useMemo(() => {
    const stride = Math.max(1, Math.ceil(samples.length / 160));
    const positions: number[] = [];
    samples.forEach((sample, i) => {
      if (i % stride || !Array.isArray(sample.position) || !Array.isArray(sample.velocity)) return;
      const speed = Math.hypot(...sample.velocity);
      if (!Number.isFinite(speed) || speed < 1e-8 || !sample.position.every(Number.isFinite)) return;
      const length = size * 0.07;
      const direction = new THREE.Vector3(...(sample.velocity as FlowPoint)).divideScalar(speed);
      const tip = new THREE.Vector3(...(sample.position as FlowPoint)).addScaledVector(direction, length);
      const across = new THREE.Vector3().crossVectors(direction,
        Math.abs(direction.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(0, 0, 1)).normalize();
      const base = tip.clone().addScaledVector(direction, -length * 0.24);
      positions.push(...sample.position, ...tip.toArray(),
        ...tip.toArray(), ...base.clone().addScaledVector(across, length * 0.09).toArray(),
        ...tip.toArray(), ...base.addScaledVector(across, -length * 0.09).toArray());
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    return geometry;
  }, [samples, size]);
  useEffect(() => () => lines.dispose(), [lines]);
  return <lineSegments geometry={lines}>
    <lineBasicMaterial color="#63cad3" transparent opacity={0.75} />
  </lineSegments>;
}

export default function CfdFlowView({ data, flow, pressure, size, settings = defaultCfdFlowSettings }: {
  data: any; flow: boolean; pressure: boolean; size: number; settings?: CfdFlowSettings;
}) {
  const grid = useMemo(() => getCfdFlowGrid(data), [data]);
  const samples: any[] = data?.samples || [];
  const surface: any[] = data?.surface || [];
  const points = useMemo(() => {
    const source = surface.length ? surface : samples;
    const [minimum, maximum] = fieldRange(source.map((sample) => sample.pressure_pa));
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(source.flatMap((s) => s.position), 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(source.flatMap((s) => color(s.pressure_pa, minimum, maximum).toArray()), 3));
    return geometry;
  }, [data]);
  useEffect(() => () => points.dispose(), [points]);
  return <>
    {pressure && <points geometry={points}>
      <pointsMaterial vertexColors size={size * 0.008} sizeAttenuation transparent opacity={0.9} />
    </points>}
    {flow && (grid ? <Streamlines grid={grid} data={data} settings={settings} /> :
      <SparseVectors samples={samples} size={size} />)}
  </>;
}

export function CfdFlowLegend({ data, settings = defaultCfdFlowSettings, units }: {
  data: any; settings?: CfdFlowSettings; units: Units;
}) {
  const grid = useMemo(() => getCfdFlowGrid(data), [data]);
  const converged = data.summary?.converged === true;
  const paths = useMemo(() => grid ? solvedPaths(grid, data, settings) : [],
    [grid, data, settings.density, settings.length]);
  const segments = paths.reduce((total, path) => total + path.points.length - 1, 0);
  return <>
    <div className={`cfd-field-status ${converged ? "converged" : "partial"}`}
      data-flow-renderer={grid ? "structured-streamlines" : "sparse-vectors"}
      data-flow-grid-nodes={grid?.fluid.length || 0}
      data-flow-paths={paths.length}
      data-flow-segments={segments}
      data-flow-color={settings.colorBy}
      data-flow-tracers={String(settings.animate)}>
      <strong>{converged ? "Numerically converged snapshot" : "Partial CFD snapshot · not steady"}</strong>
      <span>{grid ? `${paths.length} streamlines from solved velocity` : "Sparse solved vectors · rerun for streamlines"}</span>
      <small>{data.backend || "Backend unavailable"} · inviscid Euler · unvalidated</small>
      {grid && <small>{data.flow_grid?.stride > 1 ? `Conservative display sampling ×${data.flow_grid.stride} · ` : ""}
        {settings.animate ? "Direction tracers · visual timing" : "Frozen field"}</small>}
    </div>
    {grid && settings.colorBy === "speed" && <div className="cfd-speed-legend" aria-label="CFD velocity magnitude legend">
      <span>Solved speed</span><div />
      <small>{quantity(grid.speedRange[0], "speed", units, 1)}
        <span>{quantity(grid.speedRange[1], "speed", units, 1)}</span></small>
    </div>}
  </>;
}
