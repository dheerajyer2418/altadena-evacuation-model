"""Traffic-assumption sensitivity sweep.

    python -m scripts.sweep_traffic --mode toy
    python -m scripts.sweep_traffic --mode altadena --capacities 1000 1500 1800 2000 \
        --fleets 0 300 --max-seeds 1

Why this exists
---------------
The traffic model is UNCALIBRATED (see VALIDATION_REPORT.md section 3): per-lane
saturation flow (default 1800 veh/h/lane) and jam density (default 130 veh/km/lane)
are assumptions, not measured Altadena values. The no-AV baseline is also
congestion-dominated (top-link saturation 1.0), so those assumptions could drive
even the RELATIVE policy comparison, not just absolute numbers.

This script re-runs the policy comparison across a grid of capacity / jam-density
values on the SAME population, hazard, and seeds (only the traffic parameters
change) and reports whether the AV-policy ranking for carless households is
ROBUST to the traffic assumptions. A stable ranking lets you claim the finding
survives the uncalibrated traffic; an unstable ranking tells you calibration is
worth the effort before publishing.

How the parameters are injected
-------------------------------
capacity_veh_s and storage_veh bake into the cached graphml at build time
(network.build.attach_meso_attributes). Both are LINEAR in the swept parameters:

    capacity_veh_s = per_lane_veh_hour * lanes / 3600
    storage_veh    = jam_density * lanes * (length_m / 1000)

so we rescale each edge from its as-built baseline by the ratio to the config's
base value. This preserves all per-edge lane/length heterogeneity and needs no
OSM re-download. (Assumes the cached graphml was built with the base values in
config/network.yaml, which is how acquire_data/make_toy_grid produce it.)
"""
from __future__ import annotations

import argparse

from altadena_evac.config import load_config, project_path
from altadena_evac.sim import metrics, runner

DEFAULT_POLICIES = ["withdrawal", "normal", "evac_priority", "adaptive_geofencing"]


def _capture_baseline(G) -> dict:
    """Snapshot each edge's as-built (capacity_veh_s, storage_veh)."""
    return {(u, v): (float(d["capacity_veh_s"]), float(d["storage_veh"]))
            for u, v, d in G.edges(data=True)}


