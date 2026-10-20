"""Controlled scenarios proving the four policies make DISTINCT decisions
(requirement 9), plus zero-AV behavior."""
from __future__ import annotations

import numpy as np

from altadena_evac.behavior.timeline import BehaviorModel
from altadena_evac.config import load_config
from altadena_evac.fleet.dispatch import AVDispatcher
from altadena_evac.fleet.policies import resolve_policy
from altadena_evac.hazard.scenario import Forecast, GroundTruthHazard
from altadena_evac.network.build import make_toy_grid
from altadena_evac.network.mesoscopic import MesoNetwork
from tests.conftest import make_population


def _setup(policy_name, fire_everywhere=False, trigger_override=None):
    cfg = load_config("config/experiments.yaml")
    G = make_toy_grid()
    dests = {12, 13, 14, 15}
    net = MesoNetwork(G, dests)
    scen = dict(cfg["hazard"]["scenarios"]["foothill_santa_ana"])
    scen["ignition"] = {"lat": 34.19, "lon": -118.15}
    scen["spread"] = dict(scen["spread"])
    if fire_everywhere:
        scen["spread"]["speed_mps"] = 1000.0     # arrival ~0 everywhere
    gt = GroundTruthHazard(scen)
    forecast = Forecast(gt, {"perfect_information": True, "safety_margin_s": 0,
                             "lead_time_s": 0}, seed=0)
    pop = make_population([{"node": 5, "vehicles": 0, "assistance": True, "size": 2}])
    persons = {p.pid: p for p in pop.persons}
    policy = resolve_policy(policy_name, cfg["fleet"])
    if trigger_override is not None:
        policy.withdrawal_trigger_value = trigger_override
    disp = AVDispatcher(net, forecast, cfg["fleet"], policy, persons,
                        n_vehicles=1, seats_per_av=4,
                        service_centroid=(-118.15, 34.19), max_av_wait_s=99999)
    return cfg, net, disp, pop


def test_geofencing_rejects_infeasible_trip_that_normal_accepts():
    # NORMAL: no screening -> request gets assigned even into a hazard.
    _, _, disp_n, pop_n = _setup("normal", fire_everywhere=True)
    disp_n.submit_household(pop_n.households[0], [0, 1], now=0.0)
    disp_n.tick(0.0, 10.0)
    assert any(r.status != "pending" for r in disp_n.requests.values()), \
        "normal policy should assign the trip"

    # ADAPTIVE GEOFENCING: screens against forecast -> rejects, stays pending.
    _, _, disp_g, pop_g = _setup("adaptive_geofencing", fire_everywhere=True)
    disp_g.submit_household(pop_g.households[0], [0, 1], now=0.0)
    disp_g.tick(0.0, 10.0)
    assert all(r.status == "pending" for r in disp_g.requests.values()), \
        "geofencing should reject an infeasible trip"


def test_withdrawal_stops_new_pickups():
    _, _, disp, pop = _setup("withdrawal", trigger_override=1e12)  # trigger immediately
    disp.submit_household(pop.households[0], [0, 1], now=0.0)
    disp.tick(0.0, 10.0)
    assert disp.withdrawn is True
    # no NEW assignment made while withdrawn
    assert all(r.status in ("pending", "unserved") for r in disp.requests.values())


def test_normal_serves_when_feasible():
    _, _, disp, pop = _setup("normal", fire_everywhere=False)
    disp.submit_household(pop.households[0], [0, 1], now=0.0)
    disp.tick(0.0, 10.0)
    assert any(r.status == "assigned" for r in disp.requests.values())


def test_zero_av_strands_carless():
    cfg = load_config("config/experiments.yaml")
    pop = make_population([{"node": 5, "vehicles": 0, "size": 2},
                           {"node": 6, "vehicles": 1, "size": 2}])
    gt = GroundTruthHazard(cfg["hazard"]["scenarios"]["foothill_santa_ana"])
    bmodel = BehaviorModel(cfg["behavior"])
    summary = bmodel.assign(pop, gt, fleet_exists=False, rng=np.random.default_rng(0))
    assert summary["stranded_no_fleet"] >= 1
    carless = [h for h in pop.households if h.no_vehicle]
    assert all(h.stranded for h in carless), "carless must be stranded with no fleet"
