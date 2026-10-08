import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

export interface WorkspaceLayout {
  assembly: boolean;
  setup: boolean;
  focus: boolean;
  assemblyWidth: number;
  setupWidth: number;
  sceneRatio: number;
}
const key = "rocket-workbench.workspace-layout.v1";
const bounded = (value: unknown, min: number, max: number, fallback: number) =>
  typeof value === "number" && Number.isFinite(value)
    ? Math.min(max, Math.max(min, value))
    : fallback;
export function defaultLayout(): WorkspaceLayout {
  return {
    assembly: window.innerWidth >= 1120,
    setup: window.innerWidth >= 900,
    focus: false,
    assemblyWidth: 240,
    setupWidth: 340,
    sceneRatio: 1.3,
  };
}
export function useWorkspaceLayout() {
  const [layout, setLayout] = useState<WorkspaceLayout>(() => {
    const defaults = defaultLayout();
    try {
      const saved = JSON.parse(localStorage.getItem(key) || "null");
      return saved && typeof saved === "object"
        ? {
            assembly:
              typeof saved.assembly === "boolean"
                ? saved.assembly && defaults.assembly
                : defaults.assembly,
            setup:
              typeof saved.setup === "boolean"
                ? saved.setup && defaults.setup
                : defaults.setup,
            focus: false,
            assemblyWidth: bounded(
              saved.assemblyWidth,
              190,
              380,
              defaults.assemblyWidth,
            ),
            setupWidth: bounded(
              saved.setupWidth,
              280,
              480,
              defaults.setupWidth,
            ),
            sceneRatio: bounded(saved.sceneRatio, 0.6, 3, defaults.sceneRatio),
          }
        : defaults;
    } catch {
      return defaults;
    }
  });
  useEffect(() => {
    const timer = setTimeout(() => {
      try {
        localStorage.setItem(key, JSON.stringify(layout));
      } catch {
        /* A read-only browser profile still supports layout changes. */
      }
    }, 150);
    return () => clearTimeout(timer);
  }, [layout]);
  useEffect(() => {
    let previousWidth = window.innerWidth;
    const resize = () => {
      const width = window.innerWidth;
      if (
        (width < 1120 && previousWidth >= 1120) ||
        (width < 900 && previousWidth >= 900)
      )
        setLayout((current) => ({
          ...current,
          assembly: width < 1120 ? false : current.assembly,
          setup: width < 900 ? false : current.setup,
        }));
      previousWidth = width;
    };
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  return { layout, setLayout, resetLayout: () => setLayout(defaultLayout()) };
}

export function PanelDivider({
  label,
  orientation = "vertical",
  value,
  min,
  max,
  onChange,
  reverse = false,
}: {
  label: string;
  orientation?: "vertical" | "horizontal";
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
  reverse?: boolean;
}) {
  const dragging = useRef<{
    coordinate: number;
    value: number;
    available: number;
  } | null>(null);
  const axis = orientation === "vertical" ? "clientX" : "clientY";
  const clamp = (next: number) => Math.max(min, Math.min(max, next));
  const move = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    const delta = event[axis] - dragging.current.coordinate;
    if (orientation === "horizontal") {
      const fraction = Math.max(
        0.375,
        Math.min(
          0.75,
          dragging.current.value / (1 + dragging.current.value) +
            delta / dragging.current.available,
        ),
      );
      onChange(clamp(fraction / (1 - fraction)));
    } else onChange(clamp(dragging.current.value + delta * (reverse ? -1 : 1)));
  };
  return (
    <div
      className={`panel-divider-handle ${orientation}`}
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation={orientation}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={Math.round(value * 100) / 100}
      title={`${label} · drag or use arrow keys`}
      onPointerDown={(event) => {
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        dragging.current = {
          coordinate: event[axis],
          value,
          available: Math.max(
            250,
            (event.currentTarget.closest("main")?.clientHeight || 650) - 90,
          ),
        };
      }}
      onPointerMove={move}
      onPointerUp={() => {
        dragging.current = null;
      }}
      onPointerCancel={() => {
        dragging.current = null;
      }}
      onLostPointerCapture={() => {
        dragging.current = null;
      }}
      onKeyDown={(event) => {
        if (
          ![
            "ArrowLeft",
            "ArrowRight",
            "ArrowUp",
            "ArrowDown",
            "Home",
            "End",
          ].includes(event.key)
        )
          return;
        event.preventDefault();
        if (event.key === "Home") onChange(min);
        else if (event.key === "End") onChange(max);
        else {
          const sign = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1;
          onChange(
            clamp(
              value +
                sign *
                  (reverse ? -1 : 1) *
                  (orientation === "horizontal" ? 0.15 : 20),
            ),
          );
        }
      }}
    >
      <span />
    </div>
  );
}
