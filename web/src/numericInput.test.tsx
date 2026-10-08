import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { parseNumberInput, numberInputIssue } from "./numericInput";
import { SIField } from "./Controls";

describe("engineering number entry", () => {
  it("accepts decimal/scientific edits and rejects incomplete or nondecimal values", () => {
    expect(parseNumberInput("-.25")).toBe(-0.25);
    expect(parseNumberInput(" 1.2e-3 ")).toBe(0.0012);
    expect(parseNumberInput("2.")).toBe(2);
    for (const invalid of [
      "",
      "-",
      "1e",
      "0x10",
      "Infinity",
      "NaN",
      "1e999",
      "1,000",
    ])
      expect(parseNumberInput(invalid)).toBeNull();
  });
  it("marks out-of-range values without silently clipping them", () => {
    expect(numberInputIssue("2", 0, 2)).toBe("");
    expect(numberInputIssue("3", 0, 2)).toBe("Must be at most 2.");
    expect(numberInputIssue("-1", 0, 2)).toBe("Must be at least 0.");
    expect(numberInputIssue("1e", 0, 2)).toBe("Enter a finite decimal number.");
  });
  it("converts SI bounds alongside a US customary display value", () => {
    const html = renderToStaticMarkup(
      <SIField
        label="Length"
        kind="length"
        units="us"
        value={2}
        min={1}
        max={3}
        onChange={() => {}}
      />,
    );
    expect(Number(html.match(/aria-valuemin="([^"]+)"/)![1])).toBeCloseTo(
      3.280839895,
      7,
    );
    expect(Number(html.match(/aria-valuemax="([^"]+)"/)![1])).toBeCloseTo(
      9.842519685,
      7,
    );
    expect(html).toContain('aria-invalid="false"');
    const pressure = renderToStaticMarkup(
      <SIField
        label="Pressure"
        kind="pressure"
        units="metric"
        value={1000}
        min={500}
        max={2000}
        onChange={() => {}}
      />,
    );
    expect(pressure).toContain('aria-valuemin="0.5"');
    expect(pressure).toContain('aria-valuemax="2"');
    const atBoundary = renderToStaticMarkup(
      <SIField
        label="Wind"
        kind="speed"
        units="us"
        value={150}
        min={0}
        max={150}
        onChange={() => {}}
      />,
    );
    expect(atBoundary).toContain('aria-invalid="false"');
  });
});
