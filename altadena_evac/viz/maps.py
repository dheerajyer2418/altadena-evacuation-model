"""A map showing origins, roads, destinations, and hazard conditions."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def scenario_map(net, population, hazard_gt, out: str | Path, t_snapshot: float = 1800.0,
                 title="Study map"):
    fig, ax = plt.subplots(figsize=(8, 8))

    # roads (open vs closed at snapshot)
    closed = hazard_gt.closed_links_at(t_snapshot, net)
    for (u, v), link in net.links.items():
        du, dv = net.G.nodes[u], net.G.nodes[v]
        if du.get("lon") is None or dv.get("lon") is None:
            continue
        c = "#cc3311" if (u, v) in closed else "#bbbbbb"
        lw = 1.4 if (u, v) in closed else 0.5
        ax.plot([du["lon"], dv["lon"]], [du["lat"], dv["lat"]], color=c, lw=lw, zorder=1)

    # household origins
    xs = [h.lon for h in population.households]
    ys = [h.lat for h in population.households]
    colors = ["#ee6677" if h.no_vehicle else "#4477aa" for h in population.households]
    ax.scatter(xs, ys, s=6, c=colors, alpha=0.6, zorder=2,
               label="households (red=carless)")

    # destinations
    dxs = [net.G.nodes[n].get("lon") for n in net.destinations]
    dys = [net.G.nodes[n].get("lat") for n in net.destinations]
    ax.scatter(dxs, dys, s=120, marker="*", c="#228833", edgecolor="black",
               zorder=3, label="safety destinations")

    # hazard ignition + front marker (radial only)
    if getattr(hazard_gt, "model", "") == "radial_front":
        ax.scatter([hazard_gt.ig_lon], [hazard_gt.ig_lat], s=150, marker="^",
                   c="#ccbb44", edgecolor="black", zorder=4, label="ignition")

    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(f"{title}  (hazard snapshot t={t_snapshot/60:.0f} min; "
                 f"{len(closed)} links closed)")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out
