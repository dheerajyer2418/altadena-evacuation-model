"""Traffic-engine mechanisms: finite storage, discharge capacity, queues,
spillback, rerouting, closures, and vehicle conservation."""
from __future__ import annotations

from altadena_evac.fleet.vehicles import Vehicle


def _veh(vid, pax=1):
    return Vehicle(vid=vid, kind="private", seats=4, passengers=list(range(pax)))


def test_finite_storage_never_exceeded_and_queue_forms(tiny_capacity_net):
    net = tiny_capacity_net
    for i in range(10):
        net.inject(_veh(i), 0)
    max_pending = 0
    for step in range(2000):
        net.step(now=step * 10.0, dt=10.0)
        link = net.links[(0, 1)]
        assert link.occupancy <= link.storage_veh, "finite storage violated"
        max_pending = max(max_pending, len(net.pending_injection))
        # conservation every step
        assert net.active_count() + len(net.arrived) + len(net.trapped) == 10
        if len(net.arrived) == 10:
            break
    assert max_pending > 0, "no origin queue formed despite tight capacity"
    assert len(net.arrived) == 10, "not all vehicles discharged"


def test_discharge_capacity_limits_outflow(tiny_capacity_net):
    net = tiny_capacity_net           # capacity 0.1 veh/s -> <=1 veh per 10 s step
    for i in range(5):
        net.inject(_veh(i), 0)
    # prime: let them enter and traverse
    outs = []
    prev = 0
    for step in range(60):
        net.step(step * 10.0, 10.0)
        outs.append(len(net.arrived) - prev)
        prev = len(net.arrived)
    assert max(outs) <= 1, "exceeded discharge capacity of ~1 veh per 10 s"


def test_reroute_around_closure(diamond_net):
    net = diamond_net
    p0, _ = net.shortest_path_to_any(0)
    assert p0 == [0, 1, 3], "expected short arm first"
    net.set_closed(1, 3, True)
    p1, _ = net.shortest_path_to_any(0)
    assert p1 == [0, 2, 3], "did not reroute around closed short arm"


def test_unreachable_is_trapped_not_deleted(diamond_net):
    net = diamond_net
    net.set_closed(1, 3, True)
    net.set_closed(2, 3, True)       # all arms to destination closed
    assert not net.is_reachable(0)
    ok = net.inject(_veh(99), 0)
    assert ok is False
    assert 99 in net.trapped          # recorded, not silently dropped
    assert 99 not in net.arrived


def test_vehicle_on_closing_link_not_removed(line_net):
    net = line_net
    net.inject(_veh(7), 0)
    # advance a few steps so the vehicle is somewhere on the path
    for step in range(5):
        net.step(step * 10.0, 10.0)
    net.set_closed(1, 2, True)        # close a mid link while vehicle in system
    for step in range(5, 60):
        net.step(step * 10.0, 10.0)
        # vehicle 7 is always accounted for: active, arrived, or trapped
        total = net.active_count() + len(net.arrived) + len(net.trapped)
        assert total == 1
