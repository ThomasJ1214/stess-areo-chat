import {
  useEffect,
  useMemo,
  useState,
  useRef,
  Component as ReactComponent,
} from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Html, Line } from "@react-three/drei";
import * as THREE from "three";
import {
  Maximize2,
  RotateCcw,
  MousePointer2,
  Move3D,
  Focus,
  Camera,
  Wind,
} from "lucide-react";
import type { Conditions, MeshResponse, Overlays, Units } from "./types";
import { defaultConditions } from "./types";
import { fmt, quantity, fitSphereDistance } from "./units";
import { flightDragDirection, fieldRange } from "./viewerData";
import CfdFlowView, { CfdFlowLegend, getCfdFlowGrid } from "./CfdFlowView";
import type { CfdFlowSettings } from "./flowFieldMath";
import { cfdCutawayPlane } from "./cfdInspection";
import {
  ambientWind,
  flightLocalDrag,
  flightPose,
  inertialToScene,
  followCameraDistance,
  railDirection,
  solvedGeometryQuaternion,
  trajectoryPoints,
} from "./launchScene";
import type { FlightEvent } from "./launchScene";
import FollowCamera from "./FollowCamera";
import type { FlightPresentationSample } from "./flightPlaybackMath";

interface Props {
  meshes: MeshResponse | null;
  originalMeshes: MeshResponse | null;
  alignmentPreview?: MeshResponse | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  overlays: Overlays;
  aero: any;
  flightRow: any;
  /** Smooth visual pose only. Labels, heatmaps and forces still use flightRow. */
  flightDisplayRow?: FlightPresentationSample | null;
  flightStructuralMode?: "quasi_static" | "dynamic_fins";
  fea: any;
  cfd: any;
  flowSettings?: CfdFlowSettings;
  deformationScale: number;
  workspace: string;
  trajectory: any[];
  units: Units;
  launchConditions?: Conditions;
  playing?: boolean;
  launchReady?: boolean;
  flightEvents?: FlightEvent[];
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
  stressUnavailable = false,
  maxStress = 1,
  xray = false,
  clippingPlanes,
}: {
  part: NonNullable<MeshResponse>["components"][0];
  index: number;
  selected: boolean;
  wireframe: boolean;
  onSelect: () => void;
  ghost?: boolean;
  stressValue?: number;
  stressUnavailable?: boolean;
  maxStress?: number;
  xray?: boolean;
  clippingPlanes?: THREE.Plane[];
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
            : stressUnavailable
              ? "#87939b"
              : selected
                ? "#e4b87d"
                : palette[index % palette.length]
        }
        metalness={ghost ? 0 : 0.28}
        roughness={0.48}
        wireframe={wireframe || ghost}
        transparent={ghost || xray}
        opacity={ghost ? 0.17 : xray ? 0.16 : 1}
        depthWrite={!ghost && !xray}
        clippingPlanes={clippingPlanes}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}
