"""Hazard randomization sweep (Monte Carlo over fire geometry).

    python -m scripts.sweep_hazard --mode toy
    python -m scripts.sweep_hazard --mode altadena --n 20 --fleets 0 300 --max-seeds 1

Why this exists
---------------
The ground-truth fire is currently a single fixed front. Different fires ignite
in different places and run along different axes, hitting the road network in
very different ways. This script randomizes WHERE the fire starts and its SPREAD
AXIS (plus anisotropy and speed), runs the model many times on the SAME
population + network + seeds, and reports how outcomes vary -- and, crucially,
whether the AV-policy ranking for CARLESS households is robust to fire geometry
(the same robustness logic as scripts/sweep_traffic.py, applied to the hazard).

Two fire sets are generated and compared (docs/HAZARD_RANDOMIZATION_PLAN.md):
  foothills : realistic northern-band origin, spread biased south.
  unbiased  : ignite anywhere, any axis (stress test).

Only the ground-truth fire varies between realizations; the forecast-error seed
is held fixed, so differences are attributable to fire geometry alone.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from altadena_evac.config import load_config, project_path
from altadena_evac.hazard import sampler
from altadena_evac.sim import metrics, runner

DEFAULT_POLICIES = ["withdrawal", "normal", "evac_priority", "adaptive_geofencing"]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def _pct(xs, q):
    xs = [x for x in xs if x is not None]
    return float(np.percentile(xs, q)) if xs else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/experiments.yaml")
    ap.add_argument("--mode", choices=["toy", "altadena"], default="toy")
    ap.add_argument("--sets", nargs="+", default=["foothills", "unbiased"],
                    choices=["foothills", "unbiased"])
    ap.add_argument("--n", type=int, default=20,
                    help="fire realizations per set")
    ap.add_argument("--fleets", type=int, nargs="+", default=[0, 300])
    ap.add_argument("--policies", nargs="+", default=DEFAULT_POLICIES)
    ap.add_argument("--max-seeds", type=int, default=1)
    ap.add_argument("--sample-seed", type=int, default=7,
                    help="master seed for the fire sampler (reproducible)")
    ap.add_argument("--rank-metric", default="carless_reached_frac",
                    help="metric used to rank policies (research focus)")
    args = ap.parse_args()

    # Make progress visible when stdout is redirected to a file (block-buffered
    # by default): line-buffer so the heartbeat below appears in real time.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001 — best-effort; never fatal
        pass

    cfg = load_config(args.config)
    base_scenario = cfg["hazard"]["scenarios"][cfg["scenarios"]["av_sweep"]["hazard"]]

    # ONE population + network, reused for every realization (apples-to-apples).
    G, dests, base_pop = runner.prepare(cfg, args.mode, cfg["sim"]["seeds"]["population"])
    seeds_b = cfg["sim"]["seeds"]["behavior"][:args.max_seeds]
    seeds_d = cfg["sim"]["seeds"]["dispatch"][:args.max_seeds]
    seeds_h = cfg["sim"]["seeds"]["hazard"][:args.max_seeds]

    # Ignition region: real demand bbox for altadena, the grid's own bbox for toy.
    if args.mode == "altadena" and cfg.get("study", {}).get("boundary", {}).get("demand_bbox"):
        b = cfg["study"]["boundary"]["demand_bbox"]
        bbox = (b["west"], b["south"], b["east"], b["north"])
    else:
        bbox = sampler.bbox_from_graph(G)

    print(f"[{args.mode}] {G.number_of_nodes()} nodes / {G.number_of_edges()} edges; "
          f"pop {base_pop.n_households} hh / {base_pop.n_persons} persons")
    print(f"ignition bbox (W,S,E,N) = ({bbox[0]:.4f}, {bbox[1]:.4f}, "
          f"{bbox[2]:.4f}, {bbox[3]:.4f})")
    per_real = sum(1 if f == 0 else len(args.policies) for f in args.fleets)
    total_runs = len(args.sets) * args.n * per_real * len(seeds_b)
    print(f"sweep: sets={args.sets} n={args.n}/set fleets={args.fleets} "
          f"policies={args.policies} seeds={len(seeds_b)} -> {total_runs} runs\n")
    t0 = time.time()
    done = 0

    rows = []
    # aggregated[(set, fleet, policy, real_id)] -> list of rank-metric over seeds
    aggregated: dict = {}
    # baseline reached_frac per (set, real_id) for the ignition map
    baseline_reached: dict = {}
    for si, set_name in enumerate(args.sets):
        reals = sampler.sample_realizations(set_name, args.n, bbox,
                                            seed=args.sample_seed + si)
        for real in reals:
            scenario_cfg = sampler.apply_realization(base_scenario, real)
            for fleet in args.fleets:
                pols = ["normal"] if fleet == 0 else args.policies
                for policy in pols:
                    vals, reached_vals = [], []
                    for sb, sd, sh in zip(seeds_b, seeds_d, seeds_h):
                        seeds = {"behavior": sb, "dispatch": sd, "hazard": sh}
                        res = runner.run_single(G, dests, base_pop, cfg, scenario_cfg,
                                                policy, fleet, seeds)
                        row = metrics.summarize(res)
                        row = {"set": set_name, "realization": real["id"],
                               "policy_req": policy,
                               "ignition_lon": round(real["ignition_lon"], 5),
                               "ignition_lat": round(real["ignition_lat"], 5),
                               "direction_bias_deg": round(real["direction_bias_deg"], 1),
                               "anisotropy": round(real["anisotropy"], 3),
                               "fire_speed_mps": round(real["speed_mps"], 3),
                               **row}
                        rows.append(row)
                        vals.append(row.get(args.rank_metric))
                        reached_vals.append(row.get("reached_frac"))
                        done += 1
                        el = time.time() - t0
                        eta = (el / done) * (total_runs - done)
                        print(f"  [{done:3d}/{total_runs}] {set_name} real "
                              f"{real['id']} fleet={fleet} {policy}: "
                              f"reached={row['reached_frac']} "
                              f"carless={row.get('carless_reached_frac')} "
                              f"({el/60:.1f}m elapsed, ~{eta/60:.0f}m left)")
                    aggregated[(set_name, fleet, policy, real["id"])] = vals
                    if fleet == 0:
                        baseline_reached[(set_name, real["id"])] = (
                            real["ignition_lon"], real["ignition_lat"],
                            _mean(reached_vals))
            print(f"[{set_name}] real {real['id']:3d} "
                  f"ign=({real['ignition_lat']:.4f},{real['ignition_lon']:.4f}) "
                  f"axis={real['direction_bias_deg']:5.1f} "
                  f"aniso={real['anisotropy']:.2f} v={real['speed_mps']:.2f}")

    out = project_path("outputs", f"sweep_hazard_{args.mode}")
    out.mkdir(parents=True, exist_ok=True)
    metrics.write_rows_csv(rows, out / "hazard_runs.csv")

    ranking_rows, verdict = _analyze(aggregated, args)
    metrics.write_rows_csv(ranking_rows, out / "hazard_ranking.csv")

    print("\n" + "=" * 72)
    print("ROBUSTNESS OF THE POLICY RANKING ACROSS FIRE GEOMETRY (by %s)"
          % args.rank_metric)
    print("=" * 72)
    for line in verdict:
        print(line)
    _plot(aggregated, baseline_reached, args, out)
    print(f"\nwrote {len(rows)} run rows + ranking + plots -> {out}")


def _analyze(aggregated, args):
    """Per (set, fleet>0): for each fire realization rank policies by the mean
    rank-metric and tally how often each policy wins. One policy winning every
    realization = STABLE; otherwise report win-rates."""
    eps = 1e-9
    ranking_rows = []
    verdict = []
    fleets = [f for f in args.fleets if f > 0]
    for set_name in args.sets:
        for fleet in fleets:
            real_ids = sorted({rid for (s, fl, p, rid) in aggregated
                               if s == set_name and fl == fleet})
            win = {p: 0 for p in args.policies}
            per_policy_vals = {p: [] for p in args.policies}
            ties = 0
            for rid in real_ids:
                scored = []
                for policy in args.policies:
                    m = _mean(aggregated.get((set_name, fleet, policy, rid), []))
                    scored.append((policy, m))
                    per_policy_vals[policy].append(m)
                scored.sort(key=lambda t: (t[1] is None, -(t[1] or 0.0)))
                top_v = scored[0][1]
                second_v = scored[1][1] if len(scored) > 1 else None
                # Only credit a win if the top policy is STRICTLY better than the
                # next; otherwise it's a tie (don't let sort order fake a winner).
                if top_v is None or (second_v is not None
                                     and (top_v - second_v) <= eps):
                    ties += 1
                else:
                    win[scored[0][0]] += 1
            n_real = len(real_ids)
            for policy in args.policies:
                vals = per_policy_vals[policy]
                ranking_rows.append({
                    "set": set_name, "fleet_size": fleet, "policy": policy,
                    "n_realizations": n_real,
                    "win_count": win[policy],
                    "win_rate": round(win[policy] / n_real, 3) if n_real else None,
                    f"{args.rank_metric}_mean": round(_mean(vals), 4) if _mean(vals) is not None else None,
                    f"{args.rank_metric}_p10": round(_pct(vals, 10), 4) if _pct(vals, 10) is not None else None,
                    f"{args.rank_metric}_median": round(_pct(vals, 50), 4) if _pct(vals, 50) is not None else None,
                    f"{args.rank_metric}_p90": round(_pct(vals, 90), 4) if _pct(vals, 90) is not None else None,
                })
            winners = [p for p in args.policies if win[p] > 0]
            tag = f"set={set_name}, fleet={fleet}, {n_real} fires"
            tie_note = f" ({ties} tie(s))" if ties else ""
            if ties == n_real:
                verdict.append(f"  [{tag}] ALL TIED -- policies indistinguishable "
                               f"on these fires (likely no AV benefit realized).")
            elif len(winners) == 1:
                verdict.append(f"  [{tag}] STABLE -- '{winners[0]}' wins "
                               f"{win[winners[0]]}/{n_real} fires{tie_note}; "
                               f"no other policy ever wins.")
            else:
                share = {p: f"{win[p]}/{n_real}" for p in winners}
                best = max(winners, key=lambda p: win[p])
                verdict.append(f"  [{tag}] MIXED -- winner varies by fire: {share}"
                               f"{tie_note} (most-frequent: '{best}').")
    if not fleets:
        verdict.append("  (no fleet>0 in --fleets, nothing to rank)")
    return ranking_rows, verdict


def _plot(aggregated, baseline_reached, args, out):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001 — plotting is optional
        print(f"[plot skipped: {type(e).__name__}: {e}]")
        return
    # 1. distribution of rank-metric across fires, one box per policy, per (set, fleet)
    for set_name in args.sets:
        for fleet in [f for f in args.fleets if f > 0]:
            data, labels = [], []
            for policy in args.policies:
                vals = []
                for (s, fl, p, rid), xs in aggregated.items():
                    if s == set_name and fl == fleet and p == policy:
                        m = _mean(xs)
                        if m is not None:
                            vals.append(m)
                if vals:
                    data.append(vals)
                    labels.append(policy)
            if not data:
                continue
            fig, ax = plt.subplots(figsize=(7, 4.5))
            ax.boxplot(data, showmeans=True)   # label via set_xticklabels (version-safe)
            ax.set_xticks(range(1, len(labels) + 1))
            ax.set_xticklabels(labels, rotation=20)
            ax.set_ylabel(args.rank_metric)
            ax.set_title(f"Outcome spread across {set_name} fires (fleet={fleet})")
            ax.grid(True, axis="y", alpha=0.3)
            fig.tight_layout()
            fig.savefig(out / f"dist_{set_name}_fleet{fleet}.png", dpi=120)
            plt.close(fig)
    # 2. ignition map: ignition location colored by baseline (no-AV) reached_frac,
    #    showing which fire origins are most dangerous.
    if baseline_reached:
        for set_name in args.sets:
            pts = [(lon, lat, v) for (s, _rid), (lon, lat, v)
                   in baseline_reached.items() if s == set_name and v is not None]
            if not pts:
                continue
            lons = [p[0] for p in pts]
            lats = [p[1] for p in pts]
            vals = [p[2] for p in pts]
            fig, ax = plt.subplots(figsize=(6, 5))
            sc = ax.scatter(lons, lats, c=vals, cmap="RdYlGn", vmin=0, vmax=1,
                            s=60, edgecolor="k", linewidth=0.3)
            fig.colorbar(sc, ax=ax, label="baseline reached_frac (no-AV)")
            ax.set_xlabel("ignition lon")
            ax.set_ylabel("ignition lat")
            ax.set_title(f"Where the fire starts vs. no-AV outcome ({set_name})")
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            fig.savefig(out / f"ignition_map_{set_name}.png", dpi=120)
            plt.close(fig)


if __name__ == "__main__":
    main()
