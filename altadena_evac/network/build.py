"""Build routable networks.

Two paths:
  * build_from_osm(...)  — real Altadena network via osmnx (needs internet).
  * make_toy_grid(...)   — deterministic synthetic grid for tests/demo (no deps
                            beyond networkx).

Both produce a networkx.DiGraph whose edges carry the attributes the mesoscopic
engine needs: length_m, speed_mps, lanes, capacity_veh_s, storage_veh,
speed_source. One-way restrictions are preserved (directed edges).
"""
from __future__ import annotations

import datetime as _dt
import json
import math
from pathlib import Path

import networkx as nx


# --------------------------------------------------------------------- units
def _kmh_to_mps(kmh: float) -> float:
    return kmh / 3.6


def _parse_maxspeed(val) -> float | None:
    """Parse an OSM maxspeed tag -> km/h, or None if absent/unparseable."""
    if val is None:
        return None
    if isinstance(val, list):
        val = val[0]
    s = str(val).lower().strip()
    try:
        if "mph" in s:
            return float(s.replace("mph", "").strip()) * 1.609344
        return float(s.split()[0])
    except (ValueError, IndexError):
        return None


def _first(val, default):
    if isinstance(val, list):
        return val[0] if val else default
    return val if val is not None else default


# ------------------------------------------------------------ attribute pass
def attach_meso_attributes(G: nx.DiGraph, net_cfg: dict) -> nx.DiGraph:
    """Impute speed, lanes, capacity, and storage onto every edge.

    speed_source is recorded per edge ('osm_maxspeed' vs 'default_<class>') so the
    provenance of each speed is auditable (requirement 4)."""
    sp = net_cfg["edges"]["speed"]
    ln = net_cfg["edges"]["lanes"]
    cap_per_lane = net_cfg["edges"]["capacity"]["per_lane_veh_hour"]
    jam = net_cfg["edges"]["capacity"]["jam_density_veh_km_lane"]
    speed_defaults = sp["defaults_kmh"]
    lane_defaults = ln["defaults"]

    for u, v, data in G.edges(data=True):
        hwy = _first(data.get("highway"), "residential")
        if isinstance(hwy, list):
            hwy = hwy[0]
        # length (m)
        length_m = float(data.get("length_m", data.get("length", 0.0)) or 0.0)
        if length_m <= 0:
            length_m = 1.0
        data["length_m"] = length_m
        # speed
        ms = _parse_maxspeed(data.get("maxspeed"))
        if ms is not None:
            data["speed_mps"] = _kmh_to_mps(ms)
            data["speed_source"] = "osm_maxspeed"
        else:
            kmh = speed_defaults.get(hwy, speed_defaults.get("residential", 40))
            data["speed_mps"] = _kmh_to_mps(kmh)
            data["speed_source"] = f"default_{hwy}"
        # lanes (per direction)
        raw_lanes = _first(data.get("lanes"), None)
        try:
            lanes = int(float(raw_lanes)) if raw_lanes is not None else None
        except (ValueError, TypeError):
            lanes = None
        if not lanes or lanes < 1:
            lanes = lane_defaults.get(hwy, 1)
            data["lanes_source"] = f"default_{hwy}"
        else:
            data["lanes_source"] = "osm"
        data["lanes"] = max(1, lanes)
        # capacity (veh/s) and storage (veh)
        data["capacity_veh_s"] = cap_per_lane * data["lanes"] / 3600.0
        data["storage_veh"] = max(1.0, jam * data["lanes"] * (length_m / 1000.0))
    return G


def _to_digraph_simple(G) -> nx.DiGraph:
    """Collapse an osmnx MultiDiGraph to a simple DiGraph, keeping the shortest
    parallel edge between each (u, v). Node lon/lat preserved as x/y."""
    H = nx.DiGraph()
    for n, d in G.nodes(data=True):
        H.add_node(n, lon=d.get("x"), lat=d.get("y"),
                   px=d.get("px"), py=d.get("py"))
    for u, v, d in G.edges(data=True):
        length = float(d.get("length", 1.0))
        if H.has_edge(u, v):
            if length >= H[u][v].get("length", math.inf):
                continue
        attrs = dict(d)
        attrs["length_m"] = length
        H.add_edge(u, v, **attrs)
    return H