def _apply_traffic(G, baseline: dict, cap_ratio: float, jam_ratio: float) -> None:
    """Rescale every edge's discharge capacity and storage in place.

    Always computed from the captured baseline (never from the current mutated
    state) so repeated grid points are independent."""
    for u, v, d in G.edges(data=True):
        base_cap, base_sto = baseline[(u, v)]
        d["capacity_veh_s"] = base_cap * cap_ratio
        d["storage_veh"] = max(1.0, base_sto * jam_ratio)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/experiments.yaml")
    ap.add_argument("--mode", choices=["toy", "altadena"], default="toy")
    ap.add_argument("--capacities", type=float, nargs="+",
                    default=[1000, 1500, 1800, 2000],
                    help="per-lane saturation flow values (veh/h/lane) to sweep")
    ap.add_argument("--jam-densities", type=float, nargs="+", default=[130],
                    help="jam density values (veh/km/lane) to sweep")
    ap.add_argument("--fleets", type=int, nargs="+", default=[0, 300],
                    help="AV fleet sizes (0 = no-AV baseline)")
    ap.add_argument("--policies", nargs="+", default=DEFAULT_POLICIES)
    ap.add_argument("--max-seeds", type=int, default=2)
    ap.add_argument("--hazard", default=None,
                    help="hazard scenario name (default: the av_sweep hazard)")
    ap.add_argument("--rank-metric", default="carless_reached_frac",
                    help="metric used to rank policies (research focus)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    hazard_name = args.hazard or cfg["scenarios"]["av_sweep"]["hazard"]
    scenario_cfg = cfg["hazard"]["scenarios"][hazard_name]

    base_cap = float(cfg["network"]["edges"]["capacity"]["per_lane_veh_hour"])
    base_jam = float(cfg["network"]["edges"]["capacity"]["jam_density_veh_km_lane"])

    # ONE population + network, reused for every grid point (apples-to-apples).
    G, dests, base_pop = runner.prepare(cfg, args.mode, cfg["sim"]["seeds"]["population"])
    baseline = _capture_baseline(G)
    seeds_b = cfg["sim"]["seeds"]["behavior"][:args.max_seeds]
    seeds_d = cfg["sim"]["seeds"]["dispatch"][:args.max_seeds]
    seeds_h = cfg["sim"]["seeds"]["hazard"][:args.max_seeds]

    print(f"[{args.mode}] {G.number_of_nodes()} nodes / {G.number_of_edges()} edges; "
          f"pop {base_pop.n_households} hh / {base_pop.n_persons} persons; "
          f"hazard={hazard_name}")
    print(f"base capacity={base_cap:.0f} veh/h/lane, jam={base_jam:.0f} veh/km/lane")
    print(f"sweep: capacities={args.capacities} jam={args.jam_densities} "
          f"fleets={args.fleets} policies={args.policies} seeds={len(seeds_b)}\n")

    rows = []
    # aggregated[(cap, jam, fleet, policy)] -> list of rank-metric values over seeds
    aggregated: dict = {}
    for cap in args.capacities:
        for jam in args.jam_densities:
            _apply_traffic(G, baseline, cap / base_cap, jam / base_jam)
            for fleet in args.fleets:
                pols = ["normal"] if fleet == 0 else args.policies
                for policy in pols:
                    vals = []
                    for sb, sd, sh in zip(seeds_b, seeds_d, seeds_h):
                        seeds = {"behavior": sb, "dispatch": sd, "hazard": sh}
                        res = runner.run_single(G, dests, base_pop, cfg, scenario_cfg,
                                                policy, fleet, seeds)
                        row = metrics.summarize(res)
                        row = {"per_lane_veh_hour": cap, "jam_density": jam, **row}
                        rows.append(row)
                        vals.append(row.get(args.rank_metric))
                        print(f"cap={cap:5.0f} jam={jam:3.0f} fleet={fleet:4d} "
                              f"{policy:20s} seed={sb} "
                              f"reached={row['reached_frac']} "
                              f"carless={row.get('carless_reached_frac')}")
                    aggregated[(cap, jam, fleet, policy)] = vals

    out = project_path("outputs", f"sweep_traffic_{args.mode}")
    out.mkdir(parents=True, exist_ok=True)
    metrics.write_rows_csv(rows, out / "sweep_results.csv")

    ranking_rows, verdict = _analyze_ranking(aggregated, args, base_cap, base_jam)
    metrics.write_rows_csv(ranking_rows, out / "ranking_by_grid_point.csv")

    print("\n" + "=" * 72)
    print("ROBUSTNESS OF THE POLICY RANKING (by %s)" % args.rank_metric)
    print("=" * 72)
    for line in verdict:
        print(line)
    _plot(aggregated, args, out)
    print(f"\nwrote {len(rows)} run rows + ranking + plots -> {out}")


def _analyze_ranking(aggregated, args, base_cap, base_jam):
    """For each (jam, fleet>0): rank policies by the mean rank-metric at every
    capacity and report whether the order (and the top policy) is stable."""
    ranking_rows = []
    verdict = []
    fleets = [f for f in args.fleets if f > 0]
    for jam in args.jam_densities:
        for fleet in fleets:
            orders = []          # ordered policy tuples, one per capacity
            tops = []
            for cap in args.capacities:
                scored = []
                for policy in args.policies:
                    m = _mean(aggregated.get((cap, jam, fleet, policy), []))
                    scored.append((policy, m))
                # rank by metric desc; None sorts last
                scored.sort(key=lambda t: (t[1] is None, -(t[1] or 0.0)))
                order = tuple(p for p, _ in scored)
                orders.append(order)
                tops.append(order[0])
                ranking_rows.append({
                    "jam_density": jam, "fleet_size": fleet,
                    "per_lane_veh_hour": cap,
                    "ranking_best_to_worst": " > ".join(
                        f"{p}({'' if m is None else round(m, 3)})" for p, m in scored),
                    "top_policy": order[0],
                })
            order_stable = len(set(orders)) == 1
            top_stable = len(set(tops)) == 1
            tag = f"jam={jam:.0f}, fleet={fleet}"
            if order_stable:
                verdict.append(f"  [{tag}] STABLE -- identical full ranking at every "
                               f"capacity: {' > '.join(orders[0])}")
            elif top_stable:
                verdict.append(f"  [{tag}] TOP STABLE -- best policy is always "
                               f"'{tops[0]}', but lower-rank order shifts.")
            else:
                verdict.append(f"  [{tag}] UNSTABLE -- best policy changes with "
                               f"capacity: {dict(zip(args.capacities, tops))}")
    if not fleets:
        verdict.append("  (no fleet>0 in --fleets, nothing to rank)")
    return ranking_rows, verdict


def _plot(aggregated, args, out):
    """One line plot per (jam, fleet>0): rank-metric vs capacity, line per policy."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001 — plotting is optional
        print(f"[plot skipped: {type(e).__name__}: {e}]")
        return
    for jam in args.jam_densities:
        for fleet in [f for f in args.fleets if f > 0]:
            fig, ax = plt.subplots(figsize=(7, 4.5))
            for policy in args.policies:
                ys = [_mean(aggregated.get((cap, jam, fleet, policy), []))
                      for cap in args.capacities]
                ax.plot(args.capacities, ys, marker="o", label=policy)
            ax.set_xlabel("per-lane saturation flow (veh/h/lane)")
            ax.set_ylabel(args.rank_metric)
            ax.set_title(f"Policy robustness to traffic capacity "
                         f"(jam={jam:.0f}, fleet={fleet})")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            fig.savefig(out / f"robustness_jam{jam:.0f}_fleet{fleet}.png", dpi=120)
            plt.close(fig)


if __name__ == "__main__":
    main()
