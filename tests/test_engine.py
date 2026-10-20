"""End-to-end engine invariants: person conservation, reproducibility,
chronological event ordering, and correct incomplete-clearance accounting."""
from __future__ import annotations

import numpy as np

from altadena_evac.config import load_config
from altadena_evac.population.donors import make_synthetic
from altadena_evac.population.placement import place_on_network
from altadena_evac.population.synthesize import synthesize_population
from altadena_evac.network.build import make_toy_grid
from altadena_evac.network.mesoscopic import MesoNetwork
from altadena_evac.sim import runner


def _small(cfg, seed=5):
    coding = cfg["population"]["coding"]
    bg, donors = make_synthetic(coding, n_block_groups=1, hh_per_bg=(40, 60), seed=seed)
    pop = synthesize_population(bg, donors, coding, cfg["population"]["assistance_need"],
                                cfg["population"]["fitting"], seed=seed)
    G = make_toy_grid()
    dests = {12, 13, 14, 15}
    place_on_network(pop, MesoNetwork(G, dests), np.random.default_rng(seed))
    return G, dests, pop


def _scenario(cfg):
    scen = dict(cfg["hazard"]["scenarios"]["foothill_santa_ana"])
    scen["ignition"] = {"lat": 34.195, "lon": -118.15}
    scen["spread"] = dict(scen["spread"]); scen["spread"]["speed_mps"] = 0.15
    return scen


def test_person_conservation_and_clearance_flag():
    cfg = load_config("config/experiments.yaml")
    G, dests, pop = _small(cfg)
    scen = _scenario(cfg)
    seeds = {"behavior": 1, "dispatch": 1, "hazard": 1}
    res = runner.run_single(G, dests, pop, cfg, scen, "normal", 50, seeds)
    # everyone present is either reached or not-reached; nobody vanishes
    assert res["n_reached_safety"] + res["n_not_reached"] == res["n_persons_present"]
    # clearance time only reported when full clearance
    if res["full_clearance"]:
        assert res["clearance_time_s"] is not None
    else:
        assert res["clearance_time_s"] is None


def test_reproducible_with_same_seeds():
    cfg = load_config("config/experiments.yaml")
    G, dests, pop = _small(cfg)
    scen = _scenario(cfg)
    seeds = {"behavior": 42, "dispatch": 7, "hazard": 9}
    r1 = runner.run_single(G, dests, pop, cfg, scen, "evac_priority", 40, seeds)
    r2 = runner.run_single(G, dests, pop, cfg, scen, "evac_priority", 40, dict(seeds))
    assert r1["n_reached_safety"] == r2["n_reached_safety"]
    assert r1["total_exposure_person_s"] == r2["total_exposure_person_s"]
    assert r1["dispatch"]["served_persons"] == r2["dispatch"]["served_persons"]


def test_incomplete_clearance_reported_at_short_horizon():
    cfg = load_config("config/experiments.yaml")
    cfg["sim"]["horizon_s"] = 60        # far too short to clear
    cfg["sim"]["step_s"] = 10
    G, dests, pop = _small(cfg)
    scen = _scenario(cfg)
    res = runner.run_single(G, dests, pop, cfg, scen, "normal", 20,
                            {"behavior": 1, "dispatch": 1, "hazard": 1})
    assert res["full_clearance"] is False
    assert res["clearance_time_s"] is None
    assert res["n_not_reached"] > 0


def test_chronological_event_ordering():
    cfg = load_config("config/experiments.yaml")
    G, dests, pop = _small(cfg)
    scen = _scenario(cfg)
    # rebuild a Simulation to inspect its timeline_log
    from altadena_evac.sim.engine import Simulation
    from altadena_evac.hazard.scenario import GroundTruthHazard
    import copy
    from altadena_evac.behavior.timeline import BehaviorModel
    p = copy.deepcopy(pop)
    runner._reset_state(p)
    net = MesoNetwork(G, dests)
    gt = GroundTruthHazard(scen)
    BehaviorModel(cfg["behavior"]).assign(p, gt, fleet_exists=False,
                                          rng=np.random.default_rng(1))
    sim = Simulation(p, net, gt, None, cfg["sim"], {}, scen)
    sim.run()
    times = [ev[0] for ev in sim.timeline_log]
    assert times == sorted(times), "event log not chronological"
