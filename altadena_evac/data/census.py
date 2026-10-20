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
# Female mirror. B01001 layout: _002 "Male:" header, male age cells _003.._025;
# _026 "Female:" header, female age cells _027.._049. So the female age cell is
# the male age cell + 24 (NOT +23 — _026 is the female header, not ages 0-4).
_B01001_FEMALE = {f"B01001_{int(k.split('_')[1][:3]) + 24:03d}E": v
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
        # vehicles available (B25044, block-group level) — the critical carless control
        if "B25044" in tables:
            rec["vehicles"] = _extract_b25044(tables["B25044"], g)
            rec["n_households"] = _num(tables["B25044"], g, "B25044_001E")
        # household size (B11016, block-group level)
        if "B11016" in tables:
            rec["hh_size"] = _extract_b11016(tables["B11016"], g)
            rec.setdefault("n_households", _num(tables["B11016"], g, "B11016_001E"))
        # income brackets: B19001_002 is bracket index 0 ("Less than $10,000") ...
        # B19001_017 is index 15 ("$200,000+"), matching donors._income_bracket.
        if "B19001" in tables:
            rec["income"] = {i - 2: _num(tables["B19001"], g, f"B19001_{i:03d}E")
                             for i in range(2, 18)}
        # NOTE: disability (B18101) is NULL at block-group geography, so it is NOT
        # fitted as a BG marginal; disability is inherited from PUMS donors (real
        # DIS flags, age-conditioned). See DATA_MANIFEST.md / ASSUMPTIONS.md.
        out[g] = rec
    return out


def _num(df, g, var):
    try:
        v = df.loc[g, var]
        return float(v) if pd.notna(v) else 0.0
    except KeyError:
        return 0.0


def _extract_b25044(df, g) -> dict:
    """B25044 Tenure by Vehicles Available -> {veh_cat: households}, veh in {0,1,2,3+}.

    Layout (verified): _001 total; owner block _002(header) _003=no vehicle,
    _004=1, _005=2, _006=3, _007=4, _008=5+; renter block _009(header) _010=no
    vehicle, _011=1, _012=2, _013=3, _014=4, _015=5+. Owner+renter are summed per
    vehicle count; 3/4/5+ collapse to category 3 (matching coding vehicles 0,1,2,3+).
    """
    pairs = {0: ("B25044_003E", "B25044_010E"),
             1: ("B25044_004E", "B25044_011E"),
             2: ("B25044_005E", "B25044_012E"),
             3: ("B25044_006E", "B25044_013E"),
             4: ("B25044_007E", "B25044_014E"),
             5: ("B25044_008E", "B25044_015E")}
    out = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
    for vcat, (ov, rv) in pairs.items():
        out[min(vcat, 3)] += _num(df, g, ov) + _num(df, g, rv)
    return out


def _extract_b11016(df, g) -> dict:
    """B11016 Household Type by Household Size -> {size_cat: households}, size in {1,2,3,4+}.

    Layout (verified): family block _002(header) _003=2p _004=3 _005=4 _006=5 _007=6
    _008=7+; nonfamily block _009(header) _010=1p _011=2p _012=3 _013=4 _014=5 _015=6
    _016=7+. Size 1 = _010; 2 = _003+_011; 3 = _004+_012; 4+ = the rest.
    """
    one = _num(df, g, "B11016_010E")
    two = _num(df, g, "B11016_003E") + _num(df, g, "B11016_011E")
    three = _num(df, g, "B11016_004E") + _num(df, g, "B11016_012E")
    fourplus = sum(_num(df, g, v) for v in
                   ["B11016_005E", "B11016_006E", "B11016_007E", "B11016_008E",
                    "B11016_013E", "B11016_014E", "B11016_015E", "B11016_016E"])
    return {1: one, 2: two, 3: three, 4: fourplus}


def tract_disability_rate(year, dataset, state, county, tracts, api_key=None) -> dict:
    """Optional: tract-level disability share from B18101 (NULL at block group).

    Returns {tract6: with_disability_fraction}. Not used as an IPU control (no BG
    marginal exists); available for reporting/validation of the donor-inherited
    disability rate. Universe: civilian noninstitutionalized population."""
    df = acs_group(year, dataset, "B18101", state=state, county=county,
                   tract=",".join(tracts) if isinstance(tracts, list) else tracts,
                   api_key=api_key)
    with_vars = ["B18101_004E", "B18101_007E", "B18101_010E", "B18101_013E",
                 "B18101_016E", "B18101_019E", "B18101_023E", "B18101_026E",
                 "B18101_029E", "B18101_032E", "B18101_035E", "B18101_038E"]
    out = {}
    for g in df.index:
        total = _num(df, g, "B18101_001E")
        with_d = sum(_num(df, g, v) for v in with_vars)
        out[g[5:11]] = (with_d / total) if total else 0.0
    return out
