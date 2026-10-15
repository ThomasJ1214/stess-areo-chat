# Aerodynamics, mass properties and flight

Rocket Workbench is a preliminary engineering tool. It does not reproduce the
OpenRocket simulator internally and does not claim certification, wind-tunnel
agreement, or validated transonic flight/stress predictions. Every calculation
returns its fidelity, backend, warnings and relevant validity flags. GPU rendering
does not turn a CPU empirical calculation into GPU CFD.

## Coordinates and operating scope

Geometry is SI: metres, kg, seconds, Pa; stored/displayed angles are degrees.
Rocket X goes from nose to tail. Static freestream is +X, angle of attack acts
in XY, sideslip in XZ. Static `speed` is the primary freestream speed; setting
`mach` sets that speed from the local sound speed. Lateral wind is then added in
YZ: direction zero is toward +Y and 90 degrees toward +Z. Returned speed/Mach
are the resultant air-relative values, so nonzero wind may exceed a specified
primary Mach. The UI should inspect effective incidence, not just entered angle.

Flight uses east/north/up inertial coordinates. Launch angle is measured from
vertical; azimuth zero is north and 90 degrees east. Wind direction is a **toward**
azimuth, not a meteorological **from** direction. Flight `altitude` is height above
launch level (AGL); `altitude_msl` also includes the geometric launch altitude.

The target is passive, single-stage, single-motor high-power rockets through Mach
2, including single or dual deployment. Multistage, clustered motors, parallel
stages, pod assemblies, active guidance, and custom ignition/deployment event
semantics are rejected by both flight solvers. Imported unsupported components
remain visible and are identified in warnings. Speeds above Mach 2 are explicitly
out of scope; the trajectory may complete using extrapolated estimates, but its
validity flag is false. A point-mass solver cannot determine if a rocket tumbles.
Import limitations are checked for the selected configuration, so an inactive
unsupported stage does not block a supported single-stage configuration. Disabling
an assembly or excluding it from a configuration also excludes all descendants;
an assigned motor mount must still belong to that selected, enabled subtree.

## Atmosphere

`aero.atmosphere` implements the 1976 standard atmosphere through 50 km geometric
altitude, and allows a -500 m launch level. It converts geometric height `z` to
geopotential height `h = R_e z / (R_e + z)`, using `R_e = 6,356,766 m`.

Layers start at geopotential heights 0, 11, 20, 32, 47 and 51 km with lapse rates
-0.0065, 0, +0.001, +0.0028 and 0 K/m. Sea level is 288.15 K and 101325 Pa.
For nonzero lapse rate `L`,

`T = T_b + L(h-h_b)` and `p = p_b (T_b/T)^(g0/(R_air L))`.

For isothermal layers, `p = p_b exp[-g0(h-h_b)/(R_air T_b)]`.
Density is `p/(R_air T)` and sound speed is `sqrt(1.4 R_air T)`, with
`R_air = 287.05287 J/(kg K)` and `g0 = 9.80665 m/s²`. Sutherland's law uses
reference viscosity `1.716e-5 Pa s` at 273.15 K and constant 110.4 K. Local gravity
varies as `g0 [R_e/(R_e+z)]²`. Temperature offset changes density, sound speed and
viscosity at standard pressure; it does not solve a new measured hydrostatic
atmosphere or humidity profile.

Reference checks use standard sea-level and layer-table values. The pressure
tolerance at layer boundaries is 0.001% to accommodate rounded published gas
constants/base pressures; this is verification of the standard equations, not
validation against launch-site weather measurements.

## Mass and CG

Original shells/tubes/rings use their annular volumes and material density.
Supported nose families and shaped transitions use numerical quadrature of the
same canonical radius profile used by the viewer (including secant-ogive
parameters, clipped transitions and flipped noses);
hollow walls are radial-thickness shells. Fins use actual polygon area for
freeform shapes, analytic polygon/elliptic area, thickness and fin count. Replica
counts/separations affect mass/CG without multiplying fin count twice. Unspecified
mass objects/recovery hardware contribute zero and emit a warning; their packed
display shape is not interpreted as solid fiberglass.

