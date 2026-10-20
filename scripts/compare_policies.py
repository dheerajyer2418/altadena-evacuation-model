"""Compare AV policies on identical population + hazard, repeated across seeds.

    python -m scripts.compare_policies --mode toy
    python -m scripts.compare_policies --mode altadena

Runs the `av_sweep` grid (policies x fleet sizes x seeds) from config/experiments.
Every (policy, fleet) pair sees the SAME base population and hazard; only the
random streams and the policy differ (requirement 9).
"""
from __future__ import annotations

import argparse

from altadena_evac.config import load_config, project_path
from altadena_evac.sim import metrics, runner
from altadena_evac.viz import plots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/experiments.yaml")
    ap.add_argument("--mode", choices=["toy", "altadena"], default="toy")
    ap.add_argument("--max-seeds", type=int, default=3)
    args = ap.parse_args()
    cfg = load_config(args.config)

    sweep = cfg["scenarios"]["av_sweep"]
    scenario_cfg = cfg["hazard"]["scenarios"][sweep["hazard"]]
    policies = sweep["policies"]
    fleets = sweep["fleet_sizes"]

    G, dests, base_pop = runner.prepare(cfg, args.mode, cfg["sim"]["seeds"]["population"])
    seeds_b = cfg["sim"]["seeds"]["behavior"][:args.max_seeds]
    seeds_d = cfg["sim"]["seeds"]["dispatch"][:args.max_seeds]
    seeds_h = cfg["sim"]["seeds"]["hazard"][:args.max_seeds]

    rows = []
    for fleet in fleets:
        pols = ["normal"] if fleet == 0 else policies
        for policy in pols:
            for sb, sd, sh in zip(seeds_b, seeds_d, seeds_h):
                seeds = {"behavior": sb, "dispatch": sd, "hazard": sh}
                res = runner.run_single(G, dests, base_pop, cfg, scenario_cfg,
                                        policy, fleet, seeds)
                row = metrics.summarize(res)
                rows.append(row)
                print(f"fleet={fleet:4d} {policy:20s} seed={sb} "
                      f"reached={row['reached_frac']} "
                      f"carless={row.get('carless_reached_frac')} "
                      f"exposed={row['n_exposed']}")

    out = project_path("outputs", f"compare_{args.mode}")
    out.mkdir(parents=True, exist_ok=True)
    metrics.write_rows_csv(rows, out / "policy_comparison.csv")
    plots.policy_comparison(rows, out / "reached_by_policy.png",
                            metric="reached_frac",
                            title=f"Reached fraction by policy ({args.mode})")
    plots.policy_comparison(rows, out / "carless_reached_by_policy.png",
                            metric="carless_reached_frac",
                            title=f"Carless reached fraction by policy ({args.mode})")
    print(f"\nwrote {len(rows)} rows + plots -> {out}")


if __name__ == "__main__":
    main()
