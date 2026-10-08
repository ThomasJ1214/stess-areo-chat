import type { Workspace } from "./types";

export type TourId = "app" | Workspace;
export interface TutorialStep {
  title: string;
  instruction: string;
  check: string;
  workspace: Workspace;
  note?: string;
}
export interface TutorialTour {
  id: TourId;
  title: string;
  description: string;
  steps: TutorialStep[];
}

const designSteps: TutorialStep[] = [
  {
    title: "Start with the rocket you want to test",
    instruction:
      "Choose Import → OpenRocket .ork for your design, or use the Example rocket to learn. Select a Flight configuration in the project panel. Click a component in the tree or the 3D view to inspect it.",
    check:
      "The selected configuration and highlighted component match the rocket you intend to test. Read the import warnings before continuing.",
    workspace: "design",
    note: "The Example rocket uses synthetic motor and material data. It teaches the controls; it is not a measured flight benchmark.",
  },
  {
    title: "Learn the view controls",
    instruction:
      "Drag in the 3D view to orbit, scroll to zoom, and use Fit model if it goes off screen. Drag the panel dividers to make room; Assembly and Inspector / Setup show or hide side panels. Focus view enlarges 3D, and Reset layout restores the default windows.",
    check:
      "You can see the entire rocket and identify the nose, body, fins, and selected component. The design axis goes from nose to tail along +X.",
    workspace: "design",
  },
  {
    title: "Supply a real motor curve",
    instruction:
      "Open Flight setup. Import a measured .eng or .rse file, or click Find motor online: enter Motor designation, optionally Manufacturer, then Search catalog → Review curves → Preview curve → Import reviewed motor. Select the imported Motor curve and apply the configuration.",
    check:
      "The configuration shows the intended motor, mount, placement, and ignition delay. A motor name in an .ork file alone is not a thrust curve.",
    workspace: "design",
    note: "Online search uses ThrustCurve.org records. Check the curve's source, motor designation, hardware size, masses, and total impulse; a search match is not verification.",
  },
  {
    title: "Set up recovery",
    instruction:
      "In Flight setup, choose Single or Dual deployment. Enter the main canopy Cd × area. For dual deployment, also enter drogue Cd × area and main deployment altitude. Choose the primary deployment trigger and delay, then apply the configuration.",
    check:
      "Recovery matches your hardware. If recovery was missing from the import, explicitly confirm the entered setup. Main deployment altitude is above launch level (AGL).",
    workspace: "design",
    note: "The flight model uses fully deployed, constant canopy drag. It does not resolve inflation, opening shock, separated parts, or cord loads.",
  },
  {
    title: "Replace just the selected component with CAD",
    instruction:
      "Select the OpenRocket part, open Geometry, and import STEP/STP or STL with the correct Mesh file units. Leave Automatic alignment on and click Preview automatic alignment. Check Source axis, Reverse direction and Placement anchor, then click Attach & use detailed geometry. Leave Fit selected length off to preserve actual hardware dimensions.",
    check:
      "Only the selected component changes. Enable Original geometry and inspect nose/tail, shoulders, roll and neighboring gaps. Turn Automatic alignment off for manual adjustments, then Apply alignment / mode. Automatic placement is a starting guess, not a confirmed joint.",
    workspace: "design",
    note: "Fit selected length uniformly changes every dimension and computed volume/mass. Placement creates no material union or structural bond. CFD uses a separate exterior-connected flow grid without editing CAD or neighbors; resolved open passages remain open.",
  },
  {
    title: "Check material and mass assumptions",
    instruction:
      "Open Component and check Material, External surface, and any mass or local CG override. Mark enclosed electronics and ballast as internal. Apply component changes. Use Materials to enter properties for your actual material.",
    check:
      "Exposed parts are external, internal hardware is not, and the displayed mass and CG agree with your intended model. Remove obsolete mass overrides if CAD should determine the mass.",
    workspace: "design",
    note: "An imported CAD assembly has one selected component material. Ambiguous or unclosed meshes cannot supply trustworthy solid mass or volume-based FEA.",
  },
  {
    title: "Keep a portable backup",
    instruction:
      "Click Save project. Store the downloaded JSON with a clear rocket and configuration name. To reopen it, choose Import → Saved project .json.",
    check:
      "The saved file contains components, CAD assets, materials, motors, and analysis settings. Numerical solution fields need separate result exports.",
    workspace: "design",
  },
];

