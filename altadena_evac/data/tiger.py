"""TIGER/Line geographic selection (no API key required).

Selects which Census block groups fall in Altadena and returns their polygons so
ACS tables can be joined by GEOID and households can be placed inside the correct
boundaries. TIGER shapefiles are geometry ONLY — never treated as demographic
data (requirement 2).

Selection rule: a block group is "in Altadena" if its centroid lies inside the
Altadena CDP place polygon. Block groups that merely touch the boundary are
included only if their centroid is inside, which keeps the demand area aligned to
the CDP while handling geographies that cross the study boundary (requirement 2).

Downloads are cached under data/raw/tiger/. Vintage matches the ACS year.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from ..config import project_path

TIGER_BASE = "https://www2.census.gov/geo/tiger"


def _cache_dir() -> Path:
    d = project_path("data", "raw", "tiger")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    import requests
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    return dest


def load_places(state_fips: str, year: int) -> gpd.GeoDataFrame:
    url = f"{TIGER_BASE}/TIGER{year}/PLACE/tl_{year}_{state_fips}_place.zip"
    path = _download(url, _cache_dir() / f"tl_{year}_{state_fips}_place.zip")
    return gpd.read_file(path)


def load_block_groups(state_fips: str, year: int) -> gpd.GeoDataFrame:
    url = f"{TIGER_BASE}/TIGER{year}/BG/tl_{year}_{state_fips}_bg.zip"
    path = _download(url, _cache_dir() / f"tl_{year}_{state_fips}_bg.zip")
    return gpd.read_file(path)


def select_altadena_block_groups(study_cfg: dict, year: int | None = None):
    """Return (geoids, bg_gdf, place_polygon_gdf) for Altadena.

    geoids       : list of 12-digit block-group GEOIDs whose centroid is in the
                   Altadena CDP.
    bg_gdf       : GeoDataFrame of those block groups (indexed by GEOID, EPSG:4326).
    place_gdf    : single-row GeoDataFrame with the Altadena CDP polygon.
    """
    geo = study_cfg["geography"]
    year = year or int(study_cfg["acs"]["year"])
    state = geo["state_fips"]
    county = geo["county_fips"]
    place_fips = geo["place_fips"]

    places = load_places(state, year)
    place = places[places["PLACEFP"] == place_fips]
    if place.empty:
        raise ValueError(f"Altadena place FIPS {place_fips} not found in TIGER places "
                         f"for state {state}, year {year}")
    place = place.to_crs(epsg=4326)
    place_geom = place.geometry.union_all() if hasattr(place.geometry, "union_all") \
        else place.geometry.unary_union

    bgs = load_block_groups(state, year).to_crs(epsg=4326)
    bgs = bgs[(bgs["STATEFP"] == state) & (bgs["COUNTYFP"] == county)].copy()
    # centroid-in-place selection (use a projected CRS for valid centroids)
    cent = bgs.to_crs(epsg=26911).geometry.centroid.to_crs(epsg=4326)
    bgs["_in"] = cent.within(place_geom)
    sel = bgs[bgs["_in"]].copy()
    sel["GEOID"] = sel["GEOID"]
    sel = sel.set_index("GEOID")
    geoids = list(sel.index)
    return geoids, sel[["geometry"]], place


def tracts_from_geoids(geoids: list[str]) -> list[str]:
    """Unique 6-digit tract codes from 12-digit block-group GEOIDs (for ACS 'in')."""
    return sorted({g[5:11] for g in geoids})
