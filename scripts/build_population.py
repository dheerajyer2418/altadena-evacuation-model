"""Build & CHECK the synthetic population; write fit report.

    python -m scripts.build_population --config config/experiments.yaml

Without CENSUS_API_KEY the real ACS/PUMS synthesis cannot run; this script builds
the SYNTHETIC offline population instead and labels it. The real path (census.py
+ pums.py + synthesize.py) is implemented and wired; it activates automatically
once a key and TIGER block-group selection are available.
"""
from __future__ import annotations

import argparse
import os

from altadena_evac.config import load_config, project_path
from altadena_evac.sim import metrics, runner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/experiments.yaml")
    args = ap.parse_args()
    cfg = load_config(args.config)

    seed = cfg["sim"]["seeds"]["population"]
    has_key = bool(os.environ.get("CENSUS_API_KEY"))
    if has_key:
        print("CENSUS_API_KEY set -> building REAL ACS/PUMS population for Altadena "
              "(TIGER block-group selection + IPU synthesis).")
        try:
            from altadena_evac.population.build_real import build_census_population
            pop, _bg_gdf = build_census_population(cfg, seed=seed)
            print(f"  source: {pop.meta['SOURCE']}")
        except Exception as e:  # noqa: BLE001
            print(f"  REAL path failed ({type(e).__name__}: {e}); using SYNTHETIC.")
            pop = runner.build_offline_population(cfg, seed=seed)
    else:
        print("CENSUS_API_KEY not set -> building SYNTHETIC offline population "
              "(labeled). Real ACS/PUMS synthesis requires a key.")
        pop = runner.build_offline_population(cfg, seed=seed)

    print(f"households: {pop.n_households}, persons: {pop.n_persons}")
    problems = pop.check_integrity()
    print(f"integrity problems: {len(problems)}")
    print(f"mean SRMSE: {pop.meta['mean_srmse']}  mean TAE: {pop.meta['mean_tae']}")
    carless = sum(1 for h in pop.households if h.no_vehicle)
    asst = sum(1 for h in pop.households if h.assistance_need)
    print(f"carless households: {carless} ({carless/pop.n_households:.1%}); "
          f"assistance-need households: {asst} ({asst/pop.n_households:.1%})")

    out = project_path("data", "processed")
    metrics.write_json(pop.meta, out / "population_fit_report.json")

    # person/household tables
    import csv
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "persons.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pid", "hid", "age", "sex", "race", "hispanic", "disability", "is_driver"])
        for p in pop.persons:
            w.writerow([p.pid, p.hid, p.age, p.sex, p.race, p.hispanic, p.disability, p.is_driver])
    with open(out / "households.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["hid", "block_group", "size", "n_vehicles", "no_vehicle",
                    "income_bracket", "assistance_need"])
        for h in pop.households:
            w.writerow([h.hid, h.block_group, h.size, h.n_vehicles, h.no_vehicle,
                        h.income_bracket, h.assistance_need])
    print(f"wrote persons.csv, households.csv, population_fit_report.json -> {out}")


if __name__ == "__main__":
    main()