const aeroSteps: TutorialStep[] = [
  {
    title: "Choose the air conditions",
    instruction:
      "Enter airspeed and altitude in the setup panel. Leave the optional Mach field empty to use airspeed, or set Mach to calculate speed from local sound speed. Choose small Angle of attack and Sideslip values.",
    check:
      "Units match the top-bar unit system. Review the actual resultant speed and incidence after solving, especially with wind.",
    workspace: "aero",
    note: "The fast stability model is a small-angle estimate. Large incidence, transonic corrections, and arbitrary CAD drag need more evidence than this model supplies.",
  },
  {
    title: "Add wind deliberately",
    instruction:
      "Enter lateral wind speed and Wind direction. Click the question mark beside unfamiliar terms. Click Run aerodynamic analysis in the setup panel.",
    check:
      "Read CG, CP, Static margin, Dynamic pressure, and the drag/load breakdown. A positive static margin places CP aft of CG in the model's nose-to-tail convention.",
    workspace: "aero",
    note: "Static wind direction is measured in the rocket's YZ plane: 0° toward +Y and 90° toward +Z. Flight uses north/east bearings instead.",
  },
  {
    title: "Read the result in 3D",
    instruction:
      "Enable CG / CP markers and Forces in the view controls. Select components and compare their reported loads. Orbit the rocket to understand the directions of the force vectors.",
    check:
      "Read the fidelity label and warnings. CAD replacement does not silently turn original-reference CP and drag estimates into geometry-resolved results.",
    workspace: "aero",
  },
  {
    title: "Use measured coefficients only with matching geometry",
    instruction:
      "If you have verified geometry-specific coefficients, import the aerodynamic polar CSV for the current configuration. Otherwise keep the fast result as an estimate and assess detailed exterior geometry in CFD. Export a report and Run input project to record this setup.",
    check:
      "The result identifies whether the supplied polar was used and whether its Mach coverage and geometry signature match. Rerun after geometry or condition changes.",
    workspace: "aero",
    note: "A geometry signature associates coefficients with a shape; it does not validate the coefficient source. Experimental pressure-only CFD is not automatically a complete viscous drag polar.",
  },
];

const flightSteps: TutorialStep[] = [
  {
    title: "Prepare the rocket on its launch rail",
    instruction:
      "Check the selected configuration's motor and recovery setup. Enter Launch rail length, Angle from vertical, and Launch azimuth. The Flight view places the rocket on a rail above an open flat launch plane.",
    check:
      "Rail angle and orientation match your intended launch. 0° launch angle is vertical; azimuth 0° is north and 90° is east.",
    workspace: "flight",
    note: "The flat plane is a launch-relative reference surface. This model does not import terrain or determine obstacle clearance.",
  },
  {
    title: "Set wind and simulation duration",
    instruction:
      "Enter wind speed, direction, and gust intensity. Flight wind direction is the bearing the air moves toward. Set Duration limit long enough for recovery; Time step is the integration step ceiling. Keep a fixed Random seed for repeatable comparisons.",
    check:
      "Wind, launch conditions, motor, and deployment settings are plausible. A 90° wind blows toward east; 270° blows toward west.",
    workspace: "flight",
    note: "Gusts are a deterministic sensitivity model, not a measured atmospheric turbulence spectrum. Flight integrates position and velocity, not full vehicle attitude or weathercocking.",
  },
  {
    title: "Launch and watch progress",
    instruction:
      "Click the large red Launch button. Watch the percentage and ETA while the full trajectory is calculated. When it is ready, playback shows the rocket leaving the rail and the camera follows the flight.",
    check:
      "A real computed trajectory appears. If the solver reports an unsupported configuration, missing motor, or incomplete recovery, correct the setup rather than treating the preview as a valid launch.",
    workspace: "flight",
  },
  {
    title: "Control the camera and map",
    instruction:
      "During playback, orbit, pan, or zoom to adjust the camera. In Follow mode, tracking resumes after 5 seconds with no camera input; Resume follow returns immediately. Overview fits the trajectory, Inspect shows local geometry, and Flight map shows launch, events, and landing.",
    check:
      "The map and camera use the same recorded trajectory. Landing is shown only when the computed flight reaches ground; an unfinished run must not invent a landing point.",
    workspace: "flight",
    note: "The map is a local east/north distance plot, not a satellite map or live GPS tracking. Rocket attitude and enlarged rendering are illustrative aids for this point-mass trajectory.",
  },
  {
    title: "Inspect the important moments",
    instruction:
      "Pause or scrub the timeline. Click events such as Rail exit, Max Q, Burnout, Apogee, and Recovery to inspect the corresponding time. Enable Forces, wind, or stress overlays and compare them with the flight graphs.",
    check:
      "Read altitude, air-relative speed, Mach, dynamic pressure, and deployment state at that moment. Flight stress colors are quasi-static beam/fin estimates, not transient FEA.",
    workspace: "flight",
    note: "Max acceleration can include the idealized instant canopy force change; it is not a resolved recovery opening-shock prediction. Recovery marks ground contact, not a claim of a safe landing.",
  },
  {
    title: "Record and compare the flight",
    instruction:
      "Read landing speed and whether the summary says the flight is complete. Export flight data, an HTML report, and Run input project. Use Studies to compare launch angles, wind speeds, motors/configurations, or seeded uncertainty samples.",
    check:
      "You have both the results and the exact inputs. If Duration limit ended first, increase it and rerun before comparing landing distance.",
    workspace: "flight",
  },
];

