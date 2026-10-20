"""Result plots. All functions save a PNG and return its path."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def completion_curve(result: dict, out: str | Path, title="Evacuation completion"):
    cc = result.get("completion_curve", [])
    if not cc:
        return None
    t = [c[0] / 60.0 for c in cc]
    n = [c[1] for c in cc]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(t, n, lw=2)
    ax.set_xlabel("time (min)")
    ax.set_ylabel("people reached safety")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def travel_time_hist(result: dict, out: str | Path, title="AV travel times"):
    disp = result.get("dispatch")
    if not disp or not disp.get("travel_times_s"):
        return None
    tt = np.array(disp["travel_times_s"]) / 60.0
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(tt, bins=20, color="#4477aa", edgecolor="white")
    ax.set_xlabel("travel time (min)")
    ax.set_ylabel("AV trips")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def policy_comparison(summary_rows: list[dict], out: str | Path,
                      metric="reached_frac", title="Policy comparison"):
    """summary_rows: [{'policy':, 'fleet_size':, metric:...}]."""
    if not summary_rows:
        return None
    policies = sorted({r["policy"] for r in summary_rows})
    fleets = sorted({r["fleet_size"] for r in summary_rows})
    fig, ax = plt.subplots(figsize=(8, 5))
    width = 0.8 / max(len(policies), 1)
    x = np.arange(len(fleets))
    for i, pol in enumerate(policies):
        vals = []
        for f in fleets:
            match = [r for r in summary_rows if r["policy"] == pol and r["fleet_size"] == f]
            vals.append(np.mean([m[metric] for m in match]) if match else np.nan)
        ax.bar(x + i * width, vals, width, label=pol)
    ax.set_xticks(x + width * (len(policies) - 1) / 2)
    ax.set_xticklabels(fleets)
    ax.set_xlabel("AV fleet size (vehicles)")
    ax.set_ylabel(metric)
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out
