"""Run a scenario, record it, and export a replay JSON for the live UI.

    python -m scripts.export_replay --mode altadena --policy normal --fleet 300 --label "Normal 300 AVs"
    python -m scripts.export_replay --mode altadena --fleet 0 --label "No-AV baseline"

Writes outputs/ui/replay_<id>.json and updates outputs/ui/index.json (the list the
UI reads). Run it a few times with different policies/fleets to populate the
scenario buttons. With CENSUS_API_KEY set and --mode altadena, the REAL population
is used; otherwise a labeled synthetic population.
"""
from __future__ import annotations

import argparse
import json
import re

from altadena_evac.config import load_config, project_path
from altadena_evac.sim import metrics, runner
from altadena_evac.viz.replay import build_replay


def _toy_scenario(cfg):
    scen = dict(cfg["hazard"]["scenarios"]["foothill_santa_ana"])
    scen["ignition"] = {"lat": 34.195, "lon": -118.15}
    scen["spread"] = dict(scen["spread"])
    scen["spread"]["speed_mps"] = 0.15
    scen["spread"]["anisotropy"] = 1.5
    return scen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/experiments.yaml")
    ap.add_argument("--mode", choices=["toy", "altadena"], default="altadena")
    ap.add_argument("--hazard", default="foothill_santa_ana")
    ap.add_argument("--policy", default="normal")
    ap.add_argument("--fleet", type=int, default=0)
    ap.add_argument("--label", default=None)
    ap.add_argument("--record-every", type=float, default=30.0, dest="record_every")
    ap.add_argument("--max-render", type=int, default=4000, dest="max_render")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    seed = args.seed if args.seed is not None else cfg["sim"]["seeds"]["population"]
    scenario_cfg = (_toy_scenario(cfg) if args.mode == "toy"
                    else cfg["hazard"]["scenarios"][args.hazard])

    G, dests, base_pop = runner.prepare(cfg, args.mode, seed)
    pol = args.policy if args.fleet > 0 else "none(no_av)"
    label = args.label or f"{pol} / fleet {args.fleet} ({args.mode})"
    print(f"running '{label}': {base_pop.n_households} hh / {base_pop.n_persons} persons")

    seeds = {"behavior": cfg["sim"]["seeds"]["behavior"][0],
             "dispatch": cfg["sim"]["seeds"]["dispatch"][0],
             "hazard": cfg["sim"]["seeds"]["hazard"][0]}
    result, sim = runner.run_single(
        G, dests, base_pop, cfg, scenario_cfg,
        args.policy if args.fleet > 0 else "normal", args.fleet, seeds,
        record_every_s=args.record_every, max_render=args.max_render, return_sim=True)

    row = metrics.summarize(result)
    replay_meta = {
        "label": label, "mode": args.mode, "policy": pol, "fleet": args.fleet,
        "population_source": result["meta"]["population_source"],
        "summary": row, "horizon_s": cfg["sim"]["horizon_s"],
        "record_every_s": args.record_every,
        "rendered_vehicle_cap": args.max_render,
        "note": ("SYNTHETIC" if "SYNTHETIC" in result["meta"]["population_source"]
                 else "real ACS/PUMS") + " population; hypothetical hazard; "
                 "uncalibrated traffic — relative comparison only.",
    }
    replay = build_replay(sim.net, base_pop, scenario_cfg, sim.frames, replay_meta)

    out_dir = project_path("outputs", "ui")
    out_dir.mkdir(parents=True, exist_ok=True)
    rid = re.sub(r"[^a-z0-9]+", "_", f"{args.mode}_{pol}_{args.fleet}".lower()).strip("_")
    path = out_dir / f"replay_{rid}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(replay, fh, separators=(",", ":"), default=float)

    # update index.json
    idx_path = out_dir / "index.json"
    index = {}
    if idx_path.exists():
        try:
            index = json.load(open(idx_path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            index = {}
    index[rid] = {"id": rid, "file": path.name, "label": label,
                  "reached_frac": row.get("reached_frac"),
                  "carless_reached_frac": row.get("carless_reached_frac"),
                  "n_frames": len(sim.frames),
                  "population": result["meta"]["population_source"],
                  "summary": row}
    with open(idx_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2)

    kb = path.stat().st_size / 1024
    print(f"wrote {path.name} ({kb:.0f} KB, {len(sim.frames)} frames) + index.json")
    print(f"  reached={row['reached_frac']} carless={row.get('carless_reached_frac')} "
          f"exposed={row['n_exposed']}")
    print("launch the UI with:  python -m scripts.serve_ui")


if __name__ == "__main__":
    main()
