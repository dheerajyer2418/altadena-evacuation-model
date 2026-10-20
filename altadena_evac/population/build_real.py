"""Real ACS/PUMS population pipeline (activates when CENSUS_API_KEY is set).

End-to-end:
  1. TIGER: select Altadena CDP block groups + polygons (no key).
  2. ACS: pull detailed tables, subset to the selected block groups, reduce to
     marginal controls.
  3. PUMS: pull donor households from the containing PUMA(s).
  4. IPU synthesis -> Population with per-block-group fit report.
  5. Placement: OSM residential buildings inside each block-group polygon
     (fallback to network-node placement, labeled).

Everything except steps 1 and 5-fallback needs a Census API key. Without one,
callers use the synthetic offline population instead.
"""
from __future__ import annotations

import os

from ..data import census, pums, tiger
from .donors import donors_from_pums
from .placement import place_from_osm, place_on_network
from .synthesize import synthesize_population

ACS_TABLES = ["B01001", "B02001", "B03003", "B08201", "B18101", "B19001"]


def build_census_population(cfg: dict, api_key: str | None = None, seed: int = 12345):
    """Return (Population, bg_gdf). Raises census.CensusAPIError without a key."""
    api_key = api_key or os.environ.get("CENSUS_API_KEY")
    study = cfg["study"]
    popcfg = cfg["population"]
    geo = study["geography"]
    year = int(study["acs"]["year"])
    dataset = study["acs"]["dataset"]

    # 1. geographic selection (no key)
    geoids, bg_gdf, _place = tiger.select_altadena_block_groups(study, year)
    geoid_set = set(geoids)

    # 2. ACS tables (county-wide pull, then subset to selected block groups —
    #    robust to multi-tract 'in' quirks)
    tables = {}
    for tbl in ACS_TABLES:
        df = census.acs_group(year, dataset, tbl, state=geo["state_fips"],
                              county=geo["county_fips"], tract="*", api_key=api_key)
        keep = [g for g in df.index if g in geoid_set]
        tables[tbl] = df.loc[keep]
    marginals = census.extract_marginals(tables, popcfg["coding"])

    # 3. PUMS donors from the containing PUMA(s)
    hh_df, p_df = pums.fetch_donors(year, geo["state_fips"],
                                    popcfg["pums"]["pumas"], api_key=api_key)
    donors = donors_from_pums(hh_df, p_df, popcfg["coding"])

    # 4. IPU synthesis
    pop = synthesize_population(marginals, donors, popcfg["coding"],
                                popcfg["assistance_need"], popcfg["fitting"], seed=seed)
    pop.meta["SOURCE"] = (f"ACS {year} 5-year (real) + PUMS donors (real); "
                          f"{len(geoids)} Altadena block groups")
    pop.meta["pumas"] = popcfg["pums"]["pumas"]
    return pop, bg_gdf


def place_real(pop, net, bg_gdf, study_cfg, rng):
    """Place households from OSM residential buildings inside block-group polygons;
    fall back to network-node placement (labeled) if OSM buildings are unavailable."""
    try:
        import osmnx as ox
        place_geom = bg_gdf.geometry.union_all() if hasattr(bg_gdf.geometry, "union_all") \
            else bg_gdf.geometry.unary_union
        feats = ox.features_from_polygon(place_geom, tags={"building": True})
        # residential-ish buildings only
        if "building" in feats.columns:
            res = feats[feats["building"].isin(
                ["residential", "house", "detached", "apartments", "yes",
                 "semidetached_house", "terrace", "bungalow"])]
        else:
            res = feats
        res = res[res.geometry.type.isin(["Polygon", "MultiPolygon"])]
        return place_from_osm(pop, net, bg_gdf, res,
                              study_cfg["crs"]["projected"], rng)
    except Exception as e:  # noqa: BLE001 — any OSM/geo failure -> labeled fallback
        pop.meta["placement_fallback_reason"] = f"{type(e).__name__}: {e}"
        return place_on_network(pop, net, rng, method_label="network_node_fallback")
