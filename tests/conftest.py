"""Shared fixtures: small controlled networks and populations for mechanism tests."""
from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from altadena_evac.network.build import make_toy_grid
from altadena_evac.network.mesoscopic import MesoNetwork
from altadena_evac.population.agents import Household, Person, Population


def _edge(G, u, v, length=300.0, speed=10.0, lanes=1, cap_lane=1800.0, jam=130.0):
    G.add_edge(u, v, length_m=length, speed_mps=speed, lanes=lanes,
               capacity_veh_s=cap_lane * lanes / 3600.0,
               storage_veh=max(1.0, jam * lanes * (length / 1000.0)),
               speed_source="test")


@pytest.fixture
def line_net():
    """Linear path 0->1->2->3 with node 3 a destination. Coords along a line."""
    G = nx.DiGraph()
    for n in range(4):
        G.add_node(n, lon=-118.15 + 0.001 * n, lat=34.19, px=300.0 * n, py=0.0)
    for u in range(3):
        _edge(G, u, u + 1)
    return MesoNetwork(G, destinations={3})


@pytest.fixture
def diamond_net():
    """0 -> {1 (short), 2a->2b (long)} -> 3 (dest). Lets us close the short arm."""
    G = nx.DiGraph()
    coords = {0: (-118.16, 34.20), 1: (-118.15, 34.195),
              2: (-118.17, 34.195), 3: (-118.15, 34.18)}
    for n, (lon, lat) in coords.items():
        G.add_node(n, lon=lon, lat=lat, px=0.0, py=0.0)
    _edge(G, 0, 1, length=200.0)     # short arm
    _edge(G, 1, 3, length=200.0)
    _edge(G, 0, 2, length=800.0)     # long arm
    _edge(G, 2, 3, length=800.0)
    return MesoNetwork(G, destinations={3})


@pytest.fixture
def tiny_capacity_net():
    """0 -> 1 (dest) with VERY small storage + capacity to force queueing."""
    G = nx.DiGraph()
    G.add_node(0, lon=-118.15, lat=34.19, px=0.0, py=0.0)
    G.add_node(1, lon=-118.15, lat=34.18, px=0.0, py=300.0)
    # storage ~ 3 vehicles, capacity ~ 1 veh / 10 s
    G.add_edge(0, 1, length_m=100.0, speed_mps=10.0, lanes=1,
               capacity_veh_s=0.1, storage_veh=3.0, speed_source="test")
    return MesoNetwork(G, destinations={1})


@pytest.fixture
def toy_net():
    G = make_toy_grid(rows=4, cols=4)
    dests = {(4 - 1) * 4 + c for c in range(4)}
    return MesoNetwork(G, dests), G, dests


def make_population(specs):
    """specs: list of dicts {node, vehicles, assistance, size, disability}.
    Returns a Population with one household per spec (persons = size)."""
    persons, households = [], []
    pid = 0
    for hid, s in enumerate(specs):
        members = []
        for k in range(s.get("size", 1)):
            p = Person(pid=pid, hid=hid, age=40, sex="female", race="white",
                       hispanic=False, disability=s.get("disability", False),
                       is_driver=True)
            persons.append(p)
            members.append(pid)
            pid += 1
        h = Household(hid=hid, block_group="T", members=members,
                      n_vehicles=s.get("vehicles", 1), seats_per_vehicle=4,
                      assistance_need=s.get("assistance", False))
        h.origin_node = s["node"]
        h.lon, h.lat = -118.15, 34.19
        households.append(h)
    return Population(persons=persons, households=households)