const cfdSteps: TutorialStep[] = [
  {
    title: "Check the actual exterior geometry",
    instruction:
      "Confirm the selected configuration and CAD alignment in Design. Mark exposed components External surface; enclosed internal hardware should be internal. Return to CFD and set freestream speed or Mach, altitude, and incidence.",
    check:
      "The rendered exterior is the shape you want to solve. Sealed interior cavities add no pressure faces; resolved open bores can admit airflow.",
    workspace: "cfd",
    note: "The solver builds a separate aerodynamic flow mask. It does not cap, fill, or overwrite the stored CAD/material mesh.",
  },
  {
    title: "Begin with a manageable grid",
    instruction:
      "Set Lengthwise grid cells, Transverse grid cells, Cell budget, and Farfield padding. Start with a modest grid and choose CPU, automatic or GPU. If GPU is unavailable, open GPU diagnostics for the failed check; a working 3D view does not establish NVIDIA CUDA numerical support.",
    check:
      "The cell budget covers the proposed domain. Thin fins and small openings need enough cells to remain visible to the solver.",
    workspace: "cfd",
    note: "Farfield padding is a multiple of each axis's geometry extent. A larger domain at the same cell resolution increases memory and work; neither a large budget nor GPU use proves accuracy.",
  },
  {
    title: "Allow the solution time to settle",
    instruction:
      "For a bounded check, set Maximum steps, Flow-through times, Wall time limit, CFL number and Convergence tolerance. For longer settling, enable Run until converged. A Wall time limit of 0 removes the elapsed-computation deadline. Click Solve flow field; cancel when needed.",
    check:
      "Read Stop reason and Convergence before using pressures. Budget-limited fields and forces are partial. Without a time limit, convergence completion percent and ETA are unknown; inspect elapsed time, steps and residuals instead.",
    workspace: "cfd",
    note: "Removing limits does not guarantee convergence or accuracy. Below Mach 0.3 this scheme's pressure drag is especially unreliable even after numerical convergence.",
  },
  {
    title: "Inspect solved flow and pressure",
    instruction:
      "Enable Flow and Pressure in the 3D controls. Read pressure drag and the conservation, wall-pressure, force, and moment residual histories. These overlays come from the numerical solution.",
    check:
      "All convergence measures settle and the pressure/force values are finite. Review the result warnings, actual backend, and exterior-flow diagnostics.",
    workspace: "cfd",
    note: "This experimental compressible Euler solver is inviscid. It excludes skin friction, boundary layers, and physical turbulence; a converged solution alone is not validated drag accuracy.",
  },
  {
    title: "Test grid and domain sensitivity",
    instruction:
      "Save the current result. Increase grid resolution and rerun, then separately increase Farfield padding. Compare integrated forces, pressure patterns, and convergence rather than only the number of cells.",
    check:
      "You know how much the quantities you care about change with mesh and domain size. Keep unresolved features and transonic limitations in the report.",
    workspace: "cfd",
  },
  {
    title: "Transfer pressure only to matching structures",
    instruction:
      "For a completed, converged CFD result, open Structures, select the same component and choose Converged CFD surface pressure. Keep the geometry unchanged. Export the CFD solution, report, and Run input project first.",
    check:
      "FEA reports mapped pressure coverage and distances. A saved project does not include the numerical pressure field; rerun CFD after reopening the app to transfer it.",
    workspace: "cfd",
    note: "Pressure transfer is one-way and quasi-static. It does not make this a coupled aeroelastic simulation or add the missing viscous loads.",
  },
];

