"""Mesoscopic traffic engine (spatial-queue / link-transmission style).

Why not a fixed-travel-time graph? Requirement 4 forbids it. Each directed link
has FINITE STORAGE, a DISCHARGE (outflow) CAPACITY, a FIFO QUEUE, and DOWNSTREAM
BLOCKING (spillback). Congestion and queues therefore emerge endogenously.

Model summary (per directed link e):
  length  L_e    [m]
  speed   v_e    [m/s]        -> free-flow traversal time  tff_e = L_e / v_e
  lanes   n_e
  capacity Q_e   [veh/s]      = per_lane_veh_hour * n_e / 3600   (discharge rate)
  storage  N_e   [veh]        = jam_density * n_e * (L_e/1000)    (finite storage)

Per time step dt, each link is a single FIFO queue. A vehicle must spend at least
tff_e on the link ("running") before it is eligible to leave from the head. The
head vehicle moves to its next link B only if (a) e has remaining sending budget
(<= Q_e*dt this step) and (b) B has remaining RECEIVING capacity
(min(Q_B*dt, N_B - occupancy_B)). If B is full, the head blocks — head-of-line
blocking — and the queue on e grows, spilling back upstream when e fills. Vehicles
reaching a destination node leave through an infinite-capacity sink.

Determinism: links are processed in a fixed sorted order each step; cross-link
spillback relief propagates over successive steps (dt is small). No RNG is used
inside the engine, so runs are reproducible given identical injections.

Units: seconds, meters, vehicles.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import networkx as nx


@dataclass
class Link:
    u: int
    v: int
    length_m: float
    speed_mps: float
    lanes: int
    capacity_veh_s: float          # discharge capacity
    storage_veh: float             # finite storage (jam)
    speed_source: str = "osm"      # provenance flag
    closed: bool = False

    # dynamic state
    queue: deque = field(default_factory=deque)       # vehicle ids, entry order (FIFO)
    entry_time: dict = field(default_factory=dict)    # vid -> time entered link
    occupancy: int = 0
    # metrics
    max_occupancy: int = 0
    cumulative_out: int = 0

    @property
    def tff_s(self) -> float:
        return self.length_m / max(self.speed_mps, 0.1)

    def earliest_exit(self, vid: int, now: float) -> float:
        return self.entry_time[vid] + self.tff_s


class Trapped(Exception):
    """Raised internally when a vehicle has no route to any destination."""


class MesoNetwork:
    """Directed routable network + spatial-queue dynamics.

    Build from a networkx DiGraph whose edges carry: length_m, speed_mps, lanes,
    capacity_veh_s, storage_veh (see network.build). Destinations are a set of
    node ids acting as infinite sinks.
    """

    def __init__(self, graph: nx.DiGraph, destinations: set[int]):
        self.G = graph
        self.destinations = set(destinations)
        self.links: dict[tuple[int, int], Link] = {}
        for u, v, data in graph.edges(data=True):
            self.links[(u, v)] = Link(
                u=u, v=v,
                length_m=float(data["length_m"]),
                speed_mps=float(data["speed_mps"]),
                lanes=int(data.get("lanes", 1)),
                capacity_veh_s=float(data["capacity_veh_s"]),
                storage_veh=max(1.0, float(data["storage_veh"])),
                speed_source=data.get("speed_source", "osm"),
            )
        # vehicle registry (engine-owned dynamic state keyed by vid)
        self.state: dict[int, dict] = {}   # vid -> {route, idx, link, mode}
        self.vehicles: dict[int, object] = {}   # vid -> external Vehicle object
        self.pending_injection: list[int] = []  # vids waiting to enter first link
        self.arrived: list[int] = []            # vids that reached a destination
        self.trapped: list[int] = []            # vids with no route when needed
        self._closed_edges: set[tuple[int, int]] = set()

    # ---------------------------------------------------------------- routing
    def _edge_cost(self, u, v, data) -> float:
        if (u, v) in self._closed_edges:
            return math.inf
        link = self.links.get((u, v))
        if link is None or link.closed:
            return math.inf
        return link.tff_s

    def shortest_path_to_any(self, origin: int, dests: set[int] | None = None):
        """Free-flow shortest path from origin to the NEAREST destination.

        Returns (path_nodes, cost) or (None, inf) if unreachable. Closed links
        are excluded (used for rerouting around closures)."""
        dests = self.destinations if dests is None else dests
        if origin in dests:
            return [origin], 0.0
        best_path, best_cost = None, math.inf
        # Multi-target Dijkstra from origin.
        try:
            lengths, paths = nx.single_source_dijkstra(
                self.G, origin, weight=self._edge_cost
            )
        except nx.NodeNotFound:
            return None, math.inf
        for d in dests:
            if d in lengths and lengths[d] < best_cost:
                best_cost, best_path = lengths[d], paths[d]
        return best_path, best_cost

    def is_reachable(self, origin: int) -> bool:
        path, _ = self.shortest_path_to_any(origin)
        return path is not None

    def reachable_origins(self) -> set[int]:
        """Set of nodes from which at least one destination is reachable, via a
        single reverse traversal (ancestors of the destinations). Ignores dynamic
        closures — intended for static placement/connectivity checks."""
        reach: set[int] = set(self.destinations)
        for d in self.destinations:
            if d in self.G:
                reach |= nx.ancestors(self.G, d)
        return reach

    # --------------------------------------------------------------- closures
    def set_closed(self, u: int, v: int, closed: bool = True) -> None:
        link = self.links.get((u, v))
        if link is None:
            return
        link.closed = closed
        if closed:
            self._closed_edges.add((u, v))
        else:
            self._closed_edges.discard((u, v))

    # ------------------------------------------------------------- injection
    def inject(self, vehicle, origin_node: int, targets: set[int] | None = None,
               route: list[int] | None = None) -> bool:
        """Register a vehicle for entry at origin_node toward a target node set.

        targets defaults to the global safety destinations. For AV pickup legs,
        pass targets={pickup_node}. Returns False if no route to any target exists
        (vehicle recorded as trapped and NOT silently dropped)."""
        vid = vehicle.vid
        tgt = set(targets) if targets is not None else set(self.destinations)
        if route is None:
            route, cost = self.shortest_path_to_any(origin_node, tgt)
        if route is None:
            if vid not in self.trapped:
                self.trapped.append(vid)
            self.vehicles[vid] = vehicle
            self.state[vid] = {"route": None, "idx": 0, "link": None,
                               "status": "trapped", "targets": tgt}
            return False
        self.vehicles[vid] = vehicle
        self.state[vid] = {"route": route, "idx": 0, "link": None,
                           "status": "pending", "targets": tgt}
        self.pending_injection.append(vid)
        return True

    def _try_inject(self, vid: int, now: float) -> bool:
        st = self.state[vid]
        route = st["route"]
        if route is None or len(route) < 2:
            # origin already a target
            self._arrive(vid, now, route[0] if route else None)
            return True
        first = (route[0], route[1])
        link = self.links.get(first)
        if link is None or link.closed:
            # reroute from origin
            return self._reroute(vid, route[0], now)
        if link.occupancy + 1 > link.storage_veh:
            return False  # origin queue: link full, wait (spillback to origin)
        self._enter_link(vid, link, now, idx=0)
        st["status"] = "moving"
        return True

    # -------------------------------------------------------------- movement
    def _enter_link(self, vid: int, link: Link, now: float, idx: int) -> None:
        link.queue.append(vid)
        link.entry_time[vid] = now
        link.occupancy += 1
        link.max_occupancy = max(link.max_occupancy, link.occupancy)
        self.state[vid]["link"] = (link.u, link.v)
        self.state[vid]["idx"] = idx

    def _leave_link(self, link: Link, vid: int) -> None:
        link.queue.popleft()
        link.entry_time.pop(vid, None)
        link.occupancy -= 1
        link.cumulative_out += 1

    def _arrive(self, vid: int, now: float, node: int | None = None) -> None:
        st = self.state[vid]
        st["status"] = "arrived"
        st["link"] = None
        if node is None and st.get("route"):
            node = st["route"][-1]
        self.arrived.append(vid)
        veh = self.vehicles[vid]
        if node is not None:
            setattr(veh, "node", node)
        if hasattr(veh, "on_arrival"):
            veh.on_arrival(now, node)

    def _reroute(self, vid: int, current_node: int, now: float) -> bool:
        """Recompute a path from current_node avoiding closed links."""
        tgt = self.state[vid].get("targets", self.destinations)
        path, cost = self.shortest_path_to_any(current_node, tgt)
        if path is None or math.isinf(cost):
            # no escape route: vehicle is trapped at current node
            st = self.state[vid]
            st["status"] = "trapped"
            st["link"] = None
            if vid not in self.trapped:
                self.trapped.append(vid)
            veh = self.vehicles[vid]
            if hasattr(veh, "on_trapped"):
                veh.on_trapped(now, current_node)
            return False
        self.state[vid]["route"] = path
        self.state[vid]["idx"] = 0
        return True

    def step(self, now: float, dt: float) -> dict:
        """Advance the whole network by dt seconds. Returns step event summary."""
        events = {"arrived": [], "trapped": [], "injected": 0}

        # 1. per-link budgets for this step
        send_budget: dict = {}
        recv_budget: dict = {}
        for key, link in self.links.items():
            if link.closed:
                send_budget[key] = 0.0
                recv_budget[key] = 0.0
            else:
                send_budget[key] = link.capacity_veh_s * dt
                recv_budget[key] = min(link.capacity_veh_s * dt,
                                       link.storage_veh - link.occupancy)

        # 2. attempt injections (origin -> first link), subject to receiving cap
        still_pending = []
        for vid in self.pending_injection:
            st = self.state[vid]
            route = st["route"]
            if route is None or len(route) < 2:
                self._arrive(vid, now, route[0] if route else None)
                events["arrived"].append(vid)
                continue
            key = (route[0], route[1])
            if recv_budget.get(key, 0.0) >= 1.0 and not self.links[key].closed:
                if self._try_inject(vid, now):
                    recv_budget[key] -= 1.0
                    events["injected"] += 1
                else:
                    still_pending.append(vid)
            else:
                still_pending.append(vid)
        self.pending_injection = still_pending

        # 3. move vehicles link by link (deterministic order)
        for key in sorted(self.links.keys()):
            link = self.links[key]
            if link.closed:
                continue
            # discharge head vehicles while budget + eligibility + receiving allow
            while link.queue and send_budget[key] >= 1.0:
                vid = link.queue[0]
                if link.earliest_exit(vid, now) > now:
                    break  # head still running; FIFO head-of-line
                st = self.state[vid]
                route = st["route"]
                idx = st["idx"]
                targets = st["targets"]
                # current node is route[idx+1] (downstream end of this link)
                cur_node = route[idx + 1]
                if cur_node in targets:
                    self._leave_link(link, vid)
                    send_budget[key] -= 1.0
                    self._arrive(vid, now, cur_node)
                    events["arrived"].append(vid)
                    continue
                # next link is route[idx+1] -> route[idx+2]
                if idx + 2 >= len(route):
                    # malformed; treat as arrival at last node if it's a target else trapped
                    self._leave_link(link, vid)
                    send_budget[key] -= 1.0
                    if cur_node in targets:
                        self._arrive(vid, now, cur_node)
                        events["arrived"].append(vid)
                    else:
                        self._reroute(vid, cur_node, now)
                        if self.state[vid]["status"] == "trapped":
                            events["trapped"].append(vid)
                        else:
                            self.pending_injection.append(vid)
                    continue
                nkey = (cur_node, route[idx + 2])
                nlink = self.links.get(nkey)
                if nlink is None or nlink.closed:
                    # downstream closed -> reroute from current node
                    self._leave_link(link, vid)
                    send_budget[key] -= 1.0
                    if self._reroute(vid, cur_node, now):
                        # re-inject into new first link next opportunity
                        self.pending_injection.append(vid)
                    else:
                        events["trapped"].append(vid)
                    continue
                if recv_budget.get(nkey, 0.0) >= 1.0:
                    self._leave_link(link, vid)
                    send_budget[key] -= 1.0
                    recv_budget[nkey] -= 1.0
                    self._enter_link(vid, nlink, now, idx=idx + 1)
                else:
                    break  # spillback: downstream full, head blocks
        return events

    # ------------------------------------------------------- dispatch helpers
    def node_lonlat(self, n: int) -> tuple[float, float]:
        d = self.G.nodes[n]
        return d.get("lon"), d.get("lat")

    def free_flow_eta(self, path: list[int]) -> float:
        """Sum of free-flow link times along a node path (seconds)."""
        if not path or len(path) < 2:
            return 0.0
        total = 0.0
        for u, v in zip(path[:-1], path[1:]):
            link = self.links.get((u, v))
            total += link.tff_s if link else math.inf
        return total

    def path_between(self, origin: int, target: int):
        """Free-flow shortest path origin -> single target (avoiding closures)."""
        return self.shortest_path_to_any(origin, {target})

    # --------------------------------------------------------------- queries
    def active_count(self) -> int:
        return sum(1 for s in self.state.values() if s["status"] in ("moving", "pending"))

    def link_stats(self) -> list[dict]:
        rows = []
        for (u, v), link in self.links.items():
            rows.append({
                "u": u, "v": v, "occupancy": link.occupancy,
                "max_occupancy": link.max_occupancy,
                "storage_veh": round(link.storage_veh, 2),
                "cumulative_out": link.cumulative_out,
                "closed": link.closed,
                "saturation": round(link.max_occupancy / link.storage_veh, 3),
            })
        return rows

    def bottlenecks(self, top: int = 10) -> list[dict]:
        rows = self.link_stats()
        rows.sort(key=lambda r: r["saturation"], reverse=True)
        return rows[:top]
