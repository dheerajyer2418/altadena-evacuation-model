# Validation report (v0.1)

This separates four very different claims. **Only the first is satisfied.** The
model executing successfully does **not** mean it is validated.

---

## 1. Software verification — ✅ done

Does the code do what it says? Yes, as far as the unit tests cover.

`python -m pytest -q` → **28 passed**. Tests (in `tests/`):

| Invariant (requirement 9) | Test |
|---|---|
| Person / vehicle conservation | `test_network.py`, `test_engine.py::test_person_conservation_and_clearance_flag` |
| Finite storage never exceeded; queue forms | `test_network.py::test_finite_storage_never_exceeded_and_queue_forms` |
| Discharge capacity limits outflow | `test_network.py::test_discharge_capacity_limits_outflow` |
| Rerouting on closure; unreachable → trapped (not deleted) | `test_network.py::test_reroute_around_closure`, `test_unreachable_is_trapped_not_deleted` |
| Vehicle on a closing link not removed | `test_network.py::test_vehicle_on_closing_link_not_removed` |
| Seat-capacity constraint | `test_dispatch.py::test_seat_capacity_enforced` |
| No duplicate passenger assignment | `test_dispatch.py::test_no_duplicate_passenger_assignment` |
| Valid household membership | `test_population.py::test_membership_integrity` |
| Zero-AV behavior (carless stranded) | `test_policies.py::test_zero_av_strands_carless` |
| Distinct policy decisions (controlled) | `test_policies.py` (geofencing rejects / withdrawal stops / normal serves) |
| Forecast information boundary | `test_dispatch.py::test_dispatcher_sees_only_forecast_not_ground_truth`, `test_hazard.py` |
| Chronological event ordering | `test_engine.py::test_chronological_event_ordering` |
| Reproducibility (same seeds → same result) | `test_engine.py::test_reproducible_with_same_seeds` |
| Incomplete-clearance accounting | `test_engine.py::test_incomplete_clearance_reported_at_short_horizon` |
| Race does not drive behavior; disability ≠ non-driver; assistance ≠ disability | `test_population.py` |

End-to-end runs confirmed: offline demo (`scripts.run_demo`), baseline on the
**real Altadena network** (`scripts.run_scenario --mode altadena`), and a policy
comparison on both toy and real networks.

## 2. Population fit — ✅ measured on REAL Altadena ACS (good fit)

- **Real population synthesized** from live ACS 2019–2023 + PUMS (activated key):
  **15,099 households / 41,341 persons** across 34 Altadena block groups.
- Validated against raw ACS totals: population −0.8%, households +1.2%.
- IPU fit: **mean per-block-group SRMSE 0.060** (range 0.003–0.24); per-control
  TAE/unsupported reported in `data/processed/population_fit_report.json`.
- **Known gap:** synthesized carless rate **4.5% vs ACS 3.7%** — carless
  households are rare, so small-count/donor-pool effects overstate them. Because
  carless households are the research focus, treat the absolute carless count as
  approximate pending a stronger vehicle constraint or post-calibration.
- Two ACS cell-mapping bugs (female-age offset, income-bracket index) were found
  and fixed during this live verification — see DATA_MANIFEST.md.
- B18101 disability is NULL at block group, so disability is **inherited from
  PUMS donors** (not fitted); its distribution is realistic but not constrained to
  Altadena BG marginals.

## 3. Traffic calibration — ❌ none

- Link speeds/capacities are **defaults** (OSM `maxspeed` where present, else
  class defaults; 1,800 veh/h/lane). **No INRIX or count data** were supplied, so
  travel times and capacities are **uncalibrated**. Simulated congestion is
  internally consistent (queues/spillback emerge) but not matched to observations.

## 4. External validation — ❌ none

- Outcomes have **not** been compared to any observed evacuation. The Camp Fire
  coefficients are a disabled, labeled transfer hypothesis, not validation. No
  claim is made that Altadena results are realistic in magnitude.

---

## What the current numbers are

All quantitative results produced here are either:
- **synthetic test results** (toy network + synthetic population), or
- **real-network / synthetic-population** results (real OSM Altadena roads, but a
  synthetic population and an **uncalibrated** traffic model and a **hypothetical**
  hazard).

They are useful for **relative** comparison of AV policies under identical inputs
(the research question), **not** as absolute predictions for Altadena.

## Illustrative relative finding (synthetic population, real network)

On the real Altadena network with 551 synthetic households and the default
hypothetical front, across one seed:

| policy | fleet | reached | carless reached |
|---|---|---|---|
| no-AV | 0 | 0.75 | 0.00 |
| normal | 300 | 0.93 | 0.77 |
| evac_priority | 300 | 0.93 | 0.77 |
| adaptive_geofencing | 300 | 0.87 | 0.54 |
| withdrawal | 300 | (see CSV) | (reduced) |

Interpretation (qualitative only): AVs substantially help carless households;
withdrawal and (more conservatively) geofencing trade total/carless throughput
for avoiding sending vehicles into forecast hazard. Normal and evacuation-priority
coincide when the fleet is ample; they diverge only under fleet scarcity (the
priority mechanism is unit-tested).

## Real-population path status (updated)
- **Altadena block-group selection — ✅ done & live-verified.** `data/tiger.py`
  selects **34 Altadena CDP block groups (8 tracts)** from TIGER 2023 with no API
  key. `population/build_real.py` wires TIGER → ACS (subset to those GEOIDs) →
  PUMS donors → IPU → OSM-building placement, and activates automatically when
  `CENSUS_API_KEY` is set (`scripts/build_population.py`, `runner.prepare`).
- **Still needs a key to run** the ACS/PUMS download itself, and the ACS cell
  mappings below need verification before the real numbers are trusted.

## Needs Dr. Grajdura's review
1. ACS table cell mappings and universes (esp. B08201, B18101) before real runs.
2. PUMA selection for donors; group-quarters handling.
3. Hazard scenario parameters (front speed/shape) and exposure metric.
4. Behavioral distributions / whether to enable the Camp Fire transfer (and with
   the exact published coefficients).
5. Destination/egress definition and presence factor.
6. Traffic calibration inputs (INRIX) to move capacities off defaults.
