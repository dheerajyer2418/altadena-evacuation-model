"""ACS PUMS donor-household importer (live api.census.gov, needs API key).

PUMS geography is the PUMA — BROADER than Altadena (requirement 2). We draw donor
households from the PUMA(s) containing Altadena and reweight them to Altadena
block-group marginals with IPU (see synthesize.py). Each donor carries its person
records so household relationships are preserved.

Variables pulled (household + person):
  household: SERIALNO, WGTP, NP (size), VEH (vehicles), HINCP (income), TYPE
  person:    SPORDER, AGEP, SEX, RAC1P (race), HISP (hispanic), DIS (disability)
"""
from __future__ import annotations

import os

import pandas as pd
import requests

from .census import CensusAPIError

BASE = "https://api.census.gov/data"

# NOTE: ACS PUMS renamed TYPE -> TYPEHUGQ in 2019+ (type of housing unit/GQ).
# TYPEHUGQ == 1 is a housing unit (household); 2/3 are group quarters.
HH_VARS = ["SERIALNO", "WGTP", "NP", "VEH", "HINCP", "TYPEHUGQ"]
PERSON_VARS = ["SERIALNO", "SPORDER", "AGEP", "SEX", "RAC1P", "HISP", "DIS", "PWGTP"]


def _pull(year, puma, state, variables, api_key, timeout=120) -> pd.DataFrame:
    url = f"{BASE}/{year}/acs/acs5/pums"
    params = {"get": ",".join(variables), "for": f"public use microdata area:{puma}",
              "in": f"state:{state}"}
    key = api_key or os.environ.get("CENSUS_API_KEY")
    if key:
        params["key"] = key
    r = requests.get(url, params=params, timeout=timeout)
    if "json" not in r.headers.get("content-type", "") or r.text.lstrip().startswith("<"):
        if "missing_key" in r.url or "Missing Key" in r.text:
            raise CensusAPIError("PUMS pull requires CENSUS_API_KEY (see census.py).")
        raise CensusAPIError(f"Unexpected PUMS response: {r.text[:200]}")
    rows = r.json()
    return pd.DataFrame(rows[1:], columns=rows[0])


def fetch_donors(year: int, state: str, pumas: list[str],
                 api_key: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (households_df, persons_df) for the given PUMAs.

    households_df indexed by SERIALNO; persons_df has one row per person with a
    SERIALNO foreign key, preserving household membership."""
    hh_frames, p_frames = [], []
    for puma in pumas:
        hh = _pull(year, puma, state, HH_VARS, api_key)
        pp = _pull(year, puma, state, PERSON_VARS, api_key)
        hh_frames.append(hh)
        p_frames.append(pp)
    hh = pd.concat(hh_frames, ignore_index=True)
    pp = pd.concat(p_frames, ignore_index=True)
    for c in ["WGTP", "NP", "VEH", "HINCP"]:
        hh[c] = pd.to_numeric(hh[c], errors="coerce")
    for c in ["AGEP", "SEX", "RAC1P", "HISP", "DIS", "PWGTP", "SPORDER"]:
        pp[c] = pd.to_numeric(pp[c], errors="coerce")
    # Keep only housing units (TYPEHUGQ==1) i.e. households, not group quarters.
    hh = hh[pd.to_numeric(hh["TYPEHUGQ"], errors="coerce") == 1]
    hh = hh.drop_duplicates("SERIALNO").set_index("SERIALNO")
    pp = pp[pp["SERIALNO"].isin(hh.index)]
    return hh, pp
