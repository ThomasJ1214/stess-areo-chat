import {
  useEffect,
  useMemo,
  useState,
  useRef,
  Component as ReactComponent,
} from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Html, Line } from "@react-three/drei";
import * as THREE from "three";
import { Maximize2, RotateCcw, MousePointer2, Move3D } from "lucide-react";
import type { MeshResponse, Overlays, Units } from "./types";
import { fmt, quantity, fitSphereDistance } from "./units";

interface Props {
  meshes: MeshResponse | null;
  originalMeshes: MeshResponse | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  overlays: Overlays;
  aero: any;
  flightRow: any;
  fea: any;
  cfd: any;
  deformationScale: number;
  workspace: string;
  trajectory: any[];
  units: Units;
}
const palette = [
  "#d5dce2",
  "#9eb6c6",
  "#bbc7d3",
  "#49aaa8",
  "#a8b8c7",
  "#d6a671",
];
function geometry(vertices: number[][], faces: number[][]) {
  const g = new THREE.BufferGeometry();
  g.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(vertices.flat(), 3),
  );
  g.setIndex(faces.flat());
  g.computeVertexNormals();
  return g;
}
function heat(value: number, min: number, max: number) {
  const t = Math.max(0, Math.min(1, (value - min) / Math.max(max - min, 1e-9)));
  return new THREE.Color().setHSL((1 - t) * 0.66, 0.85, 0.55);
}
function Solid({
  part,
  index,
  selected,
  wireframe,
  onSelect,
  ghost = false,
  stressValue,
  maxStress = 1,
}: {
  part: NonNullable<MeshResponse>["components"][0];
  index: number;
  selected: boolean;
  wireframe: boolean;
  onSelect: () => void;
  ghost?: boolean;
  stressValue?: number;
  maxStress?: number;
}) {
  const g = useMemo(() => geometry(part.vertices, part.faces), [part]);
  useEffect(() => () => g.dispose(), [g]);
  return (
    <mesh
      geometry={g}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
    >
      <meshStandardMaterial
        color={
          typeof stressValue === "number"
            ? heat(stressValue, 0, maxStress)
            : selected
              ? "#e4b87d"
              : palette[index % palette.length]
        }
        metalness={ghost ? 0 : 0.28}
        roughness={0.48}
        wireframe={wireframe || ghost}
        transparent={ghost}
        opacity={ghost ? 0.17 : 1}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}
function FEA({
  data,
  scale,
  deform,
  stress,
}: {
  data: any;
  scale: number;
  deform: boolean;
  stress: boolean;
}) {
  const g = useMemo(() => {
    if (!data?.vertices?.length || !data?.tetrahedra?.length) return null;
    const faces = new Map<string, number[]>();
    for (const tet of data.tetrahedra) {
      for (const f of [
        [tet[0], tet[1], tet[2]],
        [tet[0], tet[3], tet[1]],
        [tet[0], tet[2], tet[3]],
        [tet[1], tet[3], tet[2]],
      ]) {
        const key = [...f].sort((a, b) => a - b).join("_");
        if (faces.has(key)) faces.delete(key);
        else faces.set(key, f);
      }
    }
    const values: number[] = data.von_mises_pa || [];
    const nodeValues = data.vertices.map((_: any, i: number) =>
      values.length === data.vertices.length ? values[i] : 0,
    );
    if (
      values.length !== data.vertices.length &&
      values.length === data.tetrahedra.length
    ) {
      const count = new Array(nodeValues.length).fill(0);
      data.tetrahedra.forEach((tet: number[], i: number) =>
        tet.forEach((v) => {
          nodeValues[v] += values[i] || 0;
          count[v]++;
        }),
      );
      nodeValues.forEach(
        (_: number, i: number) => (nodeValues[i] /= count[i] || 1),
      );
    }
    const min = nodeValues.reduce(
        (a: number, b: number) => Math.min(a, b),
        Infinity,
      ),
      max = nodeValues.reduce(
        (a: number, b: number) => Math.max(a, b),
        -Infinity,
      );
    const pos = data.vertices.flatMap((v: number[], i: number) =>
      v.map(
        (n, j) =>
          n + (deform ? (data.displacements?.[i]?.[j] || 0) * scale : 0),
      ),
    );
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geom.setIndex(Array.from(faces.values()).flat());
    geom.setAttribute(
      "color",
      new THREE.Float32BufferAttribute(
        nodeValues.flatMap((n: number) => heat(n, min, max).toArray()),
        3,
      ),
    );
    geom.computeVertexNormals();
    return geom;
  }, [data, scale, deform]);
  useEffect(() => () => g?.dispose(), [g]);
  return g ? (
    <mesh geometry={g}>
      <meshStandardMaterial
        vertexColors={stress}
        color={stress ? "white" : "#64c3bd"}
        side={THREE.DoubleSide}
        roughness={0.6}
      />
    </mesh>
  ) : null;
}
function Arrow({
  start,
  direction,
  length,
  color,
}: {
  start: number[];
  direction: number[];
  length: number;
  color: string;
}) {
  const arrow = useMemo(() => {
    const dir = new THREE.Vector3(
      ...(direction as [number, number, number]),
    ).normalize();
    return new THREE.ArrowHelper(
      dir,
      new THREE.Vector3(...(start as [number, number, number])),
      length,
      color,
      length * 0.18,
      length * 0.08,
    );
  }, [start.join(","), direction.join(","), length, color]);
  return <primitive object={arrow} />;
}
function CFD({
  data,
  flow,
  pressure,
  size,
}: {
  data: any;
  flow: boolean;
  pressure: boolean;
  size: number;
}) {
  const samples: any[] = data?.samples || [];
  const surface: any[] = data?.surface || [];
  const pressures = (surface.length ? surface : samples).map(
    (s: any) => s.pressure_pa,
  );
  const min = Math.min(...pressures),
    max = Math.max(...pressures);
  const stride = Math.max(1, Math.ceil(samples.length / 120));
  const points = useMemo(() => {
    const source = surface.length ? surface : samples;
    const g = new THREE.BufferGeometry();
    g.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(
        source.flatMap((s: any) => s.position),
        3,
      ),
    );
    g.setAttribute(
      "color",
      new THREE.Float32BufferAttribute(
        source.flatMap((s: any) => heat(s.pressure_pa, min, max).toArray()),
        3,
      ),
    );
    return g;
  }, [data]);
  useEffect(() => () => points.dispose(), [points]);
  return (
    <>
      {pressure && (
        <points geometry={points}>
          <pointsMaterial vertexColors size={size * 0.011} sizeAttenuation />
        </points>
      )}
      {flow &&
        samples
          .filter((_, i) => i % stride === 0)
          .map((s: any, i: number) => (
            <Arrow
              key={i}
              start={s.position}
              direction={s.velocity}
              length={Math.min(
                size * 0.15,
                Math.max(
                  size * 0.025,
                  (Math.hypot(...s.velocity) / 500) * size * 0.2,
                ),
              )}
              color="#51c5ce"
            />
          ))}
    </>
  );
}
function Framing({
  center,
  size,
  radius,
  resetKey,
  overview = false,
  far = 10000,
}: {
  center: number[];
  size: number;
  radius: number;
  resetKey: number;
  overview?: boolean;
  far?: number;
}) {
  const { camera, size: viewport } = useThree();
  const aspect = viewport.width / Math.max(1, viewport.height);
  const previous = useRef<{
    center: number[];
    size: number;
    radius: number;
    aspect: number;
    resetKey: number;
    overview: boolean;
  } | null>(null);
  useEffect(() => {
    const prior = previous.current;
    if (
      !prior ||
      prior.size !== size ||
      prior.radius !== radius ||
      prior.aspect !== aspect ||
      prior.resetKey !== resetKey ||
      prior.overview !== overview
    ) {
      const perspective = camera as THREE.PerspectiveCamera;
      const distance = fitSphereDistance(
        radius,
        perspective.getEffectiveFOV(),
        aspect,
      );
      const direction = new THREE.Vector3(
        0.25,
        overview ? 0.25 : 0.3,
        1.25,
      ).normalize();
      camera.position.copy(
        new THREE.Vector3(
          ...(center as [number, number, number]),
        ).addScaledVector(direction, distance),
      );
    } else {
      camera.position.add(
        new THREE.Vector3(
          center[0] - prior.center[0],
          center[1] - prior.center[1],
          center[2] - prior.center[2],
        ),
      );
    }
    camera.lookAt(...(center as [number, number, number]));
    camera.near = Math.max(Math.min(size, radius) / 1000, 1e-6);
    camera.far = Math.max(far, size * 100);
    camera.updateProjectionMatrix();
    previous.current = {
      center: [...center],
      size,
      radius,
      aspect,
      resetKey,
      overview,
    };
  }, [center.join(","), size, radius, aspect, resetKey, overview, far]);
  return null;
}
function Scene({
  p,
  resetKey,
  mode,
}: {
  p: Props;
  resetKey: number;
  mode: "follow" | "overview" | "inspect";
}) {
  const parts = p.meshes?.components || [];
  const box = useMemo(() => {
    const b = new THREE.Box3();
    parts.forEach((part) =>
      part.vertices.forEach((v) =>
        b.expandByPoint(new THREE.Vector3(...(v as [number, number, number]))),
      ),
    );
    if (b.isEmpty())
      b.setFromCenterAndSize(
        new THREE.Vector3(0.5, 0, 0),
        new THREE.Vector3(1, 0.15, 0.15),
      );
    return b;
  }, [p.meshes]);
  const center = box.getCenter(new THREE.Vector3()).toArray();
  const dimensions = box.getSize(new THREE.Vector3());
  const size = Math.max(dimensions.x, dimensions.y, dimensions.z, 0.1);
  const min = box.min.x;
  const cg = p.flightRow?.cg ?? p.aero?.cg_m;
  const cp = p.flightRow?.cp ?? p.aero?.cp_m;
  const tracking =
    p.workspace === "flight" && mode !== "inspect" && p.trajectory?.length > 1;
  const overview = tracking && mode === "overview";
  const path = useMemo<[number, number, number][]>(
    () =>
      p.trajectory
        .filter(
          (_, i) =>
            i % Math.max(1, Math.floor(p.trajectory.length / 1200)) === 0,
        )
        .map((r) => [r.east, r.altitude, r.north]),
    [p.trajectory],
  );
  const flightBox = useMemo(() => {
    const b = new THREE.Box3();
    path.forEach((v) => b.expandByPoint(new THREE.Vector3(...v)));
    return b;
  }, [path]);
  const extent = flightBox.isEmpty()
    ? size
    : Math.max(...flightBox.getSize(new THREE.Vector3()).toArray(), size);
  const rocketPoint: [number, number, number] = tracking
    ? [p.flightRow.east, p.flightRow.altitude, p.flightRow.north]
    : [0, 0, 0];
  const frameCenter = overview
    ? flightBox.getCenter(new THREE.Vector3()).toArray()
    : tracking
      ? rocketPoint
      : center;
  const frameSize = overview ? extent : tracking ? size * 1.3 : size;
  const rocketScale = overview ? Math.max(1, (extent / size) * 0.08) : 1;
  const estimated =
    p.workspace === "flight" && p.overlays.stress
      ? (p.flightRow?.structural_components || []).filter(
          (c: any) => c.supported !== false && Number.isFinite(c.stress_pa),
        )
      : [];
  const maxStress = estimated.reduce(
    (n: number, c: any) => Math.max(n, c.stress_pa || 0),
    0,
  );

  return (
    <>
      <color attach="background" args={["#141e29"]} />
      <ambientLight intensity={1.3} />
      <directionalLight position={[-size, size, size]} intensity={2.2} />
      <directionalLight
        position={[size, -size, 0]}
        intensity={0.6}
        color="#64b0d5"
      />
      <Framing
        center={frameCenter}
        size={frameSize}
        radius={
          overview
            ? flightBox.getBoundingSphere(new THREE.Sphere()).radius
            : box.getBoundingSphere(new THREE.Sphere()).radius *
              (tracking ? 1.15 : 1)
        }
        resetKey={resetKey}
        overview={overview}
        far={extent * 4}
      />
      <OrbitControls
        target={frameCenter as [number, number, number]}
        makeDefault
        minDistance={size * 0.04}
        maxDistance={frameSize * 8}
      />
      <gridHelper
        args={[frameSize * 8, 40, "#2b3f50", "#1c2c3b"]}
        position={
          tracking
            ? [0, -0.01, 0]
            : [center[0], -dimensions.y * 0.55 - size * 0.08, 0]
        }
      />
      {tracking && (
        <>
          <Line points={path} color="#526a80" lineWidth={1.5} />
          <mesh position={rocketPoint}>
            <sphereGeometry args={[size * 0.018, 16, 16]} />
            <meshBasicMaterial color="#ddb37e" transparent opacity={0.45} />
          </mesh>
          <Html
            position={[
              rocketPoint[0] + size * rocketScale * 0.35,
              rocketPoint[1],
              rocketPoint[2],
            ]}
          >
            <div className="scene-label">
              {quantity(p.flightRow.altitude, "length", p.units, 0)} AGL ·{" "}
              {fmt(p.flightRow.time, 1)} s
            </div>
          </Html>
        </>
      )}
      <group position={rocketPoint}>
        <group
          rotation={tracking ? [0, 0, -Math.PI / 2] : [0, 0, 0]}
          scale={rocketScale}
        >
          <group position={tracking ? [-center[0], 0, 0] : [0, 0, 0]}>
            <Line
              points={[
                [min - size * 0.12, 0, 0],
                [box.max.x + size * 0.13, 0, 0],
              ]}
              color="#3b5668"
              lineWidth={1}
              dashed
              dashSize={size * 0.012}
              gapSize={size * 0.009}
            />
            {parts
              .filter(
                (part) =>
                  !(
                    p.fea &&
                    (p.overlays.stress || p.overlays.deformation) &&
                    part.id === (p.fea.component_id || p.selectedId)
                  ),
              )
              .map((part, i) => (
                <Solid
                  key={part.id}
                  part={part}
                  index={i}
                  selected={part.id === p.selectedId}
                  wireframe={p.overlays.wireframe}
                  onSelect={() => p.onSelect(part.id)}
                  stressValue={
                    estimated.find((c: any) => c.component_id === part.id)
                      ?.stress_pa
                  }
                  maxStress={maxStress}
                />
              ))}
            {p.overlays.original &&
              p.originalMeshes?.components.map((part, i) => (
                <Solid
                  key={`original-${part.id}`}
                  part={part}
                  index={i}
                  selected={false}
                  wireframe={true}
                  ghost
                  onSelect={() => p.onSelect(part.id)}
                  stressValue={
                    estimated.find((c: any) => c.component_id === part.id)
                      ?.stress_pa
                  }
                  maxStress={maxStress}
                />
              ))}
            {p.fea && (p.overlays.stress || p.overlays.deformation) && (
              <FEA
                data={p.fea}
                scale={p.deformationScale}
                deform={p.overlays.deformation}
                stress={p.overlays.stress}
              />
            )}
            {p.cfd && (
              <CFD
                data={p.cfd}
                flow={p.overlays.flow}
                pressure={p.overlays.pressure}
                size={size}
              />
            )}
            {p.overlays.markers &&
              [
                [cg, "CG", "#edbd73"],
                [cp, p.aero?.cp_valid === false ? "CP*" : "CP", "#72c9c6"],
              ].map(
                ([x, label, color]) =>
                  typeof x === "number" && (
                    <group
                      key={String(label)}
                      position={[x, dimensions.y * 0.8 + size * 0.04, 0]}
                    >
                      <mesh>
                        <sphereGeometry args={[size * 0.008, 16, 16]} />
                        <meshBasicMaterial color={String(color)} />
                      </mesh>
                      <Line
                        points={[
                          [0, 0, 0],
                          [0, -dimensions.y * 0.8 - size * 0.04, 0],
                        ]}
                        color={String(color)}
                        lineWidth={1}
                      />
                      {!overview && (
                        <Html center position={[0, size * 0.04, 0]}>
                          <div
                            className="scene-label"
                            style={{ color: String(color) }}
                          >
                            {label}{" "}
                            <span>{quantity(x, "length", p.units, 3)}</span>
                          </div>
                        </Html>
                      )}
                    </group>
                  ),
              )}
            {p.overlays.forces && (p.aero || p.flightRow) && (
              <>
                {p.workspace !== "flight" && (
                  <Arrow
                    start={[min - size * 0.1, 0, 0]}
                    direction={p.aero.freestream_m_s || [1, 0, 0]}
                    length={size * 0.12}
                    color="#829dba"
                  />
                )}
                <Arrow
                  start={[cg ?? center[0], 0, dimensions.z * 0.7]}
                  direction={[1, 0, 0]}
                  length={size * 0.22}
                  color="#e9a777"
                />
                {!overview && (
                  <Html
                    position={[
                      (cg ?? center[0]) + size * 0.15,
                      0,
                      dimensions.z * 0.7 + size * 0.025,
                    ]}
                    center
                  >
                    <div className="scene-label force-label">
                      Drag{" "}
                      {quantity(
                        p.flightRow?.drag ?? p.aero?.drag_n,
                        "force",
                        p.units,
                      )}
                    </div>
                  </Html>
                )}
                {p.workspace !== "flight" && (
                  <>
                    <Arrow
                      start={[cp ?? center[0], 0, dimensions.z * 0.7]}
                      direction={[0, Math.sign(p.aero.normal_force_n) || 1, 0]}
                      length={size * 0.13}
                      color="#74c6bd"
                    />
                    <Html
                      position={[
                        cp ?? center[0],
                        size * 0.19,
                        dimensions.z * 0.7,
                      ]}
                      center
                    >
                      <div className="scene-label force-label teal">
                        Normal{" "}
                        {quantity(p.aero.normal_force_n, "force", p.units)}
                      </div>
                    </Html>
                  </>
                )}
              </>
            )}
            <axesHelper
              args={[size * 0.09]}
              position={[
                min - size * 0.08,
                -dimensions.y * 0.65 - size * 0.08,
                0,
              ]}
            />
          </group>
        </group>
      </group>
    </>
  );
}
class ViewerBoundary extends ReactComponent<
  { children: React.ReactNode },
  { error: boolean }
> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    return this.state.error ? (
      <div className="viewer-fallback">
        GPU viewport unavailable. Verify your graphics driver and WebGL support.
        Analysis and project controls remain available.
      </div>
    ) : (
      this.props.children
    );
  }
}
export default function Viewport(p: Props) {
  const [reset, setReset] = useState(0),
    [mode, setMode] = useState<"follow" | "overview" | "inspect">("follow");
  const peak = p.flightRow?.structural_components?.find(
    (c: any) =>
      c.component_id === p.selectedId &&
      c.supported !== false &&
      Number.isFinite(c.stress_pa),
  );
  const flightStress =
    p.workspace === "flight" &&
    p.overlays.stress &&
    p.flightRow?.structural_components?.some(
      (c: any) => c.supported !== false && Number.isFinite(c.stress_pa),
    );
  const [legendMin, legendMax] = useMemo(() => {
    const field: number[] = flightStress
      ? (p.flightRow.structural_components || [])
          .filter(
            (c: any) => c.supported !== false && Number.isFinite(c.stress_pa),
          )
          .map((c: any) => c.stress_pa)
      : p.overlays.stress && p.fea
        ? p.fea.von_mises_pa || []
        : ((p.cfd?.surface?.length ? p.cfd.surface : p.cfd?.samples) || []).map(
            (c: any) => c.pressure_pa,
          );
    const min = flightStress
      ? 0
      : field.reduce((a, b) => Math.min(a, b), Infinity);
    const max = field.reduce((a, b) => Math.max(a, b), -Infinity);
    return [min, max];
  }, [flightStress, p.flightRow, p.fea, p.cfd, p.overlays.stress]);
  const legendKind =
    flightStress || (p.overlays.stress && p.fea) ? "stress" : "pressure";
  return (
    <section className="viewport">
      <div className="viewport-top">
        <span className="live-dot" /> GPU 3D VIEWPORT{" "}
        <span className="viewport-space">LOCAL AXIS · X NOSE → TAIL</span>
      </div>
      <ViewerBoundary>
        <Canvas
          camera={{ position: [1, 1, 3], fov: 42 }}
          dpr={[1, 2]}
          gl={{
            antialias: true,
            alpha: false,
            powerPreference: "high-performance",
          }}
        >
          <Scene p={p} resetKey={reset} mode={mode} />
        </Canvas>
      </ViewerBoundary>
      <div className="viewport-tools">
        {p.workspace === "flight" && p.trajectory?.length > 1 && (
          <>
            {(["follow", "overview", "inspect"] as const).map((m) => (
              <button
                className={`track-view ${mode === m ? "active" : ""}`}
                key={m}
                onClick={() => setMode(m)}
                title={
                  m === "follow"
                    ? "Follow rocket at actual flight position"
                    : m === "overview"
                      ? "Fit full actual trajectory (rocket exaggerated)"
                      : "Inspect rocket in local coordinates"
                }
              >
                {m === "follow"
                  ? "Follow"
                  : m === "overview"
                    ? "Overview"
                    : "Inspect"}
              </button>
            ))}
          </>
        )}
        <button title="Fit model" onClick={() => setReset((x) => x + 1)}>
          <Maximize2 size={16} />
        </button>
        <button title="Reset view" onClick={() => setReset((x) => x + 1)}>
          <RotateCcw size={16} />
        </button>
      </div>
      <div className="viewport-bottom">
        <span>
          <MousePointer2 size={12} /> Click a component to inspect
        </span>
        <span>
          <Move3D size={12} />{" "}
          {p.workspace === "flight" && mode !== "inspect"
            ? mode === "overview"
              ? "Actual trajectory · model enlarged · attitude illustrative"
              : "Actual position · following camera · attitude illustrative"
            : "Drag to orbit · scroll to zoom"}
        </span>
      </div>
      {((p.overlays.stress && p.fea) ||
        (p.overlays.pressure && p.cfd) ||
        flightStress) && (
        <div className="heat-legend">
          <span>
            {flightStress
              ? "Estimated peak per component · not FEA"
              : p.overlays.stress && p.fea
                ? "Von Mises · solver field"
                : "Pressure · CFD samples"}
          </span>
          <div />
          <small>
            {quantity(legendMin, legendKind, p.units, 2)}{" "}
            <span>{quantity(legendMax, legendKind, p.units, 2)}</span>
          </small>
        </div>
      )}
      {flightStress && peak && (
        <div className="flight-stress-note">
          <strong>{peak.name}</strong>
          <span>
            Peak estimate {quantity(peak.stress_pa, "stress", p.units)}
          </span>
          <small>Beam / fin estimate · uniform component color</small>
        </div>
      )}
      {!p.meshes?.components.length && (
        <div className="viewport-empty">
          Import an OpenRocket project or create the example rocket to begin.
        </div>
      )}
    </section>
  );
}
