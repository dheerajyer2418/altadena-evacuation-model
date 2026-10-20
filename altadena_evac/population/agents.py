"""Person and Household agent records.

Three levels are kept strictly separate (requirement 3):
  * Person    — an individual whose outcome is tracked.
  * Household — the evacuation DECISION-MAKER; owns vehicles and location.
  * Vehicle   — a moving agent (see altadena_evac/fleet/vehicles.py).

A household with four members and one car produces ONE vehicle trip carrying
four people. Seats, drivers, and multi-trip needs are tracked on the household.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Person:
    pid: int
    hid: int
    age: int
    sex: str                      # "male" | "female"
    race: str                     # B02001 category (SEPARATE from ethnicity)
    hispanic: bool                # B03003 ethnicity, separate attribute
    disability: bool              # has any disability (B18101); NOT a driving/AV inference
    is_driver: bool               # modeled licensure/ability; NOT derived from disability alone
    present: bool = True          # present at scenario t=0

    # --- outcome tracking (filled by sim) ---
    reached_safety: bool = False
    arrival_time_s: float | None = None
    exposure_time_s: float = 0.0


@dataclass
class Household:
    hid: int
    block_group: str              # 12-digit GEOID (state+county+tract+bg)
    members: list[int] = field(default_factory=list)   # person ids
    x: float = 0.0                # projected meters (EPSG:26911)
    y: float = 0.0
    lon: float = 0.0
    lat: float = 0.0
    placement_method: str = "unknown"   # labeled; "bbox_random" flagged as fallback

    n_vehicles: int = 0           # usable private vehicles
    seats_per_vehicle: int = 4
    income_bracket: int = 0       # B19001 bracket index
    assistance_need: bool = False # explicit, SEPARATE from disability

    # --- derived convenience ---
    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def no_vehicle(self) -> bool:
        return self.n_vehicles == 0

    @property
    def total_seats(self) -> int:
        return self.n_vehicles * self.seats_per_vehicle

    def trips_needed_private(self) -> int:
        """Number of private-vehicle trips to move all present members.

        If members exceed total seats, extra trips are required (vehicle returns).
        Zero vehicles -> 0 private trips (household needs AV or is stranded).
        """
        if self.n_vehicles == 0:
            return 0
        import math
        return max(1, math.ceil(self.size / self.seats_per_vehicle))

    # --- decision-maker state (set during sim) ---
    aware_time_s: float | None = None
    prepared_time_s: float | None = None
    request_time_s: float | None = None    # AV households only
    departed: bool = False
    uses_av: bool = False
    stranded: bool = False                 # carless and no AV service available


@dataclass
class Population:
    """Container with cross-checked person + household records."""
    persons: list[Person]
    households: list[Household]
    meta: dict = field(default_factory=dict)   # fit error, source dates, counts

    def check_integrity(self) -> list[str]:
        """Validate household membership consistency. Returns list of problems."""
        problems: list[str] = []
        hid_set = {h.hid for h in self.households}
        by_hid: dict[int, list[int]] = {}
        for p in self.persons:
            by_hid.setdefault(p.hid, []).append(p.pid)
            if p.hid not in hid_set:
                problems.append(f"person {p.pid} references missing household {p.hid}")
        for h in self.households:
            declared = set(h.members)
            actual = set(by_hid.get(h.hid, []))
            if declared != actual:
                problems.append(
                    f"household {h.hid} member mismatch: declared {len(declared)} "
                    f"vs {len(actual)} person records"
                )
        return problems

    @property
    def n_persons(self) -> int:
        return len(self.persons)

    @property
    def n_households(self) -> int:
        return len(self.households)
