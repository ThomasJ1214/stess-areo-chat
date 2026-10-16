"""Actual steady MUSCL exterior solve against exact quiescent air.

Run from the repository with the locked development environment. This can take
several minutes on CPU because the real minimum flow-through time is retained.
The case does not validate nonzero drag, low-Mach accuracy or GPU execution.
"""

import json
from pathlib import Path
import trimesh, numpy as np
from rocket_workbench.models import Project, Component, GeometryAsset, Conditions
from rocket_workbench.solvers import cfd

mesh = trimesh.creation.box(extents=[0.4, 0.1, 0.1])
asset = GeometryAsset(
    id="steady-reference",
    name="Quiescent exterior box",
    format="stl",
    vertices=mesh.vertices.tolist(),
    faces=mesh.faces.tolist(),
    watertight=True,
    volume=float(mesh.volume),
)
project = Project(
    assets=[asset],
    components=[Component(id="body", asset_id=asset.id, geometry_mode="replacement")],
)
before = project.model_dump(mode="json")
r = cfd.solve(
    project,
    Conditions(speed=0, wind_speed=0),
    options={
        "mode": "steady",
        "physics_model": "euler",
        "spatial_scheme": "muscl_mc",
        "backend": "cpu",
        "grid_resolution": 12,
        "transverse_resolution": 12,
        "max_cells": 30000,
        "sample_limit": 20,
        "surface_limit": 30,
    },
)
s = r["summary"]
assert s["status"] == "converged" and s["time_integrator"] == "ssprk2"
assert s["physical_time_s"] >= s["minimum_convergence_time_s"] and s["steps"] > 20
np.testing.assert_allclose(s["force_n"], 0, atol=1e-12)
np.testing.assert_allclose(s["moment_about_origin_nm"], 0, atol=1e-12)
assert s["residual"] == 0 and not s["source_material_mesh_modified"]
assert project.model_dump(mode="json") == before
Path("build").mkdir(exist_ok=True)
Path("build/quiescent-steady-muscl.json").write_text(
    json.dumps(r, indent=2, allow_nan=False)
)
print(
    json.dumps(
        {
            "status": "passed",
            "reference": "Exact quiescent exterior air; no nonzero drag validation claim",
            "steps": s["steps"],
            "flow_time_s": s["physical_time_s"],
            "source_geometry_unchanged": True,
        }
    )
)
