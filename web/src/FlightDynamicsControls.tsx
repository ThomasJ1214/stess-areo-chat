import { Activity, Wind, ShieldCheck } from "lucide-react";
import { FieldSelect, NumberField, SIField, Toggle } from "./Controls";
import HelpTip from "./HelpTip";
import type { Conditions, Configuration, Units } from "./types";
import "./flightDynamicsControls.css";

export interface FlightOptions {
  time_integrator: string;
  structural_mode: string;
  damping_ratio: number;
  elements: number;
  steps_per_period: number;
  allow_isotropic_surrogate: boolean;
  [key: string]: unknown;
}

export default function FlightDynamicsControls({
  conditions,
  onConditions,
  options,
  onOptions,
  units,
}: {
  conditions: Conditions;
  onConditions: (next: Conditions) => void;
  options: FlightOptions;
  onOptions: (next: FlightOptions) => void;
  units: Units;
}) {
  const set = <K extends keyof Conditions>(key: K, value: Conditions[K]) =>
    onConditions({ ...conditions, [key]: value });
  return (
    <div className="flight-dynamics-controls">
      <div className="panel-divider" />
      <div className="subheading">
        <Activity size={13} /> FLIGHT DYNAMICS
      </div>
      <FieldSelect
        label="Flight dynamics model"
        value={conditions.flight_model}
        onChange={(model) =>
          set("flight_model", model as Conditions["flight_model"])
        }
        hint="Rigid-body 6DOF integrates position, velocity, attitude and angular rates. It can react to wind through normal force and aerodynamic moments. The point-mass model retains the earlier prescribed gravity-turn behavior. Both use simplified engineering aerodynamic coefficients."
      >
        <option value="point_mass">Point mass · previous model</option>
        <option value="rigid_body">
          Rigid body · 6DOF · recommended for attitude
        </option>
      </FieldSelect>
      <p className="solver-note">
        {conditions.flight_model === "rigid_body"
          ? "Attitude reacts to actual calculated loads. Check the inertia estimate and aerodynamic validity warnings; this does not resolve separated flow or parachute suspension dynamics."
          : "Body attitude follows a prescribed gravity turn. Select rigid body to calculate wind-induced rotation."}
      </p>
      {conditions.flight_model === "rigid_body" && (
        <details className="flight-advanced">
          <summary>
            Initial body angular rates{" "}
            <HelpTip
              term="Body angular rates"
              definition="Rotation rates about the nose-body axes, in radians per second. Positive body X points toward the nose. The rail constrains motion and rotation until rail exit."
            />
          </summary>
          {conditions.initial_angular_velocity_body_rad_s.map(
            (value, index) => (
              <NumberField
                key={index}
                label={`Initial ${["roll", "pitch", "yaw"][index]} rate`}
                value={value}
                unit="rad/s"
                onChange={(n) => {
                  if (n !== null) {
                    const rates = [
                      ...conditions.initial_angular_velocity_body_rad_s,
                    ];
                    rates[index] = n;
                    set("initial_angular_velocity_body_rad_s", rates);
                  }
                }}
              />
            ),
          )}
        </details>
      )}
      <div className="panel-divider" />
      <div className="subheading">
        <Wind size={13} /> WIND & GUST MODEL
      </div>
      <FieldSelect
        label="Wind model"
        value={conditions.wind_model}
        onChange={(model) =>
          set("wind_model", model as Conditions["wind_model"])
        }
        hint="Dryden uses reproducible stochastic gusts with a finite length scale. It is an engineering atmospheric-disturbance model, not resolved turbulent CFD or a weather forecast. The legacy model uses smooth seeded sinusoidal gusts."
      >
        <option value="legacy_gust">Smooth gusts · previous model</option>
        <option value="dryden">Dryden stochastic gusts</option>
      </FieldSelect>
      <p className="solver-note">
        Gust strength uses Turbulence intensity above. A zero value produces no
        gust perturbation; the random seed reproduces a run.
      </p>
      {conditions.wind_model === "dryden" && (
        <>
          <SIField
            label="Turbulence length scale"
            kind="length"
            units={units}
            value={conditions.turbulence_length_scale_m}
            min={0.01}
            onChange={(n) => n !== null && set("turbulence_length_scale_m", n)}
            hint="Spatial correlation scale of modeled atmospheric gusts. Use measured or justified site conditions; this does not control CFD mesh size."
          />
          <SIField
            label="Dryden convection speed override"
            kind="speed"
            units={units}
            value={conditions.turbulence_transport_speed_m_s}
            min={0.000001}
            onChange={(n) => set("turbulence_transport_speed_m_s", n)}
            hint="Optional fixed transport speed converting gust length scales to time scales. Leave blank for the solver's documented automatic value. This is an atmospheric modeling assumption, not a live aircraft airspeed measurement."
          />
        </>
      )}
      <details className="flight-advanced">
        <summary>Wind shear and gust sampling</summary>
        <SIField
          label="Wind reference height"
          kind="length"
          units={units}
          value={conditions.wind_reference_height_m}
          min={0.01}
          onChange={(n) => n !== null && set("wind_reference_height_m", n)}
          hint="Height above ground at which the entered lateral wind speed applies. The power-law shear exponent changes the mean wind with height."
        />
        <NumberField
          label="Wind shear exponent"
          value={conditions.wind_shear_exponent}
          min={0}
          max={1}
          onChange={(n) => n !== null && set("wind_shear_exponent", n)}
          hint="Exponent in the mean-wind height law. Zero keeps mean wind constant. Choose a justified value for the launch site's terrain and weather."
        />
        <NumberField
          label="Gust sample interval"
          unit="s"
          value={conditions.turbulence_sample_interval_s}
          min={0.001}
          max={0.2}
          onChange={(n) => n !== null && set("turbulence_sample_interval_s", n)}
          hint="Time spacing of the precomputed reproducible gust field, independent of adaptive flight integration. Refine this when checking sensitivity to rapid gusts."
        />
      </details>
      {conditions.wind_events?.length > 0 && (
        <div className="flight-wind-schedule">
          <p className="solver-note">
            This launch includes {conditions.wind_events.length} saved
            environment changes. The flight timeline will show their actual
            event times.
          </p>
          <button className="quiet-btn" onClick={() => set("wind_events", [])}>
            Clear scheduled environment changes
          </button>
        </div>
      )}
      <div className="panel-divider" />
      <div className="subheading">
        <ShieldCheck size={13} /> FLIGHT STRUCTURAL RESPONSE
      </div>
      <FieldSelect
        label="Flight structural model"
        value={options.structural_mode}
        onChange={(structural_mode) =>
          onOptions({ ...options, structural_mode })
        }
        hint="Quasi-static estimates follow each sample's loads. Dynamic fins integrate the dynamic bending response of one-dimensional beam finite elements with a complete modal basis. Neither is time-dependent solid FEA or fluid–structure coupling."
      >
        <option value="quasi_static">
          Quasi-static beam and fin estimates
        </option>
        <option value="dynamic_fins">Dynamic fin bending · 1D beam FEA</option>
      </FieldSelect>
      {options.structural_mode === "dynamic_fins" && (
        <>
          <FieldSelect
            label="Fin time integrator"
            value={String(options.time_integrator ?? "exact_foh")}
            onChange={(time_integrator) =>
              onOptions({ ...options, time_integrator })
            }
            hint="Exact propagation retains every beam mode for linearly interpolated recorded loads. It cannot recover unrecorded load fluctuations or stress peaks between samples. Legacy Newmark uses fundamental-period substeps and needs higher-mode time-convergence checks."
          >
            <option value="exact_foh">
              Exact modal · recorded linear loads
            </option>
            <option value="newmark">
              Legacy Newmark · convergence study required
            </option>
          </FieldSelect>
          <NumberField
            label="Fin modal damping ratio"
            value={options.damping_ratio}
            min={0}
            max={0.2}
            onChange={(n) =>
              n !== null && onOptions({ ...options, damping_ratio: n })
            }
            hint="Fraction of critical damping applied to the supported fin beam modes. This property requires measurement or a justified sensitivity study; 0.01 is a nominal assumption, not a material certification."
          />
          <details className="flight-advanced">
            <summary>Dynamic fin discretization and material scope</summary>
            <NumberField
              label="Fin beam elements"
              value={options.elements}
              min={2}
              max={64}
              step={1}
              onChange={(n) =>
                n !== null && onOptions({ ...options, elements: n })
              }
              hint="Number of one-dimensional bending elements along the fin span. Check convergence by refining this discretization. This is not a three-dimensional solid mesh."
            />
            {options.time_integrator === "newmark" && (
              <NumberField
                label="Steps per fundamental beam period"
                value={options.steps_per_period}
                min={12}
                max={100}
                step={1}
                onChange={(n) =>
                  n !== null && onOptions({ ...options, steps_per_period: n })
                }
                hint="Controls Newmark steps relative to the fundamental period only. Higher modes require a separate time-convergence study."
              />
            )}
            <Toggle
              label="Allow isotropic composite approximation"
              value={options.allow_isotropic_surrogate}
              onChange={() =>
                onOptions({
                  ...options,
                  allow_isotropic_surrogate: !options.allow_isotropic_surrogate,
                })
              }
            />
            <p className="solver-note">
              Carbon and fiberglass require this explicit acknowledgement to use
              scalar material properties. This approximation does not evaluate
              laminate ply directions, interlaminar stress, or composite failure
              criteria.
            </p>
          </details>
        </>
      )}
    </div>
  );
}

