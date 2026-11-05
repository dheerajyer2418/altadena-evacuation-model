# Session Log

> **Note on the "different font":** GitHub-rendered Markdown strips custom font
> styling, so each session entry below is wrapped in a **monospace code block** —
> that's the distinct, different-looking typeface that actually survives on
> GitHub. (A true custom font would have to live on the website via CSS.)

---

```text
╔══════════════════════════════════════════════════════════════════════╗
║  SESSION — 2026-11-04                                                  ║
║  Theme: traffic/hazard robustness tooling + pull-out depot             ║
╚══════════════════════════════════════════════════════════════════════╝

WHAT WAS DONE THIS SESSION
--------------------------

1. Codebase walkthrough.
   Reviewed the engine, agents, policies, hazard, population, and UI.

2. Traffic sensitivity sweep  (NEW: scripts/sweep_traffic.py)
   Re-runs the policy comparison across a grid of road-capacity / jam-density
   values (per-lane saturation flow, jam density) on the SAME pop/hazard/seeds,
   and reports whether the carless policy ranking is robust to the UNCALIBRATED
   traffic assumptions. Rescales each edge from its as-built baseline (no OSM
   re-download). Tested on toy; injection proven to bite (cap=30 -> 0 reached).
   PENDING: run on --mode altadena.

3. Hazard randomization  (NEW: hazard/sampler.py + scripts/sweep_hazard.py)
   Monte Carlo over the fire itself: ignition point, spread AXIS, anisotropy,
   speed. Two sets — "foothills" (realistic northern origin, spread south) and
   "unbiased" (anywhere, any axis). Tie-aware STABLE/MIXED/ALL-TIED verdict on
   whether the carless policy ranking survives fire geometry. Writes CSVs + box
   plots + ignition maps. Added line-buffered stdout + a [done/total] + ETA
   heartbeat so progress is visible when backgrounded.

4. Validation of the hazard sweep on the REAL network (synthetic pop).
   n=2/set, 12 runs, 57.5 min. Result = MEANINGFUL, non-tied variation:
     - no-AV baseline:   carless reached 0%
     - +300 AV (normal): carless reached ~80–88%
     - +300 AV (geofencing): ~16–83%, always below normal
   Verdict STABLE (normal > geofencing for carless across all fires). The gap
   widens under nastier/unbiased fires (geofencing trades throughput for caution).

5. Dataset check — Kaggle "Next Day Wildfire Spread" (Huot et al. 2022).
   REJECTED as a hazard source: 1 km / 1-day resolution, US-wide ML tiles — far
   too coarse for road-level closure and a minutes-scale evacuation. Kept only as
   a reference; real sources would be LANDFIRE / 3DEP / HRRR / gridMET / FIRMS.

6. Design doc  (NEW: docs/HAZARD_RANDOMIZATION_PLAN.md)
   Level 1 (randomized synthetic fire) — BUILT. Level 2 (real wind/terrain/fuel,
   elliptical Rothermel-style or external ELMFIRE/Cell2Fire) — DESIGNED, unbuilt.

7. Replay/animation integration  (scripts/export_replay.py)
   Added --fire-set / --fire-id so the live UI can animate the EXACT sweep fire.
   Generated 3 local altadena animations for foothills fire #1 (no-AV / normal /
   geofencing), then REMOVED them from the local site per request.

8. Pull-out depot  (dispatch.py, sim/runner.py, config/fleet.yaml)  *** main build
   The withdrawal ("pull out") strategy now retreats AVs to a single staging
   DEPOT set off the egress corridor (fleet.depot -> nearest node), instead of
   dispersing them to the evacuation exits — so a pull-out doesn't add AV traffic
   to the roads evacuees use. Config: withdrawal.retreat: depot. Verified: 29/29
   tests pass; a toy withdrawal run parked retreating AVs at the depot node.
   Also added a plain-language note in the UI "Sources & Methodology" panel.

SIMULATIONS RUN THIS SESSION (approximate)
------------------------------------------
~180 full scenario runs launched across: traffic sweeps (~72), hazard sweeps
(toy ~70 + altadena validation 12), replays (4), and verification (1); plus one
altadena n=5 hazard sweep and one n=20 killed early. The pytest suite (29 tests)
was run ~4× and executes many additional mini-simulations internally.
NOTE: exact count is not reconstructable; a persistent run counter is a proposed
quick win that would make this precise going forward.

STILL PENDING / DECIDED
-----------------------
- Survey data: to be provided; agreed to process it LOCAL-ONLY (gitignored
  data/raw/, parsed by local scripts that emit only aggregates).
- Recommended quick wins: pull-out depot (DONE), carpool-for-carless (mechanism,
  placeholder %), run counter + richer comparison metrics. Deferred: walking
  mode (medium), AV energy/recharge (heavy).
- Full n=20 hazard sweep: not started (compute + real-vs-synthetic-pop decision).
```
