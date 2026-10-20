# Modeling assumptions and their provenance

Everything here is an explicit, editable choice. Config keys are named so you can
find and change each one. Nothing below is a calibrated or validated Altadena
value unless it says so (none do yet).

## Study definition
- **Baseline:** pre-January-2025 Altadena, represented by ACS 2019–2023 5-year
  estimates (`config/study.yaml → acs`). These are hypothetical scenarios, **not
  a reconstruction of the Eaton Fire.**
- **Three population concepts kept separate** (`study.yaml → population_concepts`):
  1. *Census baseline* — ACS usual-residence population.
  2. *Present during evacuation* — baseline × `presence_factor` (time-of-day).
     A flat factor; no visitor/commuter inflow (documented simplification).
  3. *Within evacuation area* — subset inside the scenario's evacuation polygon.
- **Network extent > demand extent:** roads extend 3 km beyond the demand bbox so
  vehicles can reach safety outside Altadena. **Destinations** are network nodes
  near southbound egress to I-210 / Pasadena — a modeling choice, not an order.

## Population synthesis (`config/population.yaml`)
- **Method:** IPU (Ye et al. 2009) reweights **PUMS donor households** to match
  **both** household marginals (size×vehicles, income) **and** person marginals
  (age×sex, race, hispanic, disability) per block group. Donors are whole
  households, so within-household joint structure is inherited, not fabricated.
- **Fit reporting:** per-block-group TAE and SRMSE; unsupported combinations
  listed. We do **not** assign attributes independently.
- **Race vs ethnicity:** two separate attributes (B02001, B03003).
- **Behavior must not be inferred from race** (`guards.no_behavior_from_race`);
  unit-tested in `tests/test_population.py::test_race_does_not_drive_behavior`.
- **Disability ≠ cannot drive / needs AV** (`guards.disability_implies_nothing`).
  "Assistance need" is a **separate, probabilistic** household flag
  (`assistance_need.*`), editable, and not equal to disability (unit-tested).
- **Group quarters excluded** in v0.1 (`group_quarters.include: false`) with this
  documented limitation; enabling needs a GQ facility layer + non-household model.
- **Placement:** OSM residential buildings within block-group polygons preferred;
  fallbacks (`landuse_random`, `bbox_random`, `network_node_fallback`) are
  **labeled** on each household.

## Behavior timeline (`config/behavior.yaml`) — five separable stages
`awareness → preparation → AV-request delay → departure/pickup → arrival`.
- Default distributions are **generic placeholders** (lognormal), not Camp Fire
  values. Medians: awareness ~15 min, preparation ~20 min, AV-request ~5 min.
- **Mode:** households with ≥1 usable vehicle drive (one trip per vehicle; seat
  capacity enforced; overflow members → AV request or stranded). Carless
  households request an AV; with no fleet they are **stranded demand**, reported.
- **Communication:** smartphone ownership is distinct from a functioning network;
  outages delay or block AV requests (`communication.*`).

### Optional Camp Fire transfer scenario (`behavior.yaml → campfire_transfer`)
- **Disabled by default.** Source: Grajdura, Borjigin & Niemeier (2022), a survey
  of Camp Fire (Paradise, 2018) evacuees. Time reference: minutes after first
  official alert.
- These are **observational associations from a different fire**, with a small
  survey N; the paper also omitted congestion/interactions and used 200 agents.
  We do **not** reproduce those simplifications and do **not** treat the
  coefficients as causal or as validated for Altadena. The values in
  `behavior/campfire.py` are **labeled placeholders** approximating the published
  departure-curve shape; replace with the exact paper table before any transfer
  analysis.

## Hazard (`config/hazard.yaml`)
- Hypothetical, reproducible, **time-dependent** radial anisotropic front.
- **Ground truth vs forecast are strictly separated.** The AV controller reads
  **only** the `Forecast` object (lead time, spatial + speed error, safety
  margin). It never sees ground truth unless `perfect_information: true`.
  Unit-tested in `tests/test_dispatch.py` and `tests/test_hazard.py`.
- **Exposure = hazard contact (a duration)**, explicitly **not** injury or death.
  No casualty model exists; none is implied.
- **Default front speed 0.6 m/s** is illustrative — fast enough to be "dire" but
  slow enough to leave an evacuation window so AV policies are comparable. **Not
  a calibrated value.**
- **Vehicles caught on a closing link are held and exposed, not deleted**
  (`on_closure`), and reroute if an open route exists.

## AV fleet & policies (`config/fleet.yaml`)
- **Fleet size is an explicit vehicle count.** A ratio option names its
  denominator (carless households). We do **not** call vehicles-per-resident
  "market penetration".
- Common dispatch rules (nearest-idle assignment, boarding time, control cadence,
  reassessment) are **identical across policies**; only the policy block differs.
- **Nearest-AV** uses a great-circle heuristic + one route computation (a
  documented simplification for tractability on the full network).
- **Four policies:** withdrawal, normal (FCFS), evacuation priority (carless +
  assistance first), adaptive geofencing (priority + forecast screening of both
  pickup and passenger journeys, with reassessment). Geofencing's optional
  retreat-behavior change has an **ablation** (`retreat_changes`).
- Normal vs evac_priority diverge **only when the fleet is scarce** (otherwise all
  carless are served either way); the priority mechanism is unit-tested.

## Traffic engine
- Custom **mesoscopic** spatial-queue model: finite link storage, discharge
  capacity, FIFO queues, head-of-line blocking, and **spillback**. Not a
  fixed-travel-time graph. Deterministic given injections.
- **Simplifications:** single FIFO queue per link (no lane-changing / overtaking);
  cross-link spillback relief resolves over successive steps; trip reassignment
  cancellations take effect at the next node, not mid-link. SI units throughout.
