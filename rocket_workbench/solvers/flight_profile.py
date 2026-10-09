"""Immutable, one-way launch-history boundary inputs for transient Euler CFD.

These are prescribed body-equivalent farfield conditions on fixed geometry, not
moving-vehicle CFD. The point-mass flight model has no resolved attitude or roll;
its stated rail/gravity-turn nose-axis assumption supplies a coordinate basis.
No rotating-frame or acceleration source is inferred from that assumption.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rocket_workbench.solvers import aero

_GAMMA = 1.4
_MAX_MACH = 2.05
_VECTOR_EPS = 1e-10


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Flight history {name} must be finite.") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"Flight history {name} must be {'positive and ' if positive else ''}finite.")
    return result


def _vector(value: Any, name: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Flight history {name} must be a finite three-component vector.") from exc
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"Flight history {name} must be a finite three-component vector.")
    return result.copy()


def _basis(nose_axis: np.ndarray) -> np.ndarray:
    """Right-handed body axes: +X tailward, +Y projected world east.

    A world-north reference is used when east is parallel to the tail axis.
    This is a declared display/flow convention, not measured vehicle roll.
    """
    tail = -nose_axis / np.linalg.norm(nose_axis)
    east = np.array([1.0, 0.0, 0.0])
    lateral = east - np.dot(east, tail) * tail
    if np.linalg.norm(lateral) < 1e-8:
        north = np.array([0.0, 1.0, 0.0])
        lateral = north - np.dot(north, tail) * tail
    lateral /= np.linalg.norm(lateral)
    return np.stack((tail, lateral, np.cross(tail, lateral)))


def _segment_mach_extrema(v0, v1, rho0, rho1, p0, p1):
    """Exact minimum/maximum of interpolated Mach on one segment.

    The numerator is cubic and pressure linear. Stationary points are roots of
    N' p - N p'; checking those and the endpoints avoids missing an interior
    extremum when velocity and the atmospheric state vary simultaneously.
    """
    difference = v1 - v0
    speed_squared = np.array([np.dot(v0, v0), 2 * np.dot(v0, difference), np.dot(difference, difference)])
    numerator = np.polynomial.polynomial.polymul(speed_squared, [rho0, rho1 - rho0])
    pressure = np.array([p0, p1 - p0])
    derivative = np.polynomial.polynomial.polysub(
        np.polynomial.polynomial.polymul(np.polynomial.polynomial.polyder(numerator), pressure),
        numerator * pressure[1],
    )
    candidates = [0.0, 1.0]
    if np.any(derivative):
        for root in np.polynomial.polynomial.polyroots(derivative):
            if abs(root.imag) <= 1e-9 and 0 < root.real < 1:
                candidates.append(float(root.real))
    squared_machs = [np.polynomial.polynomial.polyval(fraction, numerator) /
                     (_GAMMA * np.polynomial.polynomial.polyval(fraction, pressure)) for fraction in candidates]
    return (math.sqrt(max(0.0, float(min(squared_machs)))),
            math.sqrt(max(0.0, float(max(squared_machs)))))


def _segment_peak_mach(v0, v1, rho0, rho1, p0, p1):
    """Maximum incoming Mach, including interior interpolation extrema."""
    return _segment_mach_extrema(v0, v1, rho0, rho1, p0, p1)[1]


@dataclass(frozen=True)
class FlightFreestreamProfile:
    start_s: float
    end_s: float
    metadata: dict
    warnings: tuple[str, ...]
    _times: np.ndarray = field(repr=False)
    _relative: np.ndarray = field(repr=False)
    _axes: np.ndarray = field(repr=False)
    _axis_fallbacks: np.ndarray = field(repr=False)
    _rho: np.ndarray = field(repr=False)
    _pressure: np.ndarray = field(repr=False)
    _altitude: np.ndarray = field(repr=False)
    _temperature: np.ndarray = field(repr=False)
    _trajectory: tuple[dict, ...] = field(repr=False)

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def __call__(self, elapsed_s: float) -> dict:
        elapsed = _number(elapsed_s, "CFD elapsed time")
        tolerance = 1e-9 * max(1.0, self.duration_s)
        if elapsed < -tolerance or elapsed > self.duration_s + tolerance:
            raise ValueError("CFD physical time lies outside the selected launch-history interval.")
        flight_time = self.start_s + min(self.duration_s, max(0.0, elapsed))
        i = min(len(self._times) - 2, max(0, int(np.searchsorted(self._times, flight_time, side="right") - 1)))
        fraction = (flight_time - self._times[i]) / (self._times[i + 1] - self._times[i])
        relative = self._relative[i] + fraction * (self._relative[i + 1] - self._relative[i])
        axis = self._axes[i] + fraction * (self._axes[i + 1] - self._axes[i])
        if np.linalg.norm(axis) < _VECTOR_EPS:
            # Opposite gravity-turn axes can meet at apogee. There is no attitude
            # solution to interpolate; choose the nearest documented sample.
            axis = self._axis_fallbacks[i if fraction <= 0.5 else i + 1]
        velocity = _basis(axis) @ -relative
        rho = float(self._rho[i] + fraction * (self._rho[i + 1] - self._rho[i]))
        pressure = float(self._pressure[i] + fraction * (self._pressure[i + 1] - self._pressure[i]))
        speed = float(np.linalg.norm(relative))
        mach = speed / math.sqrt(_GAMMA * pressure / rho)
        if mach > _MAX_MACH + 1e-12:
            raise ValueError("Selected launch history exceeds the supported CFD Mach 2 range (maximum incoming Mach 2.05); no speed was clamped.")
        return {
            "density_kg_m3": rho,
            "pressure_pa": pressure,
            "velocity_m_s": velocity.tolist(),
            "altitude_msl_m": float(self._altitude[i] + fraction * (self._altitude[i + 1] - self._altitude[i])),
            "flight_time_s": float(flight_time),
            "freestream_mach": mach,
            "dynamic_pressure_pa": 0.5 * rho * speed * speed,
            "air_relative_speed_m_s": speed,
            "temperature_k": float(self._temperature[i] + fraction * (self._temperature[i + 1] - self._temperature[i])),
            "velocity_world_minus_wind_m_s": relative.tolist(),
            "body_axis_world": (axis / np.linalg.norm(axis)).tolist(),
        }

    def to_dict(self) -> dict:
        """Self-contained selected boundary inputs; no fluid fields fabricated."""
        return {
            "schema_version": 1,
            "trajectory": copy.deepcopy(list(self._trajectory)),
            "metadata": copy.deepcopy(self.metadata),
            "warnings": list(self.warnings),
            "conventions": {
                "body_axis_world": "Assumed nose-directed rail/gravity-turn axis, not resolved attitude.",
                "air_relative_velocity_vector": "World vehicle velocity minus world wind; east, north, up.",
            },
        }


def build_flight_profile(
    result: dict,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
    temperature_delta: float = 0.0,
) -> FlightFreestreamProfile:
    """Copy actual flight history and select a physical-time CFD interval.

    Geometry/configuration/source matching belongs to the job coordinator. This
    adapter validates the scientific history and never changes/clamps airspeed.
    Linear interpolation applies to the *flight inputs*, not CFD solution fields.
    """
    rows = result.get("trajectory")
    if not isinstance(rows, list) or len(rows) < 2 or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Launch-driven CFD requires at least two actual computed trajectory states.")
    times = np.array([_number(row.get("time"), "time") for row in rows])
    if np.any(np.diff(times) <= 0):
        raise ValueError("Flight history times must be strictly increasing.")
    start = float(times[0]) if start_s is None else _number(start_s, "interval start")
    end = float(times[-1]) if end_s is None else _number(end_s, "interval end")
    if start < times[0] or end > times[-1] or end <= start:
        raise ValueError("Select a positive launch interval entirely inside the computed flight history.")
    temperature_delta = _number(temperature_delta, "temperature offset")
    first = max(0, int(np.searchsorted(times, start, side="right") - 1))
    last = min(len(times) - 1, int(np.searchsorted(times, end, side="left")))
    if last <= first:
        last = first + 1
    selected = rows[first:last + 1]
    selected_times = times[first:last + 1]
    warnings = [
        "Launch-driven transient CFD uses actual computed air-relative velocity and atmospheric history as prescribed farfield on fixed rocket geometry; it is one-way coupling, not a moving-vehicle CFD trajectory or a feedback flight solution.",
        "The point-mass rail/gravity-turn nose-axis assumption supplies a body-equivalent airflow convention. Vehicle attitude, roll, moving mesh, rotating/accelerating-frame forces and weathercocking are not resolved.",
        "Flight-history inputs are linearly interpolated between actual computed states. CFD fluid fields still advance through their actual CFL-limited physical time; no flight-time acceleration or independent steady snapshots are substituted.",
    ]
    # Older saved results did not export an axis. Infer the original model's
    # rail direction from its first nonzero velocity, rather than assuming that
    # an inclined rail was vertical. New runs export the model axis explicitly.
    legacy_axis = next((
        vector / np.linalg.norm(vector)
        for row in rows
        if row.get("velocity_vector") is not None
        for vector in [_vector(row["velocity_vector"], "velocity_vector")]
        if np.linalg.norm(vector) > _VECTOR_EPS
    ), np.array([0.0, 0.0, 1.0]))
    previous_axis = legacy_axis
    # A window can start at a zero-velocity apogee state in an older file.
    # Reconstruct the last preceding gravity-turn axis, rather than resetting
    # that state to the original rail merely because preceding rows are omitted.
    for row in reversed(rows[:first]):
        if row.get("body_axis_world") is not None:
            candidate = _vector(row["body_axis_world"], "body_axis_world")
        else:
            candidate = _vector(row.get("velocity_vector"), "velocity_vector")
        if np.linalg.norm(candidate) > _VECTOR_EPS:
            previous_axis = candidate / np.linalg.norm(candidate)
            break
    vectors, axes, axis_fallbacks, densities, pressures, altitudes, temperatures, normalized = [], [], [], [], [], [], [], []
    atmosphere_from_rows = True
    axis_from_rows = True
    for row in selected:
        velocity = _vector(row.get("velocity_vector"), "velocity_vector")
        wind = _vector(row.get("wind_vector"), "wind_vector")
        relative = velocity - wind
        if row.get("air_relative_velocity_vector") is not None:
            supplied = _vector(row["air_relative_velocity_vector"], "air_relative_velocity_vector")
            if not np.allclose(supplied, relative, atol=1e-7, rtol=1e-7):
                raise ValueError("Flight history air-relative velocity disagrees with vehicle velocity minus wind.")
            relative = supplied
        if row.get("air_relative_speed") is not None:
            supplied_speed = _number(row["air_relative_speed"], "air_relative_speed")
            if not math.isclose(supplied_speed, float(np.linalg.norm(relative)), rel_tol=1e-7, abs_tol=1e-7):
                raise ValueError("Flight history air-relative speed disagrees with its actual velocity and wind vectors.")
        axis = _vector(row["body_axis_world"], "body_axis_world") if row.get("body_axis_world") is not None else (
            velocity / np.linalg.norm(velocity) if np.linalg.norm(velocity) > _VECTOR_EPS else previous_axis
        )
        axis_from_rows &= row.get("body_axis_world") is not None
        if np.linalg.norm(axis) < _VECTOR_EPS:
            raise ValueError("Flight history body_axis_world must have nonzero length.")
        axis /= np.linalg.norm(axis)
        previous_axis = axis.copy()
        if row.get("body_axis_interpolation_vector_world") is not None:
            interpolation_axis = _vector(row["body_axis_interpolation_vector_world"], "body_axis_interpolation_vector_world")
            interpolation_length = float(np.linalg.norm(interpolation_axis))
            if interpolation_length >= _VECTOR_EPS and not np.allclose(interpolation_axis / interpolation_length, axis, atol=1e-7, rtol=1e-7):
                raise ValueError("Flight history axis interpolation vector must have the declared body-axis direction.")
            # A clipped window endpoint lies inside the original unit-axis
            # interpolation. Retaining its pre-normalization length preserves
            # exactly the same direction at common whole/window flight times.
            axis = interpolation_axis
        altitude = _number(row.get("altitude_msl"), "altitude_msl")
        if not -500 <= altitude <= 50_000:
            raise ValueError("Selected launch history exceeds the atmospheric model's -500 to 50,000 m MSL range.")
        exported_atmosphere = all(row.get(key) is not None for key in ("density_kg_m3", "pressure_pa", "temperature_k"))
        atmosphere_from_rows &= exported_atmosphere
        atmosphere = row if exported_atmosphere else aero.atmosphere(altitude, temperature_delta)
        rho = _number(atmosphere["density_kg_m3"], "density_kg_m3", positive=True)
        pressure = _number(atmosphere["pressure_pa"], "pressure_pa", positive=True)
        temperature = _number(atmosphere["temperature_k"], "temperature_k", positive=True)
        vectors.append(relative)
        axes.append(axis)
        axis_fallbacks.append(previous_axis)
        densities.append(rho)
        pressures.append(pressure)
        altitudes.append(altitude)
        temperatures.append(temperature)
        normalized.append({
            "time": _number(row["time"], "time"), "altitude_msl": altitude,
            "velocity_vector": velocity.tolist(), "wind_vector": wind.tolist(),
            "air_relative_velocity_vector": relative.tolist(),
            "air_relative_speed": float(np.linalg.norm(relative)), "body_axis_world": previous_axis.tolist(),
            "body_axis_interpolation_vector_world": axis.tolist(),
            "density_kg_m3": rho, "pressure_pa": pressure, "temperature_k": temperature,
            "phase": str(row.get("phase", "unknown")),
        })
    vectors, axes, axis_fallbacks = np.asarray(vectors), np.asarray(axes), np.asarray(axis_fallbacks)
    densities, pressures = np.asarray(densities), np.asarray(pressures)
    altitudes, temperatures = np.asarray(altitudes), np.asarray(temperatures)
    # Exact window endpoints are copied/interpolated flight inputs; data outside
    # the window is not exported or used to reject a Mach-limited valid interval.
    final_times = np.unique(np.r_[start, selected_times[(selected_times > start) & (selected_times < end)], end])
    interpolate_vector = lambda values: np.column_stack([np.interp(final_times, selected_times, values[:, axis]) for axis in range(3)])
    final_vectors = interpolate_vector(vectors)
    final_axes = interpolate_vector(axes)
    final_axis_fallbacks = np.zeros_like(final_axes)
    for i, axis in enumerate(final_axes):
        if np.linalg.norm(axis) < _VECTOR_EPS:
            j = int(np.argmin(np.abs(selected_times - final_times[i])))
            final_axis_fallbacks[i] = axis_fallbacks[j]
        else:
            final_axis_fallbacks[i] = axis / np.linalg.norm(axis)
    final_rho = np.interp(final_times, selected_times, densities)
    final_pressure = np.interp(final_times, selected_times, pressures)
    final_altitude = np.interp(final_times, selected_times, altitudes)
    final_temperature = np.interp(final_times, selected_times, temperatures)
    final_ground = interpolate_vector(np.asarray([row["velocity_vector"] for row in normalized]))
    final_wind = interpolate_vector(np.asarray([row["wind_vector"] for row in normalized]))
    snapshot = []
    for i, at_time in enumerate(final_times):
        row_index = min(len(normalized) - 1, max(0, int(np.searchsorted(selected_times, at_time, side="right") - 1)))
        snapshot.append({
            "time": float(at_time), "altitude_msl": float(final_altitude[i]),
            "velocity_vector": final_ground[i].tolist(), "wind_vector": final_wind[i].tolist(),
            "air_relative_velocity_vector": final_vectors[i].tolist(),
            "air_relative_speed": float(np.linalg.norm(final_vectors[i])),
            "body_axis_world": final_axis_fallbacks[i].tolist(),
            "body_axis_interpolation_vector_world": final_axes[i].tolist(), "density_kg_m3": float(final_rho[i]),
            "pressure_pa": float(final_pressure[i]), "temperature_k": float(final_temperature[i]),
            "phase": normalized[row_index]["phase"],
        })
    mach_extrema = [_segment_mach_extrema(final_vectors[i], final_vectors[i + 1], final_rho[i], final_rho[i + 1],
                                        final_pressure[i], final_pressure[i + 1]) for i in range(len(final_times) - 1)]
    min_mach = min(extrema[0] for extrema in mach_extrema)
    max_mach = max(extrema[1] for extrema in mach_extrema)
    if max_mach > _MAX_MACH + 1e-12:
        raise ValueError(f"Selected launch history reaches incoming Mach {max_mach:.3f}, above the supported CFD Mach 2 range (maximum 2.05); choose another interval. No speed was clamped.")
    if min_mach < 0.3:
        warnings.append("The selected launch interval includes incoming Mach below 0.3, including any zero-airspeed startup. This acoustic-speed Rusanov scheme has no all-speed preconditioning; numerical dissipation can dominate physical pressure differences and pressure drag is especially unreliable in those portions of the flight.")
    if not atmosphere_from_rows:
        warnings.append("Older flight history did not export a complete atmospheric state; its actual altitude and original temperature offset reconstruct the documented standard atmosphere.")
    if not axis_from_rows:
        warnings.append("Older flight history did not export a body axis; the original rail/gravity-turn model convention is reconstructed from actual ground velocity. This does not establish resolved attitude.")
    if any(row["phase"] in {"drogue", "main", "landed"} for row in snapshot):
        warnings.append("The selected interval includes recovery. CFD retains rigid rocket geometry and does not add parachutes, separated sections, inflation or opening-shock flow; recovered trajectory inputs do not make those aerodynamic loads resolved.")
    if result.get("summary", {}).get("complete") is False:
        warnings.append("The source flight trajectory is incomplete; this CFD profile uses only the available computed history and does not extrapolate it to landing.")
    if any(np.dot(final_axis_fallbacks[i], final_axis_fallbacks[i + 1]) < -0.9 for i in range(len(final_axes) - 1)):
        warnings.append("The assumed gravity-turn nose axis reverses near zero velocity; that coordinate change is not a resolved physical rotation. Inspect a pre-apogee interval for ascent-focused CFD.")
    profile_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    events = [copy.deepcopy(event) for event in result.get("events", [])
              if isinstance(event, dict) and isinstance(event.get("time"), (int, float)) and start <= event["time"] <= end]
    metadata = {
        "source": "computed_launch_history", "start_s": start, "end_s": end, "duration_s": end - start,
        "source_sample_count": len(rows), "profile_sample_count": len(snapshot), "profile_sha256": profile_hash,
        "min_incoming_mach": min_mach, "max_incoming_mach": max_mach,
        "source_flight_fidelity": str(result.get("fidelity", "Computed point-mass flight history")),
        "source_flight_complete": result.get("summary", {}).get("complete"), "events": events,
        "atmosphere_basis": "actual exported computed atmospheric state" if atmosphere_from_rows else "computed altitude plus original temperature offset; standard atmosphere fallback for older rows",
        "interpolation": "Piecewise linear actual flight vectors, pre-normalized axis interpolation vectors and atmospheric inputs; exact selected endpoints. Axis normalized only when constructing the body basis. No extrapolation and no CFD-field interpolation.",
        "coordinate_frame": "+X nose-to-tail; +Y world-east projected transverse to assumed nose axis (north fallback when parallel); +Z right-handed cross product. Unresolved roll.",
        "coupling": "One-way prescribed body-equivalent farfield on fixed geometry; no moving/rotating/accelerating frame, canopy geometry or flight-feedback coupling.",
    }
    for array in (final_times, final_vectors, final_axes, final_axis_fallbacks, final_rho, final_pressure, final_altitude, final_temperature):
        array.setflags(write=False)
    return FlightFreestreamProfile(start, end, metadata, tuple(dict.fromkeys(warnings)), final_times,
                                  final_vectors, final_axes, final_axis_fallbacks, final_rho, final_pressure, final_altitude,
                                  final_temperature, tuple(snapshot))
