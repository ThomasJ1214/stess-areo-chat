import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, SkipBack, SkipForward, RotateCcw } from "lucide-react";
import type { Units } from "./types";
import { fmt, quantity } from "./units";
import {
  boundedCfdFrameIndex,
  cfdFrameAtTime,
  cfdTransientFrames,
  selectCfdFrame,
} from "./cfdTransientData";
import "./cfdTransientPlayer.css";

export interface CfdTransientPlayerProps {
  data: any;
  frameIndex: number;
  onFrameChange: (index: number) => void;
  units: Units;
}

export default function CfdTransientPlayer({
  data,
  frameIndex,
  onFrameChange,
  units,
}: CfdTransientPlayerProps) {
  const frames = useMemo(() => cfdTransientFrames(data), [data]);
  const index = boundedCfdFrameIndex(data, frameIndex);
  const frame = frames[index];
  const selected = useMemo(() => selectCfdFrame(data, index), [data, index]);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const callback = useRef(onFrameChange);
  callback.current = onFrameChange;
  const clock = useRef(0);
  const currentIndex = useRef(index);
  currentIndex.current = index;
  const lastTime = frames.at(-1)?.time_s || 0;
  useEffect(() => {
    setPlaying(false);
  }, [data]);
  useEffect(() => {
    if (!playing || frames.length < 2) return;
    const firstTime = frames[0].time_s;
    // A normalized full-pass duration makes very short physical experiments
    // inspectable. Playback timing never changes or interpolates solver fields.
    const fullPassSeconds = 8 / speed;
    clock.current = frames[currentIndex.current].time_s;
    let previousWallTime: number | null = null;
    let handle: number;
    const advance = (wallTime: number) => {
      if (previousWallTime !== null) {
        clock.current +=
          ((Math.max(0, wallTime - previousWallTime) / 1000) *
            (lastTime - firstTime)) /
          fullPassSeconds;
      }
      previousWallTime = wallTime;
      const nextIndex = cfdFrameAtTime(frames, clock.current);
      if (nextIndex !== currentIndex.current) callback.current(nextIndex);
      if (clock.current >= lastTime) {
        callback.current(frames.length - 1);
        setPlaying(false);
      } else handle = requestAnimationFrame(advance);
    };
    handle = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(handle);
  }, [playing, frames, lastTime, speed]);
  if (!data?.transient) return null;
  if (!frame || !selected)
    return (
      <div className="cfd-transient-player" role="alert">
        Saved transient fields are incomplete or invalid. The final field has
        not been substituted for this frame.
      </div>
    );
  const seek = (value: number) => {
    setPlaying(false);
    onFrameChange(value);
  };
  return (
    <section
      className="cfd-transient-player"
      aria-label="Transient CFD playback"
      data-cfd-frame-index={index}
      data-cfd-frame-count={frames.length}
      data-cfd-time={frame.time_s}
      data-cfd-flight-time={frame.flight_time_s ?? ""}
      data-cfd-playing={String(playing)}
    >
      <div className="cfd-transient-heading">
        <strong>Transient snapshots</strong>
        <span>
          {data.transient.completed
            ? "Requested duration completed"
            : "Partial run"}
        </span>
      </div>
      <div className="cfd-transient-controls">
        <button
          aria-label={playing ? "Pause CFD playback" : "Play CFD playback"}
          disabled={frames.length < 2}
          onClick={() => {
            if (!playing && index === frames.length - 1) onFrameChange(0);
            setPlaying((value) => !value);
          }}
        >
          {playing ? <Pause size={15} /> : <Play size={15} />}
        </button>
        <button
          aria-label="Previous CFD snapshot"
          disabled={index === 0}
          onClick={() => seek(index - 1)}
        >
          <SkipBack size={14} />
        </button>
        <button
          aria-label="Next CFD snapshot"
          disabled={index === frames.length - 1}
          onClick={() => seek(index + 1)}
        >
          <SkipForward size={14} />
        </button>
        <button aria-label="Restart CFD playback" onClick={() => seek(0)}>
          <RotateCcw size={14} />
        </button>
        <label>
          Replay{" "}
          <select
            aria-label="CFD playback speed"
            value={speed}
            onChange={(event) => setSpeed(Number(event.target.value))}
          >
            <option value={0.5}>Slow</option>
            <option value={1}>Normal</option>
            <option value={2}>Fast</option>
          </select>
        </label>
      </div>
      <input
        type="range"
        min={0}
        max={frames.length - 1}
        step={1}
        value={index}
        aria-label="CFD snapshot timeline"
        aria-valuetext={`Saved snapshot ${index + 1} of ${frames.length}, CFD time ${frame.time_s} seconds${frame.flight_time_s == null ? "" : `, launch time ${frame.flight_time_s} seconds`}`}
        onChange={(event) => seek(Number(event.target.value))}
      />
      <div className="cfd-transient-readout">
        <span>
          Frame {index + 1} / {frames.length} · step {frame.step}
        </span>
        <strong>CFD {fmt(frame.time_s, 5)} s</strong>
        {frame.flight_time_s != null && (
          <span>Launch {fmt(frame.flight_time_s, 4)} s</span>
        )}
        <span>
          Incoming{" "}
          {quantity(
            Math.hypot(...frame.freestream_velocity_m_s),
            "speed",
            units,
            2,
          )}{" "}
          · Mach {fmt(frame.freestream_mach, 3)}
        </span>
      </div>
      <small>
        Saved accepted states only; no interpolation in time. Replay speed is
        visual. Lines are instantaneous streamlines, not particle trajectories.
      </small>
    </section>
  );
}