/** Overrides stay in the configuration draft until Apply flight setup. */
export function FlightConfigurationDynamics({
  configuration,
  onChange,
  units,
}: {
  configuration: Configuration | null;
  onChange: (key: string, value: unknown) => void;
  units: Units;
}) {
  if (!configuration) return null;
  const tensor = configuration.inertia_override_kg_m2;
  const enabled = Array.isArray(tensor);
  const entries = [
    [0, 0, "Ixx"],
    [1, 1, "Iyy"],
    [2, 2, "Izz"],
    [0, 1, "Ixy"],
    [0, 2, "Ixz"],
    [1, 2, "Iyz"],
  ] as const;
  return (
    <div className="flight-configuration-dynamics">
      <div className="panel-divider" />
      <div className="subheading">
        <Activity size={13} /> ATTITUDE & RECOVERY RESPONSE
      </div>
      <div className="field-pair">
        <NumberField
          label="Main chute inflation time"
          value={configuration.main_inflation_time ?? 0}
          unit="s"
          min={0}
          onChange={(n) => n !== null && onChange("main_inflation_time", n)}
          hint="Time for the lumped main recovery drag area to grow after deployment. Zero preserves instantaneous deployment. This approximates force buildup, not line shock or canopy dynamics."
        />
        {configuration.deployment === "dual" && (
          <NumberField
            label="Drogue inflation time"
            value={configuration.drogue_inflation_time ?? 0}
            unit="s"
            min={0}
            onChange={(n) => n !== null && onChange("drogue_inflation_time", n)}
            hint="Time for drogue effective drag area to grow after deployment. This is a prescribed inflation model, not a resolved canopy simulation."
          />
        )}
      </div>
      <details className="flight-advanced">
        <summary>Rigid-body inertia and aerodynamic damping</summary>
        <Toggle
          label="Override inertia tensor"
          value={enabled}
          onChange={() =>
            onChange(
              "inertia_override_kg_m2",
              enabled
                ? null
                : [
                    [0, 0, 0],
                    [0, 0, 0],
                    [0, 0, 0],
                  ],
            )
          }
        />
        <p className="solver-note">
          Default inertia is calculated from supported component geometry with
          explicit fallback warnings. Enter an override only from a justified
          calculation or measurement.
        </p>
        {enabled && (
          <>
            <div className="field-pair">
              {entries.map(([i, j, label]) => (
                <SIField
                  key={label}
                  label={label}
                  kind="inertia"
                  units={units}
                  value={tensor?.[i]?.[j] ?? 0}
                  min={i === j ? 0.000000001 : undefined}
                  hint="Complete dry rocket's symmetric inertia tensor about dry CG in right-handed nose-body axes: X toward nose, Y CAD +Y, Z CAD −Z. Propellant inertia is added during flight. Must be positive definite; cross terms use matrix-entry signs."
                  onChange={(n) => {
                    if (n !== null) {
                      const next = tensor!.map((row) => [...row]);
                      next[i][j] = n;
                      next[j][i] = n;
                      onChange("inertia_override_kg_m2", next);
                    }
                  }}
                />
              ))}
            </div>
            <label className="flight-provenance">
              Inertia source{" "}
              <HelpTip
                term="Inertia source"
                definition="Required provenance describing how the tensor was measured or computed, including its reference frame and dry-vehicle state."
              />
              <input
                aria-label="Inertia source"
                type="text"
                value={configuration.inertia_override_source ?? ""}
                onChange={(e) =>
                  onChange("inertia_override_source", e.target.value)
                }
                placeholder="Measurement or calculation reference"
              />
            </label>
            {!configuration.inertia_override_source?.trim() && (
              <p className="field-error">
                Enter the inertia calculation or measurement source before
                applying.
              </p>
            )}
          </>
        )}
        <Toggle
          label="Supply pitch/yaw damping coefficient"
          value={configuration.pitch_damping_coefficient != null}
          onChange={() =>
            onChange(
              "pitch_damping_coefficient",
              configuration.pitch_damping_coefficient == null ? 0 : null,
            )
          }
        />
        {configuration.pitch_damping_coefficient != null && (
          <NumberField
            label="Pitch damping coefficient Cmq"
            value={configuration.pitch_damping_coefficient}
            max={0}
            onChange={(n) => onChange("pitch_damping_coefficient", n)}
            hint="User-supplied dimensionless aerodynamic rate-damping coefficient, applied to pitch and yaw. Non-positive values oppose rotation. There is no built-in empirical damping calibration; missing means zero with a warning."
          />
        )}
      </details>
    </div>
  );
}
