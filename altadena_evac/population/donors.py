"""Donor-household builders for the synthesizer.

Two sources, one output format (see synthesize.py docstring for the donor dict):
  * donors_from_pums(...)  — real ACS PUMS households (needs the PUMS pull).
  * make_synthetic(...)    — SYNTHETIC donors + block-group marginals for the
                             offline demo and tests. NOT Altadena data.
"""
from __future__ import annotations

import numpy as np

# PUMS RAC1P -> our race categories
_RAC1P = {1: "white", 2: "black", 3: "native", 4: "native", 5: "native",
          6: "asian", 7: "nhpi", 8: "other", 9: "two_or_more"}

# HINCP -> B19001 bracket index (0..15); coarse, documented mapping
_INCOME_EDGES = [10000, 15000, 20000, 25000, 30000, 35000, 40000, 45000,
                 50000, 60000, 75000, 100000, 125000, 150000, 200000]


def _income_bracket(hincp) -> int:
    if hincp is None or (isinstance(hincp, float) and np.isnan(hincp)):
        return 0
    for i, edge in enumerate(_INCOME_EDGES):
        if hincp < edge:
            return i
    return len(_INCOME_EDGES)


def donors_from_pums(hh_df, persons_df, coding) -> list[dict]:
    donors = []
    grouped = persons_df.groupby("SERIALNO")
    for serial, hh in hh_df.iterrows():
        try:
            members_df = grouped.get_group(serial)
        except KeyError:
            continue
        members = []
        for _, m in members_df.iterrows():
            members.append({
                "age": int(m["AGEP"]),
                "sex": "male" if int(m["SEX"]) == 1 else "female",
                "race": _RAC1P.get(int(m["RAC1P"]), "other"),
                "hispanic": int(m["HISP"]) > 1,
                "disability": int(m["DIS"]) == 1,
            })
        if not members:
            continue
        donors.append({
            "weight": float(hh["WGTP"]) if hh["WGTP"] and hh["WGTP"] > 0 else 1.0,
            "size_cat": min(int(hh["NP"]), 4) if hh["NP"] >= 1 else 1,
            "veh_cat": min(int(hh["VEH"]) if hh["VEH"] >= 0 else 0, 3),
            "income_bracket": _income_bracket(hh["HINCP"]),
            "members": members,
        })
    return donors


# --------------------------------------------------------------- synthetic
def _make_archetypes(coding, rng, n=80) -> list[dict]:
    races = coding["race_categories"]
    race_p = np.array([0.45, 0.17, 0.01, 0.16, 0.01, 0.14, 0.06])  # synthetic mix
    race_p = race_p / race_p.sum()
    archetypes = []
    for _ in range(n):
        size = int(rng.integers(1, 6))          # 1..5 members
        veh = int(rng.integers(0, 4))           # 0..3 (0 => carless)
        income = int(rng.integers(0, 16))
        members = []
        for k in range(size):
            if k == 0:
                age = int(rng.integers(20, 80))
            else:
                age = int(rng.integers(0, 80))
            members.append({
                "age": age,
                "sex": "male" if rng.random() < 0.49 else "female",
                "race": str(rng.choice(races, p=race_p)),
                "hispanic": bool(rng.random() < 0.26),
                "disability": bool(rng.random() < (0.35 if age >= 65 else 0.08)),
            })
        archetypes.append({"weight": 1.0, "size_cat": min(size, 4),
                           "veh_cat": veh, "income_bracket": income,
                           "members": members})
    return archetypes


def _tally(hhs, coding) -> dict:
    """Tally control marginals from a list of donor households (synthetic BG)."""
    brackets = coding["age_brackets"]

    def abidx(age):
        for i, (lo, hi) in enumerate(brackets):
            if lo <= age <= hi:
                return i
        return len(brackets) - 1

    veh, size, inc, age_sex, race = {}, {}, {}, {}, {}
    hisp = {"hispanic": 0.0, "not_hispanic": 0.0}
    for h in hhs:
        veh[h["veh_cat"]] = veh.get(h["veh_cat"], 0.0) + 1
        size[h["size_cat"]] = size.get(h["size_cat"], 0.0) + 1
        inc[h["income_bracket"]] = inc.get(h["income_bracket"], 0.0) + 1
        for m in h["members"]:
            k = (m["sex"], abidx(m["age"]))
            age_sex[k] = age_sex.get(k, 0.0) + 1
            race[m["race"]] = race.get(m["race"], 0.0) + 1
            hisp["hispanic" if m["hispanic"] else "not_hispanic"] += 1
    # Mirrors the real block-group controls (vehicles=B25044, hh_size=B11016,
    # income=B19001, age_sex=B01001, race=B02001, hispanic=B03003). Disability is
    # inherited from donors, not fitted (no BG marginal).
    return {"vehicles": veh, "hh_size": size, "income": inc, "age_sex": age_sex,
            "race": race, "hispanic": hisp}


def make_synthetic(coding, n_block_groups=4, hh_per_bg=(80, 160), seed=0):
    """Return (bg_marginals, donors) for the offline demo. SYNTHETIC, not Altadena.

    Marginals are tallied from sampled donor households so support is guaranteed
    and IPU converges cleanly — this exercises the full pipeline deterministically.
    """
    rng = np.random.default_rng(seed)
    donors = _make_archetypes(coding, rng, n=80)
    bg_marginals = {}
    for b in range(n_block_groups):
        h = int(rng.integers(hh_per_bg[0], hh_per_bg[1]))
        sample = [donors[int(i)] for i in rng.integers(0, len(donors), size=h)]
        geoid = f"SYNTH{b:08d}"
        bg_marginals[geoid] = _tally(sample, coding)
    return bg_marginals, donors
