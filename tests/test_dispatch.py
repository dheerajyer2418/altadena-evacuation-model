"""AV dispatch invariants: seat capacity, no duplicate passenger assignment,
priority ordering, and the forecast information boundary."""
from __future__ import annotations

import pytest

from altadena_evac.config import load_config
from altadena_evac.fleet.dispatch import AVDispatcher, Request
from altadena_evac.fleet.policies import resolve_policy
from altadena_evac.fleet.vehicles import Vehicle
from altadena_evac.hazard.scenario import Forecast, GroundTruthHazard
from tests.conftest import make_population


def _cfg():
    return load_config("config/experiments.yaml")


def _forecast(perfect=True):
    cfg = _cfg()
    gt = GroundTruthHazard(cfg["hazard"]["scenarios"]["foothill_santa_ana"])
    return Forecast(gt, {"perfect_information": perfect}, seed=0), cfg


def test_seat_capacity_enforced():
    v = Vehicle(vid=1, kind="av", seats=4)
    v.board([1, 2, 3, 4])
    with pytest.raises(ValueError):
        v.board([5])             # 5th passenger -> capacity violation


def test_no_duplicate_passenger_assignment():
    forecast, cfg = _forecast()
    net_pop = make_population([{"node": 5, "vehicles": 0, "size": 6}])
    persons = {p.pid: p for p in net_pop.persons}
    # fake tiny net not needed; dispatcher only splits requests here
    from tests.conftest import make_toy_grid
    from altadena_evac.network.mesoscopic import MesoNetwork
    G = make_toy_grid(); net = MesoNetwork(G, {12, 13, 14, 15})
    disp = AVDispatcher(net, forecast, cfg["fleet"], resolve_policy("normal", cfg["fleet"]),
                        persons, n_vehicles=2, seats_per_av=4,
                        service_centroid=(-118.15, 34.19), max_av_wait_s=9999)
    h = net_pop.households[0]
    reqs = disp.submit_household(h, list(range(6)), now=0.0)
    assert len(reqs) == 2                       # ceil(6/4)
    seen = [pid for r in reqs for pid in r.person_ids]
    assert sorted(seen) == [0, 1, 2, 3, 4, 5]   # every person exactly once
    assert len(seen) == len(set(seen))


def test_priority_sort_vulnerability_first():
    pol = resolve_policy("evac_priority", _cfg()["fleet"])
    r_plain = Request(0, 0, 1, [0], request_time_s=10.0, no_vehicle=True, assistance_need=False)
    r_asst = Request(1, 1, 2, [1], request_time_s=50.0, no_vehicle=True, assistance_need=True)
    ordered = sorted([r_plain, r_asst], key=pol.request_sort_key)
    assert ordered[0] is r_asst, "assistance-need request should sort first"

    fcfs = resolve_policy("normal", _cfg()["fleet"])
    ordered2 = sorted([r_asst, r_plain], key=fcfs.request_sort_key)
    assert ordered2[0] is r_plain, "FCFS should order by request time"


def test_dispatcher_sees_only_forecast_not_ground_truth():
    forecast, cfg = _forecast()
    from tests.conftest import make_toy_grid
    from altadena_evac.network.mesoscopic import MesoNetwork
    G = make_toy_grid(); net = MesoNetwork(G, {12, 13, 14, 15})
    disp = AVDispatcher(net, forecast, cfg["fleet"], resolve_policy("normal", cfg["fleet"]),
                        {}, n_vehicles=1, seats_per_av=4,
                        service_centroid=(-118.15, 34.19), max_av_wait_s=9999)
    # the controller holds a Forecast and NO ground-truth hazard reference
    assert isinstance(disp.forecast, Forecast)
    assert not hasattr(disp, "hazard")
    assert not hasattr(disp, "gt")
    # even the Forecast object only exposes estimates, not the raw front schedule
    assert hasattr(disp.forecast, "estimated_arrival")
