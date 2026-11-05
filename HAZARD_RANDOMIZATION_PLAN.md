# Hazard randomization & real-wildfire plan (design only — not yet built)

Status: **PLAN ONLY.** No code written yet (per decision 2026-11-04). This
document is the agreed design to review before implementation.

Goal: stress-test the AV-policy conclusions against *where* a fire starts and
*how* it spreads, and chart a path toward terrain/wind/fuel-driven fires.

---

## 0. The hook that makes all of this clean

`altadena_evac/hazard/scenario.py::GroundTruthHazard` exposes only two things to
the rest of the model:

- `arrival_time(lon, lat) -> seconds` — when the front reaches a point
- `closed_links_at(t, net) -> set[(u,v)]` — which roads are cut by time `t`

The forecast layer (`Forecast`) and the engine consume *only* these. **Any fire
model that can produce an arrival-time field satisfies this interface**, so every
option below plugs in behind the same seam without changing the ABM, dispatcher,
or engine. The config already anticipates alternatives via `spread.model`
(`radial_front` today; `polygon_series` reserved).

---

## LEVEL 1 — Randomized synthetic fire (Monte Carlo). Cheap, no new deps.

The existing `radial_front` model already carries the four knobs we want to
randomize (see `config/hazard.yaml::foothill_santa_ana`):

| Knob | Meaning | Current value |
|---|---|---|
| `ignition.lon/lat` | where it starts | 34.2180, -118.1250 |
| `direction_bias_deg` | spread **axis** (0=N, clockwise) | 215 (SW) |
| `anisotropy` | downwind speed-up along that axis | 1.6 |
| `speed_mps` | base front speed | 0.6 |

> Note: today the three `hazard` seeds only perturb **forecast error**; the
> ground-truth front is fixed. Level 1 is what makes the *fire itself* stochastic.

### Planned script: `scripts/sweep_hazard.py`
Mirrors the structure of the existing `scripts/sweep_traffic.py` (same
population/network/seeds held fixed; only the hazard varies), reusing
`runner.prepare`, `runner.run_single`, and `metrics.summarize`.

1. **Sample N fire realizations** from a master seed. Each realization clones the
   base `foothill_santa_ana` scenario dict and overrides ignition/axis/anisotropy/
   speed. Reproducible: realization `i` derives from `seed + i`.
2. **Run each realization** on the shared base population + network, optionally
   across each AV policy and the no-AV baseline, for the configured behavior/
   dispatch/forecast seeds.
3. **Aggregate the distribution** of outcomes across fires: reached_frac,
   **carless_reached_frac** (research focus), exposed, trapped, clearance.
4. **Ranking-stability verdict** (same idea as the traffic sweep): does the same
   policy win for carless households across the fire ensemble, or do some fire
   geometries flip it? Report fraction of fires each policy "wins."

### Two ignition sets (decision: build BOTH, compare)

Study bounds (`config/study.yaml`): demand bbox N 34.2300 / S 34.1720 /
E -118.0850 / W -118.1800; destinations are in the **south** (~34.147–34.168).

- **Set A — "foothills" (realistic WUI origin).** Ignite along the northern
  foothill band, proposed `lat ∈ [34.212, 34.230]`, `lon ∈ [-118.180, -118.085]`.
  Spread axis biased **southward** toward the evacuation routes:
  `direction_bias_deg ∈ [180, 250]` (S→SW, Santa Ana-consistent). This is the
  realistic case: fire above town pushing down into it.
- **Set B — "unbiased" (stress test).** Ignite anywhere in the demand bbox;
  `direction_bias_deg ∈ [0, 360)`. Tests robustness to arbitrary fire geometry,
  including less-likely cases (fire from the south/east).

Shared sampling ranges (proposed, editable): `anisotropy ∈ [1.2, 2.5]`,
`speed_mps ∈ [0.3, 1.0]` — the upper bound kept modest so the fire stays *dire
but survivable* (per `docs/ASSUMPTIONS.md`; a front that traps everyone leaves no
room to compare policies). Report both sets side by side.

### Outputs (to `outputs/sweep_hazard_<mode>/`)
- `hazard_runs.csv` — one row per (set, realization, policy, seed) with the
  sampled fire params + `metrics.summarize` columns.
- `hazard_ranking.csv` — per set: policy win-rate and ranking-stability verdict.
- Plots: distribution (box/violin) of `carless_reached_frac` per policy per set;
  a scatter of **ignition points colored by baseline outcome** (shows which fire
  origins are most dangerous and whether different fires stress different roads —
  `result["bottlenecks"]` already gives the top-saturated links per run).

