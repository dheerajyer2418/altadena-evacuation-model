"""Assemble a self-contained replay payload for the live UI.

A replay bundles the STATIC geometry (roads, household origins, destinations,
hazard parameters) once, plus the per-frame vehicle positions and live stats
recorded by the Simulation. The browser UI (ui/index.html) loads this JSON and
animates it.
"""
from __future__ import annotations


def _nodes_bounds(net):
    lons = [d["lon"] for _, d in net.G.nodes(data=True) if d.get("lon") is not None]
    lats = [d["lat"] for _, d in net.G.nodes(data=True) if d.get("lat") is not None]
    return {"west": min(lons), "east": max(lons), "south": min(lats), "north": max(lats),
            "clon": sum(lons) / len(lons), "clat": sum(lats) / len(lats)}


def build_replay(net, pop, scenario_cfg, frames, meta: dict) -> dict:
    # roads (undirected, deduped) as coordinate pairs
    roads, seen = [], set()
    for (u, v) in net.links:
        key = (u, v) if u < v else (v, u)
        if key in seen:
            continue
        seen.add(key)
        du, dv = net.G.nodes[u], net.G.nodes[v]
        if du.get("lon") is None or dv.get("lon") is None:
            continue
        roads.append([[round(du["lon"], 5), round(du["lat"], 5)],
                      [round(dv["lon"], 5), round(dv["lat"], 5)]])

    origins = [[round(h.lon, 5), round(h.lat, 5), 1 if h.no_vehicle else 0]
               for h in pop.households if h.lon]
    dests = [[net.G.nodes[n]["lon"], net.G.nodes[n]["lat"]]
             for n in net.destinations if net.G.nodes[n].get("lon") is not None]

    hz = {}
    if scenario_cfg.get("spread", {}).get("model") == "radial_front":
        ig = scenario_cfg["ignition"]
        sp = scenario_cfg["spread"]
        hz = {"model": "radial_front", "ig_lon": ig["lon"], "ig_lat": ig["lat"],
              "speed_mps": sp["speed_mps"], "anisotropy": sp.get("anisotropy", 1.0),
              "dir_bias_deg": sp.get("direction_bias_deg", 0.0),
              "detection_s": scenario_cfg.get("detection_time_s", 0.0)}

    return {
        "meta": meta,
        "bounds": _nodes_bounds(net),
        "roads": roads,
        "origins": origins,
        "destinations": dests,
        "hazard": hz,
        "frames": frames,
    }