const structureSteps: TutorialStep[] = [
  {
    title: "Choose the part and its material",
    instruction:
      "Select a component in the tree or 3D view. Check its material density, Young's modulus, Poisson's ratio, and yield strength in Design. Use beam/fin estimates for quick screening, or configure finite element analysis for a closed solid part.",
    check:
      "The component and material match the hardware. The solid volume is unambiguous, and the selected density agrees with the structural mass model.",
    workspace: "structure",
    note: "Linear isotropic FEA cannot represent a composite layup simply by entering one modulus. Contact, buckling, yielding, and transient shock are outside this solver.",
  },
  {
    title: "Choose a physically meaningful support",
    instruction:
      "Set Clamp type, axis, and side to represent where the part is attached. For original procedural fins, use Fin radial root. A Coordinate plane clamp fixes nodes at the selected coordinate extreme.",
    check:
      "The fixed region is the real load path. A convenient but unrealistic clamp can substantially change peak stress and deformation.",
    workspace: "structure",
  },
  {
    title: "Enter the actual load case",
    instruction:
      "Choose estimated aerodynamic pressure, uniform pressure, prescribed end traction, or a converged geometry-matched CFD pressure field. Enter prescribed body acceleration when appropriate; its X/Y/Z components use the model coordinates.",
    check:
      "Load units and directions are correct. Uniform pressure acts normally; traction is force per area with an explicit vector. CFD transfer requires a valid source result in this session.",
    workspace: "structure",
  },
  {
    title: "Mesh and solve",
    instruction:
      "Leave Automatic mesh sizing on and inspect Mesh readiness. The recommendation applies automatically only if it fits the current element budget. Use recommended mesh may raise that budget within 300,000 elements. For manual refinement, turn automatic sizing off and set Target mesh size. Choose Run finite element analysis when ready.",
    check:
      "Keep original-part mesh size at or below thickness/2. If the whole thin part exceeds the permitted budget, choose Use beam/fin estimates where supported or import a smaller physical CAD part with justified local supports/loads. Repair ambiguous/open solids before solving.",
    workspace: "structure",
    note: "Shell FEA and region cutting are not included. CAD thickness is unknown; the scale-based suggestion is a starting mesh and does not prove bending resolution. A passing readiness check does not validate supports, loads or convergence.",
  },
  {
    title: "Read the stress field carefully",
    instruction:
      "Enable Stress and Deformation. Adjust Deformation display scale to make motion visible; this changes the display only. Inspect peak stress, maximum displacement, strain energy, and equilibrium residual.",
    check:
      "Forces balance, the motion makes sense, and the safety factor is interpreted against the entered material strength. Large displacement may violate the small-deformation model.",
    workspace: "structure",
    note: "Peak stress at a sharp corner or fully clamped edge can be a mesh-dependent singularity. Compare regions away from the support and refine the mesh before treating a peak as a failure prediction.",
  },
  {
    title: "Refine and save the evidence",
    instruction:
      "Repeat the same load case with a finer mesh and compare displacement, reactions, and stresses. Export Full solver data, FEA report, and Run input project. Record the chosen support and load assumptions.",
    check:
      "Your conclusion includes mesh sensitivity, load coverage, equilibrium, and material limits. A stress heatmap alone is not a structural qualification.",
    workspace: "structure",
  },
];

