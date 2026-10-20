"""OPTIONAL Camp Fire (2018) transfer coefficients — DISABLED by default.

Source: Grajdura, S., Borjigin, S., & Niemeier, D. (2022), "Fast-moving dire
wildfire evacuation simulation", Transportation Research Part D, based on a
survey of Camp Fire (Paradise, CA, 2018-11-08) evacuees.

IMPORTANT CAVEATS (requirement 5):
  * These are OBSERVATIONAL associations, not causal effects.
  * They come from a DIFFERENT fire and community; they are NOT validated for
    Altadena. Treat enabling this as a transfer HYPOTHESIS only.
  * The original survey N is small and the paper itself omitted congestion and
    agent interactions and used 200 agents. We do NOT reproduce those
    simplifications; this model adds congestion and full-population demand.
  * Time reference: minutes after the first official alert.

This module provides a departure-time generator with the paper's STRUCTURE
(awareness + mobilization delay, right-skewed departure curve). The numeric
values below are LABELED PLACEHOLDERS approximating the published cumulative
departure curve shape; replace with the exact table values from the paper before
any transfer analysis. They are loaded ONLY when behavior.yaml sets
campfire_transfer.enabled: true.
"""
from __future__ import annotations

import math

import numpy as np

# Placeholder departure-curve parameters (minutes after first alert), clearly
# labeled. Dr. Grajdura should overwrite with the exact paper coefficients.
CAMP_FIRE_DEPARTURE = {
    "distribution": "lognormal",
    "median_min": 46.0,        # PLACEHOLDER approximation of published median
    "sigma": 0.85,             # PLACEHOLDER spread
    "time_reference": "minutes after first official alert (Camp Fire, 2018)",
    "status": "PLACEHOLDER — not the validated paper table",
}


def departure_offset_s(rng: np.random.Generator) -> float:
    """Draw a departure time (seconds after first alert) using the transfer curve."""
    p = CAMP_FIRE_DEPARTURE
    mu = math.log(p["median_min"] * 60.0)
    return float(rng.lognormal(mean=mu, sigma=p["sigma"]))


def provenance() -> dict:
    return dict(CAMP_FIRE_DEPARTURE)
