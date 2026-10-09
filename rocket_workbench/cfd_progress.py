"""Measured CFD integration progress; convergence is never a percentage.

The solver supplies accepted numerical states and integration-only wall time.
Transient ETA estimates the remaining requested physical interval. Steady ETA is
only a tentative extrapolation of a sustained decline in every active residual;
plateaus, growing modes and insufficient observations deliberately return None.
"""
from __future__ import annotations

from collections import deque
import math

import numpy as np


_RESIDUALS = ("residual", "wall_pressure_residual", "force_residual", "moment_residual")


def _finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


class CfdProgress:
    """Keep a small recent measurement window, independent of job startup time."""

    def __init__(self):
        self.observations = deque(maxlen=32)
        self.phase = None
        self.stage = None

    def update(self, event: dict) -> dict:
        result = {
            "eta_seconds": None, "eta_range_seconds": None,
            "eta_basis": None, "eta_confidence": None,
        }
        phase, stage = event.get("phase"), event.get("comparison_stage")
        if stage != self.stage or phase == "voxelization":
            self.observations.clear()
        self.phase, self.stage = phase, stage
        if phase != "integration" or event.get("done"):
            return result
        elapsed = _finite(event.get("integration_elapsed_seconds"))
        physical = _finite(event.get("physical_time_s"))
        steps = _finite(event.get("integration_steps"))
        if elapsed is None or physical is None or steps is None or min(elapsed, physical, steps) < 0:
            return result
        point = (elapsed, physical, steps, tuple(_finite(event.get(name)) for name in _RESIDUALS))
        if self.observations and elapsed <= self.observations[-1][0]:
            return result
        self.observations.append(point)
        if len(self.observations) < 4:
            return result
        points = list(self.observations)
        elapsed_span = points[-1][0] - points[0][0]
        if elapsed_span <= 0:
            return result
        physical_rate = (physical - points[0][1]) / elapsed_span
        step_rate = (steps - points[0][2]) / elapsed_span
        if physical_rate <= 0 or step_rate <= 0 or not math.isfinite(physical_rate) or not math.isfinite(step_rate):
            return result
        result.update(simulated_seconds_per_wall_second=physical_rate,
                      integration_steps_per_wall_second=step_rate,
                      eta_scope="current CFD integration; preparation and field extraction excluded")
        if event.get("mode") == "transient":
            target = _finite(event.get("target_physical_time_s"))
            if target is None or target <= 0:
                return result
            remaining = max(0.0, target - physical)
            rates = [(second[1] - first[1]) / (second[0] - first[0])
                     for first, second in zip(points, points[1:])
                     if second[0] > first[0] and second[1] > first[1]
                     and math.isfinite((second[1] - first[1]) / (second[0] - first[0]))]
            if len(rates) < 3:
                return result
            low_rate, high_rate = np.percentile(rates, [10, 90])
            if low_rate <= 0 or high_rate <= 0:
                return result
            estimate = remaining / physical_rate
            interval = [min(estimate, remaining / float(high_rate)), max(estimate, remaining / float(low_rate))]
            if not all(math.isfinite(value) for value in [estimate, *interval]):
                return result
            result.update(eta_seconds=estimate,
                          eta_range_seconds=interval,
                          eta_basis="physical_time_throughput", eta_confidence="measured")
            return result
        trend_points = [value for value in points
                        if not (value[2] == 0 and any(residual is None for residual in value[3]))]
        if event.get("mode") != "steady" or len(trend_points) < 12:
            return result
        tolerance = _finite(event.get("convergence_tolerance"))
        minimum = _finite(event.get("minimum_convergence_time_s"))
        streak = _finite(event.get("stable_streak"))
        required = _finite(event.get("required_stable_steps"))
        if tolerance is None or tolerance <= 0 or any(value is None for value in (minimum, streak, required)):
            return result
        estimates, lower, upper = [], [], []
        times = np.asarray([value[0] - trend_points[0][0] for value in trend_points])
        centered = times - times.mean()
        sxx = float(np.dot(centered, centered))
        if sxx <= 0:
            return result
        for index in range(len(_RESIDUALS)):
            values = [value[3][index] for value in trend_points]
            if any(value is None or value < 0 for value in values):
                return result
            current = values[-1]
            if current <= tolerance:
                # A residual already below tolerance may consume the required
                # stability streak, but does not need a logarithmic fit.
                continue
            if any(value <= 0 for value in values):
                return result
            logarithms = np.log(values)
            slope = float(np.dot(centered, logarithms - logarithms.mean()) / sxx)
            fitted = logarithms.mean() + slope * centered
            squared_error = float(np.sum((logarithms - fitted) ** 2))
            variation = float(np.sum((logarithms - logarithms.mean()) ** 2))
            quality = 1 - squared_error / variation if variation > 0 else 0
            # The two halves must also decline. A curve that first decays and
            # then stalls must not retain an optimistic whole-window ETA.
            split = len(trend_points) // 2
            slopes = [float(np.polyfit(times[slice_], logarithms[slice_], 1)[0])
                      for slice_ in (slice(None, split), slice(split, None))]
            if slope >= 0 or quality < .9 or max(slopes) >= 0:
                return result
            if min(abs(value) for value in slopes) < .4 * max(abs(value) for value in slopes):
                return result
            standard_error = math.sqrt(squared_error / (len(trend_points) - 2) / sxx)
            slow_decay = -slope - 2 * standard_error
            fast_decay = -slope + 2 * standard_error
            if slow_decay <= 0:
                return result
            distance = math.log(current / tolerance)
            estimates.append(distance / -slope)
            lower.append(distance / fast_decay)
            upper.append(distance / slow_decay)
        minimum_wait = max(0.0, minimum - physical) / physical_rate
        streak_wait = max(0.0, required - streak) / step_rate
        # The minimum physical time and residual decay can overlap. Once the
        # residuals are below tolerance, the consecutive-step test must finish.
        estimate = max([minimum_wait, *estimates]) + streak_wait
        low = max([minimum_wait, *lower]) + streak_wait
        high = max([minimum_wait, *upper]) + streak_wait
        if not all(math.isfinite(value) for value in [estimate, low, high]):
            return result
        result.update(eta_seconds=estimate, eta_range_seconds=[low, high],
                      eta_basis="convergence_trend", eta_confidence="tentative")
        return result
