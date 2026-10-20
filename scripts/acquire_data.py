"""Acquire real data: OSM road network (no credentials) + ACS tables (needs key).

    python -m scripts.acquire_data --config config/study.yaml

OSM download works without credentials. The ACS pull requires a free CENSUS_API_KEY
(see altadena_evac/data/census.py); without it the script reports exactly what is
missing and continues — it NEVER fabricates demographic data.
"""
from __future__ import annotations

import argparse
import json
import os

from altadena_evac.config import load_yaml, project_path
from altadena_evac.data.census import CensusAPIError, acs_group
from altadena_evac.network.build import build_from_osm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/study.yaml")
    ap.add_argument("--network-config", default="config/network.yaml")
    ap.add_argument("--skip-network", action="store_true")
    ap.add_argument("--skip-census", action="store_true")
    args = ap.parse_args()

    study = load_yaml(args.config)
    net_cfg = load_yaml(args.network_config)
    manifest = {"acquired": []}

    # 1) OSM network (real, no credentials)
    if not args.skip_network:
        out = project_path(net_cfg["cache"]["graphml"])
        print(f"Downloading OSM drive network for Altadena + "
              f"{study['boundary']['network_buffer_m']} m buffer ...")
        meta = build_from_osm(study, net_cfg, out)
        print(f"  network: {meta['n_nodes']} nodes, {meta['n_edges']} edges "
              f"(snapshot {meta['downloaded_at']}) -> {out}")
        manifest["acquired"].append({"source": "OpenStreetMap", **meta})

    # 2) ACS tables (needs key)
    if not args.skip_census:
        geo = study["geography"]
        try:
            df = acs_group(study["acs"]["year"], study["acs"]["dataset"], "B01001",
                           state=geo["state_fips"], county=geo["county_fips"],
                           tract="*")
            # NOTE: this returns the whole county; selecting Altadena block groups
            # requires a TIGER place/tract filter (see docstring in census.py).
            print(f"  ACS B01001 pulled: {len(df)} block groups (county-wide; "
                  f"filter to Altadena with TIGER).")
            manifest["acquired"].append({"source": "ACS", "table": "B01001",
                                         "n_block_groups": int(len(df))})
        except CensusAPIError as e:
            print("  ACS pull SKIPPED — missing credentials / input:")
            print("   ", str(e))
            manifest["census_blocked"] = str(e)

    outm = project_path("data", "interim", "data_manifest_stamp.json")
    outm.parent.mkdir(parents=True, exist_ok=True)
    with open(outm, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"wrote acquisition stamp -> {outm}")
    if "census_blocked" in manifest:
        print("\nTo enable the real Census population: set CENSUS_API_KEY and re-run.")


if __name__ == "__main__":
    main()
