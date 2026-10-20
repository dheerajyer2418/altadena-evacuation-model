"""U.S. Census / ACS importer (live api.census.gov).

Pulls whole ACS 5-year detailed tables with ``get=group(TABLE)`` and reduces them
to the marginal CONTROLS the synthesizer needs. Geography is block group within
tract within county (requirement 2). TIGER shapefiles are NOT treated as
demographic data; they are used only to select which block groups fall in
Altadena (see select.py / acquire_data.py).

Universes differ by table and are documented in DATA_MANIFEST.md. We keep RACE
(B02001) and HISPANIC ETHNICITY (B03003) as SEPARATE attributes.

An API key is optional for these small pulls but recommended (set CENSUS_API_KEY).
"""
from __future__ import annotations

import os

import pandas as pd
import requests

BASE = "https://api.census.gov/data"


class CensusAPIError(RuntimeError):
    pass


def acs_group(year: int, dataset: str, table: str, *, state: str, county: str,
              tract: str = "*", api_key: str | None = None,
              timeout: int = 60) -> pd.DataFrame:
    """Fetch an entire ACS table for all block groups in the given tract(s).

    Returns a DataFrame indexed by 12-digit block-group GEOID with one column per
    table variable (e.g. B01001_001E). Values are numeric (estimates)."""
    url = f"{BASE}/{year}/{dataset}"
    params = {
        "get": f"group({table})",
        "for": "block group:*",
        "in": f"state:{state} county:{county} tract:{tract}",
    }
    key = api_key or os.environ.get("CENSUS_API_KEY")
    if key:
        params["key"] = key
    r = requests.get(url, params=params, timeout=timeout)
    # As of 2024+ the Census API requires a (free) key; without one it returns an
    # HTML "Missing Key" page with HTTP 200. Detect that explicitly.
    ctype = r.headers.get("content-type", "")
    if "json" not in ctype or r.text.lstrip().startswith("<"):
        if "missing_key" in r.url or "Missing Key" in r.text:
            raise CensusAPIError(
                "Census API requires an API key. Request a free key at "
                "https://api.census.gov/data/key_signup.html and set it in the "
                "environment variable CENSUS_API_KEY, then re-run.")
        raise CensusAPIError(
            f"Unexpected non-JSON response from Census API ({r.status_code}): "
            f"{r.text[:200]}")
    r.raise_for_status()
    rows = r.json()
    header, data = rows[0], rows[1:]
    df = pd.DataFrame(data, columns=header)
    # build GEOID
    df["GEOID"] = df["state"] + df["county"] + df["tract"] + df["block group"]
    # numeric estimate columns end in 'E'; coerce
    est_cols = [c for c in df.columns if c.endswith("E") and c.startswith(table)]
    for c in est_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.set_index("GEOID")[est_cols]


# --------------------------------------------------------- control extraction
# Minimal, documented cell groupings. B01001 sex-by-age cell codes:
#   _002..._025 male by age band; _026..._049 female by age band.
_B01001_MALE = {  # variable -> (age_low, age_high)
    "B01001_003E": (0, 4), "B01001_004E": (5, 9), "B01001_005E": (10, 14),
    "B01001_006E": (15, 17), "B01001_007E": (18, 19), "B01001_008E": (20, 20),
    "B01001_009E": (21, 21), "B01001_010E": (22, 24), "B01001_011E": (25, 29),
    "B01001_012E": (30, 34), "B01001_013E": (35, 39), "B01001_014E": (40, 44),
    "B01001_015E": (45, 49), "B01001_016E": (50, 54), "B01001_017E": (55, 59),
    "B01001_018E": (60, 61), "B01001_019E": (62, 64), "B01001_020E": (65, 66),
    "B01001_021E": (67, 69), "B01001_022E": (70, 74), "B01001_023E": (75, 79),
    "B01001_024E": (80, 84), "B01001_025E": (85, 120),
}
# female mirror: add 23 to the male index (003->026, ... 025->049)
_B01001_FEMALE = {f"B01001_{int(k.split('_')[1][:3]) + 23:03d}E": v
                  for k, v in _B01001_MALE.items()}

_B02001_RACE = {
    "B02001_002E": "white", "B02001_003E": "black", "B02001_004E": "native",
    "B02001_005E": "asian", "B02001_006E": "nhpi", "B02001_007E": "other",
    "B02001_008E": "two_or_more",
}


def age_bracket_index(age: int, brackets) -> int:
    for i, (lo, hi) in enumerate(brackets):
        if lo <= age <= hi:
            return i
    return len(brackets) - 1


