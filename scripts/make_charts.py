"""Render result charts as PNGs for the web app (and anywhere images are handy).

    python -m scripts.make_charts     # -> outputs/ui/charts/*.png

Charts (built only from data we have — scenario summaries, replay frames, and the
population fit report):
  reached_vs_carless.png     grouped bar: overall vs. carless reached
  left_behind_exposed.png    grouped bar: not-reached vs. exposed share
  completion_over_time.png   line: % reached vs. minutes, per scenario
  population_fit.png         bar: synthesis fit error per neighborhood
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from altadena_evac.config import project_path  # noqa: E402

UI = project_path("outputs", "ui")
OUT = UI / "charts"
PALETTE = ["#2b8cbe", "#e0a500", "#d6604d", "#1a8a4a", "#7b5bd6"]
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.alpha": 0.25,
                     "figure.autolayout": True})


def _index() -> dict:
    p = UI / "index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _short(label: str) -> str:
    s = label.replace("baseline", "").replace("(real roads, synthetic pop)", "(synth)")
    s = s.replace("(REAL population)", "(REAL)").replace("Evacuation-priority", "Evac-priority")
    s = s.replace("  ", " ").strip(" -")
    return s[:26]


def _scenarios():
    idx = _index()
    out = []
    for e in idx.values():
        s = e.get("summary", {})
        pres = s.get("n_present") or 0
        out.append({
            "label": _short(e.get("label", e.get("id"))),
            "file": e["file"],
            "reached": s.get("reached_frac") or 0,
            "carless": s.get("carless_reached_frac") or 0,
            "not_reached": 1 - (s.get("reached_frac") or 0),
            "exposed": (s.get("n_exposed") or 0) / pres if pres else 0,
        })
    return out


def _grouped_bar(scen, keys, labels, title, fname, ylabel="fraction of people"):
    n = len(scen)
    x = np.arange(n)
    w = 0.8 / len(keys)
    fig, ax = plt.subplots(figsize=(9, 4.4), dpi=120)
    for i, (k, lab) in enumerate(zip(keys, labels)):
        ax.bar(x + (i - (len(keys) - 1) / 2) * w, [s[k] for s in scen], w,
               label=lab, color=PALETTE[i], edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels([s["label"] for s in scen], rotation=18, ha="right", fontsize=9)
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, 1)
    ax.set_title(title, fontweight="bold")
    ax.legend(fontsize=9)
    fig.savefig(OUT / fname)
    plt.close(fig)


def _completion(scen):
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=120)
    for i, s in enumerate(scen):
        try:
            rep = json.loads((UI / s["file"]).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        xs, ys = [], []
        for fr in rep.get("frames", []):
            st = fr.get("stats", {})
            pres = st.get("present") or 0
            xs.append(fr.get("t", 0) / 60.0)
            ys.append((st.get("reached", 0) / pres) if pres else 0)
        if xs:
            ax.plot(xs, ys, label=s["label"], color=PALETTE[i % len(PALETTE)], lw=2)
    ax.set_xlabel("minutes since fire start")
    ax.set_ylabel("fraction reached safety")
    ax.set_ylim(0, 1)
    ax.set_title("Evacuation completion over time", fontweight="bold")
    ax.legend(fontsize=9)
    fig.savefig(OUT / "completion_over_time.png")
    plt.close(fig)


def _population_fit():
    p = project_path("data", "processed", "population_fit_report.json")
    if not p.exists():
        return
    rep = json.loads(p.read_text(encoding="utf-8"))
    pbg = rep.get("per_block_group_fit", {})
    if not pbg:
        return
    items = sorted(pbg.items(), key=lambda kv: kv[1].get("srmse", 0), reverse=True)
    vals = [v.get("srmse", 0) for _, v in items]
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=120)
    ax.bar(range(len(vals)), vals, color="#2b8cbe", edgecolor="white")
    ax.set_xlabel("Altadena neighborhoods (block groups), worst-fit first")
    ax.set_ylabel("fit error (SRMSE, lower = better)")
    ax.set_title("Synthetic-population fit error by neighborhood", fontweight="bold")
    ax.set_xticks([])
    mean = float(np.mean(vals))
    ax.axhline(mean, color="#d6604d", ls="--", lw=1.5, label=f"mean {mean:.3f}")
    ax.legend(fontsize=9)
    fig.savefig(OUT / "population_fit.png")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    scen = _scenarios()
    if not scen:
        print("No scenarios found (outputs/ui/index.json). Run export_replay first.")
        return
    _grouped_bar(scen, ["reached", "carless"], ["Everyone", "Carless households"],
                 "Who reaches safety: overall vs. carless", "reached_vs_carless.png")
    _grouped_bar(scen, ["not_reached", "exposed"], ["Not reached", "Exposed to fire"],
                 "Left behind & exposed (share of people)", "left_behind_exposed.png")
    _completion(scen)
    _population_fit()
    made = sorted(p.name for p in OUT.glob("*.png"))
    print(f"wrote {len(made)} charts -> {OUT}")
    for m in made:
        print("  ", m)


if __name__ == "__main__":
    main()