function PlacementPreview({
  part,
}: {
  part: NonNullable<MeshResponse>["components"][0];
}) {
  const g = useMemo(() => geometry(part.vertices, part.faces), [part]);
  useEffect(() => () => g.dispose(), [g]);
  return (
    <group name={`CAD placement preview: ${part.name}`}>
      <mesh geometry={g} raycast={() => undefined} renderOrder={2}>
        <meshBasicMaterial
          color="#ffbd67"
          transparent
          opacity={0.34}
          depthTest={false}
          depthWrite={false}
          side={THREE.DoubleSide}
          polygonOffset
          polygonOffsetFactor={-2}
          polygonOffsetUnits={-1}
          toneMapped={false}
        />
      </mesh>
      <mesh geometry={g} raycast={() => undefined} renderOrder={3}>
        <meshBasicMaterial
          color="#ffe0a7"
          wireframe
          transparent
          opacity={0.28}
          depthTest={false}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
    </group>
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
    if (
      !data?.vertices?.length ||
      (!data?.tetrahedra?.length &&
        !(
          data?.mesh_kind === "plate_midsurface" && data?.surface_faces?.length
        ))
    )
      return null;
    const faces = new Map<string, number[]>();
    if (data.mesh_kind === "plate_midsurface")
      data.surface_faces.forEach((face: number[], i: number) =>
        faces.set(String(i), face),
      );
    for (const tet of data.tetrahedra || []) {
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
  const arrow = useMemo(() => new THREE.ArrowHelper(), []);
  useEffect(() => {
    const dir = new THREE.Vector3(
      ...(direction as [number, number, number]),
    ).normalize();
    if (dir.lengthSq() > 0) arrow.setDirection(dir);
    arrow.position.set(...(start as [number, number, number]));
    arrow.setLength(length, length * 0.18, length * 0.08);
    arrow.setColor(new THREE.Color(color));
  }, [arrow, start.join(","), direction.join(","), length, color]);
  useEffect(
    () => () => {
      // ArrowHelper shares its geometry across instances, but creates unique
      // materials. Reuse the object through playback and release those materials.
      (arrow.line.material as THREE.Material).dispose();
      (arrow.cone.material as THREE.Material).dispose();
    },
    [arrow],
  );
  return <primitive object={arrow} />;
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
function LaunchEnvironment({
  conditions,
  rocketSize,
  radius,
  extent,
  wind,
  rocketPoint,
}: {
  conditions: Conditions;
  rocketSize: number;
  radius: number;
  extent: number;
  wind: number[];
  rocketPoint: number[];
}) {
  const direction = new THREE.Vector3(...railDirection(conditions));
  const railRotation = new THREE.Quaternion().setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    direction,
  );
  const azimuth = (conditions.launch_azimuth * Math.PI) / 180;
  const sideways = new THREE.Vector3(Math.cos(azimuth), 0, Math.sin(azimuth));
  const railOffset = sideways.multiplyScalar(Math.max(0.06, radius * 0.65));
  const railCenter = direction
    .clone()
    .multiplyScalar(conditions.rail_length / 2)
    .add(railOffset);
  const groundSize = Math.max(150, extent * 3, conditions.rail_length * 15);
  const windSpeed = Math.hypot(...wind);
  return (
    <group name="launch-environment">
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, -0.045, 0]}
        name="flat-ground-plane"
      >
        <planeGeometry args={[groundSize, groundSize]} />
        <meshStandardMaterial color="#273d3b" roughness={1} />
      </mesh>
      <gridHelper
        args={[groundSize, 60, "#536b67", "#344e49"]}
        position={[0, -0.04, 0]}
      />
      <mesh position={[0, -0.015, 0]} name="launch-pad">
        <boxGeometry
          args={[
            Math.max(1.1, rocketSize * 0.7),
            0.035,
            Math.max(1.1, rocketSize * 0.7),
          ]}
        />
        <meshStandardMaterial
          color="#8d959b"
          metalness={0.45}
          roughness={0.5}
        />
      </mesh>
      <mesh position={railCenter} quaternion={railRotation} name="launch-rail">
        <boxGeometry args={[0.025, conditions.rail_length, 0.025]} />
        <meshStandardMaterial
          color="#cbd8e0"
          metalness={0.8}
          roughness={0.25}
        />
      </mesh>
      <Line
        points={[
          [0, 0.003, 0],
          [0, 0.003, -Math.max(2, rocketSize)],
        ]}
        color="#86bfb1"
        lineWidth={2}
      />
      <Html position={[0, 0.03, -Math.max(2, rocketSize)]} center>
        <span className="scene-label">N</span>
      </Html>
      <Html
        position={[
          railOffset.x,
          conditions.rail_length * direction.y + 0.15,
          railOffset.z,
        ]}
        center
      >
        <span className="scene-label">Launch rail</span>
      </Html>
      {windSpeed > 1e-8 &&
        [-1, 0, 1].map((lane) => (
          <Arrow
            key={lane}
            start={[
              rocketPoint[0] - rocketSize * 1.1,
              rocketPoint[1] + rocketSize * (0.5 + lane * 0.24),
              rocketPoint[2] + rocketSize * 0.8,
            ]}
            direction={wind}
            length={rocketSize * 0.7}
            color="#77cdd5"
          />
        ))}
    </group>
  );
}

/** An illustrative plume driven by actual motor thrust, not a combustion/CFD
 * result. Particle count is fixed, materials/geometries are shared. */
function MotorExhaust({
  row,
  tail,
  size,
  radius,
  peakThrust,
}: {
  row: any;
  tail: number;
  size: number;
  radius: number;
  peakThrust: number;
}) {
  const particles = useRef<THREE.InstancedMesh>(null);
  const transform = useMemo(() => new THREE.Object3D(), []);
  const ratio = Math.max(
    0,
    Math.min(1, (row?.thrust || 0) / Math.max(peakThrust, 1)),
  );
  const length = size * (0.28 + 0.7 * Math.sqrt(ratio));
  const width = Math.max(radius * 0.28, size * 0.007) * (0.5 + ratio);
  const active = Number.isFinite(row?.thrust) && row.thrust > 0.01;
  useFrame(() => {
    if (!particles.current || !active) return;
    const clock = row?.time || 0;
    for (let i = 0; i < 72; i++) {
      const fraction =
        (((clock * (1.5 + ratio) + i * 0.61803398875) % 1) + 1) % 1;
      const angle = i * 2.39996322973;
      const spread = width * (0.3 + fraction * 2.4);
      transform.position.set(
        tail + length * fraction * 1.3,
        Math.sin(angle) * spread,
        Math.cos(angle) * spread,
      );
      const particleSize =
        width * (0.12 + fraction * 0.12) * (1 - fraction * 0.65);
      transform.scale.setScalar(particleSize);
      transform.updateMatrix();
      particles.current.setMatrixAt(i, transform.matrix);
    }
    particles.current.instanceMatrix.needsUpdate = true;
  });
  return active ? (
    <group name="illustrative-thrust-driven-exhaust">
      <mesh
        position={[tail + length * 0.5, 0, 0]}
        rotation={[0, 0, -Math.PI / 2]}
      >
        <coneGeometry args={[width, length, 20, 1, true]} />
        <meshBasicMaterial
          color="#ff9c41"
          transparent
          opacity={0.28 + ratio * 0.12}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          side={THREE.DoubleSide}
        />
      </mesh>
      <mesh
        position={[tail + length * 0.24, 0, 0]}
        rotation={[0, 0, -Math.PI / 2]}
      >
        <coneGeometry args={[width * 0.55, length * 0.48, 16, 1, true]} />
        <meshBasicMaterial
          color="#d5f2ff"
          transparent
          opacity={0.65}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          side={THREE.DoubleSide}
        />
      </mesh>
      <instancedMesh
        ref={particles}
        args={[undefined, undefined, 72]}
        frustumCulled={false}
      >
        <sphereGeometry args={[1, 6, 4]} />
        <meshBasicMaterial
          color="#ffc88a"
          transparent
          opacity={0.28}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </instancedMesh>
    </group>
  ) : null;
}

