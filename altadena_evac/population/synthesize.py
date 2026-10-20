"""Household synthesis by Iterative Proportional Updating (IPU).

Method (Ye et al., 2009): donor households (from ACS PUMS, or synthetic in the
offline demo) are REWEIGHTED so that BOTH household-level marginals (size x
vehicles, income) and person-level marginals (age x sex, race, hispanic,
disability) match each block group's ACS controls simultaneously. Weights are
then integerized (stochastic rounding, seeded) and donors expanded into concrete
Person/Household records, PRESERVING household membership (requirement 2).

We do NOT assign attributes independently: every synthesized household is a real
donor household, so within-household joint structure (who lives with whom, their
ages, the household's vehicle count) is inherited, not fabricated.

Reported for every block group (requirement 2):
  * per-control fit error (TAE, SRMSE),
  * unsupported combinations (targets with no donor support),
  * so uncertainty is visible rather than hidden.

A "donor" is a dict:
  {"weight": float, "size_cat": 1..4, "veh_cat": 0..3, "income_bracket": int,
   "members": [{"age": int, "sex": "male"/"female", "race": str,
                "hispanic": bool, "disability": bool}, ...]}
"""
from __future__ import annotations

import math

import numpy as np

from .agents import Household, Person, Population


# ----------------------------------------------------- constraint construction
def _build_constraints(targets: dict) -> list[tuple]:
    """Return list of (level, key, target_value). level in {"hh","p"}."""
    cons = []
    for (size, veh), val in targets.get("hhsize_vehicles", {}).items():
        cons.append(("hh", ("sv", size, veh), float(val)))
    for b, val in targets.get("income", {}).items():
        cons.append(("hh", ("inc", b), float(val)))
    for (sex, b), val in targets.get("age_sex", {}).items():
        cons.append(("p", ("as", sex, b), float(val)))
    for name, val in targets.get("race", {}).items():
        cons.append(("p", ("race", name), float(val)))
    for name, val in targets.get("hispanic", {}).items():
        cons.append(("p", ("hisp", name), float(val)))
    for name, val in targets.get("disability", {}).items():
        if name == "universe_total":
            continue
        cons.append(("p", ("dis", name), float(val)))
    return cons


def _age_bracket(age: int, brackets) -> int:
    for i, (lo, hi) in enumerate(brackets):
        if lo <= age <= hi:
            return i
    return len(brackets) - 1


def _incidence(donor: dict, key: tuple, brackets) -> float:
    kind = key[0]
    if kind == "sv":
        return 1.0 if (donor["size_cat"] == key[1] and donor["veh_cat"] == key[2]) else 0.0
    if kind == "inc":
        return 1.0 if donor["income_bracket"] == key[1] else 0.0
    if kind == "as":
        _, sex, b = key
        return float(sum(1 for m in donor["members"]
                         if m["sex"] == sex and _age_bracket(m["age"], brackets) == b))
    if kind == "race":
        return float(sum(1 for m in donor["members"] if m["race"] == key[1]))
    if kind == "hisp":
        want = (key[1] == "hispanic")
        return float(sum(1 for m in donor["members"] if m["hispanic"] == want))
    if kind == "dis":
        want = (key[1] == "with")
        return float(sum(1 for m in donor["members"] if m["disability"] == want))
    return 0.0


# --------------------------------------------------------------------- IPU
def run_ipu(donors: list[dict], targets: dict, coding: dict,
            max_iter: int = 200, tol: float = 1e-4) -> dict:
    """Reweight donors to targets. Returns dict with weights, fit report."""
    brackets = coding["age_brackets"]
    cons = _build_constraints(targets)
    n = len(donors)
    w = np.array([max(d.get("weight", 1.0), 1e-6) for d in donors], dtype=float)
    # precompute incidence matrix (n_donors x n_constraints)
    A = np.zeros((n, len(cons)))
    for j, (_, key, _) in enumerate(cons):
        for i, d in enumerate(donors):
            A[i, j] = _incidence(d, key, brackets)
    targets_v = np.array([t for _, _, t in cons])

    unsupported = []
    for j, (_, key, t) in enumerate(cons):
        if t > 0 and A[:, j].sum() == 0:
            unsupported.append({"constraint": str(key), "target": t,
                                "reason": "no donor support"})

    prev = w.copy()
    for _ in range(max_iter):
        for j in range(len(cons)):
            col = A[:, j]
            denom = float((w * col).sum())
            if denom <= 0 or targets_v[j] <= 0:
                continue
            factor = targets_v[j] / denom
            w = np.where(col > 0, w * factor, w)
        if np.abs(w - prev).sum() / max(prev.sum(), 1e-9) < tol:
            break
        prev = w.copy()

    # fit error on continuous weights
    fit = []
    for j, (lvl, key, t) in enumerate(cons):
        syn = float((w * A[:, j]).sum())
        fit.append({"constraint": str(key), "level": lvl, "target": t,
                    "synthesized": round(syn, 3), "abs_error": round(abs(syn - t), 3)})
    tae = sum(f["abs_error"] for f in fit)
    denom = sum(f["target"] for f in fit) or 1.0
    srmse_num = math.sqrt(sum((f["synthesized"] - f["target"]) ** 2 for f in fit) / len(fit))
    srmse = srmse_num / (denom / len(fit))
    return {"weights": w, "fit": fit, "tae": tae, "srmse": srmse,
            "unsupported": unsupported}


