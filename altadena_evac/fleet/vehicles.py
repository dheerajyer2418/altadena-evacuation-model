"""Moving-agent records: private vehicles and AVs.

A Vehicle is a MOVING AGENT distinct from the people it carries and the household
that owns/decides it (requirement 3). Passengers are person ids; seat capacity is
enforced by the dispatcher/sim, never exceeded.

The traffic engine calls ``on_arrival(now, node)`` when a vehicle reaches the last
node of its current route, and ``on_trapped(now, node)`` when no escape route
exists. These delegate to handlers wired up by the simulation / dispatcher so leg
transitions (pickup -> board -> safety) live in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Vehicle:
    vid: int
    kind: str                       # "private" | "av"
    seats: int
    hid: int | None = None          # owning household (private)
    passengers: list[int] = field(default_factory=list)   # person ids aboard
    state: str = "idle"             # idle|to_pickup|boarding|to_safety|arrived|trapped
    node: int | None = None         # last known node (set on arrival)

    # handlers set by the simulation/dispatcher
    arrival_handler: object = None  # callable(vehicle, now, node)
    trapped_handler: object = None  # callable(vehicle, now, node)

    # AV dispatch bookkeeping (times tracked separately — requirement 5)
    request = None                  # Request currently served (av)
    ready_to_depart_s: float | None = None   # boarding end time
    exposure_time_s: float = 0.0

    @property
    def n_passengers(self) -> int:
        return len(self.passengers)

    @property
    def free_seats(self) -> int:
        return self.seats - len(self.passengers)

    def board(self, pids: list[int]) -> None:
        if len(self.passengers) + len(pids) > self.seats:
            raise ValueError(
                f"seat-capacity violation on vehicle {self.vid}: "
                f"{len(self.passengers)}+{len(pids)} > {self.seats}"
            )
        self.passengers.extend(pids)

    def on_arrival(self, now: float, node: int | None) -> None:
        self.node = node
        if self.arrival_handler is not None:
            self.arrival_handler(self, now, node)

    def on_trapped(self, now: float, node: int | None) -> None:
        self.state = "trapped"
        self.node = node
        if self.trapped_handler is not None:
            self.trapped_handler(self, now, node)
