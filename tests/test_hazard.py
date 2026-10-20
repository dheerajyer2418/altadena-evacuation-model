"""Hazard: monotonic closures, forecast-vs-ground-truth boundary, exposure
semantics (exposure is a duration, not a casualty)."""
from __future__ import annotations

from altadena_evac.config import load_config
from altadena_evac.hazard.scenario import Forecast, GroundTruthHazard


def _scen():
    cfg = load_config("config/experiments.yaml")
    return cfg["hazard"]["scenarios"]["foothill_santa_ana"]


def test_closures_are_monotonic(toy_net):
    net, G, dests = toy_net
    scen = dict(_scen())
    scen["ignition"] = {"lat": 34.195, "lon": -118.15}
    scen["spread"] = dict(scen["spread"]); scen["spread"]["speed_mps"] = 0.3
    gt = GroundTruthHazard(scen)
    prev = set()
    for t in range(0, 3600, 120):
        closed = gt.closed_links_at(float(t), net)
        assert prev <= closed, "a previously-closed link reopened (fire un-burned)"
        prev = closed


def test_perfect_forecast_equals_ground_truth():
    scen = _scen()
    gt = GroundTruthHazard(scen)
    f = Forecast(gt, {"perfect_information": True}, seed=0)
    for (lon, lat) in [(-118.13, 34.20), (-118.15, 34.185)]:
        assert f.estimated_arrival(lon, lat) == gt.arrival_time(lon, lat)


def test_imperfect_forecast_differs_from_ground_truth():
    scen = _scen()
    gt = GroundTruthHazard(scen)
    fc = dict(scen["forecast"]); fc["perfect_information"] = False
    f = Forecast(gt, fc, seed=3)
    diffs = []
    for (lon, lat) in [(-118.13, 34.20), (-118.15, 34.185), (-118.12, 34.19)]:
        diffs.append(abs(f.estimated_arrival(lon, lat) - gt.arrival_time(lon, lat)))
    assert max(diffs) > 0.0, "imperfect forecast identical to ground truth"


def test_safe_deadline_not_after_estimated_arrival():
    scen = _scen()
    gt = GroundTruthHazard(scen)
    f = Forecast(gt, scen["forecast"], seed=1)
    lon, lat = -118.14, 34.20
    assert f.safe_deadline(lon, lat) <= f.estimated_arrival(lon, lat)


def test_exposure_is_not_casualty():
    """Exposure must be a time quantity; no injury/death inferred by the model."""
    from altadena_evac.population.agents import Person
    p = Person(pid=0, hid=0, age=30, sex="male", race="white", hispanic=False,
               disability=False, is_driver=True)
    assert hasattr(p, "exposure_time_s")
    assert not hasattr(p, "dead") and not hasattr(p, "injured")