/** Canopy geometry is illustrative; inflation comes from the integrated state.
 * No cloth shape, reefing or material deformation is implied by this display. */
function RecoveryCanopy({
  row,
  point,
  size,
}: {
  row: any;
  point: number[];
  size: number;
}) {
  const fraction = Math.max(
    0,
    Math.min(1, row?.recovery_inflation_fraction || 0),
  );
  const area = Math.max(0, row?.recovery_cd_area_m2 || 0);
  const direction = new THREE.Vector3(
    ...inertialToScene(
      (row?.velocity_vector || [0, 0, -1]).map(
        (value: number, i: number) => (row?.wind_vector?.[i] || 0) - value,
      ),
    ),
  );
  if (direction.lengthSq() < 1e-8) direction.set(0, 1, 0);
  direction.normalize();
  const rotation = new THREE.Quaternion().setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    direction,
  );
  const canopyRadius =
    Math.max(size * 0.1, Math.min(size * 8, Math.sqrt(area / Math.PI))) *
    Math.sqrt(Math.max(fraction, 0.01));
  const suspension = size * (1.1 + fraction * 0.7) + canopyRadius * 0.5;
  const top = new THREE.Vector3(
    ...(point as [number, number, number]),
  ).addScaledVector(direction, suspension);
  if (fraction <= 0 || area <= 0) return null;
  return (
    <group
      name="illustrative-modeled-canopy"
      position={top}
      quaternion={rotation}
    >
      <mesh>
        <sphereGeometry
          args={[canopyRadius, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2]}
        />
        <meshStandardMaterial
          color={row.phase === "main" ? "#ed9668" : "#e0c77c"}
          side={THREE.DoubleSide}
          roughness={0.85}
        />
      </mesh>
      {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => {
        const angle = (i * Math.PI) / 4;
        return (
          <Line
            key={i}
            points={[
              [
                Math.cos(angle) * canopyRadius,
                0,
                Math.sin(angle) * canopyRadius,
              ],
              [0, -suspension, 0],
            ]}
            color="#d7d9d2"
            transparent
            opacity={0.6}
            lineWidth={1}
          />
        );
      })}
    </group>
  );
}

