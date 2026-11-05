"""Sample randomized fire realizations for the hazard Monte Carlo.

Each realization is a set of OVERRIDES applied to a base ``radial_front`` scenario
dict: ignition point, spread axis (``direction_bias_deg``), anisotropy, and base
speed. Everything else in the scenario (forecast, exposure metric, closure
threshold, detection time) is inherited UNCHANGED so that only the fire geometry
varies across runs — the comparison then isolates the effect of *where the fire
starts and which way it runs* (cf. the traffic sweep, which isolates capacity).

Two named sets (see docs/HAZARD_RANDOMIZATION_PLAN.md):
  foothills : ignite in the northern band of the area, spread biased SOUTH toward
              the evacuation routes (realistic wildland-urban-interface origin).
  unbiased  : ignite anywhere in the area, any axis (an unbiased stress test).

Both sets are defined relative to a bounding box passed in, so they are
meaningful in any mode: 'altadena' passes the demand bbox (study.yaml), 'toy'
passes the toy grid's own node bbox.

Bearing convention matches hazard.scenario: direction_bias_deg is measured with
0 = north, increasing clockwise, so 180 = due south, 225 = SW.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

# Fraction of the latitude span (from the north edge) treated as the foothill
# band. 0.30 reproduces the plan's Altadena band (lat 34.212-34.230) on the
# study demand bbox (34.172-34.230).
FOOTHILL_LAT_FRACTION = 0.30


@dataclass
class SampleRanges:
    """Shared sampling ranges (editable; see docs/ASSUMPTIONS.md). The speed
    upper bound is kept modest so the fire stays dire but survivable — a front
    that traps everyone leaves no room to compare AV policies."""
    anisotropy: tuple = (1.2, 2.5)
    speed_mps: tuple = (0.3, 1.0)
    foothill_axis_deg: tuple = (180.0, 250.0)   # S -> SW (Santa Ana consistent)


def sample_realizations(set_name: str, n: int, bbox: tuple, seed: int,
                        ranges: SampleRanges | None = None) -> list[dict]:
    """Return ``n`` fire-override dicts for the named set.

    bbox is (west, south, east, north) in lon/lat degrees."""
    ranges = ranges or SampleRanges()
    rng = np.random.default_rng(seed)
    west, south, east, north = bbox
    lat_span = north - south
    foothill_south = north - FOOTHILL_LAT_FRACTION * lat_span

    out = []
    for i in range(n):
        if set_name == "foothills":
            lat = rng.uniform(foothill_south, north)
            lon = rng.uniform(west, east)
            axis = rng.uniform(*ranges.foothill_axis_deg)
        elif set_name == "unbiased":
            lat = rng.uniform(south, north)
            lon = rng.uniform(west, east)
            axis = rng.uniform(0.0, 360.0)
        else:
            raise ValueError(f"unknown fire set '{set_name}' "
                             f"(expected 'foothills' or 'unbiased')")
        out.append({
            "id": i,
            "set": set_name,
            "ignition_lon": float(lon),
            "ignition_lat": float(lat),
            "direction_bias_deg": float(axis),
            "anisotropy": float(rng.uniform(*ranges.anisotropy)),
            "speed_mps": float(rng.uniform(*ranges.speed_mps)),
        })
    return out


def apply_realization(base_scenario: dict, real: dict) -> dict:
    """Return a NEW scenario dict = base with this realization's fire overrides.

    Only ignition + the radial_front spread fields are replaced; forecast,
    exposure_metric, link_close_exposure, detection_time_s are inherited."""
    sc = copy.deepcopy(base_scenario)
    sc["ignition"] = {"lon": real["ignition_lon"], "lat": real["ignition_lat"]}
    sp = dict(sc.get("spread", {}))
    sp["model"] = "radial_front"
    sp["speed_mps"] = real["speed_mps"]
    sp["direction_bias_deg"] = real["direction_bias_deg"]
    sp["anisotropy"] = real["anisotropy"]
    sc["spread"] = sp
    return sc


def bbox_from_graph(G) -> tuple:
    """(west, south, east, north) from a graph's node lon/lat."""
    lons = [d.get("lon") for _, d in G.nodes(data=True) if d.get("lon") is not None]
    lats = [d.get("lat") for _, d in G.nodes(data=True) if d.get("lat") is not None]
    return (min(lons), min(lats), max(lons), max(lats))
