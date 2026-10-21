# Altadena Wildfire Evacuation ABM

An agent-based model of wildfire evacuation in **pre-January-2025 Altadena, California**,
built on a U.S. Census–based synthetic population and a real OpenStreetMap road network,
with a mesoscopic traffic engine (finite road storage, discharge capacity, queues, and
downstream blocking) and four autonomous-vehicle (AV) dispatch policies.

Research project with **Dr. Sarah Grajdura (UIC)**. The scientific question is how AV
evacuation policies affect outcomes, **especially for households without private vehicles**.

> **This is a hypothetical-scenario model, not a reconstruction of the January 2025 Eaton
> Fire.** Hazard scenarios are synthetic and reproducible. Camp Fire (2018) behavioral
> coefficients from Grajdura, Borjigin & Niemeier (2022) are available only as an explicitly
> labeled *optional transfer scenario* and are **not** validated for Altadena. See
> `VALIDATION_REPORT.md` before citing any number.

---

## What actually runs today

| Component | Status | Real data? |
|---|---|---|
| Mesoscopic traffic engine (storage/capacity/queues/spillback) | ✅ working, unit-tested | n/a |
| People / households / vehicles / AV-dispatch agents | ✅ working, unit-tested | n/a |
| Behavior timeline (awareness→prep→request→departure→arrival) | ✅ working, config-driven | n/a |
| Time-dependent hazard + separate forecast (info boundary enforced) | ✅ working, unit-tested | synthetic |
| Four AV policies + geofencing ablation | ✅ working, unit-tested | n/a |
| TIGER Altadena block-group selection (34 BGs, 8 tracts) | ✅ working, live-verified | **live TIGER (no key)** |
| Census/ACS importer (B01001, B02001, B03003, B25044, B11016, B19001) | ✅ working, live-verified | **live Census API** |
| PUMS-donor + IPU household synthesis (SRMSE 0.06 vs real ACS) | ✅ working, live-verified | **live Census API (key)** |
| OSM network build (osmnx) → routable mesoscopic network | ✅ working | **live OSM** |
| Residential placement from OSM buildings/landuse | ✅ working, fallback labeled | **live OSM** |
| INRIX importer | ⚠️ documented interface only (no data supplied) | n/a |
| Offline demo fixture (toy network + synthetic pop) | ✅ end-to-end | **synthetic test data** |

See `VALIDATION_REPORT.md` for the honest line between *software verification*, *population
fit*, *traffic calibration* (none yet), and *external validation* (none yet).

---

## Install

Requires **Python 3.11+** (developed on 3.14). From the project root:

```powershell
python -m pip install -r requirements.txt
```

Core simulation, tests, and the offline demo need only: `numpy pandas scipy networkx
matplotlib pyyaml pytest`. Real-data acquisition additionally needs `osmnx geopandas
shapely pyproj requests` (geo stack). SUMO is **not required** (see "Why a custom traffic
engine" below), though a SUMO backend stub is provided.

Optionally set a Census API key (higher rate limits; not required for the small pulls here):

```powershell
$env:CENSUS_API_KEY = "your-key"
```

---

## Commands

Everything is driven from `scripts/` and reads YAML from `config/`.

```powershell
# 0. Offline demo — no internet, no credentials. Labeled SYNTHETIC results.
python -m scripts.run_demo

# 1. Acquire real data (Census ACS + OSM network). Writes to data/raw, data/interim.
python -m scripts.acquire_data --config config/study.yaml

# 2. Build & check the synthetic population.
python -m scripts.build_population --config config/population.yaml

# 3. Prepare & check the routable mesoscopic network.
python -m scripts.prepare_network --config config/network.yaml

# 4. Run one evacuation scenario with congestion.
python -m scripts.run_scenario --config config/experiments.yaml --scenario baseline_no_av

# 5. Compare AV policies on identical population + hazard, repeated seeds.
python -m scripts.compare_policies --config config/experiments.yaml

# tests
python -m pytest -q

# compile all results into one multi-sheet Excel workbook
python -m scripts.export_excel        # -> outputs/altadena_results.xlsx
```

### Live UI ("mission control")

A browser-based, video-game-style dashboard: a 3-D pitched map of Altadena in the
center (real roads, household homes, safety exits, an expanding fire front, and
vehicles moving over time) framed by control panels — play/pause, speed, timeline
scrubber, scenario buttons, and live counters (reached / exposed / carless
stranded / trapped / clearance %).

```powershell
# 1. Generate one or more replays (each run becomes a scenario button).
python -m scripts.export_replay --mode altadena --fleet 0   --label "No-AV baseline"
python -m scripts.export_replay --mode altadena --fleet 300 --policy adaptive_geofencing --label "Geofencing 300 AVs"
#    (with CENSUS_API_KEY set, these use the REAL population; else synthetic.)

# 2. Launch the UI (serves the project so the browser can read the replays).
python -m scripts.serve_ui          # opens http://localhost:8000/ui/index.html
```

The UI plays back a **recorded** simulation smoothly (frame-by-frame), which is
the practical meaning of "watch it live". It needs internet once to load deck.gl
from a CDN. Replays live in `outputs/ui/` (gitignored — regenerate with
`export_replay`). The rendered vehicles are a capped sample for performance; the
counters are full-population.

Outputs (CSV/JSON, plots, maps) land in `outputs/<experiment>/`.

---

## Why a custom mesoscopic traffic engine (not SUMO)

SUMO 1.27 + TraCI is available in the dev environment and the prompt prefers it. We chose a
**custom mesoscopic engine** (`altadena_evac/network/mesoscopic.py`) deliberately:

1. **Testability.** The research invariants (person/vehicle conservation, seat capacity, no
   duplicate pickups, queue formation, forecast-information boundary) are unit-testable only
   if we own the time-stepping loop. We do.
2. **Tight AV-dispatch coupling.** Adaptive geofencing must re-screen accepted trips against
   a *forecast* every control step and reassign vehicles mid-route. Doing that through TraCI
   round-trips is fragile; in-process it is direct.
3. **No hard runtime dependency** for Dr. Grajdura's machine.

The engine implements **finite link storage, per-link discharge (outflow) capacity, FIFO
queues, and downstream blocking (spillback)** — i.e. it is *not* a fixed-travel-time graph.
A `SumoBackend` stub (`altadena_evac/network/sumo_backend.py`) documents the alternative and
the exact TraCI calls a future port would use. Units are SI throughout: **seconds, meters,
vehicles, people.**

---

## Repository layout

```
altadena_evac/            importable package (engine, agents, policies, data, viz)
config/                   YAML: study, population, network, behavior, hazard, fleet, experiments
scripts/                  CLI entry points (acquire/build/prepare/run/compare/demo)
tests/                    pytest suite (verification invariants + controlled policy scenarios)
fixtures/                 offline toy network + synthetic population (SYNTHETIC, not Altadena)
data/                     raw/ interim/ (gitignored; real Census + OSM land here)
outputs/                  run artifacts (gitignored)
DATA_MANIFEST.md          every source: date, geography, units, universe, assumptions
VALIDATION_REPORT.md      verification vs. fit vs. calibration vs. external validation
docs/ASSUMPTIONS.md       behavioral / modeling assumptions and their provenance
```
