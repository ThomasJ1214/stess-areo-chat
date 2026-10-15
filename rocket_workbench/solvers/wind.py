"""Deterministic, causal wind inputs for adaptive flight integration.

The optional Dryden model uses exactly discretized stationary linear stochastic
filters. It is a temporal gust surrogate with user-specified intensity and scale,
not a spatial weather field, CFD turbulence, or automatic MIL-standard atmosphere.
Queries never advance a random generator: rejected integrator steps and replay
cannot change the wind realization. Scheduled environmental changes are causal.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter


def dryden_transition(rate: float, interval: float):
    """Exact lateral Dryden state transition and process covariance.

    State A=a*[[-1,0],[1,-1]], B=[sqrt(a),0], output
    sqrt(3)*x1+(1-sqrt(3))*x2 has stationary variance one. P is
    [[1/2,1/4],[1/4,1/4]]. Q integrates exp(A t) B B' exp(A' t).
    Series evaluation avoids subtracting equal numbers at small a*dt.
    """
    if not math.isfinite(rate) or not math.isfinite(interval) or min(rate, interval) <= 0:
        raise ValueError("Dryden filter rate and sample interval must be positive and finite.")
    x = rate * interval
    if x > 350:
        # Correlation is below 1e-149; avoid inf*0 in the exact formulas.
        return np.zeros((2, 2)), np.array([[0.5, 0.25], [0.25, 0.25]])
    if x < 1e-100:
        raise ValueError("Dryden filter correlation scale is below the supported floating-point resolution. Choose a finite resolvable transport speed and length scale.")
    f = math.exp(-x)
    transition = f * np.array([[1.0, 0.0], [x, 1.0]])
    if x < 0.01:
        # Integral_0^x y^n exp(-2y) dy, n=0,1,2.
        integrals = []
        for degree in range(3):
            value, coefficient = 0.0, 1.0
            for order in range(16):
                value += coefficient * x ** (degree + order + 1) / (degree + order + 1)
                coefficient *= -2.0 / (order + 1)
            integrals.append(value)
        q11, q12, q22 = integrals
    else:
        f2 = f * f
        q11 = -0.5 * math.expm1(-2 * x)
        q12 = (1 - (1 + 2 * x) * f2) / 4
        q22 = (1 - (1 + 2 * x + 2 * x * x) * f2) / 4
    covariance = np.array([[q11, q12], [q12, q22]])
    return transition, covariance


class WindField:
    def __init__(self, conditions):
        self.conditions = conditions
        self.model = getattr(conditions, "wind_model", "legacy_gust")
        self._events = list(getattr(conditions, "wind_events", []))
        self.event_times = sorted(set(
            value for event in self._events
            for value in (float(event.time_s), float(event.time_s + event.transition_s))
            if value <= conditions.max_time
        ))
        self._phase = np.random.default_rng(conditions.seed).uniform(0, 2 * math.pi, (3, 3))
        self._frequency = np.array([0.23, 0.71, 1.9])
        self._interval = getattr(conditions, "turbulence_sample_interval_s", 0.02)
        self._scale = getattr(conditions, "turbulence_length_scale_m", 50.0)
        supplied_speed = getattr(conditions, "turbulence_transport_speed_m_s", None)
        self._transport = float(supplied_speed if supplied_speed is not None else max(1.0, conditions.wind_speed))
        self._shear = getattr(conditions, "wind_shear_exponent", 0.0)
        self._reference_height = getattr(conditions, "wind_reference_height_m", 10.0)
        self._samples = None
        self.warnings = []
        if self.model not in {"legacy_gust", "dryden"}:
            raise ValueError("Wind model must be legacy_gust or dryden.")
        if self.model == "dryden":
            if (not all(math.isfinite(v) and v > 0 for v in
                        (self._interval, self._scale, self._transport))):
                raise ValueError("Dryden interval, length scale and transport speed must be positive and finite.")
            count = math.ceil(conditions.max_time / self._interval) + 2
            if count > 1_000_001:
                raise ValueError("Dryden wind table exceeds 1,000,001 samples. Increase the sample interval or reduce maximum flight time.")
            self._samples = self._dryden_samples(count, conditions.seed)
            self.warnings.append("Dryden gusts are a seeded temporal, spatially homogeneous surrogate with user-defined equal-axis RMS and length scale. They do not resolve eddies, measured weather, terrain, or the flight-path-dependent encounter spectrum.")
            self.warnings.append("Dryden filter states are exact at fixed sample times; flight queries linearly interpolate them. Sample spacing sets the highest retained gust frequencies; compare smaller intervals for sensitivity.")
        elif conditions.turbulence or any(event.turbulence for event in self._events):
            self.warnings.append("Legacy turbulence is a seeded sinusoidal gust surrogate, not a Dryden/von Karman atmosphere or resolved fluid turbulence.")
        if self._shear:
            self.warnings.append("Wind shear uses a user-assumed power law versus height above the launch plane; terrain and boundary-layer weather are not solved.")
        if self._events:
            self.warnings.append("Scheduled wind/air changes are prescribed inputs. Speed, direction vector, turbulence RMS and optional temperature offset transition over the declared duration; they do not alter physical history before their timestamps.")
        self.metadata = {
            "model": self.model, "seed": conditions.seed, "axis_order": "east, north, up",
            "spatial_model": "homogeneous temporal surrogate; optional height power law",
            "wind_reference_height_m": self._reference_height, "wind_shear_exponent": self._shear,
            "events": [event.model_dump(mode="json") for event in self._events],
            "dryden": None if self.model != "dryden" else {
                "length_scale_m": self._scale, "transport_speed_m_s": self._transport,
                "transport_speed_source": "user supplied" if supplied_speed is not None else "max(reference mean wind speed, 1 m/s); fixed for the realization",
                "sample_interval_s": self._interval,
                "component_rms_m_s": max(1.0, conditions.wind_speed) * conditions.turbulence,
                "rms_definition": "stationary ensemble RMS per axis at reference height; finite runs and interpolated samples can differ",
                "longitudinal_filter": "sqrt(2a)/(s+a)",
                "lateral_vertical_filter": "sqrt(a)*(sqrt(3)*s+a)/(s+a)^2",
                "filter_axis_convention": "longitudinal along baseline horizontal mean wind; lateral horizontal perpendicular; vertical up",
                "parameterization": "user-defined equal-axis scale/intensity; not automatic MIL-F-8785C/MIL-HDBK-1797 weather parameter selection",
                "discretization": "exact stationary stochastic state transition, linear query interpolation",
            },
        }

    def _dryden_samples(self, count, seed):
        rate = self._transport / self._scale
        transition, covariance = dryden_transition(rate, self._interval)
        f = float(transition[0, 0])
        streams = np.random.SeedSequence(seed).spawn(3)
        result = np.empty((count, 3))
        rng = np.random.default_rng(streams[0])
        result[0, 0] = rng.standard_normal()
        noise = rng.standard_normal(count - 1) * math.sqrt(-math.expm1(-2 * rate * self._interval))
        result[1:, 0] = lfilter([1.0], [1.0, -f], noise, zi=[f * result[0, 0]])[0]
        stationary = np.array([[0.5, 0.25], [0.25, 0.25]])
        root = np.linalg.cholesky(covariance)
        initial_root = np.linalg.cholesky(stationary)
        output = np.array([math.sqrt(3), 1 - math.sqrt(3)])
        for axis in (1, 2):
            rng = np.random.default_rng(streams[axis])
            initial = initial_root @ rng.standard_normal(2)
            increments = rng.standard_normal((count - 1, 2)) @ root.T
            first = np.r_[initial[0], lfilter([1.0], [1.0, -f], increments[:, 0], zi=[f * initial[0]])[0]]
            second = np.r_[initial[1], lfilter([1.0], [1.0, -f],
                transition[1, 0] * first[:-1] + increments[:, 1], zi=[f * initial[1]])[0]]
            result[:, axis] = output[0] * first + output[1] * second
        return result

    @staticmethod
    def _mean(speed, direction):
        angle = math.radians(direction)
        return np.array([speed * math.sin(angle), speed * math.cos(angle), 0.0])

    def _environment(self, time):
        mean = self._mean(self.conditions.wind_speed, self.conditions.wind_direction)
        sigma = max(1.0, self.conditions.wind_speed) * self.conditions.turbulence
        temperature = self.conditions.temperature_delta
        for event in self._events:
            if time < event.time_s:
                break
            fraction = 1.0 if event.transition_s == 0 else min(1.0, (time - event.time_s) / event.transition_s)
            mean = mean + fraction * (self._mean(event.wind_speed, event.wind_direction) - mean)
            target_sigma = max(1.0, event.wind_speed) * event.turbulence
            sigma += fraction * (target_sigma - sigma)
            if event.temperature_delta is not None:
                temperature += fraction * (event.temperature_delta - temperature)
        return mean, sigma, temperature

    def temperature_delta(self, time):
        return float(self._environment(float(time))[2])

    def velocity(self, time, altitude_agl=0.0, position=None):
        time, altitude = float(time), float(altitude_agl)
        if not math.isfinite(time) or not math.isfinite(altitude) or time < -1e-10 or time > self.conditions.max_time + 1e-8:
            raise ValueError("Wind query must use finite height and time inside the configured flight interval.")
        time = max(0.0, min(self.conditions.max_time, time))
        mean, sigma, _ = self._environment(time)
        if self.model == "legacy_gust":
            gust = sigma / math.sqrt(3) * np.sin(2 * math.pi * self._frequency[None, :] * time + self._phase).sum(axis=1)
        else:
            coordinate = time / self._interval
            index = min(len(self._samples) - 2, int(coordinate))
            fraction = coordinate - index
            sample = self._samples[index] + fraction * (self._samples[index + 1] - self._samples[index])
            # Fix the stochastic basis to the initial wind heading: later wind
            # changes never rotate the history that precedes their event.
            heading = math.radians(self.conditions.wind_direction)
            along = np.array([math.sin(heading), math.cos(heading), 0.0])
            across = np.array([math.cos(heading), -math.sin(heading), 0.0])
            gust = sigma * (sample[0] * along + sample[1] * across + np.array([0.0, 0.0, sample[2]]))
        shear = (max(0.0, altitude) / self._reference_height) ** self._shear if self._shear else 1.0
        return shear * (mean + gust)