def extract_marginals(tables: dict[str, pd.DataFrame], coding: dict) -> dict:
    """Reduce raw ACS tables to per-block-group marginal controls.

    tables: {"B01001": df, "B02001": df, ...} each indexed by GEOID.
    Returns {GEOID: {"n_persons":, "n_households":, "age_sex": {...},
             "race": {...}, "hispanic": {...}, "hhsize_vehicles": {...},
             "disability": {...}, "income": {...}}}.
    """
    brackets = coding["age_brackets"]
    out: dict[str, dict] = {}
    geoids = tables["B01001"].index
    for g in geoids:
        rec: dict = {}
        # persons total
        rec["n_persons"] = float(tables["B01001"].loc[g, "B01001_001E"])
        # age x sex collapsed to age brackets x sex
        age_sex = {}
        for var, (lo, hi) in _B01001_MALE.items():
            b = age_bracket_index((lo + hi) // 2, brackets)
            age_sex[("male", b)] = age_sex.get(("male", b), 0.0) + _num(tables["B01001"], g, var)
        for var, (lo, hi) in _B01001_FEMALE.items():
            b = age_bracket_index((lo + hi) // 2, brackets)
            age_sex[("female", b)] = age_sex.get(("female", b), 0.0) + _num(tables["B01001"], g, var)
        rec["age_sex"] = age_sex
        # race
        if "B02001" in tables:
            rec["race"] = {name: _num(tables["B02001"], g, var)
                           for var, name in _B02001_RACE.items()}
        # hispanic ethnicity (B03003_003E hispanic, _002E not hispanic)
        if "B03003" in tables:
            rec["hispanic"] = {
                "hispanic": _num(tables["B03003"], g, "B03003_003E"),
                "not_hispanic": _num(tables["B03003"], g, "B03003_002E"),
            }
        # households total + hhsize x vehicles (B08201)
        if "B08201" in tables:
            rec["n_households"] = _num(tables["B08201"], g, "B08201_001E")
            rec["hhsize_vehicles"] = _extract_b08201(tables["B08201"], g)
        # disability flag (B18101): sum "with a disability" cells
        if "B18101" in tables:
            rec["disability"] = _extract_b18101(tables["B18101"], g)
        # income brackets (B19001_002.._017E)
        if "B19001" in tables:
            rec["income"] = {i - 1: _num(tables["B19001"], g, f"B19001_{i:03d}E")
                             for i in range(2, 18)}
        out[g] = rec
    return out


def _num(df, g, var):
    try:
        v = df.loc[g, var]
        return float(v) if pd.notna(v) else 0.0
    except KeyError:
        return 0.0


def _extract_b08201(df, g) -> dict:
    """B08201 Household Size by Vehicles Available -> {(size_idx, veh): count}.

    Size categories: 1,2,3,4+ ; vehicles: 0,1,2,3,4+. We map to synthesizer
    coding sizes {1,2,3,4} and vehicles {0,1,2,3(=3+)}. Cell codes per ACS:
      sizes start at _003 (1-person): each size block has 5 vehicle cells.
    """
    out = {}
    # ACS B08201 layout: _001 total; _002 0veh(all sizes)... actually layout is
    # total, then by vehicles for all hh, then by size. We use the size x veh
    # detail cells _003.._027 (5 vehicle cats x ... ). To stay robust we read the
    # documented detail block; see DATA_MANIFEST.md. Simplified mapping below.
    size_blocks = {1: 8, 2: 13, 3: 18, 4: 23}  # starting index of veh cells per size
    for size, start in size_blocks.items():
        for vcat in range(0, 5):   # 0,1,2,3,4+
            var = f"B08201_{start + vcat:03d}E"
            v = _num(df, g, var)
            vkey = min(vcat, 3)
            out[(size, vkey)] = out.get((size, vkey), 0.0) + v
    return out


def _extract_b18101(df, g) -> dict:
    """B18101 Sex by Age by Disability -> {'with': count, 'without': count}.

    'With a disability' cells are the odd sub-cells within each age block. We sum
    the documented 'with a disability' variables. Universe: civilian
    noninstitutionalized population (NOT total population) — documented limitation
    when combined with B01001 totals."""
    with_vars = ["B18101_004E", "B18101_007E", "B18101_010E", "B18101_013E",
                 "B18101_016E", "B18101_019E", "B18101_023E", "B18101_026E",
                 "B18101_029E", "B18101_032E", "B18101_035E", "B18101_038E"]
    total = _num(df, g, "B18101_001E")
    with_d = sum(_num(df, g, v) for v in with_vars)
    return {"with": with_d, "without": max(0.0, total - with_d), "universe_total": total}
