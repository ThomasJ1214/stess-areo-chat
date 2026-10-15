import { AlertTriangle, ShieldCheck } from "lucide-react";
import HelpTip from "./HelpTip";
import { fmt } from "./units";

/** Show actual supported coverage independently of the enclosing job status. */
export default function FlightStructureCoverage({
  analysis,
  row,
}: {
  analysis: any;
  row: any;
}) {
  if (!analysis) return null;
  const summary = analysis.summary || {};
  const unavailable = (
    Array.isArray(row?.dynamic_structural_components)
      ? row.dynamic_structural_components
      : []
  ).filter((component: any) => component.supported === false);
  const hasCoverage = summary.rows_with_available_results > 0;
  return (
    <div
      className="flight-structural-coverage solver-readiness"
      aria-label="Dynamic fin structural coverage"
    >
      <h4>
        <ShieldCheck size={14} /> Dynamic fin FEA coverage{" "}
        <HelpTip
          term="Dynamic fin FEA coverage"
          definition="One-dimensional Euler–Bernoulli fin beam finite elements with consistent mass, a complete modal basis and declared exact-modal or legacy Newmark time integration. Only supported original fins and valid small-angle pre-recovery loads are solved. A completed flight job does not mean all parts or all flight times have structural results."
        />
      </h4>
      <p>
        <strong>
          {summary.status === "completed"
            ? hasCoverage
              ? "Completed within supported scope"
              : "No supported dynamic results"
            : `Partial structural analysis · ${String(summary.status || "unavailable").replaceAll("_", " ")}`}
        </strong>{" "}
        · {fmt(summary.supported_components, 0)} supported fin sets ·{" "}
        {fmt(summary.unavailable_components, 0)} unavailable fin sets.
      </p>
      <p>
        {fmt(summary.rows_with_available_results, 0)} samples with results ·{" "}
        {fmt(summary.unavailable_rows, 0)} unavailable samples ·{" "}
        {fmt(summary.substeps, 0)} actual structural substeps.{" "}
        {summary.coverage ||
          "Check the recorded component and load validity before using this result."}
      </p>
      <p>
        Detailed CAD fins, composite layups, canopy attachment and recovery
        opening shock are outside this solver's scope. Whole-vehicle stress
        remains a separate quasi-static estimate.
      </p>
      {unavailable.length > 0 && (
        <details>
          <summary>
            <AlertTriangle size={12} /> Unavailable at this sample
          </summary>
          <ul>
            {unavailable.map((component: any, index: number) => (
              <li key={component.component_id || index}>
                <strong>{component.name || "Component"}:</strong>{" "}
                {component.reason || "No supported structural solution."}
              </li>
            ))}
          </ul>
        </details>
      )}
      {analysis.warnings?.length > 0 && (
        <details>
          <summary>Structural assumptions and warnings</summary>
          <ul>
            {analysis.warnings.map((warning: string, index: number) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