Measured mass and absolute CG overrides take precedence. A parent subtree mass
override excludes descendant mass so it is not double-counted; subtree CG overrides
replace the aggregate moment. ORK tab/shoulder/joint details not represented by an
analytic volume require measured overrides; import warnings identify these limits.

A replacement watertight triangular mesh is integrated as signed tetrahedra
formed with a local integration origin near the solid to reduce cancellation for
remote CAD coordinates. Tetrahedron volume is `dot(a,cross(b,c))/6` and its centroid
is `(a+b+c)/4`. Mesh scale, Euler XYZ rotation and translation (relative to the
component's axial origin) apply before integration. Uniform solid density is an
assumption: hollow/heterogeneous assemblies need measured mass/CG. Open meshes do
not receive an invented solid volume; a measured override is required. Signed
volume needs consistent surface winding. A measured mass alone retains the
watertight CAD centroid; a measured CG overrides it.
Actual triangle closure and winding are checked before mass integration instead
of trusting a saved `watertight` flag. These topological checks do not establish
absence of self-intersection, overlapping solids or valid CAD construction.

Motor thrust is piecewise linear. Propellant consumption is proportional to its
integrated impulse, not elapsed burn time, corresponding to constant effective
specific impulse. Motor mass decreases from dry+propellant mass to dry mass;
motor CG remains at the configured geometric/measured center. A designation in
an ORK file is not a thrust curve: flight requires imported ENG/RSE data or an
explicitly supplied curve. Synthetic demo data is labelled as such.

## Small-angle aerodynamics

Reference area is the largest original external body cross-section, `pi D²/4`.
Barrowman body contributions have `CNa = 2 (A_aft-A_fore)/A_ref`. For a nose,
`x_CP = L - V_outer/A_base`, yielding `2L/3` for a cone and `L/3` for an ellipsoid.
Transitions use the corresponding frustum-area relation. Constant-radius body
tubes have zero small-angle body slope; nonlinear body lift is not represented.

For `N` evenly spaced trapezoid fins with semispan `s`, root/tip chords `Cr,Ct`,
leading-edge sweep `xs`, root radius `r`, and midchord distance
`l = sqrt(s² + [xs+(Ct-Cr)/2]²)`, classic incompressible fin slope is

`CNa = [1 + r/(r+s)] 4 N (s/D)² / [1 + sqrt(1 + [2l/(Cr+Ct)]²)]`.

Its CP is

`x_fin + xs(Cr+2Ct)/[3(Cr+Ct)] + [Cr+Ct-CrCt/(Cr+Ct)]/6`.

The rocket CP is the CNa-weighted component CP. Stability is `(CP-CG)/D`.
With zero/nonpositive total slope at the evaluated Mach, CP/stability are undefined
(`null`), while
mass/drag diagnostics remain available. Flight then requires a supported reference
shape or a geometry-matched supplied aerodynamic polar. One/two-fin systems use an
azimuth average; fin-fin interference above four fins is not resolved. Freeform/
elliptic fin lift uses an explicitly labelled equivalent trapezoid.

Subsonic fin compressibility uses the finite-wing expression documented in
OpenRocket: the denominator's `l` term is multiplied by `sqrt(1-M²)` through Mach
0.9. Above Mach 1.5, first-order supersonic thin-fin lift is `4/beta` times fin area,
with `beta=sqrt(M²-1)`, multiplied by the azimuth-averaged fin count/interference
factor. A smoothstep bridge joins the two regimes. Fin CP shifts smoothly from
quarter chord below Mach 0.5 toward half chord at Mach 2. This bridge and CP shift
are **preliminary extensions**, not a port of OpenRocket's more detailed
Mach-dependent CP and NACA interference implementation. High Mach and effective
resultant cone incidence above 10 degrees invalidate the preferred small-angle CP
claim. The limit applies to `atan2(hypot(V_y,V_z),V_x)`, not separately to yaw and
pitch: two 8-degree components already give an 11.30-degree resultant incidence.

An independent hand calculation in the tests uses `D=.1 m`, `s=.12 m`, `Cr=.25 m`,
`Ct=.12 m`, `xs=.12 m`, `N=3`, `r=.05 m`, fin position `1.18 m` and a `.3 m` cone.
It gives fin CNa `10.0348601291 /rad`, fin CP `1.2811261261 m`, and total
incompressible rocket CP `1.1014603694 m`.

## Drag estimates and provenance

Dynamic pressure is `q=.5 rho V²`; force is `q A_ref C`. The model separates skin,
pressure, induced and base contributions. Smooth plate skin friction is
`1.328/sqrt(Re)` below `Re=5e5`, and the Schlichting-type turbulent correlation
`0.455/log10(Re)^2.58 / (1+.144M²)^.65` above that threshold. It uses a documented
body form factor `1+60/fineness³+.0025*fineness`. A simple transition at the
threshold is not a model of surface roughness or measured transition location.

Base drag follows the rocket correlation `0.12+.13M²` below Mach 1 and `.25/M`
above Mach 1, scaled by exposed aft area. Nose pressure is a **conical-envelope
surrogate**: with `s_phi=R/sqrt(R²+L²)`, zero-Mach coefficient is `.8 s_phi²`,
Mach-1 coefficient is `s_phi`, and for `M>=1.3` it is
`2.1 s_phi²+.5 s_phi/sqrt(M²-1)`. Subsonic power interpolation and a cubic Hermite
bridge connect these values using the published rocket-method endpoint slopes.
These formula values were checked in the upstream OpenRocket source below.
Curved noses use their actual original shape for volume/CP, but still receive the
explicit conical-envelope pressure warning. Fin leading-edge/thickness pressure,
boattail separation and induced drag remain simple estimates. `wave_cd` is a
diagnostic nose pressure increment; it is already included in component pressure
drag and must not be added twice.

This model omits roughness, arbitrary CAD pressure distributions, wake/fin-body
interference beyond the simple factor, separated flow, viscous shock interaction,
rail-button/lug lift, base-plume interaction, fin flutter and aeroelastic motion.
Its transonic/supersonic drag is not validated for the user's exact rocket.

### Detailed CAD and supplied coefficients

Replacing an external ORK component updates actual solid mass and CG. Empirical
drag/CP still describe the **original reference shape**, and the result exposes
`cp_valid=false`, `cad_resolved=false` and a visible warning. Rendering a detailed
mesh does not create physical aerodynamic coefficients. Mesh-resolved CFD
is a separate solver with its own Euler/laminar and convergence limits;
see [CFD.md](CFD.md). It is not silently used to overwrite flight coefficients.

Users may explicitly import a Mach table with `mach,cd,cna,cp_m` and provenance.
CNa is per radian; Cd/CNa must be normalized to the project's displayed original
body reference area, and CP measured from its axial origin. A geometry-matched
table records supplied aerodynamic data, not a CFD calculation performed by the
flight solver. It must have at least two distinct increasing Mach values in
`[0,2]`, nonnegative Cd, positive CNa and finite CP. Each row is bound to the active
configuration and a SHA256 signature over its actual selected geometry, CAD mesh,
alignment and importer geometry metadata. Mass/material overrides do not change
the signature. Geometry edits invalidate the table instead of silently reusing
stale coefficients. Signature agreement records shape association, not validation
of the supplied coefficients. Report provenance as **User supplied aerodynamic
polar**; do not invent wind-tunnel verification.

Within table coverage, total drag/CNa/CP are linearly interpolated. Component force
breakdowns remain original-reference estimates and `component_breakdown_valid`
is false; total coefficients do not specify component loading. Outside coverage,
reference estimates return with a warning and `polar_applied=false`, including per
flight row. A table's zero-angle Cd does not model nonlinear angle dependence.
Tests demonstrate that a high-Cd supplied table reduces apogee and that geometry
changes invalidate it. A pressure-only, unconverged or unverified CFD result must
not be silently promoted to a full viscous Cd table.

## Flight integration and recovery

The solver integrates three position and three velocity components with
error-controlled RK4 step doubling. A full step and two half steps estimate
local truncation error; accepted states use the two half steps. The relative
tolerance is `1e-7`, with separate absolute tolerances `1e-5 m` for position
and `1e-5 m/s` for velocity. Rejected steps are reduced and retried. Recorded
`numerical_integration` metadata includes tolerances, accepted/rejected counts,
step bounds and event precision. These are local numerical accuracy controls,
not a global trajectory error bound or measured physical validation.
Gravity varies with altitude. Aerodynamic velocity is vehicle inertial velocity
minus ambient wind; drag opposes that relative velocity. The rocket is constrained
to the rail until its traveled distance reaches rail length. The pad reaction
holds it stationary until axial thrust exceeds gravity/drag. Liftoff, rail exit,
apogee, main altitude crossing and ground contact are root-located, not rounded to
the output sample time. Integration splits at all thrust-curve knots, ignition,
burnout and scheduled deployments. Combined body/canopy quadratic drag has a
stability-based step cap (including large supplied Cd and light vehicles);
user `dt` is an upper bound. A thrust curve ending at nonzero measured thrust uses
left/right limits at burnout so an extra numerical impulse is not introduced.

In the default point-mass model, after rail exit the thrust axis follows inertial velocity, giving a passive
point-mass gravity turn. It does **not** solve attitude, angular rates, restoring
moments, weathercocking, sideslip, fin loading angle through flight, or instability
tumbling. Flight drag uses zero-incidence reference coefficients; entered static
angle of attack is only the fixed reference angle for structural load estimates.

Primary deployment can trigger at apogee plus delay or at actual motor burnout
plus the configured motor ejection delay and an additional deployment delay.
Unknown/plugged motor ejection delay is rejected rather than invented. Ejection
may occur during ascent; its event is independently recorded. Single deployment
applies main canopy Cd×area at the selected primary event. Dual deployment
applies drogue then main at the specified descending AGL altitude. If the rocket
is already below main altitude at delayed drogue deployment, main deploys
immediately. Optional drogue/main inflation durations ramp effective Cd×area
linearly from the preceding canopy area to the target area. Zero duration retains
the original instantaneous deployment. This is a user-assumed inflation law:
opening shock, line stretch, cord loads, separated components and pendulum motion
are not solved. Exported `recovery_inflation_fraction`, `recovery_cd_area_m2` and
`canopy_load_n` describe that lumped drag calculation. `max_acceleration` is the
sampled maximum inertial magnitude over the whole flight; it should not be treated
as a resolved recovery opening shock.
An imported configuration without supported, positive-Cd×area recovery is marked
undefined and cannot silently use the application's default canopy values. The
user must enter and confirm a recovery setup before flight is allowed.

Uniform wind uses the supplied toward azimuth. Wind models and causal changes
are documented below; both flight solvers use the same reproducible field.

Events include ignition, liftoff, rail exit, burnout, apogee, drogue/main deployment,
max acceleration, max Q, max velocity, max airspeed, max Mach, max specific
acceleration, supported max estimated stress and recovery. Peak markers identify
accepted trajectory samples, rather than promising continuous extrema. Progress is integration time
divided by max_time, followed by completion; ETA therefore uses a conservative
time ceiling rather than knowledge of the future landing time. Cancellation is
checked throughout. Reaching max_time does not fabricate recovery: summary.complete
is false and a warning tells the user to extend the duration.
The recovery event marks ground contact, not a claim that a canopy opened or the
rocket landed safely. An undeployed impact carries an explicit warning;
`summary.recovery_deployed` and landing velocity identify it.

## Flight stress

When supported, trajectory stress comes from the actual beam/fin estimator in
[STRUCTURAL.md](STRUCTURAL.md), precomputed at a fixed reference incidence/Mach
and scaled by current dynamic pressure. Supported tubes also receive a simplified
axial inertial stress based on forward component masses. Inertial input uses
specific acceleration `|dv/dt - g_vector|`: a vacuum ballistic freefall has zero
applied acceleration load, rather than incorrectly treating gravity as stress.
Every row labels these as quasi-static estimates; absent support returns null.
These default estimates are not transient FEA, aeroelasticity, recovery shock, joint loads, laminate
failure or a material fatigue calculation. Imported total polar coefficients do
not supply component pressure/load distributions, so structural load estimates
retain their original-reference limitations.

Every trajectory row also records actual body drag, recovery drag, thrust,
gravity and ideal rail/pad reaction vectors in world east/north/up axes.
Their resultant equals mass times the recorded inertial acceleration; gravity
is excluded from specific acceleration. Body/recovery drag are separated so
the selected canopy-inflation assumption remains visible. Flight graphs offer
overview, loads/stress and wind/air groups using those calculated samples.

An optional **Dynamic fin beam FEA** pass integrates real mass/stiffness matrices
against the recorded flight loads. It writes separate `dynamic_stress` and
`dynamic_structural_components` fields without replacing the default estimates.
See [STRUCTURAL.md](STRUCTURAL.md) for supported geometry, load provenance,
missing intervals, damping and model limits.

## Experimental rigid-body flight

Selecting `flight_model:rigid_body` integrates position, velocity, Hamilton
quaternion and three body angular rates. Body axes are [+nose,+geometryY,
−geometryZ]; a `[w,x,y,z]` quaternion maps this right-handed frame to world
east/north/up. The rail constrains translation and attitude until root-located
rail exit; entered initial angular rates are applied at that release. The
integrator uses RK4 step doubling, relative tolerance 10⁻⁷, position/velocity
absolute tolerance 10⁻⁵, quaternion tolerance 10⁻⁸ and rate tolerance 10⁻⁷ rad/s.
It normalizes accepted quaternions and reports numerical diagnostics.

Drag opposes actual air-relative velocity. Small-angle normal force opposes its
component transverse to the nose, with magnitude q A CNa α. Its moment is the
cross product of the actual CP-to-CG arm and force. Thrust acts along the nose
from the assigned motor center. Euler's body equation is
`I ω̇ = M − ω × (I ω)`; quaternion kinematics use `q̇ = ½ q ⊗ [0,ω]`.
Optional supplied Cmq adds pitch/yaw damping using rate scale ωL/(2V). Missing
Cmq means **zero empirical damping**, with a visible warning. No invented roll,
fin-cant, roll-damping or post-stall coefficients are applied.

Closed component mesh volume moments are normalized to assigned masses and
combined about the actual three-dimensional dry CG. Unresolved hardware uses
disclosed point-mass/cylinder surrogates. A measured symmetric positive-definite
dry tensor can replace this estimate; supply its provenance. Principal moments
must also satisfy the physical triangle inequality. Closed topology alone is
insufficient: imported meshes marked as ambiguous material volume cannot supply
trusted volume moments and receive disclosed fallback estimates. The override is
about the **complete dry rocket's dry CG**, expressed in nose-body axes, in kg m².
The motor's remaining propellant adds a uniform cylinder at its fixed center;
the tensor and CG are recentered as propellant burns. This assumes co-rotating
symmetric mass removal and omits jet damping, grain geometry and slosh. It is not
a measured variable-mass exhaust angular-momentum model.

The aerodynamic slopes remain preliminary reference coefficients. Unrecovered
free flight stops at the first 10° resultant-incidence crossing when the
normal force at that boundary exceeds 1% of weight. The result is explicitly
partial with an aerodynamic-model-limit event; it does not predict a tumble.
At smaller loads, on the rail, or under recovery, unsupported high-incidence
normal forces/moments are omitted and the limits remain visible. Recovery is
lumped drag at CG, with no suspension or canopy attitude moment model. Supplied
total polar coefficients do not establish detailed component loading.

Actual quaternions, rates, inertia, moments, forces and component reference loads
are exported. The viewer interpolates position/wind and uses quaternion SLERP
only to render smooth playback; numeric inspectors remain tied to saved solver
samples. Point-mass attitude remains labelled illustrative. Launch-driven CFD
uses the solved attitude when available to transform freestream into CAD axes,
but keeps geometry fixed and omits moving walls, rotating-frame forces and
two-way CFD/flight feedback.

## Wind, gusts and changes during flight

The default `legacy_gust` retains three seeded smooth sinusoidal frequencies
(.23, .71, 1.9 Hz). Optional `dryden` uses a stationary Gaussian temporal
surrogate with length L and fixed transport speed V. Let a=V/L. Its normalized
filters are `H_u=√(2a)/(s+a)` and
`H_v=H_w=√a(√3s+a)/(s+a)²`. Each axis is scaled to the entered turbulence
intensity times max(1 m/s, mean wind speed). Equal-axis RMS is a user assumption,
not an altitude-dependent military weather standard.

Exact stationary state/covariance transitions generate the fixed seeded sample
grid (default 0.02 s); queries interpolate that realization without advancing
random state. Adaptive-step order therefore cannot rewrite prior gusts. The
fixed transport speed defaults to max(1 m/s, initial wind speed); the longitudinal
direction is the initial horizontal wind axis. This is not a three-dimensional
spatial field, resolved turbulence, von Kármán model or variable-encounter-speed
Dryden simulation. A sample/correlation-scale study is necessary before using
high-frequency gust loads. Optional mean/gust power-law shear scales velocity
by `(AGL/reference_height)^exponent`; exponent zero preserves uniform wind.

Scheduled `wind_events` specify start time, toward azimuth, speed, turbulence,
transition duration and optional temperature offset. They must be strictly
ordered and nonoverlapping. Mean wind vectors, gust RMS and temperature change
causally across each interval; the same seeded gust realization and earlier
physical history are retained. The integrators split at event boundaries.
The live panel pauses playback, adds a future change at the selected flight
time, recalculates the actual trajectory and resumes there. It never edits saved
result samples to simulate a wind change. Design/geometry changes require a
fresh launch. Adaptive output timestamps can differ near a newly introduced
event; causality does not promise byte-identical exported rows.

## Validation performed and references

Automated tests check standard atmosphere tables, analytic cone/tube mass/CG,
Barrowman hand calculations, CAD rotation/scale mass/CG, subtree overrides,
integrated-thrust mass depletion, wind incidence, finite Mach-range values,
coefficient provenance/invalidation, event ordering/altitudes, deterministic wind,
recovery, cancellation and explicit unsupported configurations. An independent
closed-form vacuum triangular-thrust trajectory checks burnout velocity/height
and apogee. Step halving checks flight convergence; a large recovery Cd×area case
checks dissipative integration stability. A deliberately stiff constant-Cd body
case checks the independent exact quadratic-drag terminal approach during powered
flight. These are **calculation verification**.
There is no supplied flight log, actual thrust-test campaign, wind-tunnel data,
or independently executed OpenRocket comparison establishing predictive accuracy.

Primary sources for equations and future validation:

1. NOAA/NASA/USAF, *U.S. Standard Atmosphere, 1976*, NASA-TM-X-74335,
   [NTRS 19770009539](https://ntrs.nasa.gov/citations/19770009539).
2. James S. Barrowman, *The Practical Calculation of the Aerodynamic
   Characteristics of Slender Finned Vehicles* (1967),
   [NTRS 20010047838](https://ntrs.nasa.gov/citations/20010047838).
3. Sampo Niskanen, *Development of an Open Source Model Rocket Simulation Software*
   (2009), [OpenRocket technical documentation](https://openrocket.sourceforge.net/techdoc.pdf).
4. [OpenRocket source](https://github.com/openrocket/openrocket), inspected at commit
   `591c5e5f7b7377e48f2bd5e501cef25cdfbd61d8`: `ExtendedISAModel.java` for
   geopotential layers/constants, `barrowman/FinSetCalc.java` for finite-wing and
   supersonic fin models, `barrowman/SymmetricComponentCalc.java` for conical
   pressure correlations, and `BarrowmanDragCalculator.java` for base drag.
   These mathematical models were independently implemented; the full OpenRocket
   Java simulator, its current detailed NACA interference models and full drag
   calculation are not embedded/ported here.
5. NASA TR-R-100, *Collection of Zero-Lift Drag Data on Bodies of Revolution from
   Free-Flight Investigations*,
   [NTRS 19630004995](https://ntrs.nasa.gov/citations/19630004995), cited in
   OpenRocket's nose-body drag model; its fineness-3 data motivates future
   shape-specific polar validation and is not represented as measurements of an
   arbitrary imported CAD rocket.

Direct NASA/SourceForge PDF download was blocked by this build environment's
network proxy. The upstream OpenRocket Git source was retrieved and inspected.
The documents above are authoritative references for further review; this project
does not claim it downloaded or reproduced their complete benchmark datasets.
