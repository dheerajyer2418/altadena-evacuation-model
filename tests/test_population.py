"""Population synthesis: membership integrity, person conservation, IPU fit,
assistance-need separate from disability, and race not driving behavior."""
from __future__ import annotations

import copy

import numpy as np

from altadena_evac.behavior.timeline import BehaviorModel
from altadena_evac.config import load_config
from altadena_evac.population.donors import make_synthetic
from altadena_evac.population.synthesize import synthesize_population


def _cfg():
    return load_config("config/experiments.yaml")


def _pop(seed=7):
    cfg = _cfg()
    coding = cfg["population"]["coding"]
    bg, donors = make_synthetic(coding, n_block_groups=3, hh_per_bg=(60, 100), seed=seed)
    return synthesize_population(bg, donors, coding,
                                cfg["population"]["assistance_need"],
                                cfg["population"]["fitting"], seed=seed), cfg


def test_membership_integrity():
    pop, _ = _pop()
    assert pop.check_integrity() == []


def test_person_conservation():
    pop, _ = _pop()
    assert pop.n_persons == sum(h.size for h in pop.households)
    # every person's household exists and lists them
    hids = {h.hid: set(h.members) for h in pop.households}
    for p in pop.persons:
        assert p.pid in hids[p.hid]


def test_ipu_fit_error_small_on_synthetic():
    pop, _ = _pop()
    # synthetic marginals are tallied from donors, so fit should be tight
    assert pop.meta["mean_srmse"] is not None
    assert pop.meta["mean_srmse"] < 0.05


def test_assistance_need_is_not_disability():
    pop, _ = _pop()
    # assistance_need must not be identical to "has a disabled member"
    has_disabled = {}
    for p in pop.persons:
        has_disabled[p.hid] = has_disabled.get(p.hid, False) or p.disability
    mismatch = sum(1 for h in pop.households
                   if h.assistance_need != has_disabled.get(h.hid, False))
    assert mismatch > 0, "assistance_need collapsed onto disability (must be separate)"


def test_race_does_not_drive_behavior():
    """Relabeling race must not change evacuation behavior (requirement 2)."""
    pop, cfg = _pop()
    from altadena_evac.hazard.scenario import GroundTruthHazard
    gt = GroundTruthHazard(cfg["hazard"]["scenarios"]["foothill_santa_ana"])
    bmodel = BehaviorModel(cfg["behavior"])

    pop_a = copy.deepcopy(pop)
    pop_b = copy.deepcopy(pop)
    for p in pop_b.persons:            # scramble race labels only
        p.race = "zzz_other_label"
    sa = bmodel.assign(pop_a, gt, fleet_exists=True, rng=np.random.default_rng(1))
    sb = bmodel.assign(pop_b, gt, fleet_exists=True, rng=np.random.default_rng(1))
    assert sa == sb
    for ha, hb in zip(pop_a.households, pop_b.households):
        assert ha.uses_av == hb.uses_av
        assert ha.stranded == hb.stranded


def test_disability_alone_does_not_imply_nondriver():
    pop, _ = _pop()
    # there must exist disabled persons who are drivers (disability != cannot drive)
    disabled_drivers = [p for p in pop.persons if p.disability and p.is_driver]
    assert len(disabled_drivers) > 0
