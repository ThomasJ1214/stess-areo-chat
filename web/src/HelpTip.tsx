import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CircleHelp } from "lucide-react";

export interface GlossaryEntry {
  term: string;
  definition: string;
  aliases?: string[];
}

export const engineeringGlossary: GlossaryEntry[] = [
  {
    term: "Streamlines",
    aliases: ["Streamline density", "Streamline length", "Streamline color"],
    definition: "Continuous lines tangent to the computed velocity in a CFD snapshot. They use the actual exported field and stop at walls or its boundary. Density, length and color change only the display. They are not unsteady particle trajectories, and smoother lines do not improve the solver's accuracy.",
  },
  {
    term: "Direction tracers",
    definition: "Moving markers showing direction along the computed snapshot streamlines. Their timing is slowed for viewing. They are not time-accurate CFD particles or a reconstruction of unsteady flow.",
  },
  {
    term: "Automatic alignment",
    aliases: ["Source axis", "Placement anchor", "Reverse direction"],
    definition:
      "Proposes a rigid CAD placement on the selected OpenRocket part. The source longitudinal axis maps to rocket +X, the radial center maps to the part axis, and the front or center is anchored. Axis direction and roll are guesses; inspect the amber preview. Other components and source vertices are preserved.",
  },
  {
    term: "Fit selected length",
    definition:
      "Uniformly scales the attached CAD to the reference part length. This changes every physical dimension and scales material volume and mass by the cube of the scale factor. Leave off to preserve the imported CAD's real size.",
  },
  {
    term: "Automatic mesh sizing",
    definition:
      "Uses actual selected-part dimensions and known original wall thickness to suggest a solid mesh. It applies automatically only when the current element budget can accommodate the recommendation. Imported CAD thickness must still be measured, and convergence must be checked.",
  },
  {
    term: "Run until converged",
    definition:
      "Ignores CFD step and simulated-flow-time ceilings and waits for the configured numerical residual criteria. A nonzero wall time limit still applies. With wall time 0, it runs until convergence or cancellation; completion percentage and ETA are unknown. Convergence alone does not validate physical accuracy.",
  },
  {
    term: "Partial pressure force",
    aliases: ["Inviscid pressure drag"],
    definition:
      "The current axial force from computed exterior surface pressures. A partial solution is not a steady-flow prediction. This inviscid solver omits skin friction, boundary layers, viscous separation, and turbulence; its result is not total aerodynamic drag. Low-Mach pressure forces are particularly unreliable.",
  },
  {
    term: "Mach",
    aliases: ["Mach override", "Peak Mach", "Maximum Mach"],
    definition:
      "Air-relative speed divided by the local speed of sound. Mach 1 is sonic. Temperature and altitude change the sound speed, so a given Mach is not one fixed airspeed. A static Mach override sets primary freestream speed; added wind can change the resultant Mach.",
  },
  {
    term: "CG",
    aliases: [
      "Center of gravity",
      "Centre of gravity",
      "Local CG override",
      "Local CG override (optional)",
      "CG override",
    ],
    definition:
      "Center of gravity: the mass-weighted balance point of the rocket. The axial coordinate is measured from the model origin toward the tail along +X. Motors, propellant burn, CAD, and mass overrides can move CG.",
  },
  {
    term: "CP",
    aliases: ["Center of pressure", "Centre of pressure", "cp_m"],
    definition:
      "Center of pressure: the axial point where the model's resultant small-angle aerodynamic normal force acts. It depends on shape and flow conditions. CP is unavailable when the lift slope is not positive; detailed CAD alone does not update the fast reference-geometry CP estimate.",
  },
  {
    term: "Static margin",
    aliases: ["Stability", "Stability margin"],
    definition:
      "The axial distance from CG to CP divided by the reference body diameter, often called calibers. Positive margin places CP aft of CG in the nose-to-tail convention. This is a small-angle static indicator, not proof of dynamic flight stability or immunity to tumbling.",
  },
  {
    term: "Cd",
    aliases: ["CD", "Drag coefficient", "Total Cd"],
    definition:
      "Dimensionless drag coefficient: drag divided by dynamic pressure times reference area. The reference area and coefficient source must match. The fast model estimates drag; experimental inviscid CFD supplies pressure drag and omits skin friction.",
  },
  {
    term: "CNa",
    aliases: ["Normal force slope", "Lift slope", "cna"],
    definition:
      "Small-angle normal-force coefficient slope per radian of incidence. Normal force is approximately dynamic pressure × reference area × CNa × angle in radians. It does not describe large-angle separated flow.",
  },
  {
    term: "Dynamic pressure",
    aliases: ["q", "Max Q", "Max dynamic pressure"],
    definition:
      "A flow loading scale, q = ½ × air density × air-relative speed squared, measured in pressure units. Max Q is the trajectory's highest dynamic pressure. It is not a uniform pressure applied everywhere on the rocket.",
  },
  {
    term: "Angle of attack",
    aliases: ["AoA", "AOA", "Incidence"],
    definition:
      "Angle between the rocket reference axis and incoming relative airflow. Static angle of attack acts in the model XY plane; sideslip acts in XZ. Flight does not integrate attitude: the entered angle is a fixed reference for structural estimates, not the actual flight attitude.",
  },
  {
    term: "Sideslip",
    definition:
      "The second incidence angle, perpendicular to static angle of attack, acting in the rocket's XZ plane. Wind can add to effective incidence. The fast aerodynamic model is intended for small combined incidence.",
  },
  {
    term: "AGL",
    aliases: [
      "Altitude AGL",
      "Main deployment altitude",
      "Main deploy altitude",
      "Main deployment altitude AGL",
    ],
    definition:
      "Above ground level: in this app, height above the flat launch-level plane. Main deployment altitude uses AGL. It does not account for rising terrain away from the launch site.",
  },
  {
    term: "MSL",
    aliases: ["Altitude MSL", "Launch altitude", "Ambient altitude"],
    definition:
      "Mean sea level altitude sets the atmospheric conditions at the launch site or static test. Flight height above launch level is AGL; flight altitude MSL adds the entered launch altitude to that height.",
  },
  {
    term: "Altitude",
    definition:
      "Height relative to the stated reference. In setup, Altitude sets sea-level-referenced atmospheric/launch conditions. The Flight playback Altitude is height above the flat launch-level plane (AGL). Flight MSL altitude adds launch altitude to that height.",
  },
  {
    term: "Launch azimuth",
    aliases: ["Azimuth"],
    definition:
      "Compass bearing of the rail's horizontal direction: 0° north, 90° east, 180° south, 270° west. Angle from vertical sets rail tilt separately. Flight coordinates are east, north, and up.",
  },
  {
    term: "Wind direction",
    definition:
      "Direction the air moves toward, not the weather-report direction it comes from. Flight: 0° north, 90° east. Static aerodynamic tests: 0° toward model +Y, 90° toward +Z. A meteorological 'west wind' therefore has flight toward-bearing 90°.",
  },
  {
    term: "Turbulence",
    aliases: ["Gust intensity", "Turbulence intensity"],
    definition:
      "Here this sets repeatable smooth gust perturbations scaled by wind speed. It is a sensitivity input, not a measured turbulence spectrum. The Euler CFD solver does not solve physical turbulent eddies or use a turbulence model.",
  },
  {
    term: "Rail exit",
    definition:
      "The instant the modeled rocket travels the full entered rail length and is no longer constrained to the rail. Rail-exit speed is useful for comparison, but this point-mass model cannot evaluate full attitude stability after release.",
  },
  {
    term: "Burnout",
    definition:
      "The end of the assigned motor thrust curve, after ignition delay. No thrust is supplied after burnout. It is separate from a later motor ejection or recovery deployment event.",
  },
  {
    term: "Apogee",
    aliases: ["Peak altitude", "Maximum altitude"],
    definition:
      "Highest point of the computed flight, where upward velocity changes to downward. An apogee-triggered recovery event can have an additional delay, so canopy deployment is not necessarily at the exact apex.",
  },
  {
    term: "Recovery",
    aliases: ["Landing"],
    definition:
      "In the flight event list, Recovery marks contact with the launch-level ground plane. It does not claim that the parachute deployed or that landing was safe. Check recovery-deployed status, landing speed, and whether the full trajectory completed.",
  },
  {
    term: "Cd × area",
    aliases: [
      "CdArea",
      "Cd area",
      "Drogue Cd × area",
      "Main Cd × area",
      "Drogue Cd area",
      "Main Cd area",
      "drogue_cd_area",
      "main_cd_area",
      "Main chute effective Cd × area",
      "Drogue effective Cd × area",
    ],
    definition:
      "Canopy drag coefficient multiplied by effective canopy area, with area units. Recovery drag magnitude is approximately dynamic pressure × Cd × area. Use the appropriate measured coefficient and area convention for your canopy; the solver assumes instant full deployment.",
  },
  {
    term: "Total impulse",
    aliases: ["Impulse"],
    definition:
      "Integral of motor thrust over time, in newton-seconds (N·s). It measures total delivered momentum per unit mass in an ideal fixed-mass interpretation; it is not burn time, peak thrust, or a guarantee of altitude.",
  },
  {
    term: "Ignition delay",
    definition:
      "Time between the modeled start and motor ignition. The motor's thrust history begins after this delay. The app supports passive single-stage, single-motor flight, not arbitrary staging or clustered ignition sequences.",
  },
  {
    term: "Motor ejection delay",
    aliases: ["Ejection delay", "Motor ejection delay after burnout"],
    definition:
      "Delay from actual motor burnout to its ejection charge event. It must be known for motor-ejection-triggered recovery. A plugged or unknown delay cannot be replaced by an invented value.",
  },
  {
    term: "Motor overhang",
    aliases: ["Overhang"],
    definition:
      "Distance the motor extends beyond the mount's aft end. Motor placement affects mass and CG. Check imported mount position, motor dimensions, and overhang against the actual assembly.",
  },
  {
    term: "Mass override",
    aliases: ["Mass override (optional)"],
    definition:
      "An explicit mass that takes precedence over geometry-derived mass in the flight mass model. An imported OpenRocket override can remain active after CAD attachment. Clear or update it if you want the new CAD geometry to determine mass.",
  },
  {
    term: "Reference area",
    definition:
      "The area used to normalize aerodynamic coefficients, typically the original maximum body frontal area. A supplied Cd or CNa table must use the same reference area as this project; changing normalization changes coefficient values.",
  },
  {
    term: "Aerodynamic polar",
    aliases: ["Polar", "Polar CSV"],
    definition:
      "A table of aerodynamic coefficients versus Mach, such as Cd, CNa, and CP. This app binds it to the current configuration and geometry signature. Matching a signature records shape association; it does not verify the accuracy of the supplied data.",
  },
  {
    term: "CFD",
    definition:
      "Computational fluid dynamics: numerical solution of fluid-flow equations on a grid. This app's CFD is an experimental compressible inviscid Euler solver. Solved pressure and velocity are numerical fields, with explicit convergence and accuracy limits.",
  },
  {
    term: "Euler",
    aliases: [
      "Euler CFD",
      "Cartesian Euler solver",
      "Inviscid",
      "Inviscid flow",
    ],
    definition:
      "The compressible Euler equations conserve mass, momentum, and energy without viscosity. The solver can estimate pressure-driven loading, but omits skin friction, boundary layers, viscous separation, and physical turbulence. This term is different from Euler rotation angles.",
  },
  {
    term: "Mesh",
    aliases: ["Target mesh size", "Mesh size", "FEA mesh"],
    definition:
      "A subdivision used for numerical calculations. CFD uses grid cells; solid FEA uses tetrahedral elements and nodes. Refining it should be checked for changes in the quantities you care about. A finer mesh costs memory and time and does not remove an inappropriate physical model.",
  },
  {
    term: "Voxel",
    aliases: [
      "Voxel grid",
      "Grid cells",
      "Lengthwise grid cells",
      "Transverse grid cells",
    ],
    definition:
      "A small three-dimensional grid cell. The CFD flow mask approximates the exterior on a Cartesian voxel grid. Thin fins, tiny gaps, and curved boundaries may be missed or represented as stair steps at coarse resolution.",
  },
  {
    term: "Farfield padding",
    aliases: ["Farfield"],
    definition:
      "Extra CFD domain extent around the rocket, expressed as a multiple of each geometry-axis extent. Boundaries that are too close can affect the result. Increase padding separately from grid resolution to check domain sensitivity; a larger domain needs more cells.",
  },
  {
    term: "CFL",
    aliases: ["CFL number"],
    definition:
      "Courant–Friedrichs–Lewy number: a numerical time-step factor based on cell size and wave speeds. A smaller value usually advances more cautiously and requires more steps. It is a solver stability control, not a physical turbulence or accuracy coefficient.",
  },
  {
    term: "Convergence",
    aliases: ["Convergence tolerance", "Convergence residuals"],
    definition:
      "The solution has settled according to the solver's numerical criteria. CFD checks conservation-state, wall-pressure, force, and moment changes. Reaching a time or step limit is not convergence, and convergence is not proof of experimental accuracy.",
  },
  {
    term: "Residual",
    aliases: [
      "Equilibrium residual",
      "Relative equilibrium residual",
      "Conservation",
      "Wall pressure residual",
      "Force residual",
      "Moment residual",
    ],
    definition:
      "A numerical measure of imbalance or remaining change. CFD residuals track settling; FEA equilibrium residual checks solved force balance. Small residuals support numerical consistency but do not validate geometry, materials, or boundary conditions.",
  },
  {
    term: "Reynolds number",
    aliases: ["Reynolds", "Re"],
    definition:
      "Dimensionless ratio of inertial to viscous effects, based on density × airspeed × reference length divided by dynamic viscosity. It helps characterize real flow regimes. This app's inviscid CFD does not model Reynolds-dependent boundary layers.",
  },
  {
    term: "Pressure drag",
    definition:
      "Drag obtained by integrating normal pressure forces on the exterior. It excludes viscous wall shear and skin friction in this Euler CFD solver, so it is not total real-world aerodynamic drag.",
  },
  {
    term: "Pressure coefficient",
    aliases: ["Cp coefficient", "Pressure Cp"],
    definition:
      "Local pressure difference from freestream pressure divided by dynamic pressure: (p − p∞)/q. This pressure coefficient is different from the uppercase CP center-of-pressure marker. It becomes undefined when dynamic pressure is effectively zero.",
  },
  {
    term: "FEA",
    aliases: ["Finite element analysis", "Solid FEA", "Tetrahedral FEA"],
    definition:
      "Finite element analysis divides a solid into elements and solves displacement and stress under declared supports and loads. This app uses linear static isotropic elasticity; it excludes composite layups, contact, buckling, yielding, and transient recovery shock.",
  },
  {
    term: "von Mises",
    aliases: ["Peak von Mises", "von Mises stress", "Maximum von Mises"],
    definition:
      "A scalar equivalent stress calculated from the three-dimensional stress state, commonly compared with yield strength for ductile isotropic materials. It is not a composite failure criterion and does not detect buckling or brittle failure by itself.",
  },
  {
    term: "Young's modulus",
    aliases: ["Youngs modulus", "Elastic modulus", "Young’s modulus"],
    definition:
      "Material stiffness: the ratio of uniaxial stress to elastic strain, in pressure units. A larger modulus gives less elastic deformation for the same load and geometry. It is different from yield strength.",
  },
  {
    term: "Poisson's ratio",
    aliases: ["Poisson ratio", "Poisson’s ratio"],
    definition:
      "Dimensionless ratio of transverse contraction to axial extension in a uniaxial elastic test. It helps define the three-dimensional isotropic elastic response. Enter measured or published values for the actual material.",
  },
  {
    term: "Yield strength",
    definition:
      "Stress level at which a material begins significant permanent deformation, in pressure units. The linear FEA solver does not simulate plastic yielding; stress above this value flags that its elastic assumptions may be exceeded.",
  },
  {
    term: "Density",
    definition:
      "Mass per unit volume. It controls geometry-derived mass and structural body-acceleration loading. A CAD assembly treated as one material needs an appropriate mass model; hollow space is not solid material.",
  },
  {
    term: "Clamp",
    aliases: [
      "Clamp type",
      "Clamp axis",
      "Clamp side",
      "Fin radial root",
      "Support",
    ],
    definition:
      "A structural support that fixes displacement of selected nodes. Coordinate-plane clamps select a geometry extreme; original procedural fins can use the radial root. The support must represent the actual attachment, since an artificial clamp can change stresses greatly.",
  },
  {
    term: "Traction",
    aliases: [
      "X end traction",
      "Y end traction",
      "Z end traction",
      "Prescribed free-end traction",
    ],
    definition:
      "A force vector per unit surface area, measured in pressure units. Prescribed free-end traction applies the entered X/Y/Z vector to the selected free-end surface. Pressure instead acts along the surface normal.",
  },
  {
    term: "Body acceleration",
    aliases: [
      "X body acceleration",
      "Y body acceleration",
      "Z body acceleration",
      "Prescribed body acceleration",
    ],
    definition:
      "Entered acceleration components that create volume forces proportional to material density. Coordinates follow the model axes. Flight structural estimates use specific acceleration rather than treating gravity in freefall as an applied inertial stress.",
  },
  {
    term: "Strain energy",
    definition:
      "Elastic energy stored in a deformed solid, in joules. For a valid linear elastic solution it should be consistent with load work and be nonnegative. It is not absorbed failure energy or a toughness measurement.",
  },
  {
    term: "Safety factor",
    aliases: ["Factor of safety"],
    definition:
      "Here an elastic strength indicator, typically entered yield strength divided by peak von Mises stress. It depends on the load, support, material, and mesh. It does not cover buckling, fatigue, joints, composites, or missing load cases.",
  },
  {
    term: "Deformation display scale",
    aliases: ["Deformation", "Deformation scale"],
    definition:
      "Visual multiplier applied to computed displacement so small motion is visible. It changes the rendering only, not the solved displacement, stress, or physical geometry. Large plotted deformation may be exaggerated.",
  },
  {
    term: "Isotropic",
    definition:
      "Material properties are assumed the same in all directions. This can be useful for suitable metals or homogeneous materials. A fiber composite's directional stiffness and layup cannot generally be represented by a single isotropic material.",
  },
  {
    term: "Linear static",
    definition:
      "An equilibrium calculation using small-deformation linear elasticity, without time-dependent structural dynamics. It cannot predict vibration, canopy opening shock, plastic deformation, or large-motion contact.",
  },
  {
    term: "Tetrahedra",
    aliases: ["Elements", "Element limit"],
    definition:
      "Four-cornered solid elements used by the finite element solver. Their size, shape, and count affect resolution and cost. Element limit is a calculation budget, not a mesh-quality target.",
  },
  {
    term: "Watertight",
    aliases: ["Closed mesh"],
    definition:
      "A triangle surface with no open boundary edges, as one requirement for a closed solid. Watertight alone does not prove valid material volume: overlaps, self-intersections, inconsistent winding, or ambiguous nested shells can still make mass and FEA unreliable.",
  },
  {
    term: "External surface",
    definition:
      "Marks components exposed to ambient airflow. Enclosed electronics and ballast should be internal. CFD solves only air connected to its exterior domain; sealed cavities receive no exterior pressure faces, while resolved open passages remain flow-accessible.",
  },
  {
    term: "Monte Carlo",
    aliases: ["MC"],
    definition:
      "Repeated simulations with randomly sampled inputs to explore uncertainty. Results depend on the chosen distribution, sample count, and random seed. A sample spread is not a validated probability of safe flight unless the underlying uncertainties and model are validated.",
  },
  {
    term: "Parameter sweep",
    aliases: ["Wind sweep", "Sweep"],
    definition:
      "Repeated simulations over a chosen input range. It reveals model trends while other inputs are held fixed. Select a parameter used by the chosen solver, and review validity and warnings for every sample.",
  },
  {
    term: "Random seed",
    aliases: ["Seed"],
    definition:
      "An integer selecting a repeatable random/gust realization. The same seed and inputs reproduce the sampled conditions. Monte Carlo reports its actual seed and uses independent seeded gusts per sample.",
  },
  {
    term: "GPU",
    aliases: ["CUDA", "Linear solver backend", "Compute backend", "Backend"],
    definition:
      "Graphics processing unit. The 3D view uses graphics hardware; numerical CUDA acceleration is a separate path requiring supported NVIDIA hardware and a working driver. The result's actual backend reports whether a numerical job used CPU or GPU.",
  },
  {
    term: "ETA",
    definition:
      "Estimated time remaining, based on current work and progress. Simulation budgets and solver behavior can make it change. Flight progress uses the duration ceiling until completion; it does not know the future landing time in advance.",
  },
  {
    term: "Time step",
    aliases: ["dt"],
    definition:
      "Maximum interval used by the flight integrator, in seconds. The solver takes smaller steps near thrust knots, events, and stiff drag cases. Halving the ceiling and comparing outputs helps check time-integration sensitivity.",
  },
  {
    term: "Duration limit",
    aliases: ["Maximum flight time", "max_time"],
    definition:
      "Time ceiling for flight integration. If reached before ground contact, the result is incomplete and has no computed landing. Increase the limit and rerun rather than assuming the last point is recovery.",
  },
  {
    term: "Root chord",
    definition:
      "Fin length along the rocket at the fin's attachment/root. Together with span, tip chord, sweep, thickness, and count, it defines the original procedural fin geometry.",
  },
  {
    term: "Tip chord",
    definition:
      "Fin length along the rocket at the outer tip. It is separate from the root chord at the attachment.",
  },
  {
    term: "Fin span",
    aliases: ["Span"],
    definition:
      "Distance the fin extends radially away from the body. It affects aerodynamic leverage, area, and bending loads. This is not the fin's nose-to-tail chord length.",
  },
  {
    term: "Fin sweep",
    aliases: ["Sweep distance"],
    definition:
      "Axial offset of the fin tip's leading edge from the root's leading edge in the original procedural geometry. Positive offset moves the tip aft.",
  },
  {
    term: "Primary stream speed",
    aliases: ["Primary stream speed"],
    definition:
      "Static-test freestream airspeed before the lateral wind vector is added. An optional Mach override sets this speed from local sound speed. Resultant airspeed and effective incidence can differ after wind is added. Flight speed is calculated from the trajectory.",
  },
  {
    term: "Lateral wind",
    definition:
      "Wind added across the rocket's reference axis in static aerodynamic tests. In Flight, the same speed input supplies horizontal ambient wind in the east/north launch coordinates. Check Wind direction because the static and flight direction conventions differ.",
  },
  {
    term: "Temperature deviation from ISA",
    aliases: ["ISA"],
    definition:
      "Temperature offset from the app's standard-atmosphere temperature at the entered altitude, in kelvin or equivalent Celsius temperature differences. It changes local density and sound speed using the model assumptions; it is not a measured weather profile.",
  },
  {
    term: "Launch rail length",
    definition:
      "Modeled travel distance along the rail before rail exit. The rocket is constrained to the entered rail direction until it travels this distance. Check the actual effective guiding length of your launcher and rail-button arrangement.",
  },
  {
    term: "Angle from vertical",
    definition:
      "Tilt of the launch rail measured from straight up. 0° is vertical. Launch azimuth selects the compass bearing of that tilt. This is separate from aerodynamic angle of attack.",
  },
  {
    term: "Flow-through times",
    definition:
      "CFD physical-time budget measured in characteristic flow-crossing times of the computational domain. It allows the initial flow to pass through the region before judging settling. Reaching this budget is not proof of numerical convergence.",
  },
  {
    term: "Wall time limit",
    definition:
      "Computer elapsed-time ceiling for CFD, separate from simulated flow time. 0 disables this limit. A job stopped here is partial. With Run until converged and no wall-time ceiling, completion time is unknown; Cancel retains actual partial flow fields.",
  },
  {
    term: "Cell budget",
    definition:
      "Maximum number of computational CFD cells allowed for the full domain. It limits memory/work. Grid resolution and farfield padding determine the requested count; the budget is not a target for mesh quality or accuracy.",
  },
  {
    term: "Maximum steps",
    aliases: ["Time steps"],
    definition:
      "CFD iteration/time-step ceiling. More steps allow more simulated flow evolution but do not guarantee convergence. Read the actual stop reason and residual histories before using the pressure result.",
  },
  {
    term: "Surface load",
    aliases: ["Applied pressure"],
    definition:
      "Force per area imposed on the structural surface. Pressure acts normally; prescribed traction supplies an explicit direction. Estimated aerodynamic pressure, uniform pressure, and transferred CFD pressure are different load assumptions and must be identified in the result.",
  },
  {
    term: "Estimated flight stress",
    aliases: ["Estimated component stress"],
    definition:
      "Quasi-static beam/fin screening stresses scaled by current dynamic pressure, with supported axial inertial estimates. They are not transient FEA and do not resolve recovery shock, laminate failure, joints, flutter, or missing load distributions.",
  },
  {
    term: "Standard deviation",
    definition:
      "A measure of spread around a mean. In Monte Carlo setup it defines the selected normal-distribution input spread; in a result it describes the computed sample spread. It is not a worst-case bound, and depends on the supplied uncertainty model and sample count.",
  },
  {
    term: "5th percentile",
    definition:
      "A lower sample quantile: approximately 5% of the computed values are below it. It describes this simulation sample, not a validated real-world failure probability or guaranteed lower bound.",
  },
  {
    term: "95th percentile",
    definition:
      "An upper sample quantile: approximately 95% of the computed values are below it. It describes this simulation sample, not a validated 95% safety guarantee or worst-case bound.",
  },
  {
    term: "Axial position",
    definition:
      "Position along the model's nose-to-tail +X axis. Component positions and local CAD alignment use this axis. A CAD offset is relative to the selected component, not an unrelated neighboring part.",
  },
  {
    term: "CAD offset",
    aliases: ["X offset", "Y offset", "Z offset"],
    definition:
      "Translation of the attached CAD asset along a model axis, relative to the selected component's position. Apply alignment / mode after changing it. Offsets alter this attachment rather than modifying the imported source mesh or other components.",
  },
  {
    term: "CAD rotation",
    aliases: ["X rotation", "Y rotation", "Z rotation"],
    definition:
      "Entered alignment angles in degrees for the attached CAD model. They rotate the asset relative to the component/model axes. Apply alignment / mode and compare Original geometry to check the result. These Euler angles are unrelated to Euler fluid-flow equations.",
  },
  {
    term: "Uniform scale",
    definition:
      "Single positive multiplier applied to all dimensions of the attached CAD. Doubling it increases solid volume by eight times when the geometry is valid. Correct source-file units first rather than guessing a scale to repair an STL unit mismatch.",
  },
  {
    term: "Mesh file units",
    definition:
      "Length units assumed for unitless mesh coordinates, especially STL. Selecting millimetres versus metres changes length by a factor of 1000. STEP files carry their own CAD units; check imported dimensions before attaching a mesh.",
  },
  {
    term: "Original geometry",
    definition:
      "A comparison overlay showing the OpenRocket reference geometry alongside the current attachment. It helps check CAD alignment and scale; it does not add duplicate parts to the aerodynamic, mass, or structural calculation.",
  },
  {
    term: "Wireframe",
    definition:
      "Displays triangle edges over the model so the surface tessellation is visible. It is a viewing option and does not alter source CAD, mesh resolution used by solvers, or calculated loads.",
  },
  {
    term: "POI",
    aliases: ["Point of interest", "Points of interest"],
    definition:
      "A point of interest on the local flight map, such as launch, apogee, deployment, or computed landing. Its position comes from the recorded trajectory. The map uses launch-relative east/north distances, not live GPS or satellite terrain.",
  },
  {
    term: "CG / CP",
    definition:
      "Shows the center of gravity (mass balance point) and center of pressure (modeled aerodynamic normal-force location). Positive static margin puts CP aft of CG in the nose-to-tail axis convention. These markers are computed model values, not measurements of flight attitude stability.",
  },
  {
    term: "Velocity",
    aliases: ["Resultant airspeed"],
    definition:
      "Speed or velocity must be read with its reference frame. Flight's Velocity metric is speed relative to the ground; Mach and aerodynamic loads use air-relative speed after subtracting ambient wind. CFD velocity arrows show the solved local fluid field.",
  },
  {
    term: "Acceleration",
    definition:
      "Rate of change of ground-relative velocity. Flight's displayed magnitude includes gravity, while inertial structural loading uses specific acceleration with gravity removed. The instant full-canopy assumption can create an idealized acceleration change that is not resolved opening shock.",
  },
  {
    term: "Stress",
    definition:
      "Internal force per area in a material. A Structures FEA overlay shows the solved von Mises field; Flight/component overlays show simplified engineering estimates when supported. Check the result's method and units rather than treating every stress color as a finite element solution.",
  },
  {
    term: "Pressure",
    definition:
      "Normal force per area in a fluid or applied structural load. A CFD pressure overlay comes from the numerical solution; its assumptions exclude viscosity and physical turbulence. Pressure is different from dynamic pressure and from the solid's von Mises stress.",
  },
  {
    term: "Dry mass",
    definition:
      "Mass of the spent motor hardware and remaining non-propellant material. Together with initial propellant mass it sets motor mass and CG loading. Review curve-file metadata and the actual hardware; importing a curve does not verify these masses.",
  },
  {
    term: "Propellant mass",
    definition:
      "Initial motor propellant mass. The flight model depletes it according to the cumulative thrust-curve impulse, an explicit approximation rather than a measured mass-flow history. Dry mass remains after burnout.",
  },
];

