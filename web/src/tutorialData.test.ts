import { describe, expect, it } from "vitest";
import { parseTutorialProgress, tutorialTours } from "./tutorialData";
import { getTermDefinition, glossaryEntry } from "./HelpTip";

describe("offline tutorial bookmarks", () => {
  it("restores valid topics independently while rejecting corrupt or stale bookmarks", () => {
    const progress = parseTutorialProgress(
      JSON.stringify({
        app: { step: 3, completed: false },
        flight: { step: 2, completed: true },
        cfd: { step: 999, completed: false },
        structure: { step: -1, completed: true },
        design: { step: 1.2, completed: false },
        studies: { step: 1, completed: "true" },
        aero: { step: 0 },
        unknown: { step: 0, completed: false },
      }),
    );
    expect(progress).toEqual({
      app: { step: 3, completed: false },
      flight: { step: 2, completed: true },
    });
    for (const invalid of [null, "{", "null", "[]", "12"])
      expect(parseTutorialProgress(invalid)).toEqual({});
  });
  it("makes every current page and the whole workflow available without an external URL", () => {
    expect(tutorialTours.map((tour) => tour.id).sort()).toEqual([
      "aero",
      "app",
      "cfd",
      "design",
      "flight",
      "structure",
      "studies",
    ]);
    const wholeAppPages = new Set(
      tutorialTours
        .find((tour) => tour.id === "app")!
        .steps.map((step) => step.workspace),
    );
    expect([...wholeAppPages].sort()).toEqual([
      "aero",
      "cfd",
      "design",
      "flight",
      "structure",
      "studies",
    ]);
    for (const tour of tutorialTours) {
      expect(tour.steps.length).toBeGreaterThan(1);
      for (const step of tour.steps) {
        expect(step.instruction.length).toBeGreaterThan(40);
        expect(step.check.length).toBeGreaterThan(40);
        expect(step.instruction).not.toMatch(/https?:\/\//);
      }
    }
  });
});

describe("engineering definitions", () => {
  it("distinguishes center of pressure from the pressure coefficient", () => {
    expect(glossaryEntry("CP")?.term).toBe("CP");
    expect(glossaryEntry("Pressure Cp")?.term).toBe("Pressure coefficient");
    expect(getTermDefinition("CP")).toContain("Center of pressure");
    expect(getTermDefinition("Pressure coefficient")).toContain("(p − p∞)/q");
  });
  it("keeps recovery height and atmosphere altitude conventions explicit", () => {
    expect(getTermDefinition("Main deployment altitude")).toContain(
      "flat launch-level plane",
    );
    expect(getTermDefinition("Altitude MSL")).toContain(
      "adds the entered launch altitude",
    );
    expect(getTermDefinition("Wind direction")).toContain(
      "not the weather-report direction it comes from",
    );
    expect(getTermDefinition("Wind direction")).toContain("0° north, 90° east");
  });
  it("finds punctuation variants and preserves numerical method limitations", () => {
    expect(getTermDefinition("Poisson’s ratio")).toBe(
      getTermDefinition("Poisson's ratio"),
    );
    expect(getTermDefinition("Main Cd × area")).toContain(
      "instant full deployment",
    );
    expect(getTermDefinition("Euler CFD")).toContain("omits skin friction");
    expect(getTermDefinition("Peak von Mises")).toContain(
      "not a composite failure criterion",
    );
    expect(getTermDefinition("not a technical term")).toBeUndefined();
  });
});