### Effort / risk
~1 day. No new dependencies. Main cost is runtime: altadena runs are 1–4 min
each, so N realizations × policies × seeds must be sized deliberately (start
small, e.g. N=20 per set × {no-AV, 1–2 policies} × 1 seed, then scale).

---

## LEVEL 2 — Real wind / vegetation / terrain-driven fire

Two sub-options, both plugging into the `arrival_time` seam. **Key technical
change vs Level 1:** once spread speed varies in space, you can no longer use the
closed-form `distance / speed`; you need an **arrival-time field solved on a
grid** (an Eikonal / fast-marching or Dijkstra-on-raster solve). That solver is
the core new piece.

### Datasets (all free, standard in fire science)
- **LANDFIRE** (landfire.gov) — 30 m fuel models (Scott & Burgan 40), canopy
  cover/height/bulk density, vegetation type. → *vegetation / "forest placement".*
- **USGS 3DEP / SRTM** — elevation → **slope & aspect** (fire runs uphill). → *terrain.*
- **Wind** — NOAA **HRRR** (hourly, 3 km, 10 m winds), **gridMET** (daily, 4 km,
  + RH/temp/fuel moisture), **RAWS** station obs via Synoptic/MesoWest API. For
  the San Gabriels, **WindNinja** (USFS) downscales wind over the terrain —
  important for Santa Ana channeling.
- **Historical fire (for methodology/validation only)** — NASA **FIRMS**
  (VIIRS/MODIS active fire), **NIFC** & **CAL FIRE FRAP** perimeters, **GOES**.

### 2a — In-house elliptical spread (recommended first step for Level 2)
Add a new `spread.model: wind_terrain_elliptical` to `GroundTruthHazard`:
- Build a raster grid over the study bbox.
- Per cell, compute a local spread rate from a **simplified Rothermel-style**
  rule: base rate × wind factor (from a wind vector, time-varying allowed) ×
  slope factor (from DEM) × fuel multiplier (from LANDFIRE). Direction-dependent
  → an ellipse elongated downwind/upslope.
- Solve arrival times with **fast marching** (`scikit-fmm`) or Dijkstra on the
  grid; `arrival_time(lon,lat)` interpolates that field. `closed_links_at`
  samples it exactly as today.
- Randomization layer still applies (sample wind speed/direction, ignition, fuel
  moisture), so Level 1's Monte Carlo generalizes naturally to realistic fires.
- New deps: `scikit-fmm` (or hand-rolled grid Dijkstra), `rasterio`/`rioxarray`
  + GDAL for the DEM/LANDFIRE rasters, an API client for wind. Effort: ~1–2 weeks
  incl. data plumbing + a calibration pass. Keeps everything in-process and
  testable — consistent with the project's "own the loop" philosophy.

### 2b — External fire simulator (gold standard, heavy)
Run **ELMFIRE** or **Cell2Fire** (open source) — or **FlamMap/FARSITE** (USFS) —
offline to produce an **arrival-time raster**, then add a thin
`RasterArrivalHazard` backend that loads it and interpolates. Fully decouples the
fire physics from the ABM. Highest fidelity; largest integration + ops burden
(their own raster stacks, installs, parameterization). Effort: multi-week.

---

## Research-integrity constraint (must decide before Level 2 uses real fire)

The project is deliberately **hypothetical and explicitly NOT a reconstruction of
the Jan-2025 Eaton Fire** (stated throughout README / VALIDATION_REPORT /
hazard.yaml). Therefore:

- Using real **terrain / wind / fuel** to make *hypothetical* fires realistic is
  consistent with the project framing. ✅
- **Replaying a specific real fire perimeter (e.g., the actual Eaton Fire)** is a
  different scientific claim (reconstruction/validation). It would need explicit
  sign-off from **Dr. Grajdura** and relabeling of the validation docs. ❌

---

## Open decisions for Dr. Grajdura / next session
1. Level 1 sampling ranges (ignition bands, axis ranges, anisotropy, speed) — are
   the proposed defaults acceptable, or should they reflect specific Santa Ana
   climatology?
2. Level 2 path: in-house elliptical (2a) vs external simulator (2b)?
3. Whether any **real historical fire** may be used, and if so purely as a
   spread-realism/validation exercise (not as an Altadena prediction).
4. Compute budget for the Monte Carlo (N × policies × seeds × run time).

## Where to start implementing (when approved)
Level 1 first: create `scripts/sweep_hazard.py` modeled on
`scripts/sweep_traffic.py`; add a small hazard-realization sampler (new helper,
e.g. `altadena_evac/hazard/sampler.py`) that emits scenario-dict overrides for
sets A and B from a seed. No changes needed to the engine, dispatcher, or
`GroundTruthHazard` for Level 1.
