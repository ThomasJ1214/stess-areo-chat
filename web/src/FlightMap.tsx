import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent, PointerEvent } from "react";
import {
  LocateFixed,
  MapPin,
  MapPinned,
  Minus,
  Plus,
  Trash2,
  Wind,
} from "lucide-react";
import type { Conditions, Units } from "./types";
import { fmt, quantity, unitLabel, displayValue } from "./units";
import {
  flightMapBounds,
  flightMapEvents,
  flightMapPoint,
  flightMapPoints,
  mapScaleDistance,
  mapWind,
  parseMapLandmarks,
  railMapEnd,
  sampleFlightMapPoints,
} from "./flightMapData";
import type { MapLandmark } from "./flightMapData";
import HelpTip from "./HelpTip";

const WIDTH = 640,
  HEIGHT = 360;
const ASPECT = WIDTH / HEIGHT;
const initialView = { zoom: 1, eastOffset: 0, northOffset: 0 };
const eventTerms: Record<string, string> = {
  rail_exit: "Rail exit",
  burnout: "Burnout",
  max_q: "Max Q",
  apogee: "Apogee",
  recovery: "Recovery",
};

function loadLandmarks(projectId?: string) {
  if (!projectId || typeof window === "undefined") return [];
  try {
    return parseMapLandmarks(
      window.localStorage.getItem(`rocket-workbench:map-points:${projectId}`),
    );
  } catch {
    return [];
  }
}

