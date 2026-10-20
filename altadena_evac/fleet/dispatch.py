r"""AV dispatch service (requirement 3: a SEPARATE service component).

Lifecycle of an AV request
  submitted --> pending --> assigned (AV en route to pickup) --> onboard
  (boarding, then traveling) --> served (dropped at safety)
            \-> unserved (never picked up / timed out / withdrawal)

Common dispatch rules (nearest-idle assignment, boarding time, control cadence,
reassessment) are IDENTICAL across policies; only the ResolvedPolicy flags differ,
so comparisons isolate the policy (requirement 7).

The dispatcher sees ONLY the Forecast object, never the ground-truth hazard
(requirement 6). Pickup-wait and boarding time are tracked separately from travel
time (requirement 5). Seat capacity is enforced in Vehicle.board (no overfilling,
no duplicate assignment — a person belongs to exactly one request).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .policies import ResolvedPolicy
from .vehicles import Vehicle


@dataclass
class Request:
    rid: int
    hid: int
    origin_node: int
    person_ids: list[int]
    request_time_s: float
    no_vehicle: bool
    assistance_need: bool
    status: str = "pending"      # pending|assigned|onboard|served|unserved
    av_vid: int | None = None
    assign_time_s: float | None = None
    pickup_arrive_s: float | None = None
    board_end_s: float | None = None
    dropoff_s: float | None = None

    @property
    def pickup_wait_s(self):
        if self.pickup_arrive_s is None:
            return None
        return self.pickup_arrive_s - self.request_time_s

    @property
    def travel_time_s(self):
        if self.dropoff_s is None or self.board_end_s is None:
            return None
        return self.dropoff_s - self.board_end_s


class AVDispatcher:
    def __init__(self, net, forecast, fleet_cfg: dict, policy: ResolvedPolicy,
                 persons: dict, n_vehicles: int, seats_per_av: int,
                 service_centroid: tuple[float, float],
                 max_av_wait_s: float, start_vid: int = 1_000_000):
        self.net = net
        self.forecast = forecast
        self.policy = policy
        self.persons = persons            # pid -> Person
        self.common = fleet_cfg["dispatch_common"]
        self.control_step_s = float(self.common["control_step_s"])
        self.boarding_s = float(self.common["boarding_time_s"])
        self.max_pickup_detour_s = float(self.common["max_pickup_detour_s"])
        self.reassess = bool(self.common["reassess_accepted_trips"])
        self.seats_per_av = seats_per_av
        self.service_centroid = service_centroid
        self.max_av_wait_s = max_av_wait_s
        self.nominal_front_speed = 1.4   # controller's ASSUMED front speed (m/s)

        # build fleet at staging nodes (destinations by default)
        self.avs: dict[int, Vehicle] = {}
        staging = list(net.destinations) or [next(iter(net.G.nodes))]
        for i in range(n_vehicles):
            vid = start_vid + i
            av = Vehicle(vid=vid, kind="av", seats=seats_per_av,
                         node=staging[i % len(staging)], state="idle")
            av.arrival_handler = self._on_av_arrival
            av.trapped_handler = self._on_av_trapped
            self.avs[vid] = av
        self.idle = [av.vid for av in self.avs.values()]

        self.requests: dict[int, Request] = {}
        self.pending: list[Request] = []
        self._next_rid = 0
        self._last_control = -math.inf
        self.withdrawn = False

        # metrics
        self.served_requests = 0
        self.unserved_requests = 0

    # --------------------------------------------------------- request intake
    def submit_household(self, household, present_pids: list[int], now: float) -> list[Request]:
        """Split a household's present members into seat-sized requests.

        A household needing more seats than one AV provides generates multiple
        requests (multiple AV trips). Each person appears in exactly one request
        (no duplicate assignment)."""
        reqs = []
        pids = list(present_pids)
        for i in range(0, len(pids), self.seats_per_av):
            chunk = pids[i:i + self.seats_per_av]
            r = Request(rid=self._next_rid, hid=household.hid,
                        origin_node=household.origin_node, person_ids=chunk,
                        request_time_s=now, no_vehicle=household.no_vehicle,
                        assistance_need=household.assistance_need)
            self._next_rid += 1
            self.requests[r.rid] = r
            self.pending.append(r)
            reqs.append(r)
        return reqs

    # ------------------------------------------------------------- main tick
    def tick(self, now: float, dt: float) -> None:
        # 1. depart AVs that finished boarding (every tick, fine-grained)
        for av in self.avs.values():
            if av.state == "boarding" and av.ready_to_depart_s is not None \
                    and now >= av.ready_to_depart_s:
                self._depart_to_safety(av, now)
        # 2. control logic on its own cadence
        if now - self._last_control >= self.control_step_s - 1e-9:
            self._last_control = now
            self._control(now)

    def _control(self, now: float) -> None:
        # withdrawal trigger (forecast-based; never ground truth)
        if self.policy.is_withdrawal and not self.withdrawn:
            if self._withdrawal_condition(now):
                self._trigger_withdrawal(now)

        # reassess accepted (en-route-to-pickup) trips under forecast
        if self.reassess and (self.policy.screen_pickup or self.policy.screen_passenger):
            self._reassess(now)

        # time-out requests waiting too long -> unserved (self-help / stranded)
        for r in list(self.pending):
            if r.status == "pending" and (now - r.request_time_s) > self.max_av_wait_s:
                self._mark_unserved(r)

        # assign pending requests (unless withdrawn: no NEW pickups)
        if not self.withdrawn:
            self._assign(now)

    def _mark_unserved(self, r: Request) -> None:
        r.status = "unserved"
        if r in self.pending:
            self.pending.remove(r)

    # ------------------------------------------------------------- assignment
    def _assign(self, now: float) -> None:
        self.pending = [r for r in self.pending if r.status == "pending"]
        self.pending.sort(key=self.policy.request_sort_key)
        for r in self.pending:
            if not self.idle:
                break
            best = self._best_av_for(r, now)
            if best is None:
                continue
            vid, pickup_path, pickup_eta, evac_path, evac_eta = best
            av = self.avs[vid]
            # geofencing screening of BOTH journeys (uses forecast only)
            if self.policy.screen_pickup or self.policy.screen_passenger:
                if not self._journeys_feasible(now, pickup_path, pickup_eta,
                                               evac_path, evac_eta):
                    if self.policy.reject_if_infeasible:
                        continue   # leave pending; may time out -> unserved
            # commit assignment
            self.idle.remove(vid)
            av.state = "to_pickup"
            av.request = r
            r.status = "assigned"
            r.av_vid = vid
            r.assign_time_s = now
            ok = self.net.inject(av, av.node, targets={r.origin_node},
                                 route=pickup_path)
            if not ok:
                # no route to pickup; undo
                av.state = "idle"
                av.request = None
                r.status = "pending"
                r.av_vid = None
                self.idle.append(vid)
        self.pending = [r for r in self.pending if r.status == "pending"]

    def _best_av_for(self, r: Request, now: float):
        """Nearest idle AV to the pickup, then its actual route (common rule).

        To stay tractable on a large network the candidate AV is chosen by
        great-circle distance to the pickup (a documented dispatch heuristic),
        and ONE route Dijkstra is computed for that AV. Returns
        (vid, pickup_path, pickup_eta, evac_path, evac_eta) or None."""
        evac_path, evac_cost = self.net.shortest_path_to_any(r.origin_node)
        if evac_path is None:
            return None   # pickup origin can't reach safety at all
        olon, olat = self.net.node_lonlat(r.origin_node)
        # rank idle AVs by cheap great-circle distance; try the closest few
        ranked = sorted(
            self.idle,
            key=lambda vid: self._gc2(self.net.node_lonlat(self.avs[vid].node), (olon, olat)))
        for vid in ranked[:5]:
            av = self.avs[vid]
            path, cost = self.net.path_between(av.node, r.origin_node)
            if path is None or math.isinf(cost) or cost > self.max_pickup_detour_s:
                continue
            return (vid, path, cost, evac_path, evac_cost)
        return None

    @staticmethod
    def _gc2(a, b) -> float:
        if a[0] is None or b[0] is None:
            return math.inf
        dx = (a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2))
        dy = a[1] - b[1]
        return dx * dx + dy * dy

    def _journeys_feasible(self, now, pickup_path, pickup_eta,
                           evac_path, evac_eta) -> bool:
        ok = True
        if self.policy.screen_pickup:
            ok = ok and self._journey_feasible(pickup_path, now)
        if self.policy.screen_passenger:
            board_end = now + pickup_eta + self.boarding_s
            ok = ok and self._journey_feasible(evac_path, board_end)
        return ok

    def _journey_feasible(self, path, start_time) -> bool:
        """Every node on path must be reached before its forecast safe deadline."""
        if not path:
            return True
        t = start_time
        prev = path[0]
        for nxt in path[1:]:
            link = self.net.links.get((prev, nxt))
            t += link.tff_s if link else math.inf
            lon, lat = self.net.node_lonlat(nxt)
            if lon is not None:
                deadline = self.forecast.safe_deadline(lon, lat)
                if t > deadline:
                    return False
            prev = nxt
        return True

    # --------------------------------------------------------- arrival events
    def _on_av_arrival(self, av: Vehicle, now: float, node: int) -> None:
        if av.state == "to_pickup":
            r = av.request
            if r is None or r.status != "assigned":
                # request was canceled/reoffered while en route -> retreat
                self._retreat(av, now)
                return
            # board present members (seat capacity enforced in board())
            present = [pid for pid in r.person_ids if self.persons[pid].present]
            av.board(present)
            r.status = "onboard"
            r.pickup_arrive_s = now
            av.state = "boarding"
            av.ready_to_depart_s = now + self.boarding_s
        elif av.state in ("to_safety", "retreat"):
            # drop off: passengers reach safety
            for pid in av.passengers:
                p = self.persons[pid]
                p.reached_safety = True
                p.arrival_time_s = now
            if av.request is not None and av.state == "to_safety":
                av.request.status = "served"
                av.request.dropoff_s = now
                self.served_requests += 1
            av.passengers = []
            av.request = None
            av.state = "idle"
            av.node = node
            if av.vid not in self.idle:
                self.idle.append(av.vid)

    def _on_av_trapped(self, av: Vehicle, now: float, node: int) -> None:
        av.state = "trapped"
        # onboard passengers did NOT reach safety; recorded, not deleted.
        if av.request is not None:
            av.request.status = "unserved"
            self.unserved_requests += 1

    def _depart_to_safety(self, av: Vehicle, now: float) -> None:
        if av.request is not None:
            av.request.board_end_s = now
        av.state = "to_safety"
        av.ready_to_depart_s = None
        ok = self.net.inject(av, av.node, targets=self.net.destinations)
        if not ok:
            self._on_av_trapped(av, now, av.node)

    # --------------------------------------------------------- reassessment
    def _reassess(self, now: float) -> None:
        for av in self.avs.values():
            if av.state != "to_pickup" or av.request is None:
                continue
            r = av.request
            # re-screen passenger journey from the pickup origin as if boarding now
            evac_path, _ = self.net.shortest_path_to_any(r.origin_node)
            if evac_path is None or not self._journey_feasible(evac_path, now + self.boarding_s):
                # becoming infeasible -> cancel pickup, reoffer, AV retreats at
                # its next decision point (the pickup node).
                r.status = "pending"
                r.av_vid = None
                av.request = None
                if r not in self.pending:
                    self.pending.append(r)

    # --------------------------------------------------------- withdrawal
    def _withdrawal_condition(self, now: float) -> bool:
        lon, lat = self.service_centroid
        est = self.forecast.estimated_arrival(lon, lat)
        if math.isinf(est):
            return False
        gap_m = (est - now) * self.nominal_front_speed
        return gap_m <= self.policy.withdrawal_trigger_value

    def _trigger_withdrawal(self, now: float) -> None:
        self.withdrawn = True
        # onboard passengers: default complete dropoff (already en route to safety
        # once boarding finishes) — nothing to do.
        # assigned-but-not-boarded: per rule.
        if self.policy.assigned_rule == "cancel_and_reoffer":
            for av in self.avs.values():
                if av.state == "to_pickup" and av.request is not None:
                    r = av.request
                    r.status = "pending"   # reoffered, but no NEW assignments now
                    r.av_vid = None
                    av.request = None
        # idle AVs retreat to safety so they are not left in the hazard.
        for av in list(self.avs.values()):
            if av.state == "idle" and av.node not in self.net.destinations:
                self._retreat(av, now)

    def _retreat(self, av: Vehicle, now: float) -> None:
        av.state = "retreat"
        if av.vid in self.idle:
            self.idle.remove(av.vid)
        ok = self.net.inject(av, av.node, targets=self.net.destinations)
        if not ok:
            av.state = "trapped"

    # --------------------------------------------------------- reporting
    def finalize(self, now: float) -> dict:
        """At horizon: count requests/persons never served."""
        unserved_persons = 0
        waiting_persons = 0
        for r in self.requests.values():
            if r.status in ("pending", "assigned", "onboard"):
                waiting_persons += len(r.person_ids)
                r.status = "unserved" if r.status == "pending" else r.status
            if r.status == "unserved":
                self.unserved_requests += 0  # already counted on trap; avoid double
        # recount cleanly
        served = sum(1 for r in self.requests.values() if r.status == "served")
        unserved = sum(1 for r in self.requests.values() if r.status not in ("served",))
        served_persons = sum(len(r.person_ids) for r in self.requests.values()
                             if r.status == "served")
        unserved_persons = sum(len(r.person_ids) for r in self.requests.values()
                               if r.status != "served")
        waits = [r.pickup_wait_s for r in self.requests.values()
                 if r.pickup_wait_s is not None]
        travels = [r.travel_time_s for r in self.requests.values()
                   if r.travel_time_s is not None]
        return {
            "n_requests": len(self.requests),
            "served_requests": served,
            "unserved_requests": unserved,
            "served_persons": served_persons,
            "unserved_persons": unserved_persons,
            "pickup_waits_s": waits,
            "travel_times_s": travels,
            "withdrawn": self.withdrawn,
        }