function Scene({
  p,
  resetKey,
  mode,
  manualUntil,
  interacting,
  receipt,
  onAutomaticChange,
}: {
  p: Props;
  resetKey: number;
  mode: "follow" | "overview" | "inspect";
  manualUntil: React.MutableRefObject<number>;
  interacting: React.MutableRefObject<boolean>;
  receipt: React.RefObject<HTMLElement | null>;
  onAutomaticChange: (value: boolean) => void;
}) {
  const parts = p.meshes?.components || [];
  const previewParts =
    p.workspace === "design" ? p.alignmentPreview?.components || [] : [];
  const box = useMemo(() => {
    const b = new THREE.Box3();
    const visibleParts = p.overlays.original
      ? [...parts, ...(p.originalMeshes?.components || [])]
      : parts;
    [...visibleParts, ...previewParts].forEach((part) =>
      part.vertices.forEach((v) =>
        b.expandByPoint(new THREE.Vector3(...(v as [number, number, number]))),
      ),
    );
    if (p.fea && p.overlays.deformation)
      p.fea.vertices?.forEach((v: number[], i: number) =>
        b.expandByPoint(
          new THREE.Vector3(
            ...(v.map(
              (n, axis) =>
                n +
                (p.fea.displacements?.[i]?.[axis] || 0) * p.deformationScale,
            ) as [number, number, number]),
          ),
        ),
      );
    if (b.isEmpty())
      b.setFromCenterAndSize(
        new THREE.Vector3(0.5, 0, 0),
        new THREE.Vector3(1, 0.15, 0.15),
      );
    return b;
  }, [
    p.meshes,
    p.originalMeshes,
    p.overlays.original,
    p.alignmentPreview,
    p.workspace,
    p.fea,
    p.overlays.deformation,
    p.deformationScale,
  ]);
  const center = box.getCenter(new THREE.Vector3()).toArray();
  const dimensions = box.getSize(new THREE.Vector3());
  const size = Math.max(dimensions.x, dimensions.y, dimensions.z, 0.1);
  const clippingPlanes = useMemo(() => {
    if (p.workspace !== "cfd") return undefined;
    const plane = cfdCutawayPlane(
      box.min.toArray(),
      box.max.toArray(),
      p.flowSettings,
    );
    return plane
      ? [new THREE.Plane(new THREE.Vector3(...plane.normal), plane.constant)]
      : undefined;
  }, [
    p.workspace,
    box,
    p.flowSettings?.cutaway,
    p.flowSettings?.cutawayAxis,
    p.flowSettings?.cutawayPosition,
    p.flowSettings?.cutawayReverse,
  ]);
  const xray = p.workspace === "cfd" && Boolean(p.flowSettings?.xray);
  const cfdFlowBox = useMemo(() => {
    if (p.workspace !== "cfd" || !p.overlays.flow) return null;
    const grid = getCfdFlowGrid(p.cfd);
    if (!grid) return null;
    return new THREE.Box3(
      new THREE.Vector3(...grid.origin),
      new THREE.Vector3(...grid.upper),
    ).union(box);
  }, [p.workspace, p.overlays.flow, p.cfd, box]);
  const min = box.min.x;
  const displayRow = p.flightDisplayRow || p.flightRow;
  const cg = p.flightRow?.cg ?? p.aero?.cg_m;
  const cp = p.flightRow?.cp ?? p.aero?.cp_m;
  const conditions = p.launchConditions || defaultConditions;
  const tracking = p.workspace === "flight" && mode !== "inspect";
  const overview = tracking && mode === "overview";
  const path = useMemo<[number, number, number][]>(
    () => trajectoryPoints(p.trajectory || [], p.flightEvents || []),
    [p.trajectory, p.flightEvents],
  );
  const flightBox = useMemo(() => {
    const b = new THREE.Box3();
    path.forEach((v) => b.expandByPoint(new THREE.Vector3(...v)));
    b.expandByPoint(new THREE.Vector3(0, 0, 0));
    b.expandByPoint(
      new THREE.Vector3(0, Math.max(size, conditions.rail_length), 0),
    );
    return b;
  }, [path, size, conditions.rail_length]);
  const extent = flightBox.isEmpty()
    ? size
    : Math.max(...flightBox.getSize(new THREE.Vector3()).toArray(), size);
  const anchorX = Number.isFinite(displayRow?.cg)
    ? displayRow.cg
    : Number.isFinite(cg)
      ? cg
      : center[0];
  const anchorGeometry: [number, number, number] =
    displayRow?.cg_geometry_m?.length === 3 &&
    displayRow.cg_geometry_m.every(Number.isFinite)
      ? (displayRow.cg_geometry_m as [number, number, number])
      : [anchorX, 0, 0];
  const pose = flightPose(
    displayRow,
    conditions,
    p.flightEvents || [],
    box.max.x,
    anchorX,
    p.trajectory[0],
  );
  const rocketPoint: [number, number, number] = tracking
    ? pose.position.toArray()
    : [0, 0, 0];
  const frameCenter = overview
    ? flightBox.getCenter(new THREE.Vector3()).toArray()
    : tracking
      ? rocketPoint
      : cfdFlowBox
        ? cfdFlowBox.getCenter(new THREE.Vector3()).toArray()
        : center;
  const frameSize = overview
    ? extent
    : tracking
      ? size * 1.3
      : cfdFlowBox
        ? Math.max(...cfdFlowBox.getSize(new THREE.Vector3()).toArray())
        : size;
  const followDistance = followCameraDistance(
    size,
    rocketPoint[1],
    conditions.rail_length,
  );
  const rocketScale =
    overview && !pose.onRail
      ? Math.max(1, (extent / size) * 0.025)
      : tracking && !pose.onRail
        ? Math.max(1, followDistance / (size * 28))
        : 1;
  const wind = ambientWind(displayRow, conditions);
  const peakThrust = useMemo(
    () =>
      (p.trajectory || []).reduce(
        (peak, row) =>
          Math.max(peak, Number.isFinite(row.thrust) ? row.thrust : 0),
        1,
      ),
    [p.trajectory],
  );
  const eventMarkers = useMemo(
    () =>
      (p.flightEvents || [])
        .filter((event) =>
          [
            "rail_exit",
            "burnout",
            "max_q",
            "apogee",
            "main",
            "recovery",
          ].includes(event.name),
        )
        .map((event) => {
          const row =
            event.index != null
              ? p.trajectory[event.index]
              : p.trajectory.reduce(
                  (closest, candidate) =>
                    !closest ||
                    Math.abs(candidate.time - event.time) <
                      Math.abs(closest.time - event.time)
                      ? candidate
                      : closest,
                  null,
                );
          return row
            ? {
                ...event,
                position: inertialToScene([
                  row.east || 0,
                  row.north || 0,
                  row.altitude || 0,
                ]),
              }
            : null;
        })
        .filter(Boolean),
    [p.flightEvents, p.trajectory],
  );
  const estimated =
    p.workspace === "flight" && p.overlays.stress
      ? (
          (p.flightStructuralMode === "dynamic_fins"
            ? p.flightRow?.dynamic_structural_components
            : p.flightRow?.structural_components) || []
        ).filter(
          (c: any) => c.supported !== false && Number.isFinite(c.stress_pa),
        )
      : [];
  const maxStress = estimated.reduce(
    (n: number, c: any) => Math.max(n, c.stress_pa || 0),
    0,
  );

  return (
    <>
      <color attach="background" args={[tracking ? "#a9c3d2" : "#141e29"]} />
      {tracking && (
        <fog
          attach="fog"
          args={[
            "#a9c3d2",
            Math.max(180, extent * 0.6),
            Math.max(600, extent * 3),
          ]}
        />
      )}
      <ambientLight intensity={tracking ? 0.6 : 1.3} />
      {tracking && <hemisphereLight args={["#d9ecff", "#556848", 1.6]} />}
      <directionalLight
        position={[-size, size * 2, size]}
        intensity={tracking ? 3 : 2.2}
      />
      <directionalLight
        position={[size, -size, 0]}
        intensity={0.6}
        color="#64b0d5"
      />
      {tracking ? (
        <>
          <FollowCamera
            target={pose.position}
            velocity={inertialToScene(displayRow?.velocity_vector || [0, 0, 0])}
            railDirection={railDirection(conditions)}
            onRail={pose.onRail}
            flightTime={displayRow?.time ?? null}
            playing={Boolean(p.playing)}
            box={flightBox}
            rocketSize={size}
            railLength={conditions.rail_length}
            extent={extent}
            mode={mode}
            resetKey={resetKey}
            manualUntil={manualUntil}
            interacting={interacting}
            receipt={receipt}
            onAutomaticChange={onAutomaticChange}
          />
          <LaunchEnvironment
            conditions={conditions}
            rocketSize={size}
            radius={Math.max(dimensions.y, dimensions.z) / 2}
            extent={extent}
            wind={wind}
            rocketPoint={rocketPoint}
          />
        </>
      ) : (
        <>
          <Framing
            center={frameCenter}
            size={frameSize}
            radius={
              (cfdFlowBox || box).getBoundingSphere(new THREE.Sphere()).radius
            }
            resetKey={resetKey}
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
            position={[center[0], -dimensions.y * 0.55 - size * 0.08, 0]}
          />
        </>
      )}
      {tracking && (
        <>
          {path.length > 1 && (
            <Line
              points={path}
              color="#365f71"
              lineWidth={1.8}
              transparent
              opacity={0.7}
            />
          )}
          {overview &&
            eventMarkers.map((event: any) => (
              <group key={event.name} position={event.position}>
                <mesh>
                  <sphereGeometry
                    args={[Math.max(size * 0.05, extent * 0.0025), 12, 8]}
                  />
                  <meshBasicMaterial
                    color={event.name === "apogee" ? "#f8ce78" : "#e7ece7"}
                  />
                </mesh>
                <Html center>
                  <span className="scene-label">
                    {event.name.replaceAll("_", " ")}
                  </span>
                </Html>
              </group>
            ))}
          <RecoveryCanopy
            row={displayRow}
            point={rocketPoint}
            size={size * rocketScale}
          />
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
              {p.flightRow ? (
                <>
                  {quantity(p.flightRow.altitude, "length", p.units, 0)} AGL ·{" "}
                  {fmt(p.flightRow.time, 1)} s
                </>
              ) : (
                "Ready on launch pad"
              )}
              {rocketScale > 1.01 && (
                <small> · rocket display ×{fmt(rocketScale, 1)}</small>
              )}
            </div>
          </Html>
        </>
      )}
      <group position={rocketPoint}>
        <group
          quaternion={tracking ? pose.quaternion : new THREE.Quaternion()}
          scale={rocketScale}
        >
          <group
            position={
              tracking
                ? (anchorGeometry.map((value) => -value) as [
                    number,
                    number,
                    number,
                  ])
                : [0, 0, 0]
            }
          >
            {tracking && (
              <MotorExhaust
                row={displayRow}
                tail={box.max.x}
                size={size}
                radius={Math.max(dimensions.y, dimensions.z) / 2}
                peakThrust={peakThrust}
              />
            )}
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
                  stressUnavailable={
                    p.workspace === "flight" &&
                    p.overlays.stress &&
                    p.flightStructuralMode === "dynamic_fins" &&
                    !estimated.some((c: any) => c.component_id === part.id)
                  }
                  maxStress={maxStress}
                  xray={xray}
                  clippingPlanes={clippingPlanes}
                />
              ))}
            {previewParts.map((part) => (
              <PlacementPreview key={`placement-${part.id}`} part={part} />
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
                  clippingPlanes={clippingPlanes}
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
              <CfdFlowView
                data={p.cfd}
                flow={p.overlays.flow}
                pressure={p.overlays.pressure}
                settings={p.flowSettings}
                size={size}
                clippingPlanes={clippingPlanes}
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
            {p.overlays.forces &&
              p.workspace === "structure" &&
              p.fea?.mesh_kind === "plate_midsurface" &&
              p.fea.fins.map((fin: any) => {
                const force = fin.applied_force_n as number[];
                const magnitude = Math.hypot(...force);
                const maximum = Math.max(
                  1e-30,
                  ...p.fea.fins.map((f: any) =>
                    Math.hypot(...f.applied_force_n),
                  ),
                );
                if (magnitude < 1e-12 || !fin.load_centroid_world_m)
                  return null;
                const start = fin.load_centroid_world_m.map(
                  (n: number, i: number) =>
                    n +
                    (p.overlays.deformation
                      ? fin.load_centroid_displacement_m[i] * p.deformationScale
                      : 0),
                );
                const length = (size * 0.12 * magnitude) / maximum;
                return (
                  <group key={`plate-load-${fin.fin_index}`}>
                    <Arrow
                      start={start}
                      direction={force}
                      length={length}
                      color="#7acac0"
                    />
                    <Html
                      position={start.map(
                        (n: number, i: number) =>
                          n + (force[i] / magnitude) * length,
                      )}
                      center
                    >
                      <span className="scene-label force-label teal">
                        Fin {fin.fin_index + 1}:{" "}
                        {quantity(magnitude, "force", p.units)}
                      </span>
                    </Html>
                  </group>
                );
              })}
            {p.overlays.forces &&
              !(
                p.workspace === "structure" &&
                p.fea?.mesh_kind === "plate_midsurface"
              ) &&
              (p.aero || p.flightRow) && (
                <>
                  {p.workspace !== "flight" && (
                    <Arrow
                      start={[min - size * 0.1, 0, 0]}
                      direction={p.aero.freestream_m_s || [1, 0, 0]}
                      length={size * 0.12}
                      color="#829dba"
                    />
                  )}
                  {Math.abs(p.flightRow?.drag ?? p.aero?.drag_n ?? 0) > 0 && (
                    <Arrow
                      start={[cg ?? center[0], 0, dimensions.z * 0.7]}
                      direction={
                        p.flightRow
                          ? tracking
                            ? flightLocalDrag(p.flightRow, pose.quaternion)
                            : flightDragDirection(p.flightRow)
                          : [1, 0, 0]
                      }
                      length={size * 0.22}
                      color="#e9a777"
                    />
                  )}
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
                      {Math.abs(p.aero.normal_force_n || 0) > 0 && (
                        <Arrow
                          start={[cp ?? center[0], 0, dimensions.z * 0.7]}
                          direction={[0, Math.sign(p.aero.normal_force_n), 0]}
                          length={size * 0.13}
                          color="#74c6bd"
                        />
                      )}
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
                      {Math.abs(p.aero.side_force_n || 0) > 0 && (
                        <>
                          <Arrow
                            start={[cp ?? center[0], 0, 0]}
                            direction={[0, 0, Math.sign(p.aero.side_force_n)]}
                            length={size * 0.13}
                            color="#a3b8ec"
                          />
                          <Html
                            position={[
                              cp ?? center[0],
                              0,
                              Math.sign(p.aero.side_force_n) * size * 0.19,
                            ]}
                            center
                          >
                            <div className="scene-label force-label">
                              Side{" "}
                              {quantity(p.aero.side_force_n, "force", p.units)}
                            </div>
                          </Html>
                        </>
                      )}
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
  const [automatic, setAutomatic] = useState(true);
  const manualUntil = useRef(0);
  const interacting = useRef(false);
  const receipt = useRef<HTMLElement | null>(null);
  const conditions = p.launchConditions || defaultConditions;
  const alignmentPreviewVisible =
    p.workspace === "design" && Boolean(p.alignmentPreview?.components.length);
  const flightScene = p.workspace === "flight" && mode !== "inspect";
  const railExit = p.flightEvents?.find((event) => event.name === "rail_exit");
  const groundEvent = p.flightEvents?.find(
    (event) => event.name === "recovery",
  );
  const launchState =
    !p.flightRow || (p.flightRow.time || 0) === 0
      ? "pad"
      : groundEvent && p.flightRow.time >= groundEvent.time
        ? "landed"
        : railExit && p.flightRow.time >= railExit.time
          ? "flight"
          : !railExit &&
              Math.hypot(
                p.flightRow.east || 0,
                p.flightRow.north || 0,
                p.flightRow.altitude || 0,
              ) >= conditions.rail_length
            ? "flight"
            : "on-rail";
  const wind = ambientWind(p.flightRow, conditions);
  const windAzimuth =
    Math.hypot(wind[0], wind[2]) > 1e-8
      ? ((Math.atan2(wind[0], -wind[2]) * 180) / Math.PI + 360) % 360
      : conditions.wind_direction;
  const resume = () => {
    manualUntil.current = 0;
    interacting.current = false;
    setAutomatic(true);
    setMode("follow");
  };
  useEffect(() => {
    // Starting a launch may frame the pad; resuming midway must preserve a
    // user's camera and its existing five-second idle grace.
    if (p.launchReady || (p.playing && !(p.flightRow?.time > 0))) resume();
  }, [p.launchReady, p.playing]);
  const stressComponents =
    p.flightStructuralMode === "dynamic_fins"
      ? p.flightRow?.dynamic_structural_components
      : p.flightRow?.structural_components;
  const peak = stressComponents?.find(
    (c: any) =>
      c.component_id === p.selectedId &&
      c.supported !== false &&
      Number.isFinite(c.stress_pa),
  );
  const flightStress =
    p.workspace === "flight" &&
    p.overlays.stress &&
    stressComponents?.some(
      (c: any) => c.supported !== false && Number.isFinite(c.stress_pa),
    );
  const [legendMin, legendMax] = useMemo(() => {
    const field: number[] = flightStress
      ? (stressComponents || [])
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
  }, [flightStress, stressComponents, p.fea, p.cfd, p.overlays.stress]);
  const legendKind =
    flightStress || (p.overlays.stress && p.fea) ? "stress" : "pressure";
  return (
    <section
      className="viewport"
      ref={receipt}
      data-scene={flightScene ? "launch" : "engineering"}
      data-ground-plane={String(flightScene)}
      data-launch-state={launchState}
      data-flight-presentation={String(
        Boolean(p.flightDisplayRow?.presentation_interpolated),
      )}
      data-flight-display-time={
        p.flightDisplayRow?.time ?? p.flightRow?.time ?? ""
      }
      data-flight-actual-time={p.flightRow?.time ?? ""}
      data-flight-stress-source={p.flightStructuralMode || "quasi_static"}
      data-flight-stress-available={String(Boolean(flightStress))}
      data-attitude-source={
        solvedGeometryQuaternion(
          (p.flightDisplayRow || p.flightRow)?.body_quaternion_world,
        )
          ? "solved"
          : "illustrative"
      }
      data-motor-exhaust={String(
        flightScene && Number(p.flightRow?.thrust || 0) > 0.01,
      )}
      data-canopy-inflation={
        (p.flightDisplayRow || p.flightRow)?.recovery_inflation_fraction ?? 0
      }
      data-rail-length={conditions.rail_length}
      data-camera-mode={mode}
      data-auto-follow={String(flightScene && mode === "follow" && automatic)}
      data-manual-until={manualUntil.current}
      data-alignment-preview={String(alignmentPreviewVisible)}
      data-fea-mesh-kind={p.fea?.mesh_kind || "solid"}
      data-force-source={
        p.overlays.forces
          ? p.workspace === "structure" &&
            p.fea?.mesh_kind === "plate_midsurface"
            ? "plate_resultants"
            : "aerodynamics"
          : "off"
      }
      data-cfd-frame-index={p.cfd?.transient_snapshot?.index ?? ""}
      data-cfd-time={p.cfd?.transient_snapshot?.time_s ?? ""}
      data-cfd-flight-time={p.cfd?.transient_snapshot?.flight_time_s ?? ""}
      data-cfd-xray={String(
        p.workspace === "cfd" && Boolean(p.flowSettings?.xray),
      )}
      data-cfd-cutaway={String(
        p.workspace === "cfd" && Boolean(p.flowSettings?.cutaway),
      )}
      data-cfd-cutaway-axis={p.flowSettings?.cutawayAxis || "z"}
      data-cfd-cutaway-position={p.flowSettings?.cutawayPosition ?? 0.5}
    >
      <div className="viewport-top">
        <span className="live-dot" /> GPU 3D VIEWPORT{" "}
        <span className="viewport-space">
          {flightScene
            ? "LAUNCH SITE · EAST / NORTH / UP"
            : "LOCAL AXIS · X NOSE → TAIL"}
        </span>
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
          onCreated={({ gl }) => {
            gl.localClippingEnabled = true;
          }}
        >
          <Scene
            p={p}
            resetKey={reset}
            mode={mode}
            manualUntil={manualUntil}
            interacting={interacting}
            receipt={receipt}
            onAutomaticChange={setAutomatic}
          />
        </Canvas>
      </ViewerBoundary>
      {alignmentPreviewVisible && (
        <div className="cad-placement-preview-note" role="status">
          CAD placement preview overlay
          <small>Amber preview only · attach to change assembly</small>
        </div>
      )}
      <div className="viewport-tools">
        {p.workspace === "flight" && (
          <>
            {(["follow", "overview", "inspect"] as const).map((m) => (
              <button
                className={`track-view ${mode === m ? "active" : ""}`}
                key={m}
                onClick={() => {
                  manualUntil.current = 0;
                  interacting.current = false;
                  setAutomatic(m === "follow");
                  setMode(m);
                  setReset((x) => x + 1);
                }}
                title={
                  m === "follow"
                    ? "Automatically follow the rocket; orbit or zoom pauses following for 5 seconds"
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
        <button
          aria-label="Fit model"
          title="Fit model"
          onClick={() => {
            manualUntil.current = 0;
            setReset((x) => x + 1);
          }}
        >
          <Maximize2 size={16} />
        </button>
        <button
          aria-label="Reset view"
          title="Reset view"
          onClick={() => {
            manualUntil.current = 0;
            setReset((x) => x + 1);
          }}
        >
          <RotateCcw size={16} />
        </button>
      </div>
      {flightScene && (
        <>
          <div
            className={`flight-camera-status ${mode === "follow" && !automatic ? "manual" : ""}`}
            aria-live="polite"
          >
            {mode === "follow" ? <Focus size={13} /> : <Camera size={13} />}
            <span>
              {mode === "overview"
                ? "Full flight overview"
                : automatic
                  ? "Automatic follow"
                  : "Manual camera · follows again after 5 s idle"}
            </span>
            {mode === "follow" && !automatic && (
              <button className="resume-camera" onClick={resume}>
                Resume follow
              </button>
            )}
          </div>
          <div className="launch-pad-status">
            <Wind size={13} />
            <span>
              Wind {quantity(Math.hypot(...wind), "speed", p.units, 1)} · toward{" "}
              {fmt(windAzimuth, 0)}°
            </span>
            <span>
              {launchState === "pad"
                ? "On rail · ready to launch"
                : launchState === "on-rail"
                  ? "Constrained to rail"
                  : launchState === "landed"
                    ? "Ground contact"
                    : p.flightRow?.phase || "Flight"}
            </span>
          </div>
        </>
      )}
      <div className="viewport-bottom">
        <span>
          <MousePointer2 size={12} /> Click a component to inspect
        </span>
        <span>
          <Move3D size={12} />{" "}
          {p.workspace === "flight" && mode !== "inspect"
            ? "Drag to orbit · right-drag to pan · scroll to zoom"
            : "Drag to orbit · scroll to zoom"}
        </span>
      </div>
      {p.workspace === "cfd" && p.cfd && p.overlays.flow && (
        <CfdFlowLegend data={p.cfd} settings={p.flowSettings} units={p.units} />
      )}
      {flightScene && (
        <div className="flight-scene-note">
          {solvedGeometryQuaternion(
            (p.flightDisplayRow || p.flightRow)?.body_quaternion_world,
          )
            ? "Solved rigid-body attitude · smooth pose playback"
            : "Actual trajectory · point-mass orientation illustrative"}
          {p.flightRow?.thrust > 0.01 ||
          p.flightRow?.recovery_inflation_fraction > 0
            ? " · plume / canopy illustrative"
            : ""}
          {" · engineering values use actual samples"}
        </div>
      )}
      {((p.overlays.stress && p.fea) ||
        (p.overlays.pressure && p.cfd) ||
        flightStress) && (
        <div className="heat-legend">
          <span>
            {flightStress
              ? p.flightStructuralMode === "dynamic_fins"
                ? "Dynamic fin beam FEA · peak component color"
                : "Estimated peak per component · not FEA"
              : p.overlays.stress && p.fea
                ? p.fea?.mesh_kind === "plate_midsurface"
                  ? "Plate recovered stress · midsurface"
                  : "Von Mises · solver field"
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
          <small>
            {p.flightStructuralMode === "dynamic_fins"
              ? "1D bending dynamics · uniform component color, not 3D solid stress"
              : "Beam / fin estimate · uniform component color"}
          </small>
        </div>
      )}
      {p.workspace === "flight" &&
        p.overlays.stress &&
        p.flightStructuralMode === "dynamic_fins" &&
        !flightStress && (
          <div className="flight-stress-note">
            <strong>Dynamic fin stress unavailable at this sample</strong>
            <span>
              {stressComponents?.find(
                (component: any) => component.component_id === p.selectedId,
              )?.reason ||
                stressComponents?.find(
                  (component: any) => component.supported === false,
                )?.reason ||
                "No supported dynamic fin state was computed."}
            </span>
            <small>
              Gray parts have no dynamic stress result · unavailable is not zero
            </small>
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
