"""Hazard scenarios.

Two STRICTLY separated layers (requirement 6):

  GroundTruth  — what actually happens. Only the simulation engine reads it to
                 close links and accrue exposure.
  Forecast     — what the AV controller is allowed to see. A perturbed estimate
                 of front arrival times (lead time, spatial + speed error, safety
                 margin). The controller must query ONLY this object unless the
                 experiment sets perfect_information: true.

Exposure semantics: a point is "exposed" once the fire front has reached it
(arrival_time <= t). Exposure is a hazard-CONTACT indicator, NOT injury or death
(requirement 6). Casualty modeling is out of scope and must not be inferred.

Front model (radial_front): an anisotropic expanding front from an ignition
point. Spread speed depends on bearing relative to the wind-pushed direction
(faster downwind via `anisotropy`). Arrival time at a point = geodesic distance
(equirectangular approx) divided by the bearing-dependent speed.
"""
from __future__ import annotations

import math

import numpy as np


def _meters_offset(lon0, lat0, lon, lat):
    """Equirectangular local offset (east, north) in meters from (lon0,lat0)."""
    coslat = math.cos(math.radians(lat0))
    east = math.radians(lon - lon0) * 6_371_000.0 * coslat
    north = math.radians(lat - lat0) * 6_371_000.0
    return east, north


class GroundTruthHazard:
    def __init__(self, scenario: dict):
        self.cfg = scenario
        self.model = scenario.get("spread", {}).get("model", "radial_front")
        self.detection_time_s = float(scenario.get("detection_time_s", 0.0))
        em = scenario.get("exposure_metric", {})
        self.exposure_radius_m = float(em.get("exposure_radius_m", 150.0))

        if self.model == "radial_front":
            ig = scenario["ignition"]
            self.ig_lon, self.ig_lat = ig["lon"], ig["lat"]
            sp = scenario["spread"]
            self.base_speed = float(sp["speed_mps"])
            self.dir_bias = math.radians(float(sp.get("direction_bias_deg", 0.0)))
            self.anisotropy = float(sp.get("anisotropy", 1.0))
            self.link_close_exposure = float(scenario.get("link_close_exposure", 0.5))
        elif self.model == "scripted":
            self.scripted = {(c["u"], c["v"]): float(c["close_time_s"])
                             for c in scenario.get("scripted_closures", [])}
        else:
            raise ValueError(f"unknown spread model {self.model}")

    # ---- radial front geometry ----
    def _speed_at_bearing(self, bearing: float) -> float:
        # downwind (bearing == dir_bias) fastest; upwind slowest.
        align = math.cos(bearing - self.dir_bias)  # 1 downwind, -1 upwind
        factor = 1.0 + (self.anisotropy - 1.0) * (align + 1.0) / 2.0
        return self.base_speed * max(factor, 0.15)

    def arrival_time(self, lon: float, lat: float) -> float:
        """Ground-truth time (s) the front reaches a point. inf if never."""
        if self.model != "radial_front":
            return math.inf
        east, north = _meters_offset(self.ig_lon, self.ig_lat, lon, lat)
        dist = math.hypot(east, north)
        if dist < 1e-6:
            return self.detection_time_s
        bearing = math.atan2(east, north)  # 0 = north, clockwise
        v = self._speed_at_bearing(bearing)
        return self.detection_time_s + dist / v

    def is_exposed(self, lon: float, lat: float, t: float) -> bool:
        return self.arrival_time(lon, lat) <= t

    # ---- link closure schedule ----
    def closed_links_at(self, t: float, net) -> set[tuple[int, int]]:
        """Return set of (u,v) links closed by time t under ground truth."""
        closed = set()
        if self.model == "scripted":
            for (u, v), ct in self.scripted.items():
                if t >= ct:
                    closed.add((u, v))
            return closed
        # radial_front: close a link when exposed fraction exceeds threshold
        for (u, v), link in net.links.items():
            nu, nv = net.G.nodes[u], net.G.nodes[v]
            lon_u, lat_u = nu.get("lon"), nu.get("lat")
            lon_v, lat_v = nv.get("lon"), nv.get("lat")
            if None in (lon_u, lat_u, lon_v, lat_v):
                continue
            # sample 3 points along the link
            frac_exposed = 0.0
            samples = [(0.0,), (0.5,), (1.0,)]
            hit = 0
            for (s,) in samples:
                lo = lon_u + s * (lon_v - lon_u)
                la = lat_u + s * (lat_v - lat_u)
                if self.is_exposed(lo, la, t):
                    hit += 1
            frac_exposed = hit / len(samples)
            if frac_exposed > self.link_close_exposure:
                closed.add((u, v))
        return closed


class Forecast:
    """Perturbed estimate of front arrival times for the AV controller.

    If perfect_information is True this returns ground truth exactly. Otherwise
    arrival estimates are biased by a (seeded) speed error and spatial noise, and
    callers should subtract `safety_margin_s` (+ lead_time) when forming deadlines.
    The controller NEVER receives the GroundTruthHazard object.
    """

    def __init__(self, ground_truth: GroundTruthHazard, forecast_cfg: dict, seed: int = 0):
        self.gt = ground_truth
        self.cfg = forecast_cfg
        self.perfect = bool(forecast_cfg.get("perfect_information", False))
        self.lead_time_s = float(forecast_cfg.get("lead_time_s", 0.0))
        self.position_error_m = float(forecast_cfg.get("position_error_m", 0.0))
        self.speed_error_frac = float(forecast_cfg.get("speed_error_frac", 0.0))
        self.safety_margin_s = float(forecast_cfg.get("safety_margin_s", 0.0))
        self.rng = np.random.default_rng(seed)
        # one fixed speed-bias realization per forecast instance (seeded)
        self._speed_bias = 1.0
        if not self.perfect and self.speed_error_frac > 0:
            # bias toward FASTER spread is conservative; sample symmetric then
            # the controller interprets lower arrival time as earlier danger.
            self._speed_bias = float(1.0 + self.rng.normal(0.0, self.speed_error_frac))
            self._speed_bias = max(0.3, self._speed_bias)

    def estimated_arrival(self, lon: float, lat: float) -> float:
        gt = self.gt.arrival_time(lon, lat)
        if self.perfect or math.isinf(gt):
            return gt
        # apply speed bias (faster bias -> earlier estimated arrival) and spatial
        # noise translated into a time jitter via the base front speed.
        est = gt / self._speed_bias
        if self.position_error_m > 0:
            base_v = getattr(self.gt, "base_speed", 1.0)
            jitter = self.rng.normal(0.0, self.position_error_m) / max(base_v, 0.1)
            est += jitter
        return max(0.0, est)

    def safe_deadline(self, lon: float, lat: float) -> float:
        """Latest time a vehicle may still be at this point, per the forecast.

        = estimated_arrival - safety_margin - lead_time. The controller uses this
        in geofencing to reject trips that cannot clear in time."""
        est = self.estimated_arrival(lon, lat)
        if math.isinf(est):
            return math.inf
        return est - self.safety_margin_s - self.lead_time_s
