"""Independent physical-coordinate checks of the display-only CFD field export."""
import json

import numpy as np
import pytest

from rocket_workbench.solvers import cfd


def _interpolate(export, point):
    """Strict reference trilinear interpolation, without assuming solver layout."""
    shape = np.asarray(export["shape"])
    coordinate = (point - np.asarray(export["origin_m"])) / export["spacing_m"]
    if np.any(coordinate < 0) or np.any(coordinate > shape - 1):
        return None
    lower = np.minimum(np.floor(coordinate).astype(int), shape - 2)
    fractions = coordinate - lower
    mask = np.asarray(export["fluid_mask"]).reshape(tuple(shape))
    values = np.asarray(export["velocity_m_s"]).reshape(tuple(shape) + (3,))
    result = np.zeros(3)
    for i in (0, 1):
        for j in (0, 1):
            for k in (0, 1):
                delta = np.array([i, j, k])
                weight = np.prod(np.where(delta, fractions, 1 - fractions))
                if weight <= 1e-15:
                    continue
                index = tuple(lower + delta)
                if not mask[index]:
                    return None
                result += values[index] * weight
    return result


@pytest.mark.parametrize("max_nodes", [100_000, 125])
def test_export_preserves_uniform_oblique_flow_in_physical_coordinates(max_nodes):
    spacing = np.array([0.031, 0.013, 0.007])
    origin = np.array([-0.21, 0.09, -0.04])
    shape = (13, 11, 9)
    expected = np.array([650.0, 30.0, -15.0])
    state = np.broadcast_to(cfd.conserved(1.2, expected, 101325), shape + (5,)).copy()
    solid = np.zeros(shape, dtype=bool)
    # Use the genuinely advanced Euler field, rather than a synthetic renderer.
    for _ in range(3):
        dt = cfd.stable_timestep(state, solid, spacing)
        state = cfd.finite_volume_step(state, solid, spacing, dt, state[0, 0, 0])
    _, velocity, _, _ = cfd.primitives(state)
    export = cfd._flow_grid(velocity, solid, spacing, origin, max_nodes)
    assert export["node_count"] <= max_nodes
    point = origin + np.array(export["spacing_m"]) * [1.35, 1.7, 1.2]
    np.testing.assert_allclose(_interpolate(export, point), expected, atol=2e-13)
    # Original conserved state and velocity must remain untouched by extraction.
    np.testing.assert_array_equal(velocity, np.broadcast_to(expected, velocity.shape))
    assert _interpolate(export, origin - spacing) is None
    json.dumps(export, allow_nan=False)


def test_regular_sampling_reconstructs_affine_velocity_with_correct_axes_and_units():
    shape = (15, 12, 10)
    spacing = np.array([0.12, 0.017, 0.009])
    origin = np.array([-0.8, -0.06, 0.15])
    coordinates = np.moveaxis(np.indices(shape), 0, -1) * spacing + origin
    gradient = np.array([[2, 3, 5], [-7, 11, 13], [17, -19, 23]])
    offset = np.array([100, 20, -30])
    velocity = coordinates @ gradient.T + offset
    export = cfd._flow_grid(velocity, np.zeros(shape, dtype=bool), spacing, origin, 240)
    point = origin + np.asarray(export["spacing_m"]) * [1.3, 2.2, 1.6]
    np.testing.assert_allclose(_interpolate(export, point), gradient @ point + offset, atol=3e-14)


def test_thin_unsampled_wall_stops_streamlines_without_changing_source_field():
    shape = (13, 11, 9)
    velocity = np.broadcast_to([100.0, 0, 0], shape + (3,)).copy()
    solid = np.zeros(shape, dtype=bool)
    solid[3, :, :] = True  # One-cell wall missed by ordinary stride-two sampling.
    before_velocity, before_solid = velocity.copy(), solid.copy()
    spacing = np.array([0.025, 0.014, 0.011])
    origin = np.array([-0.1, 0, 0])
    export = cfd._flow_grid(velocity, solid, spacing, origin, 240)
    assert export["stride"] == 2
    # Independent ray marching in metres must stop before the physical barrier.
    point = origin + [0, 0.052, 0.041]
    stopped = False
    for _ in range(60):
        current = _interpolate(export, point)
        if current is None:
            stopped = True
            break
        point += current / np.linalg.norm(current) * 0.002
    assert stopped and point[0] <= origin[0] + 3 * spacing[0]
    np.testing.assert_array_equal(velocity, before_velocity)
    np.testing.assert_array_equal(solid, before_solid)


def test_sealed_cavity_has_no_exported_flow_nodes_or_reconstructed_passage():
    surface = np.zeros((15, 15, 15), dtype=bool)
    surface[3:12, 3:12, 3:12] = True
    surface[4:11, 4:11, 4:11] = False
    solid = cfd._exterior_flow_mask(surface)
    velocity = np.broadcast_to([25.0, 0, 0], surface.shape + (3,)).copy()
    export = cfd._flow_grid(velocity, solid, np.ones(3), np.zeros(3), 800)
    assert not export["fluid_mask"][((3 * export["shape"][1] + 3) * export["shape"][2] + 3)]
    assert _interpolate(export, np.array([7.0, 7.0, 7.0])) is None
    assert _interpolate(export, np.array([0.0, 1.0, 1.0])) is not None
    # Source shell/cavity distinction belongs to source CAD; extraction is read-only.
    assert not surface[7, 7, 7] and solid[7, 7, 7]


def test_large_field_has_bounded_payload_and_never_reports_display_as_solver_resolution():
    shape = (170, 110, 107)
    velocity = np.broadcast_to([500.0, 2.0, -3.0], shape + (3,))
    export = cfd._flow_grid(velocity, np.zeros(shape, dtype=bool), [0.02, 0.005, 0.004], [0, 0, 0])
    assert export["node_count"] <= 100_000
    assert export["solver_shape"] == list(shape)
    assert export["shape"] != export["solver_shape"]
    assert export["visualization_only"]
    assert len(export["velocity_m_s"]) == 3 * export["node_count"]
    assert len(export["fluid_mask"]) == export["node_count"]
    assert len(json.dumps(export, allow_nan=False)) < 8_000_000


def test_partial_solve_exports_actual_field_with_original_fidelity_and_masks(monkeypatch):
    import trimesh
    import rocket_workbench.geometry as geometry
    from rocket_workbench.models import Conditions, Project

    monkeypatch.setattr(geometry, "project_mesh", lambda *args, **kwargs: trimesh.creation.box(extents=[0.1] * 3))
    calls = 0
    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 2
    result = cfd.solve(Project(), Conditions(mach=0.4, wind_speed=0), options={
        "grid_resolution": 12, "transverse_resolution": 12,
        "backend": "cpu", "sample_limit": 20, "surface_limit": 1,
    }, cancelled=cancelled)
    export = result["flow_grid"]
    assert export["stride"] == 1
    assert export["solver_shape"] == result["summary"]["grid_shape"]
    assert np.sum(export["fluid_mask"]) == result["summary"]["fluid_cells"]
    for sample in result["samples"]:
        # Same solved field at physically coincident nodes, independent of ordering.
        np.testing.assert_allclose(_interpolate(export, np.array(sample["position"])), sample["velocity"], atol=3e-12)
    assert not result["summary"]["converged"]
    assert result["fidelity"] == cfd.FIDELITY
    assert not result["summary"]["source_material_mesh_modified"]
