import {
  useEffect,
  useRef,
  type MutableRefObject,
  type RefObject,
} from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { Vec3 } from "./types";
import { fitSphereDistance } from "./units";
import {
  followCameraFraming,
  stepFollowCamera,
  type FollowCameraState,
} from "./launchCameraMath";

interface Props {
  target: THREE.Vector3;
  velocity: Vec3;
  railDirection: Vec3;
  onRail: boolean;
  flightTime: number | null;
  playing: boolean;
  box: THREE.Box3;
  rocketSize: number;
  railLength: number;
  extent: number;
  mode: "follow" | "overview" | "inspect";
  resetKey: number;
  manualUntil: MutableRefObject<number>;
  interacting: MutableRefObject<boolean>;
  receipt: RefObject<HTMLElement | null>;
  onAutomaticChange: (value: boolean) => void;
}

export default function FollowCamera(p: Props) {
  const { camera, size: viewport } = useThree();
  const controls = useRef<any>(null);
  const state = useRef<FollowCameraState>({
    position: [0, 0, 0],
    focus: [0, 0, 0],
    anchor: [0, 0, 0],
    time: null,
    automatic: true,
    initialized: false,
  });
  const automaticState = useRef(true);
  const lastReceipt = useRef(0);
  useEffect(() => {
    state.current.initialized = false;
  }, [
    p.resetKey,
    p.mode,
    p.box.min.x,
    p.box.min.y,
    p.box.min.z,
    p.box.max.x,
    p.box.max.y,
    p.box.max.z,
  ]);

  useFrame((_, delta) => {
    if (!controls.current) return;
    const now = performance.now();
    const automatic =
      p.mode === "follow" &&
      !p.interacting.current &&
      now >= p.manualUntil.current;
    if (automaticState.current !== automatic) {
      automaticState.current = automatic;
      p.onAutomaticChange(automatic);
    }
    const perspective = camera as THREE.PerspectiveCamera;
    const sample = {
      position: p.target.toArray() as Vec3,
      velocity: p.velocity,
      railDirection: p.railDirection,
      onRail: p.onRail,
      time: p.flightTime,
    };
    const desired = followCameraFraming(
      sample,
      p.rocketSize,
      p.railLength,
      perspective.getEffectiveFOV(),
      viewport.width / Math.max(1, viewport.height),
    );
    if (
      p.mode === "overview" &&
      !p.box.isEmpty() &&
      !state.current.initialized
    ) {
      const focus = p.box.getCenter(new THREE.Vector3());
      const distance = fitSphereDistance(
        Math.max(
          p.box.getBoundingSphere(new THREE.Sphere()).radius,
          p.rocketSize * 2,
        ),
        perspective.getEffectiveFOV(),
        viewport.width / Math.max(1, viewport.height),
      );
      camera.position
        .copy(focus)
        .addScaledVector(
          new THREE.Vector3(0.9, 0.65, 1.2).normalize(),
          distance,
        );
      controls.current.target.copy(focus);
      state.current.initialized = true;
    } else if (p.mode === "follow") {
      state.current = stepFollowCamera(
        {
          ...state.current,
          position: camera.position.toArray() as Vec3,
          focus: controls.current.target.toArray() as Vec3,
        },
        sample,
        desired,
        delta,
        automatic,
        p.playing,
      );
      camera.position.fromArray(state.current.position);
      controls.current.target.fromArray(state.current.focus);
    }
    camera.near = Math.max(p.rocketSize / 2000, 0.001);
    camera.far = Math.max(10000, p.extent * 6, p.target.length() * 4);
    perspective.updateProjectionMatrix();
    controls.current.update();
    if (p.receipt.current && now - lastReceipt.current > 150) {
      p.receipt.current.dataset.cameraPosition = camera.position
        .toArray()
        .map((v) => v.toFixed(5))
        .join(",");
      p.receipt.current.dataset.cameraTarget = controls.current.target
        .toArray()
        .map((v: number) => v.toFixed(5))
        .join(",");
      camera.updateMatrixWorld();
      p.receipt.current.dataset.cameraRocketNdc = p.target
        .clone()
        .project(camera)
        .toArray()
        .map((v) => v.toFixed(5))
        .join(",");
      p.receipt.current.dataset.cameraDistance = camera.position
        .distanceTo(p.target)
        .toFixed(5);
      p.receipt.current.dataset.cameraSampleTime = String(p.flightTime ?? 0);
      p.receipt.current.dataset.autoFollow = String(automatic);
      p.receipt.current.dataset.manualUntil = String(p.manualUntil.current);
      p.receipt.current.dataset.cameraTracking = automatic
        ? "velocity-aware"
        : "manual";
      lastReceipt.current = now;
    }
  });

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      minDistance={Math.max(0.2, p.rocketSize * 0.3)}
      maxDistance={Math.max(300, p.extent * 5)}
      maxPolarAngle={Math.PI * 0.495}
      enableDamping
      dampingFactor={0.12}
      onStart={() => {
        p.interacting.current = true;
        p.manualUntil.current = performance.now() + 5000;
        automaticState.current = false;
        p.onAutomaticChange(false);
      }}
      onEnd={() => {
        p.interacting.current = false;
        p.manualUntil.current = performance.now() + 5000;
      }}
    />
  );
}