def build_from_osm(study_cfg: dict, net_cfg: dict, out_graphml: str | Path) -> dict:
    """Download the Altadena drive network (with buffer) via osmnx and prepare it.

    Returns a metadata dict (snapshot date, counts). Requires internet + osmnx.
    """
    import osmnx as ox

    b = study_cfg["boundary"]["demand_bbox"]
    buf = study_cfg["boundary"]["network_buffer_m"]
    # degrees per meter (approx at Altadena latitude)
    lat0 = (b["north"] + b["south"]) / 2
    dlat = buf / 111_320.0
    dlon = buf / (111_320.0 * math.cos(math.radians(lat0)))
    north, south = b["north"] + dlat, b["south"] - dlat
    east, west = b["east"] + dlon, b["west"] - dlon

    # osmnx 2.x expects bbox=(left, bottom, right, top) = (west, south, east, north)
    try:
        G = ox.graph_from_bbox(bbox=(west, south, east, north),
                               network_type=net_cfg["source"]["network_type"],
                               simplify=True)
    except TypeError:
        # older osmnx signature fallback
        G = ox.graph_from_bbox(north, south, east, west,
                               network_type=net_cfg["source"]["network_type"],
                               simplify=True)

    # project to meters for accurate lengths, keep lon/lat too
    crs_proj = study_cfg["crs"]["projected"]
    Gp = ox.project_graph(G, to_crs=crs_proj)
    # stash projected coords onto the geographic graph nodes
    for n, d in Gp.nodes(data=True):
        if n in G.nodes:
            G.nodes[n]["px"] = d.get("x")
            G.nodes[n]["py"] = d.get("y")
    # osmnx 'length' is meters (great-circle); keep it
    H = _to_digraph_simple(G)
    attach_meso_attributes(H, net_cfg)
    H = _clean_for_graphml(H)

    meta = {
        "downloaded_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "source": "OpenStreetMap via osmnx",
        "network_type": net_cfg["source"]["network_type"],
        "bbox_with_buffer": {"north": north, "south": south, "east": east, "west": west},
        "n_nodes": H.number_of_nodes(),
        "n_edges": H.number_of_edges(),
        "note": ("Current OSM snapshot at downloaded_at. NOT the January-2025 "
                 "network; do not describe it as such."),
    }
    out_graphml = Path(out_graphml)
    out_graphml.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(H, out_graphml)
    with open(out_graphml.with_suffix(".meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return meta


def _clean_for_graphml(H: nx.DiGraph) -> nx.DiGraph:
    """Keep only primitive attributes the engine uses so GraphML can serialize
    (osmnx edges carry list-valued tags that the GraphML writer rejects)."""
    C = nx.DiGraph()
    for n, d in H.nodes(data=True):
        C.add_node(n, lon=_f(d.get("lon")), lat=_f(d.get("lat")),
                   px=_f(d.get("px")), py=_f(d.get("py")))
    for u, v, d in H.edges(data=True):
        C.add_edge(u, v,
                   length_m=_f(d.get("length_m"), 1.0),
                   speed_mps=_f(d.get("speed_mps"), 11.1),
                   lanes=int(d.get("lanes", 1)),
                   capacity_veh_s=_f(d.get("capacity_veh_s"), 0.5),
                   storage_veh=_f(d.get("storage_veh"), 10.0),
                   speed_source=str(d.get("speed_source", "osm")),
                   lanes_source=str(d.get("lanes_source", "osm")))
    return C


def load_graphml(path: str | Path) -> nx.DiGraph:
    G = nx.read_graphml(path)
    # graphml stringifies attributes; coerce the numeric ones back
    DG = nx.DiGraph()
    for n, d in G.nodes(data=True):
        DG.add_node(_coerce_node(n),
                    lon=_f(d.get("lon")), lat=_f(d.get("lat")),
                    px=_f(d.get("px")), py=_f(d.get("py")))
    for u, v, d in G.edges(data=True):
        DG.add_edge(_coerce_node(u), _coerce_node(v),
                    length_m=_f(d.get("length_m"), 1.0),
                    speed_mps=_f(d.get("speed_mps"), 11.1),
                    lanes=int(_f(d.get("lanes"), 1)),
                    capacity_veh_s=_f(d.get("capacity_veh_s"), 0.5),
                    storage_veh=_f(d.get("storage_veh"), 10.0),
                    speed_source=d.get("speed_source", "osm"))
    return DG


def _coerce_node(n):
    try:
        return int(n)
    except (ValueError, TypeError):
        return n


def _f(x, default=0.0):
    try:
        return float(x)
    except (ValueError, TypeError):
        return default


def nearest_node(G: nx.DiGraph, lon: float, lat: float) -> int:
    """Nearest graph node to a lon/lat by planar approximation on lon/lat."""
    best, best_d = None, math.inf
    coslat = math.cos(math.radians(lat))
    for n, d in G.nodes(data=True):
        nlon, nlat = d.get("lon"), d.get("lat")
        if nlon is None or nlat is None:
            continue
        dx = (nlon - lon) * coslat
        dy = (nlat - lat)
        dd = dx * dx + dy * dy
        if dd < best_d:
            best_d, best = dd, n
    return best


# ---------------------------------------------------------------- toy grid
def make_toy_grid(rows: int = 4, cols: int = 4, spacing_m: float = 300.0,
                  speed_mps: float = 11.0, lanes: int = 1,
                  cap_per_lane_veh_hour: float = 1800.0,
                  jam_density: float = 130.0,
                  base_lon: float = -118.15, base_lat: float = 34.19) -> nx.DiGraph:
    """Deterministic grid network for tests and the offline demo.

    Nodes numbered row-major: nid = r*cols + c. Bidirectional edges between
    4-neighbors. Node (0,0) is NW; destinations are chosen by the caller (the
    demo uses the south edge). Coordinates are placed near Altadena purely so
    maps render; they are SYNTHETIC, not real Altadena geometry.
    """
    G = nx.DiGraph()
    dlat = spacing_m / 111_320.0
    dlon = spacing_m / (111_320.0 * math.cos(math.radians(base_lat)))
    for r in range(rows):
        for c in range(cols):
            nid = r * cols + c
            G.add_node(nid,
                       lon=base_lon + c * dlon,
                       lat=base_lat - r * dlat,  # row 0 north, rows increase south
                       px=c * spacing_m, py=-r * spacing_m)

    def add(u, v):
        G.add_edge(u, v,
                   length_m=spacing_m,
                   speed_mps=speed_mps,
                   lanes=lanes,
                   capacity_veh_s=cap_per_lane_veh_hour * lanes / 3600.0,
                   storage_veh=max(1.0, jam_density * lanes * (spacing_m / 1000.0)),
                   speed_source="synthetic_toy")

    for r in range(rows):
        for c in range(cols):
            nid = r * cols + c
            if c + 1 < cols:
                add(nid, nid + 1); add(nid + 1, nid)
            if r + 1 < rows:
                add(nid, nid + cols); add(nid + cols, nid)
    return G
