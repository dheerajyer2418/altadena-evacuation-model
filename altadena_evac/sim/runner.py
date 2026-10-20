"""Experiment orchestration.

Builds the shared network + ONE population, then runs each (policy, fleet size,
seed) on a deep copy of that population with FRESH, SEPARATE random streams
(behavior / dispatch / hazard) so comparisons are apples-to-apples and
reproducible (requirement 9).
"""
from __future__ import annotations

import copy
import os

import numpy as np

from ..behavior.timeline import BehaviorModel
from ..fleet.dispatch import AVDispatcher
from ..fleet.policies import resolve_policy
from ..hazard.scenario import Forecast, GroundTruthHazard
from ..network.build import load_graphml, make_toy_grid, nearest_node
from ..network.mesoscopic import MesoNetwork
from ..population.donors import make_synthetic
from ..population.placement import place_on_network
from ..population.synthesize import synthesize_population


# --------------------------------------------------------------- network
def build_toy(cfg) -> tuple:
    """4x4 toy grid; destinations = bottom (south) row. Returns (G, destinations)."""
    G = make_toy_grid(rows=4, cols=4)
    cols = 4
    destinations = {(4 - 1) * cols + c for c in range(cols)}  # bottom row
    return G, destinations


def build_altadena_network(cfg) -> tuple:
    net_cfg = cfg["network"]
    study = cfg["study"]
    G = load_graphml(net_cfg["cache"]["graphml"])
    dests = set()
    for pt in study["destinations"]["points"]:
        n = nearest_node(G, pt["lon"], pt["lat"])
        if n is not None:
            dests.add(n)
    return G, dests


# --------------------------------------------------------------- population
def build_offline_population(cfg, seed) -> object:
    """SYNTHETIC population (no Census key needed). Labeled synthetic."""
    coding = cfg["population"]["coding"]
    assistance = cfg["population"]["assistance_need"]
    fit = cfg["population"]["fitting"]
    bg_marginals, donors = make_synthetic(coding, n_block_groups=4,
                                           hh_per_bg=(80, 160), seed=seed)
    pop = synthesize_population(bg_marginals, donors, coding, assistance, fit, seed=seed)
    pop.meta["SOURCE"] = "SYNTHETIC (offline demo) — NOT Altadena Census data"
    return pop


def prepare(cfg, mode: str, seed: int):
    """Return (G, destinations, placed base population) for a run mode.

    mode == 'toy'      : synthetic toy grid + synthetic population.
    mode == 'altadena' : real OSM network (data/interim graphml). Uses the REAL
                         ACS/PUMS Census population + OSM-building placement when
                         CENSUS_API_KEY is set; otherwise a labeled SYNTHETIC
                         population placed on the network.
    """
    if mode == "toy":
        G, dests = build_toy(cfg)
    elif mode == "altadena":
        G, dests = build_altadena_network(cfg)
    else:
        raise ValueError(f"unknown mode {mode}")
    net = MesoNetwork(G, dests)
    rng = np.random.default_rng(seed)

    if mode == "altadena" and os.environ.get("CENSUS_API_KEY"):
        base_pop = bg_gdf = None
        try:
            from ..population.build_real import build_census_population
            base_pop, bg_gdf = build_census_population(cfg, seed=seed)
            print(f"  real population: {base_pop.n_households} hh / "
                  f"{base_pop.n_persons} persons (SRMSE {base_pop.meta.get('mean_srmse')})")
        except Exception as e:  # noqa: BLE001 — synthesis failure -> synthetic fallback
            print(f"  [real population synthesis failed: {type(e).__name__}: {e}]")
            print("  falling back to SYNTHETIC population.")
        if base_pop is not None:
            # Placement failure must NOT discard the real population: fall back to
            # network-node placement (labeled) while keeping the real households.
            try:
                from ..population.build_real import place_real
                place_real(base_pop, net, bg_gdf, cfg["study"], rng)
            except Exception as e:  # noqa: BLE001
                print(f"  [OSM-building placement failed: {type(e).__name__}: {e}; "
                      f"using network-node placement]")
                place_on_network(base_pop, net, rng)
            return G, dests, base_pop

    base_pop = build_offline_population(cfg, seed=seed)
    place_on_network(base_pop, net, rng)
    return G, dests, base_pop


# --------------------------------------------------------------- run one
def _reset_state(pop):
    for p in pop.persons:
        p.reached_safety = False
        p.arrival_time_s = None
        p.exposure_time_s = 0.0
        p.present = True
    for h in pop.households:
        h.aware_time_s = h.prepared_time_s = h.request_time_s = None
        h.departed = h.uses_av = h.stranded = False


def run_single(G, destinations, base_pop, cfg, scenario_cfg, policy_name,
               fleet_size, seeds: dict) -> dict:
    """Run one evacuation. seeds: {behavior, dispatch, hazard} ints."""
    pop = copy.deepcopy(base_pop)
    _reset_state(pop)
    net = MesoNetwork(G, destinations)

    # hazard ground truth + forecast (controller sees forecast only)
    gt = GroundTruthHazard(scenario_cfg)
    forecast = Forecast(gt, scenario_cfg.get("forecast", {}), seed=seeds["hazard"])

    # behavior / demand realization
    bmodel = BehaviorModel(cfg["behavior"])
    rng_b = np.random.default_rng(seeds["behavior"])
    behav_summary = bmodel.assign(pop, gt, fleet_exists=(fleet_size > 0), rng=rng_b)

    # dispatcher (None if no AVs)
    dispatcher = None
    if fleet_size > 0:
        persons = {p.pid: p for p in pop.persons}
        lons = [h.lon for h in pop.households]
        lats = [h.lat for h in pop.households]
        centroid = (float(np.mean(lons)), float(np.mean(lats)))
        policy = resolve_policy(policy_name, cfg["fleet"])
        # optional ablation: toggle retreat behavior
        if scenario_cfg.get("_retreat_changes_override") is not None:
            policy.retreat_changes = scenario_cfg["_retreat_changes_override"]
        max_wait = cfg["behavior"]["mode_choice"]["max_av_wait_before_selfhelp_s"]
        dispatcher = AVDispatcher(
            net, forecast, cfg["fleet"], policy, persons,
            n_vehicles=fleet_size, seats_per_av=cfg["fleet"]["fleet"]["seats_per_av"],
            service_centroid=centroid, max_av_wait_s=max_wait)

    sim = Simulation_factory(pop, net, gt, dispatcher, cfg, scenario_cfg)
    result = sim.run()
    result["meta"] = {
        "policy": policy_name if fleet_size > 0 else "none(no_av)",
        "fleet_size": fleet_size,
        "seeds": dict(seeds),
        "behavior_summary": behav_summary,
        "population_source": base_pop.meta.get("SOURCE", "unknown"),
    }
    return result


def Simulation_factory(pop, net, gt, dispatcher, cfg, scenario_cfg):
    # imported here to avoid a circular import at module load
    from .engine import Simulation
    on_closure = cfg["hazard"].get("on_closure", {}) if "hazard" in cfg else {}
    return Simulation(pop, net, gt, dispatcher, cfg["sim"], on_closure, scenario_cfg)
