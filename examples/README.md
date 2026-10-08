# Synthetic tutorial files

Every asset here is fabricated for learning the interface and checking file
handling. None is a measured, certified or validated rocket design. Do not use
these motor/aerodynamic values for launch decisions.

| File | Purpose |
| --- | --- |
| `rocket_project.json` | Saved tutorial project with metric SI data, single/dual recovery configurations and a synthetic motor |
| `synthetic_motor.eng` | RASP motor import example; same fabricated curve as the built-in demo |
| `synthetic_polar.csv` | Coefficient-table import example over Mach 0–2; invented CD, CNa and CP, not computed/experimental data |
| `synthetic_payload_mm.stl` | Simple watertight solid rectangular payload; select **mm** during import |
| `synthetic_payload.step` | Same payload with embedded millimetre STEP units |

## Try the tutorial

1. Import `rocket_project.json` using **Saved project .json**, then explore the
   component tree, CG/CP and **Flight setup**. Run its synthetic flight and inspect
   rail exit, burnout, max Q, apogee and recovery playback.
2. Select **Payload bay — replace with CAD**, open **Geometry**, and import
   `synthetic_payload_mm.stl` with **mm** units, or `synthetic_payload.step`.
3. Select that asset and use **Attach & use detailed geometry** with scale 1,
   zero rotation and zero translation. Its X coordinates are already 0–0.65 m
   in the component frame. The tutorial component's existing 1.25 kg measured
   mass override takes precedence over the CAD solid mass; clear or change that
   override only to study the alternate homogeneous-solid assumption.
4. Toggle the original ghost geometry and compare the shapes. Fast CP/drag still
   use the original reference shape unless you import a suitable aerodynamic
   table. Use experimental CFD to study actual mesh pressure effects.
5. Optionally import `synthetic_polar.csv`. This exercises Mach interpolation and
   exact current-configuration/geometry binding; its invented coefficients do
   not become trustworthy because the software accepts them. Change alignment
   and rerun analysis to see the stale-table warning. Re-importing explicitly
   binds the file to that new shape.
6. To explore CAD-only workflows, choose the imported asset and **New project
   from CAD**. The interface starts a download of the previous project first.
   Ensure you actually save that backup before proceeding. Assign a motor,
   justified mass/CG and recovery parameters. A CAD-only passive flight needs a
   geometry-specific supplied polar because a bounding cylinder has no reliable
   nose/fin stability model. The tutorial polar can exercise that path only;
   it is not a validated coefficient set for the box.
7. In **Structures**, choose a justified plane clamp and mesh size for the box.
   A uniform prescribed pressure can demonstrate linear elasticity. Use a
   converged, matching CFD job to explore one-way pressure-transfer FEA; check
   mapped coverage and resultant forces. Numerical convergence is separate
   from physical validation.

The source checkout stores these files under `examples/`. The Windows bundle
stores them in `_internal/examples/` beneath the application install directory.
The default installation is `%LOCALAPPDATA%\Programs\Rocket Workbench`.

Regenerate with `uv run --no-sync python scripts/generate_examples.py` after
installing the engineering dependencies. Project/ENG/CSV/STL outputs are derived
from the current synthetic demo. STEP exporters may vary timestamp/header data.
