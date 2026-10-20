"""INRIX importer INTERFACE (requirement 8).

No INRIX data or documentation was supplied with this project, so this module is
a DOCUMENTED INTERFACE, not a working importer. It fabricates nothing and claims
no calibration or validation. When real INRIX exports arrive, inspect the actual
schema first, then fill in `load_inrix_speeds`.

Honest-use rules baked into the interface:
  * Probe counts are NOT traffic volumes and do NOT identify carless households.
  * Respect timestamps, travel direction, sampling, interpolated segments, and
    quality/confidence flags (c-value, confidence score) where present.
  * Potential uses: observed travel times/speeds for CALIBRATION or VALIDATION of
    the mesoscopic engine, or route-pattern priors — never as ground-truth demand.
  * Do NOT double-count congestion: if INRIX speeds already reflect congestion,
    use them to calibrate link free-flow speeds / capacities, NOT to ADD delay on
    top of a model that already produces queues (requirement 8).

Credentials and raw INRIX data must stay out of version control (see .gitignore).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InrixSchemaExpectation:
    """What a typical INRIX XD/segment speed export is expected to contain. Used
    to report which fields are missing from a supplied file."""
    segment_id: str = "XDSegID or TMC code"
    timestamp: str = "measurement timestamp (with timezone)"
    speed: str = "observed space-mean speed (mph or km/h — record units!)"
    reference_speed: str = "free-flow/reference speed"
    travel_time: str = "segment travel time"
    confidence: str = "confidence / c-value (data quality flag)"
    direction: str = "travel direction / bearing"


class InrixImporter:
    def __init__(self, path: str | None = None):
        self.path = path

    def inspect(self) -> dict:
        """Report what is available vs. required, WITHOUT inventing values."""
        exp = InrixSchemaExpectation()
        return {
            "data_present": self.path is not None,
            "status": "no data supplied" if self.path is None else "inspect schema",
            "expected_fields": exp.__dict__,
            "missing_inputs": [
                "INRIX segment geometry (XD/TMC -> OSM edge map)",
                "units of speed/travel_time",
                "timezone of timestamps",
                "quality/confidence flag semantics",
            ],
            "cannot_do_without_data": [
                "calibrate link free-flow speeds",
                "validate simulated travel-time distributions",
            ],
        }

    def load_inrix_speeds(self):
        raise NotImplementedError(
            "No INRIX data supplied. Implement against the real schema (see "
            "inspect()). Do NOT fabricate calibrated parameters.")

    def segment_to_edge_map(self):
        raise NotImplementedError(
            "Requires INRIX segment geometry to conflate XD/TMC segments to OSM "
            "edges. Not available offline.")
