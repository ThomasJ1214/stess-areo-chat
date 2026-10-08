# Development guidance

Use this checkout directly. Cloud tasks already have isolated environments;
create a Git worktree only when the user explicitly requests one.

Read README.md and the method-specific documents in docs/ before changing
engineering behavior. Store physics and project quantities in SI units; display
conversions belong in web/src/units.ts. Preserve fidelity, actual backend,
assumptions, convergence and warnings in all result/export pathways. Never
substitute illustrative values for unavailable CFD, FEA or measured data.

The project uses Python 3.12, uv.lock and web/package-lock.json. Install with
`uv sync --locked --extra dev --extra desktop --extra browser` and `npm ci`
in web/. Add `--extra gpu` for numerical CUDA development on suitable hardware.
Keep caches, local projects, credentials and generated binaries out of Git.

Relevant checks are `uv run --no-sync pytest`, the application `--smoke-test`,
and `npm test` / `npm run build` in web/. For changes to imports, jobs, the UI or
solver integration, run scripts/browser_smoke.py after building the frontend.
It starts an isolated API and records real workflow evidence. Native Qt startup
has a separate `--desktop-smoke-test`; Windows packaging must be checked on
Windows. See docs/DEVELOPMENT.md for prerequisites and commands.

Scientific changes need independent reference/limiting cases or conservation
checks, rather than assertions that repeat the implementation. Keep file readers,
geometry, solvers, job coordination and the UI modular. Document unsupported
features explicitly and retain user/import warnings.
