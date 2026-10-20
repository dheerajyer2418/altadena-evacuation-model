"""Household evacuation timeline (requirement 5).

Five SEPARABLE stages, each a configurable draw (config/behavior.yaml):

    aware_time   = hazard detection + Awareness
    prepared     = aware_time + Preparation
    request_time = prepared + AV-request delay   (AV households only)
    departure    = prepared          (private vehicle households)
                   pickup            (AV households; set by dispatcher)
    arrival      = reaching a safe destination   (set by traffic engine)

Mode: carless households request an AV (if a fleet exists), else they are
"stranded demand" reported explicitly. Households with >=1 usable vehicle drive
themselves. `assistance_need` does NOT force AV use by itself; it is a priority
signal for policies C and D (requirement 2: disability alone implies nothing).

Communication (requirement 7): smartphone ownership is distinct from a
functioning network. If a household lacks a smartphone, or the network is out
when they would request, the configured `no_comms_behavior` applies.
"""
from __future__ import annotations

import math

import numpy as np


def _lognormal(rng: np.random.Generator, median_s: float, sigma: float) -> float:
    mu = math.log(max(median_s, 1.0))
    return float(rng.lognormal(mean=mu, sigma=sigma))


class BehaviorModel:
    def __init__(self, behavior_cfg: dict):
        self.cfg = behavior_cfg
        self.tl = behavior_cfg["timeline"]
        self.comm = behavior_cfg["communication"]
        self.mode = behavior_cfg["mode_choice"]
        self.presence = behavior_cfg.get("presence", {})

    def _network_up(self, t: float) -> bool:
        if not self.comm.get("network_available", True):
            return False
        for w in self.comm.get("outage_windows", []):
            if w["start_s"] <= t < w["end_s"]:
                return False
        return True

    def _next_network_time(self, t: float) -> float:
        nxt = t
        for w in sorted(self.comm.get("outage_windows", []), key=lambda w: w["start_s"]):
            if w["start_s"] <= nxt < w["end_s"]:
                nxt = w["end_s"]
        return nxt

    def assign(self, population, hazard, fleet_exists: bool, rng: np.random.Generator) -> dict:
        """Populate timeline + mode fields on each household in-place.

        Returns a summary dict (counts of private / AV / stranded / no-comms)."""
        det = getattr(hazard, "detection_time_s", 0.0)
        aw = self.tl["awareness"]
        pr = self.tl["preparation"]
        rq = self.tl["av_request_delay"]
        anchor_det = aw.get("anchored_to", "hazard_detection") == "hazard_detection"

        member_present_prob = float(self.presence.get("member_present_prob", 1.0))
        summary = {"private": 0, "av_request": 0, "stranded_no_fleet": 0,
                   "no_comms_blocked": 0, "persons_present": 0}

        # member presence (demand realization)
        pid_to_person = {p.pid: p for p in population.persons}
        for p in population.persons:
            p.present = rng.random() < member_present_prob
            if p.present:
                summary["persons_present"] += 1

        for h in population.households:
            base = det if anchor_det else 0.0
            h.aware_time_s = base + _lognormal(rng, aw["median_s"], aw["sigma"])
            h.prepared_time_s = h.aware_time_s + _lognormal(rng, pr["median_s"], pr["sigma"])

            present_members = [pid for pid in h.members if pid_to_person[pid].present]
            if not present_members:
                h.departed = True   # nobody home; nothing to evacuate from here
                continue

            if h.no_vehicle:
                # needs AV
                if not fleet_exists:
                    h.stranded = True
                    summary["stranded_no_fleet"] += 1
                    continue
                has_phone = rng.random() < self.comm.get("smartphone_ownership_prob", 1.0)
                want_req = h.prepared_time_s + _lognormal(rng, rq["median_s"], rq["sigma"])
                if not has_phone or not self._network_up(want_req):
                    behavior = self.comm.get("no_comms_behavior", "delay_request")
                    if behavior == "cannot_request" or not has_phone:
                        h.stranded = True
                        summary["no_comms_blocked"] += 1
                        continue
                    else:  # delay_request until network returns
                        want_req = max(want_req, self._next_network_time(want_req))
                h.request_time_s = want_req
                h.uses_av = True
                summary["av_request"] += 1
            else:
                h.uses_av = False
                summary["private"] += 1
        return summary
