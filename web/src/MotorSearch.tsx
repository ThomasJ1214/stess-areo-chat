import { useEffect, useRef, useState } from "react";
import {
  Download,
  Globe,
  Search,
  X,
  ExternalLink,
  CheckCircle2,
} from "lucide-react";
import { request } from "./api";
import HelpTip from "./HelpTip";
import type { Motor, Project } from "./types";

interface CatalogMotor {
  motor_id: string;
  manufacturer: string;
  designation: string;
  common_name: string;
  diameter_m: number | null;
  length_m: number | null;
  total_impulse_ns: number | null;
  average_thrust_n: number | null;
  burn_time_s: number | null;
  cert_org: string;
  data_files: number;
  source_url: string;
}
interface CatalogCurve {
  motor_id: string;
  simfile_id: string;
  format: string;
  source: string;
  license: string;
  source_url: string;
  fetched_at: string;
}
interface Preview {
  review_token: string;
  motor: Motor;
  provenance: CatalogCurve & { provider: string; curve_sha256: string };
  summary: {
    total_impulse_ns: number;
    max_thrust_n: number;
    burn_time_s: number;
    samples: number;
  };
  warnings: string[];
}
const sourceName = (value: string) =>
  ({ cert: "Certification test", mfr: "Manufacturer", user: "Contributor" })[
    value
  ] ||
  value ||
  "Unspecified";
const n = (value: number | null, unit: string, digits = 2) =>
  value === null ? "Unavailable" : `${value.toFixed(digits)} ${unit}`;

/** A plain SVG from the actual imported curve; never invented motor data. */
function CurvePlot({ motor }: { motor: Motor }) {
  const maxT = Math.max(motor.curve.at(-1)?.[0] || 0, 0.001);
  const maxF = motor.curve.reduce(
    (maximum, point) => Math.max(maximum, point[1]),
    1,
  );
  // Keep both extrema in each time bucket when a file has many samples.
  const points: number[][] = [];
  const stride = Math.max(1, Math.ceil(motor.curve.length / 350));
  for (let i = 0; i < motor.curve.length; i += stride) {
    const bucket = motor.curve.slice(i, i + stride);
    const selected = [
      bucket[0],
      bucket.reduce((a, b) => (a[1] < b[1] ? a : b)),
      bucket.reduce((a, b) => (a[1] > b[1] ? a : b)),
      bucket.at(-1)!,
    ];
    points.push(...Array.from(new Set(selected)).sort((a, b) => a[0] - b[0]));
  }
  const path = points
    .map(
      ([t, f], i) =>
        `${i ? "L" : "M"}${(55 + (485 * t) / maxT).toFixed(2)},${(180 - (150 * f) / maxF).toFixed(2)}`,
    )
    .join(" ");
  return (
    <svg
      className="motor-curve-plot"
      data-testid="motor-curve-plot"
      viewBox="0 0 570 220"
      role="img"
      aria-label={`Downloaded ${motor.name} thrust curve, time in seconds and thrust in newtons`}
    >
      <line x1="55" y1="180" x2="540" y2="180" stroke="currentColor" />
      <line x1="55" y1="30" x2="55" y2="180" stroke="currentColor" />
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <g key={f}>
          <line
            x1="55"
            y1={180 - f * 150}
            x2="540"
            y2={180 - f * 150}
            stroke="currentColor"
            opacity=".12"
          />
          <text
            x="49"
            y={184 - f * 150}
            textAnchor="end"
            fill="currentColor"
            fontSize="10"
          >
            {Math.round(f * maxF)}
          </text>
          <text
            x={55 + f * 485}
            y="197"
            textAnchor="middle"
            fill="currentColor"
            fontSize="10"
          >
            {(f * maxT).toFixed(1)}
          </text>
        </g>
      ))}
      <path d={path} stroke="#55c9fa" strokeWidth="2" fill="none" />
      <text
        x="297"
        y="216"
        textAnchor="middle"
        fill="currentColor"
        fontSize="11"
      >
        Time (s)
      </text>
      <text
        x="12"
        y="105"
        textAnchor="middle"
        fill="currentColor"
        fontSize="11"
        transform="rotate(-90,12,105)"
      >
        Thrust (N)
      </text>
    </svg>
  );
}

