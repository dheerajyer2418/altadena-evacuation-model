"""Run ONE evacuation scenario with congestion.

    python -m scripts.run_scenario --scenario baseline_no_av --mode toy
    python -m scripts.run_scenario --scenario baseline_no_av --mode altadena

'altadena' mode requires the OSM network (run scripts.acquire_data first) and uses
the SYNTHETIC population (until a Census key is provided).
"""
from __future__ import annotations

import argparse

from altadena_evac.config import load_config, project_path
from altadena_evac.hazard.scenario import GroundTruthHazard
from altadena_evac.network.mesoscopic import MesoNetwork
from altadena_evac.sim import metrics, runner
from altadena_evac.viz import maps, plots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/experiments.yaml")
    ap.add_argument("--scenario", default="baseline_no_av")
    ap.add_argument("--mode", choices=["toy", "altadena"], default="toy")
    args = ap.parse_args()
    cfg = load_config(args.config)

    sc = cfg["scenarios"][args.scenario]
    hazard_name = sc["hazard"]
    scenario_cfg = cfg["hazard"]["scenarios"][hazard_name]
    fleet_size = sc.get("fleet_size", 0)
    policy = sc.get("policy", "normal")

    G, dests, base_pop = runner.prepare(cfg, args.mode, cfg["sim"]["seeds"]["population"])
    print(f"[{args.mode}] network {G.number_of_nodes()} nodes / {G.number_of_edges()} edges; "
          f"pop {base_pop.n_households} hh / {base_pop.n_persons} persons; "
          f"fleet={fleet_size} policy={policy}")

    seeds = {"behavior": cfg["sim"]["seeds"]["behavior"][0],
             "dispatch": cfg["sim"]["seeds"]["dispatch"][0],
             "hazard": cfg["sim"]["seeds"]["hazard"][0]}
    res = runner.run_single(G, dests, base_pop, cfg, scenario_cfg, policy, fleet_size, seeds)
    row = metrics.summarize(res)
    for k, v in row.items():
        print(f"  {k:28s}: {v}")

    out = project_path("outputs", f"{args.scenario}_{args.mode}")
    out.mkdir(parents=True, exist_ok=True)
    metrics.write_json({k: v for k, v in res.items() if k != "completion_curve"},
                       out / "result.json")
    metrics.write_rows_csv([row], out / "summary.csv")
    plots.completion_curve(res, out / "completion_curve.png",
                           title=f"{args.scenario} ({args.mode})")
    net = MesoNetwork(G, dests)
    maps.scenario_map(net, base_pop, GroundTruthHazard(scenario_cfg),
                      out / "study_map.png", t_snapshot=1800.0,
                      title=f"{args.scenario} ({args.mode})")
    print(f"wrote -> {out}")
    if not res["full_clearance"]:
        print(f"INCOMPLETE CLEARANCE: {res['n_not_reached']} people not at safety "
              f"by horizon (clearance_time withheld).")


if __name__ == "__main__":
    main()