const studySteps: TutorialStep[] = [
  {
    title: "Choose the question to compare",
    instruction:
      "Select Parameter sweep, Monte Carlo, or Compare. Choose the solver and a parameter that actually affects it. Flight speed and Mach are computed outputs; use launch or wind parameters for flight studies.",
    check:
      "Each study has one clear question, such as how wind changes landing drift or how rail length changes rail-exit speed.",
    workspace: "studies",
  },
  {
    title: "Run a parameter or wind sweep",
    instruction:
      "For Parameter sweep, choose the parameter, minimum, maximum, and sample count. Read the range units carefully: study ranges are stored in SI values, metres, m/s, and degrees. Run the study.",
    check:
      "The graph and rows cover the requested range. Review each row's solver validity and warnings before interpreting a trend.",
    workspace: "studies",
  },
  {
    title: "Explore uncertainty with Monte Carlo",
    instruction:
      "For Monte Carlo, enter the parameter's mean, standard deviation, sample count, and Random seed. Start with a small sample count; larger ensembles can be expensive. Use physically plausible uncertainty values.",
    check:
      "Record the actual seed and sample count. Repeating the same seed reproduces the sampled conditions; one random ensemble does not establish a probability of safe flight.",
    workspace: "studies",
    note: "The app varies the selected inputs and uses independent seeded gust realizations. It does not know the real-world uncertainty distribution of your hardware or weather.",
  },
  {
    title: "Compare original and detailed geometry",
    instruction:
      "For Compare, check the current CAD attachment and configuration, then choose Fast engineering, Compare flight performance, or Compare with Euler CFD. Read the original and current result labels side by side.",
    check:
      "Differences come from the chosen method. CAD can change mass and resolved CFD/FEA geometry; the default fast drag/CP model still uses the OpenRocket reference exterior unless a matching polar is supplied.",
    workspace: "studies",
    note: "Euler CFD comparison runs two numerical solutions. They must each converge and pass sensitivity checks before their difference is useful evidence.",
  },
  {
    title: "Save the comparison and inputs",
    instruction:
      "Export CSV or HTML results and Run input project. Note the configuration, geometry, units, solver fidelity, warnings, and random seed. Save the portable project separately for later work.",
    check:
      "Another person can identify the assumptions and reproduce the setup from your files. Do not mix stale results with newly edited geometry or conditions.",
    workspace: "studies",
  },
];

export const tutorialTours: TutorialTour[] = [
  {
    id: "app",
    title: "Start to finish",
    description:
      "Learn a complete rocket project, from import to launch and reports.",
    steps: [
      designSteps[0],
      designSteps[1],
      designSteps[2],
      designSteps[3],
      designSteps[4],
      designSteps[5],
      aeroSteps[0],
      aeroSteps[1],
      flightSteps[0],
      flightSteps[1],
      flightSteps[2],
      flightSteps[3],
      flightSteps[4],
      cfdSteps[0],
      cfdSteps[1],
      cfdSteps[2],
      cfdSteps[3],
      structureSteps[0],
      structureSteps[1],
      structureSteps[2],
      structureSteps[3],
      structureSteps[4],
      studySteps[0],
      studySteps[1],
      designSteps[6],
    ],
  },
  {
    id: "design",
    title: "Design & CAD",
    description:
      "Import, configure, align detailed CAD, and save your project.",
    steps: designSteps,
  },
  {
    id: "aero",
    title: "Aerodynamics",
    description: "Set air conditions and interpret stability, drag, and loads.",
    steps: aeroSteps,
  },
  {
    id: "flight",
    title: "Launch & playback",
    description:
      "Set up the rail, launch, use the camera and map, and inspect events.",
    steps: flightSteps,
  },
  {
    id: "structure",
    title: "Structures",
    description:
      "Choose material, supports, loads, and check a solid FEA result.",
    steps: structureSteps,
  },
  {
    id: "cfd",
    title: "CFD",
    description:
      "Solve exterior flow and assess convergence and grid sensitivity.",
    steps: cfdSteps,
  },
  {
    id: "studies",
    title: "Studies & comparisons",
    description:
      "Run parameter sweeps, uncertainty samples, and geometry comparisons.",
    steps: studySteps,
  },
];

export const workspaceTitles: Record<Workspace, string> = {
  design: "Design",
  aero: "Aerodynamics",
  flight: "Flight",
  structure: "Structures",
  cfd: "CFD",
  studies: "Studies",
};

export interface TutorialProgress {
  step: number;
  completed: boolean;
}
export const tutorialStorageKey = "rocket-workbench-tutorials-v1";

/** Invalid/local-storage data must not prevent the bundled help from opening. */
export function parseTutorialProgress(
  raw: string | null,
): Partial<Record<TourId, TutorialProgress>> {
  if (!raw) return {};
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null || Array.isArray(value))
      return {};
    const result: Partial<Record<TourId, TutorialProgress>> = {};
    for (const tour of tutorialTours) {
      const item = (value as Record<string, unknown>)[tour.id];
      if (typeof item !== "object" || item === null || Array.isArray(item))
        continue;
      const { step, completed } = item as Record<string, unknown>;
      if (
        typeof step === "number" &&
        Number.isInteger(step) &&
        step >= 0 &&
        step < tour.steps.length &&
        typeof completed === "boolean"
      ) {
        result[tour.id] = { step, completed };
      }
    }
    return result;
  } catch {
    return {};
  }
}