export default function MotorSearch({
  projectId,
  onImported,
  onClose,
  query = "",
}: {
  projectId: string;
  onImported: (project: Project) => void;
  onClose: () => void;
  query?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const controller = useRef<AbortController | null>(null);
  const [designation, setDesignation] = useState(query);
  const [manufacturer, setManufacturer] = useState("");
  const [motors, setMotors] = useState<CatalogMotor[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [selected, setSelected] = useState<CatalogMotor | null>(null);
  const [curves, setCurves] = useState<CatalogCurve[] | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const element = dialog.current!;
    const previousFocus = document.activeElement;
    element.showModal();
    return () => {
      controller.current?.abort();
      element.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected)
        previousFocus.focus({ preventScroll: true });
    };
  }, []);
  const close = () => {
    if (busy !== "Importing") {
      controller.current?.abort();
      onClose();
    }
  };
  const perform = async (
    label: string,
    path: string,
    body: unknown,
    receive: (value: any) => void,
    method = "POST",
  ) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(label);
    setError("");
    try {
      const value = await request(path, {
        method,
        signal: current.signal,
        ...(method === "POST" ? { body: JSON.stringify(body) } : {}),
      });
      if (!current.signal.aborted) receive(value);
    } catch (failure) {
      if (!current.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "Motor lookup failed. Import a local .eng/.rse file instead.",
        );
    } finally {
      if (!current.signal.aborted) setBusy("");
    }
  };
  const search = () => {
    setSelected(null);
    setCurves(null);
    setPreview(null);
    setTotal(null);
    setMotors([]);
    void perform(
      "Searching",
      "/motors/search",
      {
        query: designation.trim(),
        manufacturer: manufacturer.trim(),
        limit: 30,
      },
      (value) => {
        setMotors(value.motors);
        setTotal(value.total);
      },
    );
  };
  const review = (motor: CatalogMotor) => {
    setSelected(motor);
    setCurves(null);
    setPreview(null);
    void perform(
      "Loading curves",
      `/motors/${motor.motor_id}/curves`,
      null,
      (value) => setCurves(value.curves),
      "GET",
    );
  };
  return (
    <dialog
      ref={dialog}
      className="user-guide motor-search"
      aria-labelledby="motor-search-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="user-guide-content">
        <header>
          <div>
            <Globe size={20} />
            <h2 id="motor-search-title">Find a motor curve</h2>
          </div>
          <button
            aria-label="Close motor search"
            disabled={busy === "Importing"}
            onClick={close}
          >
            <X size={20} />
          </button>
        </header>
        <p>
          Search the live <strong>ThrustCurve.org</strong> catalog. Only your
          search filters and selected motor IDs are sent; your rocket stays on
          this computer. No account or API key is needed.
        </p>
        <form
          className="motor-search-fields"
          onSubmit={(event) => {
            event.preventDefault();
            search();
          }}
        >
          <label>
            <span>
              Motor designation{" "}
              <HelpTip
                term="Motor designation"
                definition="The motor's exact published code, such as J350W. Codes identify an impulse class, nominal average thrust, and often a manufacturer-specific propellant. Different manufacturers or curve tests can share similar names; review the exact hardware and source."
              />
            </span>
            <input
              aria-label="Motor designation"
              autoFocus
              value={designation}
              maxLength={80}
              placeholder="Exact designation, e.g. J350W"
              disabled={!!busy}
              onChange={(event) => setDesignation(event.target.value)}
            />
          </label>
          <label>
            Manufacturer
            <input
              aria-label="Manufacturer"
              value={manufacturer}
              maxLength={80}
              placeholder="Optional, e.g. AeroTech"
              disabled={!!busy}
              onChange={(event) => setManufacturer(event.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={!!busy || !(designation.trim() || manufacturer.trim())}
          >
            <Search size={16} />
            Search catalog
          </button>
        </form>
        <p className="muted">
          Use the exact designation, or leave it empty to browse a manufacturer.
          Catalog lookup requires internet; local .eng/.rse file imports and
          simulations work offline.
        </p>
        {busy && (
          <p className="motor-search-status" role="status">
            {busy}…
          </p>
        )}
        {error && (
          <p className="warning" role="alert">
            {error}
          </p>
        )}
        {total !== null && (
          <p role="status">
            {total === 0
              ? "No matching motors found. Check the exact designation or search by manufacturer."
              : `${motors.length} of ${total} matching motors shown.`}
          </p>
        )}
        <div className="motor-catalog-results">
          {motors.map((motor) => (
            <article
              className={`motor-catalog-card${selected?.motor_id === motor.motor_id ? " selected" : ""}`}
              key={motor.motor_id}
            >
              <div>
                <h3>
                  {motor.designation || motor.common_name}{" "}
                  <small>{motor.manufacturer}</small>
                </h3>
                <p>
                  {n(
                    motor.diameter_m === null ? null : motor.diameter_m * 1000,
                    "mm",
                    1,
                  )}{" "}
                  diameter ·{" "}
                  {n(
                    motor.length_m === null ? null : motor.length_m * 1000,
                    "mm",
                    1,
                  )}{" "}
                  length
                </p>
                <p>
                  {n(motor.total_impulse_ns, "N·s")} impulse ·{" "}
                  {n(motor.burn_time_s, "s")} burn · {motor.data_files} curve
                  file(s)
                </p>
                {motor.cert_org && (
                  <p className="muted">
                    Catalog certification organization: {motor.cert_org}
                  </p>
                )}
              </div>
              <button disabled={!!busy} onClick={() => review(motor)}>
                Review curves
              </button>
            </article>
          ))}
        </div>
        {selected && (
          <section className="motor-curve-selection">
            <h3>Available curves for {selected.designation}</h3>
            <p>
              Source labels below are reported by the provider. Review the
              downloaded curve before importing.
            </p>
            {curves?.length === 0 && (
              <p>
                No supported ENG/RSE curves are currently available for this
                motor.
              </p>
            )}
            {curves?.map((curve) => (
              <article className="motor-file-card" key={curve.simfile_id}>
                <div>
                  <strong>
                    {curve.format === "RASP" ? "ENG / RASP" : "RSE / RockSim"}
                  </strong>{" "}
                  · {sourceName(curve.source)} · License:{" "}
                  {curve.license || "unspecified"}
                  <small>Curve ID: {curve.simfile_id}</small>
                </div>
                <button
                  disabled={!!busy}
                  onClick={() => {
                    setPreview(null);
                    void perform(
                      "Downloading preview",
                      "/motors/preview",
                      {
                        motor_id: selected.motor_id,
                        simfile_id: curve.simfile_id,
                      },
                      setPreview,
                    );
                  }}
                >
                  Preview curve
                </button>
              </article>
            ))}
            {!!curves?.length && (
              <p className="muted">
                Up to 20 newest supported files are listed. Multiple curves can
                represent different tests of the same motor.
              </p>
            )}
          </section>
        )}
        {preview && (
          <section className="motor-review">
            <h3>
              <CheckCircle2 size={18} />
              Review downloaded {preview.motor.name}
            </h3>
            <CurvePlot motor={preview.motor} />
            <dl className="motor-review-values">
              <dt>Diameter / length</dt>
              <dd>
                {n(preview.motor.diameter * 1000, "mm", 1)} /{" "}
                {n(preview.motor.length * 1000, "mm", 1)}
              </dd>
              <dt>
                Dry / propellant mass{" "}
                <HelpTip
                  term="Motor masses"
                  definition="Dry mass is the loaded motor assembly mass after propellant has burned. Propellant mass is consumed during the modeled burn. The downloaded file supplies these values; verify that its case, closures, and reload match your hardware."
                />
              </dt>
              <dd>
                {n(preview.motor.dry_mass, "kg", 3)} /{" "}
                {n(preview.motor.propellant_mass, "kg", 3)}
              </dd>
              <dt>
                Integrated impulse <HelpTip term="Total impulse" />
              </dt>
              <dd>{n(preview.summary.total_impulse_ns, "N·s")}</dd>
              <dt>Final curve time / peak thrust</dt>
              <dd>
                {n(preview.summary.burn_time_s, "s")} /{" "}
                {n(preview.summary.max_thrust_n, "N")}
              </dd>
              <dt>
                Curve source{" "}
                <HelpTip
                  term="Curve source"
                  definition="ThrustCurve.org reports whether a file comes from a certification test, manufacturer, or contributor. The app preserves this label and file identity; it does not independently certify the measurement or the motor."
                />
              </dt>
              <dd>
                {sourceName(preview.provenance.source)} (provider reported)
              </dd>
              <dt>Format / license</dt>
              <dd>
                {preview.provenance.format} /{" "}
                {preview.provenance.license || "Unspecified"}
              </dd>
              <dt>Fetched (UTC)</dt>
              <dd>{preview.provenance.fetched_at}</dd>
              <dt>
                File SHA256{" "}
                <HelpTip
                  term="File SHA256"
                  definition="A fingerprint of the exact downloaded motor file. Matching fingerprints identify unchanged bytes for reproducibility. A hash does not prove the curve's accuracy, certification, or suitability for your rocket."
                />
              </dt>
              <dd className="motor-sha">{preview.provenance.curve_sha256}</dd>
            </dl>
            <a
              href={preview.provenance.source_url}
              target="_blank"
              rel="noreferrer"
            >
              View provider curve page <ExternalLink size={13} />
            </a>
            {preview.warnings.map((warning) => (
              <p className="warning" key={warning}>
                {warning}
              </p>
            ))}
            <p>
              <strong>Import adds this curve to the project.</strong> Then
              choose it under Design → Flight setup → Motor and apply the
              configuration. It will not replace geometry or change a motor
              assignment.
            </p>
            <button
              disabled={!!busy}
              onClick={() =>
                void perform(
                  "Importing",
                  "/motors/import",
                  { review_token: preview.review_token, project_id: projectId },
                  (value: Project) => {
                    onImported(value);
                    onClose();
                  },
                )
              }
            >
              <Download size={17} />
              Import reviewed motor
            </button>
          </section>
        )}
      </div>
    </dialog>
  );
}