function normalizeTerm(term: string): string {
  return term
    .toLowerCase()
    .replace(/[’']/g, "")
    .replace(/[×·_-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
const glossaryLookup = new Map<string, GlossaryEntry>();
for (const entry of engineeringGlossary)
  for (const term of [entry.term, ...(entry.aliases ?? [])])
    glossaryLookup.set(normalizeTerm(term), entry);

export function glossaryEntry(term: string): GlossaryEntry | undefined {
  return glossaryLookup.get(normalizeTerm(term));
}

export function getTermDefinition(term: string): string | undefined {
  return glossaryEntry(term)?.definition;
}

/** A clickable definition works with a mouse, keyboard, or touch, including in narrow panels. */
export default function HelpTip({
  term,
  definition,
}: {
  term: string;
  definition?: string;
}) {
  const entry = glossaryEntry(term);
  const text = definition ?? entry?.definition;
  const title = entry?.term ?? term;
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0, above: false });
  const button = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const update = () => {
      const rect = button.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(336, window.innerWidth - 24);
      const height = popup.current?.offsetHeight ?? 170;
      const above =
        rect.bottom + height + 12 > window.innerHeight &&
        rect.top > height + 12;
      setPosition({
        left: Math.max(
          12,
          Math.min(rect.left - 10, window.innerWidth - width - 12),
        ),
        top: above
          ? rect.top - height - 8
          : Math.min(
              rect.bottom + 8,
              Math.max(12, window.innerHeight - height - 12),
            ),
        above,
      });
    };
    const outside = (event: PointerEvent) => {
      if (
        !button.current?.contains(event.target as Node) &&
        !popup.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        button.current?.focus({ preventScroll: true });
      }
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape, true);
    };
  }, [open]);
  if (!text) return null;
  return (
    <span className="help-tip">
      <button
        type="button"
        ref={button}
        className="help-tip-button"
        aria-label={`Definition of ${term}`}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        title={`Definition of ${term}`}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        onBlur={(event) => {
          if (!popup.current?.contains(event.relatedTarget as Node))
            setOpen(false);
        }}
      >
        <CircleHelp size={14} aria-hidden="true" />
      </button>
      {open &&
        createPortal(
          <div
            ref={popup}
            id={id}
            role="tooltip"
            className={`help-tip-popover${position.above ? " above" : ""}`}
            style={{
              position: "fixed",
              top: position.top,
              left: position.left,
              width: "min(336px, calc(100vw - 24px))",
              zIndex: 10000,
            }}
          >
            <strong>{title}</strong>
            <p>{text}</p>
            <small>Click ? again or press Esc to close.</small>
          </div>,
          button.current?.closest("dialog") ?? document.body,
        )}
    </span>
  );
}
