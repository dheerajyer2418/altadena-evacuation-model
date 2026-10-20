"""Discrete-time evacuation simulation loop.

Order of operations each step t (dt seconds):
  1. HAZARD (ground truth): close newly-exposed links (monotonic; fire does not
     un-burn). Ground truth is read ONLY here and in exposure accrual.
  2. DEMAND: launch private-vehicle trips for households whose preparation is done;
     submit AV requests for AV households whose request time has arrived. Private
     overflow (present members exceeding vehicle seats) becomes an AV request if a
     fleet exists, else stranded — recorded, never dropped.
  3. DISPATCH: dispatcher.tick (assignment/screening/boarding/withdrawal/reassess).
  4. TRAFFIC: advance the mesoscopic network by dt (queues + spillback).
  5. EXPOSURE: accrue exposure time for people whose current location (home, or the
     link their vehicle is on, or a trapped node) is reached by the fire front.

Reproducibility: separate RNG streams for behavior, dispatch, hazard (requirement
9). The traffic engine is deterministic.
"""
from __future__ import annotations

import math

import numpy as np

from ..fleet.vehicles import Vehicle


class Simulation:
    def __init__(self, population, net, hazard_gt, dispatcher, cfg_sim: dict,
                 on_closure_cfg: dict, hazard_scenario: dict,
                 record_every_s: float | None = None, max_render_vehicles: int = 4000):
        self.pop = population
        self.net = net
        self.hazard = hazard_gt
        self.dispatcher = dispatcher
        self.horizon_s = float(cfg_sim["horizon_s"])
        self.step_s = float(cfg_sim["step_s"])
        self.on_closure_cfg = on_closure_cfg
        self.exposure_radius_m = float(
            hazard_scenario.get("exposure_metric", {}).get("exposure_radius_m", 150.0))

        # replay recording (for the live UI)
        self.record_every_s = record_every_s
        self.max_render_vehicles = max_render_vehicles
        self.frames: list[dict] = []
        self._render_ids: set[int] = set()
        self._now = 0.0
        self._last_record = -1e18

        self.persons = {p.pid: p for p in population.persons}
        self.households = {h.hid: h for h in population.households}

        self._private_vehicles: dict[int, Vehicle] = {}
        self._next_vid = 1
        self._launched_private: set[int] = set()
        self._submitted_av: set[int] = set()
        self._closed: set[tuple[int, int]] = set()

        # outputs
        self.completion_curve = []          # (t, n_reached_safety)
        self.stranded_persons: list[int] = []
        self.timeline_log = []              # chronological event records

    # --------------------------------------------------- private-vehicle trips
    def _private_arrival(self, veh: Vehicle, now: float, node: int) -> None:
        for pid in veh.passengers:
            p = self.persons[pid]
            p.reached_safety = True
            p.arrival_time_s = now
        veh.state = "arrived"
        self.timeline_log.append((now, "private_arrival", veh.vid, len(veh.passengers)))

    def _private_trapped(self, veh: Vehicle, now: float, node: int) -> None:
        veh.state = "trapped"
        self.timeline_log.append((now, "private_trapped", veh.vid, node))

    def _launch_private(self, h, now: float) -> None:
        present = [pid for pid in h.members if self.persons[pid].present]
        if not present:
            return
        n_veh = h.n_vehicles
        seats = h.seats_per_vehicle
        capacity = n_veh * seats
        carried = present[:capacity]
        overflow = present[capacity:]
        # distribute carried members across vehicles, seats enforced
        idx = 0
        for k in range(n_veh):
            chunk = carried[idx:idx + seats]
            idx += seats
            if not chunk:
                break
            vid = self._next_vid
            self._next_vid += 1
            veh = Vehicle(vid=vid, kind="private", seats=seats, hid=h.hid,
                          passengers=list(chunk), state="to_safety", node=h.origin_node)
            veh.arrival_handler = self._private_arrival
            veh.trapped_handler = self._private_trapped
            self._private_vehicles[vid] = veh
            ok = self.net.inject(veh, h.origin_node, targets=self.net.destinations)
            if not ok:
                self._private_trapped(veh, now, h.origin_node)
            self.timeline_log.append((now, "private_depart", vid, len(chunk)))
        # overflow -> AV request if fleet exists, else stranded
        if overflow:
            if self.dispatcher is not None:
                self.dispatcher.submit_household(h, overflow, now)
                self.timeline_log.append((now, "overflow_to_av", h.hid, len(overflow)))
            else:
                self.stranded_persons.extend(overflow)
                self.timeline_log.append((now, "overflow_stranded", h.hid, len(overflow)))
        h.departed = True

    # --------------------------------------------------------- exposure accrual
    def _link_midpoint(self, key):
        u, v = key
        du, dv = self.net.G.nodes[u], self.net.G.nodes[v]
        if du.get("lon") is None or dv.get("lon") is None:
            return None
        return ((du["lon"] + dv["lon"]) / 2.0, (du["lat"] + dv["lat"]) / 2.0)

    def _accrue_exposure(self, now: float, dt: float) -> None:
        # people still at home (not yet departed, present)
        for h in self.households.values():
            if h.departed:
                continue
            if self.hazard.is_exposed(h.lon, h.lat, now):
                for pid in h.members:
                    p = self.persons[pid]
                    if p.present and not p.reached_safety:
                        p.exposure_time_s += dt
        # people in moving/trapped vehicles (private + AV)
        all_vehicles = list(self._private_vehicles.values())
        if self.dispatcher is not None:
            all_vehicles += list(self.dispatcher.avs.values())
        for veh in all_vehicles:
            if not veh.passengers:
                continue
            st = self.net.state.get(veh.vid)
            loc = None
            if st and st.get("link"):
                loc = self._link_midpoint(st["link"])
            elif veh.node is not None:
                d = self.net.G.nodes[veh.node]
                loc = (d.get("lon"), d.get("lat"))
            if loc and loc[0] is not None and self.hazard.is_exposed(loc[0], loc[1], now):
                for pid in veh.passengers:
                    p = self.persons[pid]
                    if not p.reached_safety:
                        p.exposure_time_s += dt

    # ----------------------------------------------------------- replay record
    def _vehicle_lonlat(self, veh):
        """Interpolated current position of a vehicle (lon, lat) or None."""
        st = self.net.state.get(veh.vid)
        if st and st.get("link"):
            u, v = st["link"]
            du, dv = self.net.G.nodes[u], self.net.G.nodes[v]
            if du.get("lon") is None or dv.get("lon") is None:
                return None
            link = self.net.links.get((u, v))
            et = link.entry_time.get(veh.vid) if link else None
            p = 0.0
            if et is not None and link and link.tff_s > 0:
                p = min(1.0, max(0.0, (self._now - et) / link.tff_s))
            return (du["lon"] + p * (dv["lon"] - du["lon"]),
                    du["lat"] + p * (dv["lat"] - du["lat"]))
        if veh.node is not None:
            d = self.net.G.nodes[veh.node]
            return (d.get("lon"), d.get("lat"))
        return None

    def _snapshot_frame(self, t: float) -> dict:
        """One replay frame: a capped, stable sample of active vehicle positions
        plus live aggregate stats (stats are FULL-population, not the sample)."""
        all_vehicles = list(self._private_vehicles.values())
        if self.dispatcher is not None:
            all_vehicles += list(self.dispatcher.avs.values())
        pts = []
        for veh in all_vehicles:
            st = self.net.state.get(veh.vid)
            active = st and st.get("status") in ("moving", "pending")
            if not active:
                continue
            if veh.vid not in self._render_ids:
                if len(self._render_ids) >= self.max_render_vehicles:
                    continue
                self._render_ids.add(veh.vid)
            loc = self._vehicle_lonlat(veh)
            if loc is None or loc[0] is None:
                continue
            # kind: 0 private empty-ish, 1 private occupied, 2 AV empty, 3 AV w/ pax
            if veh.kind == "av":
                kind = 3 if veh.passengers else 2
            else:
                kind = 1
            pts.append([round(loc[0], 5), round(loc[1], 5), kind, veh.n_passengers])

        present = [p for p in self.persons.values() if p.present]
        reached = sum(1 for p in present if p.reached_safety)
        exposed = sum(1 for p in present if p.exposure_time_s > 0)
        carless_present = [p for p in present if self.households[p.hid].no_vehicle]
        carless_reached = sum(1 for p in carless_present if p.reached_safety)
        stats = {
            "reached": reached,
            "present": len(present),
            "exposed": exposed,
            "trapped_vehicles": len(self.net.trapped),
            "carless_reached": carless_reached,
            "carless_present": len(carless_present),
            "closed_links": len(self._closed),
            "av_active": (sum(1 for a in self.dispatcher.avs.values()
                              if a.state not in ("idle", "trapped"))
                          if self.dispatcher is not None else 0),
        }
        return {"t": round(t, 1), "pts": pts, "stats": stats}

    # ------------------------------------------------------------------- run
    def run(self) -> dict:
        t = 0.0
        # order households by prepared time for efficient launching
        prep_sorted = sorted(
            [h for h in self.households.values()],
            key=lambda h: (h.prepared_time_s if h.prepared_time_s is not None else math.inf))
        pi = 0
        req_sorted = sorted(
            [h for h in self.households.values() if h.uses_av],
            key=lambda h: (h.request_time_s if h.request_time_s is not None else math.inf))
        ri = 0

        while t <= self.horizon_s:
            self._now = t
            # 1. hazard closures (monotonic)
            new_closed = self.hazard.closed_links_at(t, self.net)
            for key in new_closed - self._closed:
                self.net.set_closed(*key, closed=True)
            self._closed |= new_closed

            # 2a. launch private trips that are prepared
            while pi < len(prep_sorted):
                h = prep_sorted[pi]
                if h.prepared_time_s is None or h.prepared_time_s > t:
                    break
                pi += 1
                if h.uses_av or h.stranded or h.departed or h.no_vehicle:
                    continue
                self._launch_private(h, t)
            # 2b. submit AV requests that are due
            while ri < len(req_sorted) and self.dispatcher is not None:
                h = req_sorted[ri]
                if h.request_time_s is None or h.request_time_s > t:
                    break
                ri += 1
                if h.hid in self._submitted_av:
                    continue
                present = [pid for pid in h.members if self.persons[pid].present]
                if present:
                    self.dispatcher.submit_household(h, present, t)
                    self._submitted_av.add(h.hid)

            # 3. dispatch
            if self.dispatcher is not None:
                self.dispatcher.tick(t, self.step_s)

            # 4. traffic
            self.net.step(t, self.step_s)

            # 5. exposure
            self._accrue_exposure(t, self.step_s)

            # completion curve sample (every ~60 s)
            if int(t) % 60 == 0:
                reached = sum(1 for p in self.persons.values() if p.reached_safety)
                self.completion_curve.append((t, reached))

            # replay frame (for the live UI)
            if self.record_every_s is not None and \
                    (t - self._last_record) >= self.record_every_s - 1e-9:
                self._last_record = t
                self.frames.append(self._snapshot_frame(t))

            # early stop: nothing left to move and nothing pending
            if self._quiescent():
                break
            t += self.step_s

        if self.dispatcher is not None:
            self.disp_result = self.dispatcher.finalize(t)
        else:
            self.disp_result = None
        self.end_time_s = t
        return self._collect()

    def _quiescent(self) -> bool:
        if self.net.active_count() > 0:
            return False
        if self.dispatcher is not None:
            if self.dispatcher.pending:
                return False
            if any(av.state not in ("idle", "trapped") for av in self.dispatcher.avs.values()):
                return False
        # any households still waiting to depart?
        for h in self.households.values():
            if not h.departed and not h.stranded and not h.no_vehicle:
                return False
        return True

    # --------------------------------------------------------------- outputs
    def _collect(self) -> dict:
        persons = list(self.persons.values())
        present = [p for p in persons if p.present]
        reached = [p for p in present if p.reached_safety]
        not_reached = [p for p in present if not p.reached_safety]
        exposed = [p for p in present if p.exposure_time_s > 0]
        full_clear = len(not_reached) == 0

        res = {
            "end_time_s": self.end_time_s,
            "n_persons_total": len(persons),
            "n_persons_present": len(present),
            "n_reached_safety": len(reached),
            "n_not_reached": len(not_reached),              # waiting/traveling/stranded
            "n_stranded_no_fleet_or_overflow": len(set(self.stranded_persons)),
            "n_exposed_persons": len(exposed),
            "total_exposure_person_s": sum(p.exposure_time_s for p in present),
            "full_clearance": full_clear,
            # Only report clearance time if EVERYONE present reached safety.
            "clearance_time_s": (max((p.arrival_time_s for p in reached), default=0.0)
                                 if full_clear else None),
            "completion_curve": self.completion_curve,
            "bottlenecks": self.net.bottlenecks(top=10),
            "n_trapped_vehicles": len(self.net.trapped),
        }
        if self.disp_result is not None:
            res["dispatch"] = self.disp_result
        res["breakdowns"] = self._breakdowns(present)
        return res

    def _breakdowns(self, present) -> dict:
        """Outcomes by neighborhood (block group), vehicle access, assistance need."""
        def agg(groups):
            out = {}
            for key, plist in groups.items():
                n = len(plist)
                safe = sum(1 for p in plist if p.reached_safety)
                out[key] = {"n": n, "reached": safe,
                            "reached_frac": round(safe / n, 4) if n else None,
                            "exposed": sum(1 for p in plist if p.exposure_time_s > 0)}
            return out

        by_bg, by_veh, by_asst = {}, {}, {}
        for p in present:
            h = self.households[p.hid]
            by_bg.setdefault(h.block_group, []).append(p)
            by_veh.setdefault("no_vehicle" if h.no_vehicle else "has_vehicle", []).append(p)
            by_asst.setdefault("assistance_need" if h.assistance_need else "none", []).append(p)
        return {"by_neighborhood": agg(by_bg),
                "by_vehicle_access": agg(by_veh),
                "by_assistance_need": agg(by_asst)}
