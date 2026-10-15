# Unintegrated solver drafts

These drafts preserve unfinished work for the next engineering pass. They are
text files outside the application package and are not installed solver options.
Neither has production integration. Initial plate references below cover only
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
The prototype still has no application integration. The MUSCL draft remains
unvalidated.
