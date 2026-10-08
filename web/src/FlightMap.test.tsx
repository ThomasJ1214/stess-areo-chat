import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FlightMap from "./FlightMap";
import { defaultConditions } from "./types";

const trajectory = [
  { time: 0, east: 0, north: 0, altitude: 0 },
  { time: 1, east: 40, north: 80, altitude: 100, wind_vector: [10, -5, 0] },
  { time: 2, east: 80, north: -20, altitude: 0 },
];

describe("interactive flight map presentation", () => {
  it("places east to the right and north above the pad using real solver coordinates", () => {
    const html = renderToStaticMarkup(
      <FlightMap
        trajectory={trajectory}
        events={[]}
        flightRow={trajectory[1]}
        conditions={defaultConditions}
        units="metric"
      />,
    );
    const current = html.match(
      /<circle[^>]*data-testid="flight-map-current"[^>]*cx="([^"]+)"[^>]*cy="([^"]+)"/,
    )!;
    const pad = html.match(
      /<g[^>]*data-testid="flight-map-pad"[^>]*transform="translate\(([^ ]+) ([^)]+)\)"/,
    )!;
    expect(Number(current[1])).toBeGreaterThan(Number(pad[1]));
    expect(Number(current[2])).toBeLessThan(Number(pad[2]));
    expect(html).toContain(
      'data-testid="flight-map-wind" data-east="10" data-north="-5"',
    );
    expect(html).toContain('preserveAspectRatio="xMidYMid meet"');
  });

  it("keeps a duration-capped flight visibly incomplete instead of inventing a landing", () => {
    const html = renderToStaticMarkup(
      <FlightMap
        trajectory={trajectory}
        events={[{ name: "apogee", time: 1, index: 1 }]}
        flightRow={trajectory[1]}
        conditions={defaultConditions}
        units="metric"
        onSeek={() => {}}
      />,
    );
    expect(html).toContain('data-ground-contact="false"');
    expect(html).not.toContain('data-testid="flight-map-landing"');
    expect(html).toContain(
      "No landing point: this simulation did not reach ground contact.",
    );
    expect(html).toContain("Simulation end, not a landing");
    expect(html).toContain('data-testid="map-event-apogee"');
    expect(html).toContain('aria-label="Definition of Apogee"');
  });

  it("shows only actual ground contact and converts its display without changing coordinates", () => {
    const html = renderToStaticMarkup(
      <FlightMap
        trajectory={trajectory}
        events={[{ name: "recovery", time: 2, index: 2 }]}
        flightRow={trajectory[2]}
        conditions={defaultConditions}
        units="us"
        onSeek={() => {}}
      />,
    );
    expect(html).toContain('data-ground-contact="true"');
    expect(html).toMatch(
      /data-event="recovery" data-east="80" data-north="-20" data-time="2" data-testid="flight-map-landing"/,
    );
    expect(html).toContain("262.47 ft");
    expect(html).toContain("−65.62 ft".replace("−", "-"));
    expect(html).not.toContain("No landing point");
  });

  it("provides accessible map controls and a truthful empty launch view", () => {
    const html = renderToStaticMarkup(
      <FlightMap
        trajectory={[]}
        events={[]}
        flightRow={null}
        conditions={defaultConditions}
        units="metric"
      />,
    );
    for (const label of [
      "Zoom in on flight map",
      "Zoom out of flight map",
      "Fit whole flight on map",
      "Add a map point",
    ])
      expect(html).toContain(`aria-label="${label}"`);
    expect(html).toContain('tabindex="0"');
    expect(html).toContain("Rocket is on the launch rail.");
    expect(html).not.toContain('data-testid="flight-map-current"');
    expect(html).not.toContain('data-testid="flight-map-landing"');
    expect(html).toContain("not a geographic basemap");
  });
});
