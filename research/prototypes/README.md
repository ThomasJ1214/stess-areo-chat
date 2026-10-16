# Unintegrated solver drafts

These drafts preserve unfinished work for the next engineering pass. They are
text files outside the application package and are not installed solver options.
The plate kernel now has a separately tested application implementation in
rocket_workbench/solvers/plate_elements.py and plate_fea.py for original flat
fins; see docs/STRUCTURAL.md. This text is an archival draft, not a runtime import. Initial plate references below cover only
the tested element and square-plate cases.

- `plate_fea.py.txt`: proposed MITC4 thin-plate element, meshing and static solve.
  Still requires broader fin-planform/stress/convergence checks, an actual component
  adapter, preflight, supports/load mapping, GUI and installed-executable tests.
- `cfd_reconstruction.py.txt`: proposed primitive-variable MUSCL face reconstruction.
  Still requires conservative solver/SSPRK2 integration, positivity and boundary
  verification, independent convergence/shock references and GPU checks.

No thin-shell/plate or higher-order CFD capability should be advertised from
these files. Preserve the existing solid-FEA thickness guards and current CFD
accuracy warnings until verified replacements are integrated.

Initial rectangular plate references are now repeatable through
`../validate_plate_draft.py`; see [the evidence and remaining limits](../PLATE_REFERENCE.md).
The MUSCL draft remains unvalidated and unintegrated.
