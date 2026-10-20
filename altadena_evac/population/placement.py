"""Place households at plausible residential locations and attach origin_node.

Preferred (real data): sample points inside each block-group polygon weighted by
OSM residential building footprints, then snap to the nearest network node.
Fallbacks are LABELED on each household (``placement_method``) so any use of a
crude fallback is auditable (requirement 2).

For the offline demo / Altadena-network run with a synthetic population we use
``place_on_network``: assign each household to a candidate residential node
(non-destination, connected). This guarantees connectivity and sets origin_node.
"""
from __future__ import annotations

import numpy as np

from ..network.build import nearest_node


def place_on_network(population, net, rng, method_label="network_node_fallback",
                     exclude_nodes=None):
    """Assign each household to a candidate residential node on `net`.

    Candidate nodes = all nodes that are not destinations and are not isolated.
    Households inherit the node's lon/lat. This is a FALLBACK placement (no
    building/land-use detail) and is labeled as such on every household."""
    exclude = set(exclude_nodes or []) | set(net.destinations)
    candidates = [n for n in net.G.nodes
                  if n not in exclude and net.G.out_degree(n) > 0]
    if not candidates:
        candidates = list(net.G.nodes)
    # keep only candidates that can actually reach safety (single reverse pass)
    reachable_set = net.reachable_origins()
    reachable = [n for n in candidates if n in reachable_set]
    if reachable:
        candidates = reachable
    idx = rng.integers(0, len(candidates), size=len(population.households))
    unreachable_assigned = 0
    for k, h in enumerate(population.households):
        n = candidates[int(idx[k])]
        d = net.G.nodes[n]
        h.origin_node = n
        h.lon, h.lat = d.get("lon", 0.0), d.get("lat", 0.0)
        h.x, h.y = d.get("px", 0.0) or 0.0, d.get("py", 0.0) or 0.0
        h.placement_method = method_label
        if n not in reachable_set:
            unreachable_assigned += 1
    population.meta["placement"] = {
        "method": method_label,
        "n_candidate_nodes": len(candidates),
        "households_on_unreachable_origin": unreachable_assigned,
    }
    return population


def place_from_osm(population, net, bg_polygons, buildings_gdf, crs_proj, rng):
    """Real placement from OSM residential buildings within block-group polygons.

    bg_polygons: GeoDataFrame indexed by GEOID (TIGER block groups).
    buildings_gdf: GeoDataFrame of OSM building footprints (residential filtered).
    Households of a block group are placed at sampled building centroids inside
    that polygon; if a block group has no buildings, fall back to a uniform random
    point in the polygon (labeled 'landuse_random'); if the polygon is missing,
    fall back to 'bbox_random'. origin_node is the nearest network node.

    This path requires live OSM + TIGER (and therefore a Census key for the
    polygons). It is implemented but cannot be exercised offline; see
    VALIDATION_REPORT.md.
    """
    import geopandas as gpd  # noqa: F401  (import guarded; only used on real path)
    from shapely.geometry import Point  # noqa: F401

    # Group households by block group
    by_bg = {}
    for h in population.households:
        by_bg.setdefault(h.block_group, []).append(h)

    res = buildings_gdf
    for geoid, hhs in by_bg.items():
        if geoid not in bg_polygons.index:
            _fallback_bbox(hhs, net, rng, "bbox_random")
            continue
        poly = bg_polygons.loc[geoid].geometry
        in_poly = res[res.intersects(poly)] if res is not None else None
        if in_poly is not None and len(in_poly) > 0:
            cents = in_poly.geometry.centroid.to_crs(epsg=4326)
            pick = rng.integers(0, len(cents), size=len(hhs))
            for h, pi in zip(hhs, pick):
                pt = cents.iloc[int(pi)]
                _assign_point(h, net, pt.x, pt.y, "osm_buildings")
        else:
            _sample_in_polygon(hhs, poly, net, rng, "landuse_random")
    return population


def _assign_point(h, net, lon, lat, label):
    h.lon, h.lat = lon, lat
    h.origin_node = nearest_node(net.G, lon, lat)
    h.placement_method = label


def _sample_in_polygon(hhs, poly, net, rng, label):
    from shapely.geometry import Point
    minx, miny, maxx, maxy = poly.bounds
    for h in hhs:
        for _ in range(50):
            lon = rng.uniform(minx, maxx)
            lat = rng.uniform(miny, maxy)
            if poly.contains(Point(lon, lat)):
                _assign_point(h, net, lon, lat, label)
                break
        else:
            _assign_point(h, net, (minx + maxx) / 2, (miny + maxy) / 2, "bbox_random")


def _fallback_bbox(hhs, net, rng, label):
    lons = [d.get("lon") for _, d in net.G.nodes(data=True) if d.get("lon")]
    lats = [d.get("lat") for _, d in net.G.nodes(data=True) if d.get("lat")]
    if not lons:
        return
    for h in hhs:
        _assign_point(h, net, float(np.mean(lons)), float(np.mean(lats)), label)
