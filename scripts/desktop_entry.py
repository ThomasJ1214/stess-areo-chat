"""Minimal PyInstaller entry point; the normal CLI owns startup and smoke checks."""
import sys

if "--cuda-bundle-smoke-test" in sys.argv:
    from rocket_workbench.cuda_bundle_smoke import main as cuda_bundle_main
    raise SystemExit(cuda_bundle_main())

from rocket_workbench.main import main

if __name__ == "__main__":
    if any(flag in sys.argv for flag in ("--smoke-test", "--bundle-smoke-test", "--desktop-smoke-test", "--desktop-preferences-smoke-test")):
        # A windowed PyInstaller exception dialog can stall unattended builds.
        # Keep a diagnostic and fail with an exit code instead for this mode.
        try:
            exit_code = main()
        except Exception:
            import os
            from pathlib import Path
            import tempfile
            import traceback
            logfile = Path(tempfile.gettempdir()) / f"rocket-workbench-smoke-error-{os.getpid()}.log"
            logfile.write_text(traceback.format_exc(), "utf-8")
            exit_code = 1
        raise SystemExit(exit_code)
    raise SystemExit(main())