def _integerize(weights: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    floor = np.floor(weights)
    frac = weights - floor
    extra = (rng.random(len(weights)) < frac).astype(int)
    return (floor + extra).astype(int)


# -------------------------------------------------------- expansion to records
def synthesize_population(bg_marginals: dict, donors: list[dict], coding: dict,
                          assistance_cfg: dict, fit_cfg: dict,
                          seed: int = 12345) -> Population:
    """Synthesize households+persons for every block group. Returns Population."""
    rng = np.random.default_rng(seed)
    brackets = coding["age_brackets"]
    persons: list[Person] = []
    households: list[Household] = []
    pid = 0
    hid = 0
    bg_reports = {}

    for geoid, targets in bg_marginals.items():
        res = run_ipu(donors, targets, coding,
                      max_iter=fit_cfg.get("max_iter", 200),
                      tol=fit_cfg.get("tolerance", 1e-4))
        counts = _integerize(res["weights"], rng)
        for i, c in enumerate(counts):
            if c <= 0:
                continue
            donor = donors[i]
            for _ in range(int(c)):
                h = Household(hid=hid, block_group=geoid,
                              n_vehicles=donor["veh_cat"],
                              seats_per_vehicle=4,
                              income_bracket=donor["income_bracket"])
                member_ids = []
                has_disab = False
                for m in donor["members"]:
                    is_driver = (m["age"] >= 16) and (rng.random() < 0.92)  # NOT from disability
                    p = Person(pid=pid, hid=hid, age=m["age"], sex=m["sex"],
                               race=m["race"], hispanic=m["hispanic"],
                               disability=m["disability"], is_driver=is_driver)
                    has_disab = has_disab or m["disability"]
                    persons.append(p)
                    member_ids.append(pid)
                    pid += 1
                h.members = member_ids
                h.assistance_need = _assistance(has_disab, h.no_vehicle, assistance_cfg, rng)
                households.append(h)
                hid += 1
        bg_reports[geoid] = {"tae": round(res["tae"], 2),
                             "srmse": round(res["srmse"], 4),
                             "n_unsupported": len(res["unsupported"]),
                             "unsupported": res["unsupported"][:10]}

    pop = Population(persons=persons, households=households)
    pop.meta = {
        "n_block_groups": len(bg_marginals),
        "n_households": len(households),
        "n_persons": len(persons),
        "mean_srmse": round(float(np.mean([r["srmse"] for r in bg_reports.values()])), 4)
        if bg_reports else None,
        "mean_tae": round(float(np.mean([r["tae"] for r in bg_reports.values()])), 2)
        if bg_reports else None,
        "per_block_group_fit": bg_reports,
        "method": f"IPU (max_iter={fit_cfg.get('max_iter', 200)})",
    }
    return pop


def _assistance(has_disability: bool, no_vehicle: bool, cfg: dict,
                rng: np.random.Generator) -> bool:
    """Assistance need is SEPARATE from disability (requirement 2). Probabilistic,
    documented, editable in config/population.yaml."""
    if has_disability and no_vehicle:
        p = cfg["base_prob_if_disability_and_no_vehicle"]
    elif has_disability:
        p = cfg["base_prob_if_disability_with_vehicle"]
    else:
        p = cfg["base_prob_otherwise"]
    return bool(rng.random() < p)