export default function FlightMap({
  trajectory,
  events,
  flightRow,
  conditions,
  units,
  onSeek,
  projectId,
}: {
  trajectory: any[];
  events: any[];
  flightRow: any | null;
  conditions: Conditions;
  units: Units;
  onSeek?: (time: number) => void;
  projectId?: string;
}) {
  const id = useId().replaceAll(":", "");
  const [view, setView] = useState(initialView);
  const [landmarkStore, setLandmarkStore] = useState(() => ({
    projectId,
    points: loadLandmarks(projectId),
  }));
  const [adding, setAdding] = useState(false);
  const [pendingPoint, setPendingPoint] = useState<{
    east: number;
    north: number;
    name: string;
  } | null>(null);
  const landmarks =
    landmarkStore.projectId === projectId ? landmarkStore.points : [];
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{
    x: number;
    y: number;
    east: number;
    north: number;
  } | null>(null);
  const points = useMemo(() => flightMapPoints(trajectory), [trajectory]);
  const pois = useMemo(
    () => flightMapEvents(trajectory, events),
    [trajectory, events],
  );
  const drawn = useMemo(
    () =>
      sampleFlightMapPoints(
        points,
        pois.map((point) => point.rowIndex),
      ),
    [points, pois],
  );
  const rail = useMemo(() => railMapEnd(conditions), [conditions]);
  const fit = useMemo(
    () => flightMapBounds(points, rail, ASPECT),
    [points, rail],
  );
  const current = flightMapPoint(flightRow);
  const time = current?.time ?? 0;
  const ground = pois.find((point) => point.name === "recovery");
  const final = points.at(-1);
  const wind = mapWind(flightRow, conditions);
  const windSpeed = Math.hypot(...wind);
  const span = fit.span / view.zoom;
  const eastCenter = fit.east + view.eastOffset;
  const northCenter = fit.north + view.northOffset;
  const pixelsPerMetre = WIDTH / span;
  const x = (east: number) => WIDTH / 2 + (east - eastCenter) * pixelsPerMetre;
  const y = (north: number) =>
    HEIGHT / 2 - (north - northCenter) * pixelsPerMetre;
  const scale = mapScaleDistance(span * 0.2, units);
  const gridStep = mapScaleDistance(span / 5, units);
  const ticks = (low: number, high: number) => {
    const values: number[] = [];
    for (
      let i = Math.ceil(low / gridStep);
      i * gridStep <= high && values.length < 32;
      i++
    )
      values.push(i * gridStep);
    return values;
  };
  const eastTicks = ticks(eastCenter - span / 2, eastCenter + span / 2);
  const northTicks = ticks(
    northCenter - span / (2 * ASPECT),
    northCenter + span / (2 * ASPECT),
  );
  const played = drawn.filter((point) => point.time <= time);
  if (current && (!played.length || played.at(-1)!.time < current.time))
    played.push(current);
  const future = drawn.filter((point) => point.time > time);
  if (current) future.unshift(current);
  const path = (values: typeof points) =>
    values
      .map(
        (point, index) =>
          `${index ? "L" : "M"}${x(point.east).toFixed(2)},${y(point.north).toFixed(2)}`,
      )
      .join(" ");

  useEffect(() => {
    setView(initialView);
    drag.current = null;
  }, [trajectory]);
  useEffect(() => {
    setLandmarkStore({ projectId, points: loadLandmarks(projectId) });
    setAdding(false);
    setPendingPoint(null);
  }, [projectId]);
  useEffect(() => {
    if (!projectId || landmarkStore.projectId !== projectId) return;
    try {
      window.localStorage.setItem(
        `rocket-workbench:map-points:${projectId}`,
        JSON.stringify(landmarkStore.points),
      );
    } catch {
      /* A full/disabled browser store does not prevent map use. */
    }
  }, [landmarkStore, projectId]);

  function zoom(factor: number) {
    setView((value) => ({
      ...value,
      zoom: Math.min(32, Math.max(0.5, value.zoom * factor)),
    }));
  }

  function keyboard(event: KeyboardEvent<SVGSVGElement>) {
    if (adding && event.key === "Enter") {
      setPendingPoint({
        east: eastCenter,
        north: northCenter,
        name: `Point ${landmarks.length + 1}`,
      });
      setAdding(false);
    } else if (adding && event.key === "Escape") setAdding(false);
    else if (event.key === "+" || event.key === "=") zoom(1.4);
    else if (event.key === "-") zoom(1 / 1.4);
    else if (event.key === "Home" || event.key === "0") setView(initialView);
    else if (
      ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)
    )
      setView((value) => ({
        ...value,
        eastOffset:
          value.eastOffset +
          (event.key === "ArrowRight"
            ? 1
            : event.key === "ArrowLeft"
              ? -1
              : 0) *
            span *
            0.1,
        northOffset:
          value.northOffset +
          (event.key === "ArrowUp" ? 1 : event.key === "ArrowDown" ? -1 : 0) *
            span *
            0.1,
      }));
    else return;
    event.preventDefault();
  }

  function pointerDown(event: PointerEvent<SVGSVGElement>) {
    if (
      adding ||
      event.button !== 0 ||
      (event.target as Element).closest("[data-map-event]")
    )
      return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      east: view.eastOffset,
      north: view.northOffset,
    };
  }

  function placePoint(event: MouseEvent<SVGSVGElement>) {
    if (!adding || (event.target as Element).closest("[data-map-event]"))
      return;
    const rect = event.currentTarget.getBoundingClientRect();
    const scale = Math.min(rect.width / WIDTH, rect.height / HEIGHT);
    const px =
      (event.clientX - rect.left - (rect.width - WIDTH * scale) / 2) / scale;
    const py =
      (event.clientY - rect.top - (rect.height - HEIGHT * scale) / 2) / scale;
    if (px < 0 || px > WIDTH || py < 0 || py > HEIGHT) return;
    setPendingPoint({
      east: eastCenter + (px - WIDTH / 2) / pixelsPerMetre,
      north: northCenter - (py - HEIGHT / 2) / pixelsPerMetre,
      name: `Point ${landmarks.length + 1}`,
    });
    setAdding(false);
  }

  function pointerMove(event: PointerEvent<SVGSVGElement>) {
    if (!drag.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    // Match SVG's centred, uniform scale; a narrow dock may letterbox the map.
    const screenScale = Math.min(rect.width / WIDTH, rect.height / HEIGHT);
    setView((value) => ({
      ...value,
      eastOffset:
        drag.current!.east -
        (event.clientX - drag.current!.x) / screenScale / pixelsPerMetre,
      northOffset:
        drag.current!.north +
        (event.clientY - drag.current!.y) / screenScale / pixelsPerMetre,
    }));
  }

  return (
    <section
      className="flight-map"
      data-testid="local-flight-map"
      data-ground-contact={Boolean(ground)}
      aria-label="Local flight map"
    >
      <div className="flight-map-heading">
        <div>
          <MapPinned size={17} aria-hidden="true" />
          <h3>Local flight map</h3>
          <HelpTip
            term="Local flight map"
            definition="A north-up view of the computed flight in local east/north coordinates, measured from the launch pad. Numbered points mark recorded flight events. Your named points are visual markers. This map contains no GPS position, geographic basemap, or terrain data."
          />
        </div>
        <div className="flight-map-tools">
          <button
            type="button"
            aria-label="Zoom in on flight map"
            title="Zoom in (+)"
            onClick={() => zoom(1.4)}
          >
            <Plus size={16} />
          </button>
          <button
            type="button"
            aria-label="Zoom out of flight map"
            title="Zoom out (−)"
            onClick={() => zoom(1 / 1.4)}
          >
            <Minus size={16} />
          </button>
          <button
            type="button"
            aria-label="Fit whole flight on map"
            title="Fit the full flight (Home)"
            onClick={() => setView(initialView)}
          >
            <LocateFixed size={16} />
          </button>
          <button
            type="button"
            aria-label="Add a map point"
            title="Add a named point on this local map"
            aria-pressed={adding}
            disabled={landmarks.length >= 50}
            onClick={() => {
              setPendingPoint(null);
              setAdding((value) => !value);
              if (!adding) requestAnimationFrame(() => svg.current?.focus());
            }}
          >
            <MapPin size={16} />
          </button>
        </div>
      </div>
      <p className="flight-map-caption" id={`${id}-description`}>
        North is up. Distances are from the launch pad; this is a local map, not
        a geographic basemap. Drag to pan. Use +/− to zoom, arrow keys to move,
        Home to fit.
      </p>
      {adding && (
        <p className="flight-map-add-hint" role="status">
          Click the map to place a named point, or press Enter to use its
          center. Escape cancels. Visual markers do not affect the simulation.
        </p>
      )}
      {pendingPoint && (
        <form
          className="flight-map-point-editor"
          onSubmit={(event) => {
            event.preventDefault();
            if (!pendingPoint.name.trim()) return;
            const point: MapLandmark = {
              ...pendingPoint,
              name: pendingPoint.name.trim().slice(0, 80),
              id: crypto.randomUUID(),
            };
            setLandmarkStore((value) => ({
              projectId,
              points: [
                ...(value.projectId === projectId ? value.points : []),
                point,
              ].slice(0, 50),
            }));
            setPendingPoint(null);
          }}
        >
          <label htmlFor={`${id}-point-name`}>Name this point</label>
          <input
            id={`${id}-point-name`}
            data-testid="map-point-name"
            value={pendingPoint.name}
            maxLength={80}
            autoFocus
            required
            onChange={(event) =>
              setPendingPoint({ ...pendingPoint, name: event.target.value })
            }
          />
          <small>
            East {quantity(pendingPoint.east, "length", units)} · north{" "}
            {quantity(pendingPoint.north, "length", units)}
          </small>
          <button type="submit">Save point</button>
          <button type="button" onClick={() => setPendingPoint(null)}>
            Cancel
          </button>
        </form>
      )}
      <svg
        ref={svg}
        className="flight-map-svg"
        data-testid="flight-map-svg"
        data-view-span={span}
        data-east-center={eastCenter}
        data-north-center={northCenter}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        role="group"
        aria-label="Interactive top-down flight path"
        aria-describedby={`${id}-description`}
        tabIndex={0}
        onKeyDown={keyboard}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onClick={placePoint}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        style={{ touchAction: "none", cursor: adding ? "crosshair" : "grab" }}
      >
        <defs>
          <clipPath id={`${id}-clip`}>
            <rect x="0" y="0" width={WIDTH} height={HEIGHT} rx="9" />
          </clipPath>
          <marker
            id={`${id}-wind-head`}
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0,0 L8,4 L0,8 Z" fill="#7cd8e4" />
          </marker>
        </defs>
        <g clipPath={`url(#${id}-clip)`}>
          <rect className="flight-map-ground" width={WIDTH} height={HEIGHT} />
          {eastTicks.map((value) => (
            <g key={`e${value}`} className="flight-map-grid">
              <line x1={x(value)} x2={x(value)} y1="0" y2={HEIGHT} />
              <text x={x(value) + 4} y={HEIGHT - 9}>
                {fmt(displayValue(value, "length", units), 0)}
              </text>
            </g>
          ))}
          {northTicks.map((value) => (
            <g key={`n${value}`} className="flight-map-grid">
              <line x1="0" x2={WIDTH} y1={y(value)} y2={y(value)} />
              <text x="7" y={y(value) - 5}>
                {fmt(displayValue(value, "length", units), 0)}
              </text>
            </g>
          ))}
          <path
            className="flight-map-future"
            data-testid="flight-map-future-path"
            d={path(future)}
          />
          <path
            className="flight-map-played"
            data-testid="flight-map-played-path"
            d={path(played)}
          />
          <line
            className="flight-map-rail"
            x1={x(0)}
            y1={y(0)}
            x2={x(rail[0])}
            y2={y(rail[1])}
          >
            <title>
              {`Rail ground projection: east ${quantity(rail[0], "length", units)}, north ${quantity(rail[1], "length", units)}`}
            </title>
          </line>
          <g
            className="flight-map-pad"
            data-testid="flight-map-pad"
            data-east="0"
            data-north="0"
            transform={`translate(${x(0)} ${y(0)})`}
          >
            <rect x="-5" y="-5" width="10" height="10" />
            <line x1="-8" x2="8" />
            <line y1="-8" y2="8" />
            <title>Launch pad: east 0, north 0</title>
          </g>
          {pois.map((point, index) => (
            <g
              key={`${point.name}-${point.time}`}
              className={`flight-map-poi ${point.time > time ? "future" : ""}`}
              data-map-event="true"
              data-event={point.name}
              data-east={point.east}
              data-north={point.north}
              data-time={point.time}
              data-testid={
                point.name === "recovery" ? "flight-map-landing" : undefined
              }
              transform={`translate(${x(point.east)} ${y(point.north)})`}
              role={onSeek ? "button" : undefined}
              tabIndex={onSeek ? 0 : undefined}
              aria-label={`${point.label}, ${fmt(point.time)} seconds. East ${quantity(point.east, "length", units)}, north ${quantity(point.north, "length", units)}${onSeek ? ". Seek to this event." : ""}`}
              onClick={() => onSeek?.(point.time)}
              onKeyDown={(event) => {
                if (onSeek && (event.key === "Enter" || event.key === " ")) {
                  event.preventDefault();
                  onSeek(point.time);
                }
              }}
            >
              <circle
                r={point.name === "recovery" ? 6 : 4}
                fill={point.color}
              />
              <text x="7" y="-7" fill={point.color}>
                {index + 1}
              </text>
              <title>{`${point.label} · ${fmt(point.time)} s`}</title>
            </g>
          ))}
          {!ground && final && (
            <g
              className="flight-map-end"
              transform={`translate(${x(final.east)} ${y(final.north)})`}
            >
              <path d="M-5,-5 L5,5 M5,-5 L-5,5" />
              <title>{`Simulation end, not a landing · ${fmt(final.time)} s`}</title>
            </g>
          )}
          {landmarks.map((point) => (
            <g
              key={point.id}
              className="flight-map-landmark"
              data-testid="flight-map-landmark"
              data-point-id={point.id}
              data-east={point.east}
              data-north={point.north}
              transform={`translate(${x(point.east)} ${y(point.north)})`}
            >
              <path d="M0,-6 L6,0 L0,6 L-6,0 Z" />
              <text x="9" y="-8">
                {point.name.length > 24
                  ? `${point.name.slice(0, 24)}…`
                  : point.name}
              </text>
              <title>
                {`${point.name} · east ${quantity(point.east, "length", units)} · north ${quantity(point.north, "length", units)}`}
              </title>
            </g>
          ))}
          {current && (
            <circle
              className="flight-map-current"
              data-testid="flight-map-current"
              data-east={current.east}
              data-north={current.north}
              data-time={current.time}
              cx={x(current.east)}
              cy={y(current.north)}
              r="6"
            >
              <title>{`Rocket · ${fmt(time)} s`}</title>
            </circle>
          )}
          <g
            className="flight-map-scale"
            transform={`translate(18 ${HEIGHT - 38})`}
          >
            <path d={`M0,-4 V0 H${scale * pixelsPerMetre} V-4`} />
            <text y="-10">{quantity(scale, "length", units, 0)}</text>
          </g>
          <g
            className="flight-map-wind"
            data-testid="flight-map-wind"
            data-east={wind[0]}
            data-north={wind[1]}
            transform={`translate(${WIDTH - 61} 63)`}
          >
            <rect x="-51" y="-48" width="103" height="104" rx="8" />
            <text x="0" y="-31" textAnchor="middle">
              N ↑
            </text>
            {windSpeed > 1e-9 && (
              <line
                x1="0"
                y1="0"
                x2={(27 * wind[0]) / windSpeed}
                y2={(-27 * wind[1]) / windSpeed}
                markerEnd={`url(#${id}-wind-head)`}
              />
            )}
            <circle r="2" />
            <text x="0" y="38" textAnchor="middle">
              {windSpeed > 1e-9
                ? quantity(windSpeed, "speed", units, 1)
                : "Calm"}
            </text>
            <text x="0" y="50" textAnchor="middle">
              Wind toward
            </text>
          </g>
          <text
            className="flight-map-axis"
            x={WIDTH / 2}
            y="17"
            textAnchor="middle"
          >
            North ↑ · {unitLabel("length", units)}
          </text>
          <text
            className="flight-map-axis"
            x={WIDTH - 12}
            y={HEIGHT - 9}
            textAnchor="end"
          >
            East →
          </text>
        </g>
      </svg>
      <div className="flight-map-legend">
        <span>
          <i className="played" /> Flown path
        </span>
        <span>
          <i className="future" /> Remaining path
        </span>
        <span>
          <i className="pad" /> Launch pad
        </span>
        <span>
          <Wind size={13} /> Wind toward arrow
          <HelpTip term="Wind direction" />
        </span>
      </div>
      <div className="flight-map-location" aria-live="off">
        {current ? (
          <span>
            Rocket: east {quantity(current.east, "length", units)} · north{" "}
            {quantity(current.north, "length", units)}
          </span>
        ) : (
          <span>Rocket is on the launch rail.</span>
        )}
        {ground ? (
          <span>
            Ground contact: east {quantity(ground.east, "length", units)} ·
            north {quantity(ground.north, "length", units)} ·{" "}
            {quantity(Math.hypot(ground.east, ground.north), "length", units)}{" "}
            from the pad
          </span>
        ) : points.length > 0 ? (
          <span className="flight-map-incomplete">
            No landing point: this simulation did not reach ground contact.
          </span>
        ) : (
          <span>Launch a simulation to see its path and event locations.</span>
        )}
      </div>
      {pois.length > 0 && (
        <ol
          className="flight-map-events"
          aria-label="Flight points of interest"
        >
          {pois.map((point, index) => (
            <li key={`${point.name}-${point.time}`}>
              <button
                type="button"
                disabled={!onSeek}
                data-testid={`map-event-${point.name}`}
                onClick={() => onSeek?.(point.time)}
                className={point.time > time ? "future" : ""}
                title={`East ${quantity(point.east, "length", units)} · north ${quantity(point.north, "length", units)}`}
              >
                <span style={{ color: point.color }}>{index + 1}</span>
                <span>{point.label}</span>
                <time>{fmt(point.time)} s</time>
              </button>
              {eventTerms[point.name] && (
                <HelpTip term={eventTerms[point.name]} />
              )}
              {point.name === "drogue_deployment" && (
                <HelpTip
                  term="Drogue parachute"
                  definition="The smaller canopy commonly used for the first stage of dual-deployment descent. This simulation applies the entered drogue Cd × area at its deployment event; it does not model canopy inflation, line stretch, or opening shock."
                />
              )}
            </li>
          ))}
        </ol>
      )}
      {landmarks.length > 0 && (
        <div className="flight-map-user-points">
          <div>
            <strong>Your map points</strong>
            <button
              type="button"
              onClick={() => setLandmarkStore({ projectId, points: [] })}
            >
              Clear points
            </button>
          </div>
          <ul className="flight-map-landmarks">
            {landmarks.map((point) => (
              <li key={point.id}>
                <button
                  type="button"
                  title="Center this point on the map"
                  onClick={() =>
                    setView((value) => ({
                      ...value,
                      eastOffset: point.east - fit.east,
                      northOffset: point.north - fit.north,
                    }))
                  }
                >
                  <MapPin size={13} />
                  <span>{point.name}</span>
                  <small>
                    E {quantity(point.east, "length", units)} · N{" "}
                    {quantity(point.north, "length", units)}
                  </small>
                </button>
                <button
                  type="button"
                  aria-label={`Remove ${point.name} from map`}
                  onClick={() =>
                    setLandmarkStore((value) => ({
                      ...value,
                      points: value.points.filter(
                        (candidate) => candidate.id !== point.id,
                      ),
                    }))
                  }
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
          <small>
            {projectId
              ? "Saved on this computer for this project."
              : "Points are available while this map is open."}{" "}
            Visual points do not change engineering inputs.
          </small>
        </div>
      )}
    </section>
  );
}
