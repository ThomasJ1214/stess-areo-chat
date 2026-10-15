# Thin-plate draft: initial reference checks

This is research evidence for a future solver, not an installed FEA capability.
The app still has its existing solid-FEA thickness guard and original-fin beam
models. There is no plate option in the UI.

Run from the repository with the existing development dependencies:

```sh
.venv/bin/python research/validate_plate_draft.py
```

The command reads the unmodified trusted text draft and writes a source-hashed
receipt to `build/research-plate-reference.json`. An assertion failure gives a
nonzero exit status; generated receipts are not committed.

On 2026-10-15, draft SHA-256
`6eeefd01ec5fa51f00a874bf80aba28790c49fabb76d8377ea64dff9b205c30a`
passed three rigid modes, element rank, constant cylindrical curvature energy,
12 square-plate mesh/thickness cases, two distorted-element constant-curvature
patches, triangle/trapezoid mesh area/boundary/manifold checks, and rejection of
concave, crossed and duplicate-corner elements. A concave element with positive
Jacobian determinants at the Gauss points was accepted by the earlier draft;
explicit corner convexity checks now reject it. The independent Navier Fourier series
includes bending and transverse shear for a hard simply supported unit square:
transverse displacement and tangential rotation constrained on each edge.
Only constraining displacement is a different support problem and must not be
compared to that reference. Series truncation is checked by doubling the order.

| Thickness/side | Meshes (elements) | Finest center-deflection relative error |
| --- | --- | --- |
| 0.1 | 16, 64, 256, 1024 | 0.0262% |
| 0.01 | 16, 64, 256, 1024 | 0.0314% |
| 0.001 | 16, 64, 256, 1024 | 0.0315% |

Each sequence reduces its error with refinement. Pressure scales with thickness
cubed to preserve small deflection. Maximum force/moment balance errors across
these cases were below 2.1e-9 / 4.1e-11. Energy/work consistency and free-DOF
residuals are also checked. These results support the tested element/rectangle
calculation; they do not validate arbitrary fin meshes or structural stresses.

Before integration, independently check full-solve convergence on skew/distorted
and triangular planforms,
root constraints, rigid coordinate transformations, pressure/force conservation,
stress convergence and thickness/shear sensitivity. Then implement real component
selection, per-fin orientation and loads, material/preflight contracts, deformation
mapping, unsupported-state reporting, UI and installed-executable checks. CAD
midsurfaces, curved shells, laminates, buckling and transient plates are separate
work. Do not infer those capabilities from this benchmark.
