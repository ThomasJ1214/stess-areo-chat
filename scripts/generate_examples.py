"""Regenerate explicitly synthetic tutorial assets; never certified design data."""
from __future__ import annotations

import csv
from pathlib import Path

import trimesh

from rocket_workbench.demo import demo_project

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    folder = ROOT / "examples"
    folder.mkdir(exist_ok=True)
    project = demo_project()
    project.id = "synthetic-example-project"
    project.name = "Synthetic tutorial rocket"
    (folder / "rocket_project.json").write_text(project.model_dump_json(indent=2) + "\n", "utf-8")

    motor = project.motors[0]
    header = f"SYNTHETIC-DEMO {motor.diameter * 1000:g} {motor.length * 1000:g} P {motor.propellant_mass:g} {motor.dry_mass + motor.propellant_mass:g} Synthetic-educational-data"
    eng = "; Synthetic tutorial motor; not a certified or measured thrust curve.\n"
    eng += "; Replace with manufacturer/test data before any design decision.\n"
    eng += header + "\n" + "\n".join(f"{t:g} {force:g}" for t, force in motor.curve) + "\n"
    (folder / "synthetic_motor.eng").write_text(eng, "utf-8")

    # These invented numbers exercise import/interpolation only. They must not
    # masquerade as Euler-generated, OpenRocket or measured aerodynamic data.
    with (folder / "synthetic_polar.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["mach", "cd", "cna", "cp_m", "source"])
        for mach, cd, cna, cp in [(0, 0.5, 12, 2.1), (0.5, 0.5, 12, 2.1), (0.9, 0.65, 13, 2.08),
                                  (1.1, 0.85, 13.5, 2.06), (1.5, 0.7, 12.5, 2.1), (2, 0.65, 12, 2.12)]:
            writer.writerow([mach, cd, cna, cp, "SYNTHETIC tutorial values only; not CFD or measured data"])

    # The model is a solid rectangular payload, X=0..650 mm, Y/Z=+-50 mm.
    # It demonstrates replacement alignment and meshing, not real rocket hardware.
    payload = trimesh.creation.box(extents=[650, 100, 100])
    payload.apply_translation([325, 0, 0])
    payload.export(folder / "synthetic_payload_mm.stl")

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.gp import gp_Pnt
    writer = STEPControl_Writer()
    writer.Transfer(BRepPrimAPI_MakeBox(gp_Pnt(0, -50, -50), 650, 100, 100).Shape(), STEPControl_AsIs)
    if writer.Write(str(folder / "synthetic_payload.step")) != IFSelect_RetDone:
        raise RuntimeError("Could not export tutorial STEP")
    print(f"Wrote synthetic example assets to {folder}")


if __name__ == "__main__":
    main()
