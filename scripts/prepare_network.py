"""Prepare & CHECK the routable mesoscopic network from the downloaded OSM graph.

    python -m scripts.prepare_network --config config/experiments.yaml

Checks (requirement 4): strong connectivity to destinations, disconnected
origins, speed provenance mix. Nothing is silently deleted — problems are
reported.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from altadena_evac.config import load_config, project_path
from altadena_evac.network.mesoscopic import MesoNetwork
from altadena_evac.sim import runner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/experiments.yaml")
    args = ap.parse_args()
    cfg = load_config(args.config)

    G, dests = runner.build_altadena_network(cfg)
    net = MesoNetwork(G, dests)
    print(f"network: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"destinations (nearest nodes to egress points): {sorted(dests)}")

    # speed provenance
    srcs = Counter(d.get("speed_source", "?") for _, _, d in G.edges(data=True))
    print("speed provenance (top):", dict(srcs.most_common(6)))

    # connectivity: how many nodes can reach ANY destination?
    reachable = sum(1 for n in G.nodes if net.is_reachable(n))
    frac = reachable / G.number_of_nodes()
    print(f"nodes able to reach a destination: {reachable}/{G.number_of_nodes()} "
          f"({frac:.3%})")
    if frac < 1.0:
        print("  WARNING: some origins cannot reach safety; households there are "
              "reported (not deleted) at run time.")

    report = {
        "n_nodes": G.number_of_nodes(), "n_edges": G.number_of_edges(),
        "destinations": sorted(dests), "speed_provenance": dict(srcs),
        "nodes_reachable_to_destination": reachable,
        "reachable_fraction": round(frac, 4),
    }
    out = project_path("data", "interim", "network_check.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"wrote network check -> {out}")


if __name__ == "__main__":
    main()
