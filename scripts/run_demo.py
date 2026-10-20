"""Offline end-to-end demonstration.

Runs the FULL pipeline — synthetic population -> toy network -> hazard -> all four
AV policies + no-AV baseline -> metrics, plots, map — with NO internet and NO
credentials. Results are SYNTHETIC TEST RESULTS, not Altadena findings.

    python -m scripts.run_demo
"""
from __future__ import annotations

from pathlib import Path

from altadena_evac.config import load_config, project_path
from altadena_evac.sim import metrics, runner
from altadena_evac.viz import maps, plots


def main():
    cfg = load_config("config/experiments.yaml")
    # smaller horizon/steps are fine for the toy demo
    out = project_path("outputs", "demo")
    out.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("OFFLINE DEMO — SYNTHETIC TEST RESULTS (NOT Altadena findings)")
    print("=" * 70)

    G, dests = runner.build_toy(cfg)
    print(f"toy network: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, "
          f"{len(dests)} destinations")

    base_pop = runner.build_offline_population(cfg, seed=cfg["sim"]["seeds"]["population"])
    print(f"synthetic population: {base_pop.n_households} households, "
          f"{base_pop.n_persons} persons")
    problems = base_pop.check_integrity()
    print(f"population integrity problems: {len(problems)}")
    print(f"mean SRMSE (fit): {base_pop.meta['mean_srmse']}")

    # place households on the toy network (fallback placement, labeled)
    import numpy as np
    rng = np.random.default_rng(cfg["sim"]["seeds"]["population"])
    runner.place_on_network(base_pop, runner.MesoNetwork(G, dests), rng)
    carless = sum(1 for h in base_pop.households if h.no_vehicle)
    print(f"carless households: {carless} / {base_pop.n_households}")

    scenario = cfg["hazard"]["scenarios"]["foothill_santa_ana"]
    # scale the hypothetical front to the toy grid's small extent
    scenario = dict(scenario)
    scenario["ignition"] = {"lat": 34.195, "lon": -118.15}  # just north of toy grid
    scenario["spread"] = dict(scenario["spread"])
    scenario["spread"]["speed_mps"] = 0.15   # slow enough that escape is feasible
    scenario["spread"]["anisotropy"] = 1.5

    rows = []
    results = {}
    runs = [("none", 0)] + [(p, 150) for p in
                            ["normal", "evac_priority", "withdrawal", "adaptive_geofencing"]]
    for policy, fleet in runs:
        seeds = {"behavior": 101, "dispatch": 201, "hazard": 301}
        res = runner.run_single(G, dests, base_pop, cfg, scenario,
                                policy if fleet > 0 else "normal", fleet, seeds)
        row = metrics.summarize(res)
        rows.append(row)
        results[f"{policy}_f{fleet}"] = res
        tag = policy if fleet > 0 else "no_av_baseline"
        print(f"  [{tag:22s}] reached={row['reached_frac']} "
              f"carless_reached={row.get('carless_reached_frac')} "
              f"exposed={row['n_exposed']} trapped_veh={row['n_trapped_vehicles']}")

    metrics.write_rows_csv(rows, out / "demo_comparison.csv")
    metrics.write_json({k: {kk: vv for kk, vv in v.items() if kk != "completion_curve"}
                        for k, v in results.items()}, out / "demo_results.json")

    # plots + map
    plots.completion_curve(results["adaptive_geofencing_f150"],
                           out / "completion_curve.png",
                           title="DEMO (synthetic) — adaptive geofencing")
    plots.policy_comparison(rows, out / "policy_comparison.png",
                            metric="carless_reached_frac",
                            title="DEMO (synthetic): carless reached fraction by policy")
    # map needs a placed population + hazard
    from altadena_evac.hazard.scenario import GroundTruthHazard
    from altadena_evac.network.mesoscopic import MesoNetwork
    net = MesoNetwork(G, dests)
    maps.scenario_map(net, base_pop, GroundTruthHazard(scenario),
                      out / "study_map.png", t_snapshot=600.0,
                      title="DEMO (synthetic toy grid)")

    print(f"\nwrote outputs to {out}")
    print("REMINDER: these are synthetic test results, not Altadena findings.")


if __name__ == "__main__":
    main()
