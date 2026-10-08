import { useEffect, useRef } from "react";
import { BookOpen, X } from "lucide-react";
import type { Workspace } from "./types";

/** Bundled instructions stay available without opening a browser or network. */
export default function UserGuide({
  onClose,
  onNavigate,
}: {
  onClose: () => void;
  onNavigate: (workspace: Workspace) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    const previousFocus = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected)
        previousFocus.focus({ preventScroll: true });
    };
  }, []);
  const go = (workspace: Workspace) => {
    onNavigate(workspace);
    onClose();
  };
  return (
    <dialog
      ref={dialog}
      className="user-guide"
      aria-labelledby="user-guide-title"
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="user-guide-content">
        <header>
          <div>
            <BookOpen size={20} />
            <h2 id="user-guide-title">Using Rocket Workbench</h2>
          </div>
          <button aria-label="Close user guide" onClick={onClose}>
            <X size={20} />
          </button>
        </header>
        <p className="guide-intro">
          Start with the Example rocket to learn the controls. Its motor and
          materials are synthetic tutorial data. Replace them with verified data
          before using results for your rocket.
        </p>
        <section>
          <h3>1. Import and check your rocket</h3>
          <p>
            Choose <strong>Import → OpenRocket .ork</strong>. Select a
            <strong> Flight configuration</strong> in the left sidebar and read
            the import warnings. Drag in the viewport to orbit, scroll to zoom,
            and click a component to inspect it. Use <strong>Fit model</strong>
            if the geometry is off screen. The nose-to-tail axis is +X.
          </p>
          <p>
            In <strong>Design → Flight setup</strong>, import a measured
            <strong> .eng or .rse motor curve</strong> and assign it to the
            configuration. Motor names in an OpenRocket file do not supply a
            thrust curve. Check motor placement, ignition timing, chute size,
            drag coefficient, and single or dual deployment, then apply the
            configuration. Confirm recovery settings when the import could not
            establish them.
          </p>
          <button className="secondary" onClick={() => go("design")}>
            Open Design
          </button>
        </section>
        <section>
          <h3>2. Replace one part with CAD</h3>
          <p>
            Select the OpenRocket component, open <strong>Geometry</strong>, and
            import STEP/STP or STL. STEP supplies its own units; select the
            correct <strong>Mesh file units</strong> before importing STL.
            Choose the asset, enter translation, rotation and uniform scale,
            then click <strong>Attach &amp; use detailed geometry</strong>.
            Translation is relative to that component’s axial position; keep the
            CAD origin and orientation in mind.
          </p>
          <p>
            Turn on <strong>Original geometry</strong> to compare alignment.
            Later edits need <strong>Apply alignment / mode</strong>. Attachment
            replaces the selected component; it does not delete neighboring
            components. Imported assets and actual material geometry remain
            available for mass, viewing and FEA.
          </p>
          <p>
            In <strong>Component</strong>, check the selected material, optional
            mass override and local CG override. Existing OpenRocket overrides
            can still take precedence after attachment; clear or update them to
            match your intended mass model. A CAD assembly is assigned one
            component material. Solid FEA uses actual material volume and
            density, so inspect any mismatch with the flight mass model.
          </p>
          <p>
            CFD solves only air connected to the exterior. Sealed cavities and
            enclosed internal parts add no wetted pressure faces. Open bores and
            leaks can admit real exterior flow; cap them in CAD only if the
            physical rocket is sealed. Grid resolution can merge small gaps or
            miss thin fins. The default fast aerodynamic model retains the
            OpenRocket reference shape. To change fast drag, CP and flight using
            detailed CAD, import a validated geometry-specific aerodynamic polar
            CSV or assess the geometry with experimental CFD.
          </p>
        </section>
        <section>
          <h3>3. Run fast aerodynamics and a complete flight</h3>
          <p>
            Open <strong>Aerodynamics</strong>, enter speed or an optional Mach
            override, altitude, wind and incidence, then run the analysis. Clear
            Mach to use airspeed. Inspect CG, CP, stability, drag breakdown and
            the visible model warnings.
          </p>
          <p>
            Open <strong>Flight</strong>, check rail length, launch angles and
            wind, then click <strong>Simulate full flight</strong>. Watch
            progress and ETA; cancellation is available. After completion, play,
            pause or scrub the timeline and select events such as rail exit, max
            Q and apogee. <strong>Follow</strong> tracks actual position;
            <strong> Overview</strong> fits the trajectory with an enlarged
            model;
            <strong> Inspect</strong> shows local geometry. Rocket attitude is
            illustrative because flight uses a point-mass model. Flight stress
            colors show beam/fin estimates, not a changing FEA solution.
          </p>
          <div className="guide-actions">
            <button className="secondary" onClick={() => go("aero")}>
              Open Aerodynamics
            </button>
            <button className="secondary" onClick={() => go("flight")}>
              Open Flight
            </button>
          </div>
        </section>
        <section>
          <h3>4. Use CFD and FEA with declared limits</h3>
          <p>
            In <strong>CFD</strong>, choose grid resolution, cell budget, step
            and time limits, then solve. Pressure and velocity overlays come
            from the numerical solution. Check the stop reason and all
            convergence residuals. Increase grid resolution and
            <strong> Farfield padding</strong> separately to assess mesh and
            domain-size sensitivity. Padding is a multiple of each axis’s
            geometry extent; larger domains may require a larger cell budget.
            This experimental inviscid solver excludes skin friction, boundary
            layers and physical turbulence; a converged run alone is not
            validated aerodynamic accuracy.
          </p>
          <p>
            In <strong>Structures</strong>, select the component, material, mesh
            size, support and applied loads. Fin radial root supports apply to
            original procedural fins. An unjustified clamp can produce
            misleading stresses. Use uniform pressure, end traction, body
            acceleration, or a converged, geometry-matched CFD pressure field.
            Only exterior CFD faces receive transferred pressure; missing
            coverage is reported. Review equilibrium, mesh convergence and
            material assumptions. Deformation scale changes display only. Linear
            isotropic solid FEA excludes composite layups, contact, buckling and
            recovery shock.
          </p>
          <div className="guide-actions">
            <button className="secondary" onClick={() => go("cfd")}>
              Open CFD
            </button>
            <button className="secondary" onClick={() => go("structure")}>
              Open Structures
            </button>
          </div>
        </section>
        <section>
          <h3>5. Compare, save and export</h3>
          <p>
            Use <strong>Studies</strong> for parameter or wind sweeps, seeded
            Monte Carlo samples and original/current geometry comparisons.
            Inspect each solver’s fidelity and warnings before comparing values.
            Switch between metric and US customary units in the top bar;
            calculations and portable data remain in SI units.
          </p>
          <p>
            <strong>Save project</strong> creates a portable JSON file
            containing components, CAD mesh assets, materials, motors and
            analysis settings. Open it through{" "}
            <strong>Import → Saved project .json</strong>. Settings also save
            locally, but a named project file is your backup. Numerical result
            fields are session data: download solution JSON, CSV and HTML
            reports for your records. <strong>Run input project</strong>
            exports the exact project and setup used by that result. Rerun after
            changing geometry, materials, configurations or conditions.
          </p>
          <button className="secondary" onClick={() => go("studies")}>
            Open Studies
          </button>
        </section>
        <p className="guide-footer">
          Numerical CUDA requires a supported NVIDIA GPU and installed driver.
          The reported solver backend tells you whether a job used CPU or GPU.
          The 3D viewport uses graphics hardware independently.
        </p>
      </div>
    </dialog>
  );
}
