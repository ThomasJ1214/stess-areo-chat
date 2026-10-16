# Unintegrated solver drafts

These drafts preserve unfinished work for the next engineering pass. They are
text files outside the application package and are not installed solver options.
The plate kernel now has a separately tested application implementation in
rocket_workbench/solvers/plate_elements.py and plate_fea.py for original flat
fins; see [the structural method](../../docs/STRUCTURAL.md). This text is an
archival draft, not a runtime import. Initial draft references below cover only
the tested element and square-plate cases.

- `plate_fea.py.txt`: archival MITC4 thin-plate element, meshing and static solve.
  The separate production implementation adds fin-planform/stress references,
  the component adapter, preflight, supports/load mapping, GUI and packaged
  checks. Use production tests and [release evidence](../../docs/VALIDATION.md)
  to determine what has actually passed; this draft is not a solver option.
- `cfd_reconstruction.py.txt`: proposed primitive-variable MUSCL face reconstruction.
  A separate production implementation now has shared-flux/SSPRK2 integration,
  smooth-wave convergence, shock, conservation, positivity and boundary tests.
  See [CFD methods](../../docs/CFD.md) and the validation checkpoint before
  claiming packaged or GPU verification. The draft is archival.

No thin-shell/plate or higher-order CFD capability should be advertised from
these files. Preserve the existing solid-FEA thickness guards and current CFD
accuracy warnings until verified replacements are integrated.

Initial rectangular plate references are now repeatable through
`../validate_plate_draft.py`; see [the evidence and remaining limits](../PLATE_REFERENCE.md).
The archival MUSCL draft is not imported by the app; production code and its
separate validation evidence define the available method.
