import { useState } from "react";
import { AlertTriangle, CheckCircle2, Copy } from "lucide-react";
import { fmt } from "./units";

type CudaDiagnostic = {
  available: boolean;
  reason: string;
  probe_stage: string;
  failure_kind?: string | null;
  root_cause?: string | null;
  cupy_version?: string | null;
  driver_version?: string | null;
  runtime_version?: string | null;
  error_details?: string;
  error_details_truncated?: boolean;
  bundled_runtime?: unknown;
  devices?: {
    index: number;
    name: string;
    memory_total_bytes: number;
    compute_capability: string;
  }[];
};

const checkNames: Record<string, string> = {
  import: "CuPy import",
  driver: "NVIDIA driver access",
  runtime: "CUDA runtime load",
  device_discovery: "NVIDIA device discovery",
  allocation: "GPU memory allocation",
  kernel: "Compiled CUDA calculation",
  synchronization: "GPU synchronization",
  verification: "Numerical verification",
  complete: "All numerical checks passed",
};

const detailStyle = {
  maxHeight: 320,
  overflow: "auto",
  whiteSpace: "pre-wrap" as const,
  overflowWrap: "anywhere" as const,
  padding: "12px",
  borderRadius: 6,
  background: "#101b23",
  fontSize: 11,
  lineHeight: 1.55,
};

export default function GpuDiagnostics({
  diagnostics,
}: {
  diagnostics?: CudaDiagnostic | null;
}) {
  const [copying, setCopying] = useState(false);
  const [feedback, setFeedback] = useState("");

  async function copyDiagnostics() {
    if (!diagnostics) return;
    setCopying(true);
    setFeedback("");
    const json = JSON.stringify(diagnostics, null, 2);
    try {
      if (!navigator.clipboard?.writeText)
        throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(json);
      setFeedback("Diagnostics copied. Nothing was sent online.");
    } catch {
      let url: string | undefined;
      try {
        url = URL.createObjectURL(
          new Blob([json], { type: "application/json" }),
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = "RocketWorkbench-GPU-diagnostics.json";
        document.body.appendChild(link);
        link.click();
        link.remove();
        setFeedback(
          "Clipboard unavailable. A local diagnostic JSON download was requested.",
        );
      } catch {
        setFeedback(
          "Copy is unavailable in this view. Select the technical details below to copy them manually.",
        );
      } finally {
        if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000);
      }
    } finally {
      setCopying(false);
    }
  }

  return (
    <div className="gpu-diagnostics">
      <h3 style={{ display: "flex", alignItems: "center", gap: 9 }}>
        {diagnostics?.available ? (
          <CheckCircle2 size={20} color="#6bd5b7" aria-hidden="true" />
        ) : (
          <AlertTriangle size={20} color="#efbd80" aria-hidden="true" />
        )}
        {diagnostics
          ? diagnostics.available
            ? "CUDA calculation available"
            : "CUDA calculation unavailable"
          : "CUDA diagnostics unavailable"}
      </h3>
      <p>
        {diagnostics?.reason ||
          "The local service has not returned a CUDA diagnostic report yet."}
      </p>
      {diagnostics && (
        <>
          <dl>
            <div>
              <dt>
                {diagnostics.available ? "Numerical check" : "Failed check"}
              </dt>
              <dd>
                {checkNames[diagnostics.probe_stage] || diagnostics.probe_stage}
              </dd>
            </div>
            {diagnostics.root_cause && (
              <div>
                <dt>Original error</dt>
                <dd>
                  <code>{diagnostics.root_cause}</code>
                </dd>
              </div>
            )}
            {diagnostics.devices?.map((device) => (
              <div key={device.index}>
                <dt>Device {device.index}</dt>
                <dd>
                  <strong>{device.name}</strong> ·{" "}
                  {fmt(device.memory_total_bytes / 1024 ** 3, 1)} GiB · compute
                  capability {device.compute_capability}
                </dd>
              </div>
            ))}
            {(
              [
                ["CuPy", diagnostics.cupy_version],
                ["Driver CUDA compatibility", diagnostics.driver_version],
                ["CUDA runtime", diagnostics.runtime_version],
              ] as const
            )
              .filter(([, value]) => value)
              .map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
          </dl>
          <p>
            This checks a small allocation and a compiled numerical calculation.
            The 3D viewport uses a separate graphics path. Restart the app after
            changing its installation or the NVIDIA driver to refresh this
            check.
          </p>
          <button onClick={copyDiagnostics} disabled={copying}>
            <Copy size={15} aria-hidden="true" />
            {copying ? "Copying diagnostics…" : "Copy diagnostics"}
          </button>
          <p className="microcopy">
            Diagnostic details stay on this computer. Copying or saving includes
            local installation paths; review them before sharing.
          </p>
          <p role="status" aria-live="polite">
            {feedback}
          </p>
          {diagnostics.error_details && (
            <details style={{ marginTop: 12 }}>
              <summary>Technical error details</summary>
              {diagnostics.error_details_truncated && (
                <p className="microcopy">
                  Long details retain the beginning and final cause.
                </p>
              )}
              <pre style={detailStyle}>{diagnostics.error_details}</pre>
            </details>
          )}
          {diagnostics.bundled_runtime && (
            <details style={{ marginTop: 12 }}>
              <summary>Bundled CUDA runtime</summary>
              <pre style={detailStyle}>
                {JSON.stringify(diagnostics.bundled_runtime, null, 2)}
              </pre>
            </details>
          )}
        </>
      )}
      <p className="microcopy">
        Automatic backend records its CPU fallback. Explicit GPU mode reports a
        failure. Numerical CUDA requires a supported NVIDIA GPU and driver.
      </p>
    </div>
  );
}
