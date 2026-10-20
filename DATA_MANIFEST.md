# Data-source manifest

Every external source: what it is, its date/geography/units, its universe, and
the assumptions attached. Confidential INRIX data and API keys are **not** in the
repository (see `.gitignore`).

---

## 1. OpenStreetMap road network — **used (live)**

| field | value |
|---|---|
| Source | OpenStreetMap via `osmnx` 2.1.1 (Overpass API) |
| Snapshot date | stamped at download in `data/interim/altadena_drive.graphml.meta.json` (`downloaded_at`) |
| Geography | Altadena CDP demand bbox + 3 km buffer (reaches I-210 and into Pasadena) |
| Extent downloaded here | **3,766 nodes, 9,972 directed edges** |
| Units | length meters; speed m/s (stored); capacity veh/s; storage veh |
| Fields preserved | directed edges & one-way restrictions, length, speed (+ provenance), lanes, derived capacity & storage |

**Assumptions / caveats**
- A **current** OSM snapshot at download time. It is **not** the January-2025
  network and is never described as such.
- Speeds: OSM `maxspeed` where present (**1,979 edges**), else a class default
  (**~6,031 residential**, etc.). Each edge carries `speed_source`.
- Lanes: OSM `lanes` where present, else class default; capacity = 1,800
  veh/h/lane (HCM-style default, editable in `config/network.yaml`), storage =
  130 veh/km/lane jam density. These are **assumptions, not calibrated** values.

## 2. ACS 5-year detailed tables — **implemented, NOT run here (needs key)**

| field | value |
|---|---|
| Source | `api.census.gov/data/2023/acs/acs5` (ACS 5-year) |
| Reference period | **2019–2023**, released Dec 2024 (pre-Eaton-Fire baseline) |
| Geography | block group within tract within LA County (state 06, county 037) |
| Tables | B01001 (sex×age), B02001 (race), B03003 (hispanic), B08201 (hhsize×vehicles), B11016, B18101 (disability), B19001 (income), B26001 (GQ) |
| Units | person / household counts (estimates) |

**Status:** the importer (`altadena_evac/data/census.py`) is implemented and
tested against the live API, but **the Census API now requires a free API key**.
None is configured in this environment, so no ACS data was pulled. Set
`CENSUS_API_KEY` and re-run `scripts/acquire_data.py` to activate the real pull.

**Universe caveats (must be verified before use — requirement 2):**
- B18101 universe is the **civilian noninstitutionalized population**, not total
  population; combining its disability share with B01001 totals is an
  approximation.
- B02001 (race) and B03003 (Hispanic ethnicity) are kept as **separate
  attributes**, never merged.
- The B08201 cell→(size,vehicles) mapping in `census.py` is a documented
  simplification and should be checked against the current ACS table shell.

## 3. ACS PUMS donor households — **implemented, NOT run here (needs key)**

| field | value |
|---|---|
| Source | `api.census.gov/.../acs5/pums`, 2023 5-year |
| Geography | **PUMA** (broader than Altadena): LA County PUMAs covering Altadena |
| Variables | HH: SERIALNO, WGTP, NP, VEH, HINCP, TYPE; Person: AGEP, SEX, RAC1P, HISP, DIS |

**Assumptions:** donors drawn from the containing PUMA(s) and reweighted to
Altadena block-group marginals by IPU. PUMA breadth is a documented
approximation; GQ (TYPE≠1) excluded (see limitation below).

## 4. TIGER/Line boundaries — **used (live, no key)**

| field | value |
|---|---|
| Source | `www2.census.gov/geo/tiger/TIGER2023/` (PLACE + BG) via `geopandas`/`pyogrio` |
| Geography | CA places + CA block groups, filtered to LA County |
| Vintage | 2023 (matches ACS year) |

Used to select which block groups fall in Altadena and to place households in the
correct polygons. **Not** treated as demographic data. **Verified live:** selects
**34 Altadena CDP block groups across 8 tracts** (4601.01, 4602, 4603.01/02, 4610,
4611, 4612, 4613); bbox ≈ (−118.179, 34.169)–(−118.090, 34.220). Selection rule:
block-group centroid inside the Altadena CDP polygon. This runs **without an API
key** (`altadena_evac/data/tiger.py`); the selected GEOIDs are the join keys for
the ACS pull once a key is present.

## 5. INRIX — **no data supplied; documented interface only**

`altadena_evac/data/inrix.py` is a documented interface. No travel-time, speed,
or probe data were provided, so **nothing was imported, calibrated, or
validated** from INRIX. Honest-use rules (probe counts ≠ volumes; don't
double-count congestion; respect quality flags) are encoded in the interface.

---

## Synthetic / offline fixtures — **SYNTHETIC, not Altadena**

- Toy 4×4 grid network (`make_toy_grid`) and a synthetic population
  (`make_synthetic`) power the offline demo and tests. Results produced from
  these are labeled **synthetic test results**, not Altadena findings.

## Known data limitations (open for Dr. Grajdura's review)
- **Group quarters excluded** from the evacuating population (documented;
  `population.group_quarters.include: false`).
- No real Census population pulled in this environment (API key).
- No traffic calibration (no INRIX / count data).
- "Present during evacuation" uses a flat presence factor; no visitor/commuter
  inflow modeled.
