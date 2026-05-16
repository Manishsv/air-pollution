# AirOS Intelligence Methodology

**A technical reference for researchers, evaluators, and implementers**

---

## Abstract

AirOS is a spatial urban intelligence system that produces human-reviewed decision support from heterogeneous environmental and infrastructure signals. This document describes the statistical and computational methodology underlying the system's reasoning layer, covering: the spatial discretisation scheme; signal ingestion and provenance tracking; three-horizon temporal context construction; agent architecture and tool design; cross-domain co-occurrence statistics; spatial coverage mechanics; city-level pattern synthesis; and the outcome feedback loop. We document known limitations, data quality constraints, and the epistemic posture the system adopts to remain honest under uncertainty.

---

## 1. Spatial Framework

### 1.1 H3 Hexagonal Discrete Global Grid

AirOS discretises urban space using Uber's H3 Hierarchical Spatial Index at **resolution 8**. Cell area and edge length are **latitude-dependent** in H3 — the values below are global averages, accurate to within a few percent at low latitudes. For Indian cities (8°N–34°N), per-cell area at resolution 8 ranges from approximately 0.71–0.74 km².

| Resolution | Avg area (km²) | Avg edge length (km) | Avg center-to-center spacing (km) | Rationale |
|------------|----------------|---------------------|-----------------------------------|-----------|
| 7 | 5.16 | ~1.22 | ~2.6 | Too coarse — mixes pollution micro-zones |
| **8** | **0.74** | **~0.46** | **~1.0** | Neighbourhood-scale operational unit |
| 9 | 0.11 | ~0.17 | ~0.4 | Sub-block scale; exceeds sensor spatial accuracy for most modalities |

Resolution 8 was selected as an **operational neighbourhood-scale unit**: fine enough to distinguish local hotspots, coarse enough to avoid false precision given sensor and satellite uncertainty. Administrative aggregation to ward, zone, or city level is performed as a downstream rollup; AirOS does **not** treat any administrative unit as the native analytical primitive. (Indian municipal wards are typically 5–25 km², larger than a single H3 res-8 cell — a ward contains many cells, not the other way around.)

Hexagonal tessellation is preferred over square grids because it provides uniform adjacency (all six neighbours are equidistant from the centroid), reducing directional bias in spatial interpolation. H3's hierarchical structure enables coarsening to resolution 7 for city-wide rollups without re-projecting data.

All signals, assessments, and insights in AirOS are cell-addressed. No spatial reasoning operates at point or polygon scale — every raw observation is mapped to a cell before entering the knowledge store.

### 1.2 Raw Signal → Cell: Four Assignment Methods

**A. Point observations → Inverse Distance Weighting (IDW)**

Used for sensor modalities (AQ stations, weather stations, rain gauges, CCTV cameras). For a target cell centroid $\mathbf{c}$, the interpolated value is:

$$\hat{v}(\mathbf{c}) = \frac{\sum_{i} w_i v_i}{\sum_{i} w_i}, \quad w_i = \frac{1}{d(\mathbf{c}, \mathbf{s}_i)^2}$$

where $\mathbf{s}_i$ are sensor locations and $d$ is the great-circle distance. A minimum distance floor of 50 m prevents weight singularities when a sensor falls within a cell centroid. A `DATA_CONFIDENCE` signal and `NEAREST_OBS_KM` signal are written alongside each interpolated value; cells far from any sensor receive lower confidence.

**Limitation:** IDW assumes spatial stationarity (the signal varies smoothly in space) and isotropy (no directional preference). Urban environments violate both assumptions — a busy road may produce a PM2.5 gradient that IDW cannot capture from a sparse sensor network. The `DATA_CONFIDENCE` signal surfaces this uncertainty but does not correct for it.

**B. Polygon features → Centroid assignment**

Used for ordinary building footprints. Each polygon's centroid determines its host cell. Per-cell aggregates (building count, floor count, commercial ratio) are computed by groupby.

**Caveat — large polygons:** centroid assignment is appropriate when polygon area ≪ cell area. For features that span multiple cells (industrial estates, campuses, malls, airports, large markets, landfills, transport terminals), naive centroid assignment misattributes the feature to a single cell and undercounts the exposure or source intensity in adjacent cells. **The `buildings` domain now uses `aggregate_polygons_to_h3` from `airos.drivers.store.geo_agg`, which routes polygons through one of two paths**: small polygons (≤ 25% of cell area) keep the fast centroid path; large polygons take **area-weighted intersection** so the polygon's count is apportioned across every overlapping cell by overlap fraction. `geometry_assignment_method` on the resulting signal row is `hybrid_polygon` so consumers can stratify. The `pois` domain currently uses centroid-only — POIs are mostly point-like and the multi-tag system (§D.16) covers the multi-role concern — but could be migrated to the hybrid path if downstream needs it.

**C. Line features → UTM clip and sum**

Used for roads, waterways, and drainage networks. OSM LineStrings are projected to UTM (zone auto-selected from the city centroid's longitude) and intersected with H3 cell polygons using an STRtree spatial index. The summed intersection length in metres is stored as `ROAD_LENGTH_M`, `DRAIN_LENGTH_M`, etc. This method correctly handles lines that cross cell boundaries, producing proportional attribution rather than centroid-based ownership.

**D. Satellite raster → Direct cell assignment**

Used for satellite-derived indices: **MODIS Land Surface Temperature** (`LST` for the `heat` domain), **Sentinel-2 derived indices** (NDVI for `green`, MNDWI / NDTI / CI / FAI for `water`, BSI for `construction`), **Sentinel-5P NO2 column** (used by `construction`), and **MODIS/VIIRS fire radiative power** (for `fire` and `waste`). Each raster pixel's centroid coordinates are mapped to an H3 cell; cells with multiple pixels receive the mean of their pixels.

**E. Tagged-point classification → Category-counted centroid**

Used for OpenStreetMap points-of-interest. Each candidate OSM feature is run through a deterministic tag classifier (`man_made`, `landuse`, `amenity`, `industrial`, `building`, `shop`) that emits a single category label or drops the feature. Polygon features collapse to their centroid. Per-cell signals (`POI_INDUSTRIAL_COUNT`, `POI_KILN_COUNT`, …) hold the count of features in each category; individual point coordinates are also retained in a side table (`poi_points`) so the dashboard can render source locations on the map. Categories cover both **pollution sources** (industrial, kiln, fuel station, construction, eatery, crematorium, waste facility) and **exposure indicators** (school, hospital, market, transit terminal). Each POI is assigned to exactly one category by a priority-ordered match — more specific tags (`man_made=kiln`) win over generic ones (`landuse=industrial`).

*Caveat — single-category collapse:* a hospital with an eatery, a market that doubles as a transit terminal, or a waste facility on industrial land fits multiple categories. The per-cell `POI_*_COUNT` aggregate uses only the **primary** (most-specific) category for back-compat. The full tag set is preserved in `poi_points.secondary_tags_json` so the cause classifier and dossier **can** reason over feature multiplicity when needed; the aggregate count is the conservative single-tag view.

### 1.3 AOIs are query lenses, not storage partitions

An **Area of Interest (AOI)** is any spatial region we want to monitor — a city, an airshed, a watershed, a regional economic corridor, a port, an airport. AOIs are declared in `data/config/aoi.yaml` with a `kind`, a bbox, an optional explicit `resolution`, optional `member_aois`, and routing/topography hints.

The architectural principle: **cells are AOI-agnostic at storage time.** A given H3 cell at (28.61°N, 77.21°E) represents the same square kilometre of central Delhi whether you view it as part of:

- the **city** AOI `delhi` (res 8, ~0.74 km² cells),
- the **airshed** AOI `igp_north` (res 5, ~250 km² cells, covering Delhi + Lucknow + Kanpur + adjacent regions),
- a **watershed** AOI covering the Yamuna basin,
- or a **corridor** AOI for Delhi-Mumbai industrial belt.

The PM2.5 reading in that cell at a given hour is one value, full stop. There is no "PM2.5-as-seen-from-Delhi" vs "PM2.5-as-seen-from-IGP-North" — that would be an ontological confusion. **An AOI is a query lens that selects + aggregates cells; it does not own them.** The same cell appears in any AOI whose bbox contains its centroid, with no re-ingestion required.

What follows from this:

| What | AOI-scoped or cell-scoped? |
|---|---|
| Time-series signal data (`h3_signals`) | **Cell-scoped** — one row per (h3_id, signal, hour_bucket) regardless of AOI |
| Static metadata (`h3_metadata`, centroid, area_name, terrain class) | **Cell-scoped** |
| Risk assessment (`h3_assessments`) | **Cell-scoped** — same risk tier whatever AOI is observing |
| Aggregation radius signals (`UPWIND_PM25_LOAD_K2` vs `..._K10`) | **Cell-scoped**, but emitted as separate named signals per radius — consumer AOIs pick which to read |
| City-relative anomaly annotation (`"+353pp vs city median"`) | **AOI-scoped at query time** — the same cell is +353pp vs Delhi median *and* +50pp vs IGP-North median simultaneously |
| Insight (`h3_insights`) | **AOI-scoped** — the same cell can produce one insight for the city dispatcher (low priority, "moderate PM in your ward") *and* one for the airshed coordinator (high priority, "top-10 receptor of regional transport"). Acts of interpretation are AOI-bound; underlying data isn't |
| Decision packet (`h3_packets`) | **AOI-scoped** — routing differs by AOI kind: city → municipal+state PCB; airshed → CPCB Central + NCAP; watershed → CWC + state irrigation |
| Outcome (`h3_outcomes`) | **AOI-scoped** — verdicts close the loop on a specific packet, which is AOI-bound |

**Resolution auto-derivation.** AOIs can declare an explicit `resolution: 5-9`; if omitted, the registry derives one from bbox area to keep total cells per AOI in the ~500–3000 range:

| Area | Default H3 resolution | Avg cell size | Typical use |
|---|---|---|---|
| < 200 km² | 9 | ~0.11 km² | Ward / sub-district |
| 200–2,500 km² | 8 | ~0.74 km² | City |
| 2,500–25,000 km² | 7 | ~5.2 km² | Metro region |
| 25,000–250,000 km² | 6 | ~36 km² | Airshed |
| > 250,000 km² | 5 | ~252 km² | Country-scale |

So an Indo-Gangetic-Plain AOI (~1.2 M km²) auto-resolves to res 5, giving ~4,800 cells — manageable. A small ward (~50 km²) auto-resolves to res 9, giving ~450 cells — also manageable. The system gracefully spans 4 orders of magnitude in AOI scale without operator tuning.

**Migration status.**

- **Phase 0** (cells AOI-agnostic): `aoi.yaml` registry, `airos.os.aoi_registry`, `signals_for_aoi` spatial query path. `city_id` column preserved for back-compat.
- **Phase 1** (dashboard AOI-aware): citymap loads via spatial bbox not `city_id`. AOI dropdown shows kind icons. `department_routing.yaml` has parallel `airsheds:` / `watersheds:` / `corridors:` blocks; `_routing_for_cause` walks them in order.
- **Phase 2** (per-AOI packets, metro-scale upwind, source/receptor): cause classifier now consumes a metro-scale `UPWIND_PM25_LOAD_K10` (k≤10 ring, ~7.5 km cone) alongside the neighbourhood `UPWIND_PM25_LOAD` (k≤2, ~1.5 km). The packet generator emits one packet per `(insight, AOI)` tuple so a Delhi cell with `regional_transport` cause produces *both* a Delhi-routed packet (`kspcb`-equivalent) *and* an IGP-North-routed packet (CPCB Central). Dedup is now `(insight_id, aoi_id)`. The dashboard's airshed view surfaces top-N **emission sources** (high local PM, low upwind) vs top-N **receptors** (high incoming load) so dispatchers see who to enforce on versus who needs cross-jurisdiction coordination.
- **Phase 3 (items 2+3)** (airshed compositor + true airshed-scale upwind): the new `airos.os.airshed_compositor` runs once per scheduler sweep after city ingest. For every enabled AOI of kind `airshed`/`watershed`/`corridor`, it (a) computes per-cell `UPWIND_PM25_LOAD_REGIONAL` over a bearing-based bbox cone with radius proportional to wind speed (50–300 km), and (b) exposes airshed-level summary stats (`avg_pm25`, `fire_count_24h`, `high_risk_cells_pct`, `population_exposed_high`) for the dashboard. The cause classifier (v0.7) now has the highest-weight evidence terms `upwind_airshed_dominates` / `upwind_airshed_high` that fire for trans-boundary cases (Punjab stubble burning → Delhi receptors). The dashboard source/receptor panel automatically uses the airshed-scale signal when present and falls back to the metro K10 signal otherwise — the scale label is shown so the dispatcher reads it honestly.
- **Phase 3 item 1** (deferred): drop the `city_id` column from cell tables. Multi-week refactor; column has been semantically dead since Phase 0 but the migration risk doesn't justify the storage win today.
- **Phase 3 item 4** (deferred): per-`(cell, AOI)` agent runs (one *finding text* tailored per AOI lens). Doubles LLM cost; today the same cell can already be routed to different bodies via per-AOI packets sharing one finding.

See `airos/os/aoi_registry.py` for the canonical API.

### 1.4 Conceptual Object Model

The system makes a deliberate distinction between several related but distinct objects. Conflating them is the most common source of overclaiming in urban analytics. Each row downstream depends on the rows above:

| Object | Definition | Where stored | Carries causation? |
|--------|------------|--------------|--------------------|
| **Observation** | A raw measurement, satellite retrieval, or model output as received from an external source | Connector output (transient) | No — it's just a number |
| **Signal** | An observation mapped to one (h3_id, signal_name, hour_bucket) tuple via one of the five assignment methods in §1.2 | `h3_signals` | No |
| **Assessment** | A domain-specific interpretation of one or more signals against thresholds, producing a discrete risk level (`severe`/`high`/`moderate`/`low`/`unknown`) | `h3_assessments` | No — it's a tier, not a cause |
| **Anomaly** | A signal value flagged as unusual relative to its 30-day or circadian baseline (§3) — distinct from "high" because a value can be both high *and* normal for that cell, or low *and* anomalously low | Derived; surfaced to the agent | No |
| **Insight** | An LLM-generated hypothesis combining assessments + anomalies + neighbour context + forecast into a written finding with a confidence score and hypothesis chain | `h3_insights` | Framed as testable hypothesis, not claim |
| **Cause hypothesis** | Deterministic ranked attribution of an air-domain insight to a source type (`construction_dust`, `waste_burning`, …) produced by §4.4 | Attached to the decision packet | Conditional — confidence per cause |
| **Decision packet** | A high-confidence insight promoted to an actionable, department-routed work item with structured evidence and safety gates | `h3_packets` | Routing is a hypothesis pending field verification |
| **Outcome** | Human-entered verdict (confirmed / refuted / unverifiable, with cause and routing sub-verdicts — §4.3) that closes the loop | `h3_outcomes` | The ground-truth signal |
| **City pattern** | LLM-aggregated theme spanning multiple insights in a time window | `city_patterns` | Pattern claim, not causation |

The discipline this enforces:

- **A high signal value is not an anomaly.** A value in the 95th percentile of its 30-day distribution is anomalous; the same value during winter inversion may be the regional norm.
- **An anomaly is not a risk.** A PM2.5 spike at 3 AM in an unoccupied industrial zone is anomalous but low-exposure.
- **A risk is not actionable.** A high heat assessment at 2 PM matters; at 2 AM it doesn't trigger an action.
- **An actionable insight is not necessarily department-routable.** Meteorological trapping has no responsible department in most cities — it's a notification-only event.
- **A routed packet is not a verified incident.** Routing is a hypothesis of departmental ownership; only the outcome verdict turns it into ground truth.

This layered model also dictates the schema: each object has its own table, and downstream rows reference upstream ones by ID so an audit can trace any decision packet back through the insight, signals, and original observations that produced it.

---

## 2. Signal Provenance and Data Quality

### 2.1 Source Taxonomy

Every signal written to `h3_signals` carries a `data_quality` tag, automatically inferred from the `source` identifier at ingest time. The tag tells the agent and the human reviewer *what kind of evidence* the signal is, which directly affects how much weight to place on it.

| Tag | Meaning | Typical sources |
|-----|---------|----------------|
| `real_station` | Measured by a physical sensor at or near the cell | CPCB AQ stations (`cpcb`), OpenAQ (`openaq`), IUDX (`iudx`) |
| `satellite_derived` | Retrieved from remotely sensed imagery or radar | Sentinel-2 indices (`sentinel`), MODIS LST (`modis`), VIIRS / FIRMS (`viirs`, `firms`), Google Earth Engine composites (`gee`), SRTM / Copernicus DEM (`srtm`, `srtm_copernicus`) |
| `model_estimate` | Output of a spatial interpolation, numerical weather model, or other physics/statistical model | OpenMeteo forecast & history (`openmeteo`, `openmeteo_forecast`), IMD model (`imd`), ERA5 reanalysis (`era5`), proximity-model noise estimate (`proximity_model`), pipeline-derived (`pipeline`) |
| `osm_structural` | Crowdsourced map data — slow-changing structural / cadastral features | OSM Overpass features for `buildings`, `roads`, `drains`, `pois` (source string `osm` or `osmnx`) |
| `derived` | Post-processing classifier or composite signal computed inside AirOS from upstream signals | `TERRAIN_CLASS` from elevation/slope/aspect (`terrain_classifier`), `ACTIVITY_CLASS` from radiance (`nightlights_classifier`) |
| `synthetic_fallback` | Literature-based or rule-based estimate emitted when a real source is unavailable | Synthetic noise (`noise_synth`), terrain synthetic mode (`terrain_synth`), generic `synthetic` |
| `unknown` | Source identifier not in the known taxonomy | Legacy data written before the taxonomy was extended; debug/seed rows |

**Reviewer weighting heuristic.**

- `real_station` is the strongest single signal — but only if `NEAREST_OBS_KM` is small. A real-station value interpolated from 25 km away is no better than a model estimate.
- `satellite_derived` is reliable for slow-changing land-surface phenomena (LST, NDVI, elevation) but inherits the satellite's revisit cadence and cloud-cover risk.
- `osm_structural` is the right tag for *what is built where* (roads, buildings, drains, POIs). Coverage is uneven — major features are mapped, informal/temporary structures usually aren't.
- `derived` should be reasoned about as a composite of its upstream signals, not as an independent measurement.
- `synthetic_fallback` is a placeholder, **not evidence**. The agent is instructed never to assert high confidence on a finding that depends materially on a `synthetic_fallback` signal.

**Source-string → quality mapping** is maintained in `airos/drivers/store/writer.py:_SOURCE_DATA_QUALITY`. Adding a new connector should add its source string to that map, or the rows will silently land as `unknown`.

### 2.2 DATA_CONFIDENCE — Composition and Semantics

Every IDW-based domain (`air`, `weather`, `fire`, `waste`, `crowd`) and every structural-OSM domain (`buildings`, `roads`, `drains`, `pois`) emits a `DATA_CONFIDENCE` signal in `[0, 1]`. **`DATA_CONFIDENCE` is a heuristic composite, not a calibrated probability.** It is intended as a *triage signal* — the agent should treat low-confidence inputs with extra scepticism — not as a measurement uncertainty in the statistical sense.

The composite combines five factors, each contributing a per-domain weight:

| Factor | What it captures | Typical inputs |
|--------|------------------|----------------|
| **Spatial support** | Distance from cell centroid to the nearest contributing observation | `NEAREST_OBS_KM`, station count within radius |
| **Temporal support** | Age of the most recent observation that contributed to the value | hours since last reading |
| **Source reliability** | Where the value came from — see the seven `data_quality` tags in §2.1 (`real_station`, `satellite_derived`, `model_estimate`, `osm_structural`, `derived`, `synthetic_fallback`, `unknown`) | `data_quality` tag column |
| **Local disagreement** | Variance among contributing observations when more than one | std-dev across IDW contributors |
| **Modality-specific risk** | Domain-specific failure modes (cloud cover for satellite, station uptime for sensors) | per-domain heuristic |

Concrete bands the agent and reviewer should treat as authoritative:

- **0.85–0.95**: structural OSM data (buildings, roads, drains) — coverage gaps possible but no temporal staleness.
- **0.6–0.85**: well-served IDW with a station within ~5 km and a recent reading; or satellite pass within 24 h.
- **0.3–0.6**: IDW with `NEAREST_OBS_KM > 10`, or satellite pass 1–7 days old.
- **< 0.3**: model-only / synthetic estimate, or station > 20 km away.

**Limitation:** the weights that combine the five factors are hand-tuned per domain and not currently calibrated against any held-out validation set. Every signal row now carries a `confidence_method_version` tag (currently `"v1"`) so downstream evaluation can stratify confirmation rates by confidence band and the weights can be revised empirically; bumping the version once revised gives a clean before/after comparison.

### 2.3 Provenance Mix in Baselines

When computing 30-day historical baselines, the system tracks the fraction of readings in each quality tier:

$$\text{provenance} = \left(\frac{n_{\text{real}}}{n}, \frac{n_{\text{sat}}}{n}, \frac{n_{\text{model}}}{n}\right)$$

This is surfaced to the reasoning agent as a note (e.g. "73% model_estimate — percentile rank less reliable"). An agent that sees a 90th-percentile reading should weight this differently depending on whether the historical distribution is drawn from real stations or from a model with known systematic biases.

---

## 3. Temporal Context Architecture

A defining feature of the AirOS intelligence layer is the assembly of **three temporal horizons** for each cell before any reasoning begins. This architecture is motivated by the observation that an anomaly is only detectable relative to a reference distribution, and the appropriate reference distribution depends on both time scale and time of day.

### 3.1 All-Day Historical Baseline (30 Days)

For each (cell, domain, signal) triple, the system computes:

\bar{x}_{30}, \quad P_{75}, \quad P_{90}, \quad x_{\min}, \quad x_{\max}, \quad \text{rank}(x_{\text{current}})

over all readings in the past 30 days regardless of time of day. The **percentile rank** of the current reading within the 30-day distribution gives a scalar anomaly score:

$$\rho = \frac{|\{v \in \mathcal{H}_{30} : v \leq x_{\text{current}}\}|}{|\mathcal{H}_{30}|} \times 100$$

**Three-state N-guard.** A simple ≥30 threshold is too coarse — 30 samples is enough to compute *a* percentile but insufficient to estimate the 90th percentile reliably. The baseline therefore reports in three states:

| State | Activation | What is surfaced |
|-------|-----------|------------------|
| **Unavailable** | $n < 10$ | Nothing — baseline is suppressed |
| **Descriptive only** | $10 \leq n < 30$ | Mean, min, max only; **no percentile rank** |
| **Rank-enabled** | $30 \leq n < 100$ | All statistics including rank — rank flagged as `low_confidence` |
| **High-confidence rank** | $n \geq 100$ | All statistics; rank treated as reliable for anomaly reasoning |

**Regime caveat.** A 30-day baseline is **regime-dependent**. For air quality in India, the same calendar window spans monsoon (heavy washout), post-monsoon, and winter inversion — three distributions with very different means. A January-vs-July comparison against a 30-day baseline is essentially comparing two different regimes and the rank is not directly interpretable. A future revision should add a **seasonal baseline** that pairs the current window with the same calendar window of prior years; until then, the agent is instructed to treat rank scores during regime transitions (monsoon onset/offset) as suspect.

### 3.2 Circadian Baseline (Same Hour of Day, 30 Days)

Urban signals exhibit strong diurnal periodicity. PM2.5 at 2 AM is drawn from a different distribution than PM2.5 at 2 PM (traffic patterns, mixing layer height, temperature inversions). Comparing a 2 AM reading against the all-day 30-day mean conflates the diurnal cycle with genuine anomalies.

The **circadian baseline** computes the same statistics as §3.1, but restricts the historical window to readings taken within ±2 hours of the current observation time, **using the city's local civil time** (timezone resolved from the cities registry):

\mathcal{H}_{\text{circ}} = \{v \in \mathcal{H}_{30}: h_{\text{local}}(v) \in [h_{\text{now}} - 2, h_{\text{now}} + 2] \pmod{24}\}

where $h_{\text{local}}(\cdot)$ returns the **local civil hour** of a reading (e.g. IST = UTC + 5:30 for Indian cities). Earlier versions used UTC hours, which produced an unintuitive 5:30 phase offset for Indian deployments; the local-time switch is required for correct same-hour comparison across time zones. UTC timestamps are still stored as the canonical observation time; the local-hour is derived at query time.

This 5-hour window out of 24 produces approximately 21% of the readings in the all-day baseline.

**Three-state N-guard (same shape as §3.1):**

| State | Activation | What is surfaced |
|-------|-----------|------------------|
| **Unavailable** | $n_{\text{circ}} < 10$ | Suppressed |
| **Descriptive only** | $10 \leq n_{\text{circ}} < 30$ | Mean, min, max for same-hour window; no rank |
| **Rank-enabled** | $30 \leq n_{\text{circ}} < 100$ | Rank surfaced with `low_confidence` flag |
| **High-confidence rank** | $n_{\text{circ}} \geq 100$ | Rank treated as reliable |

The earlier $n_{\text{circ}} \geq 5$ activation threshold was retired — five same-hour samples are too few to support rank-based reasoning and were producing misleadingly precise percentile values.

**Time-of-day effect detection:** when the circadian percentile rank and the all-day percentile rank differ by ≥ 20 percentage points, this is flagged as a **time-of-day effect** — the current reading is anomalous relative to its diurnal peer group but not relative to the broader distribution (or vice versa). The 20-point threshold is a heuristic; the evaluation framework in §9 includes a calibration step that may revise it once outcome data accumulates.

### 3.3 48-Hour Forecast Horizon

The system augments cell context with a 48-hour **operational forecast** from the OpenMeteo API (weather) and OpenMeteo Air Quality API (AQ model). Data is returned in 6-hour buckets with the following channels:

| Channel | Unit | Relevance |
|---------|------|-----------|
| Wind speed | m/s | Dispersion of pollutants, fire spread |
| Wind direction | degrees, vector-averaged per bucket | Source attribution (upwind vs downwind) |
| Precipitation probability | % | Wet deposition of particulates, flood pre-warning |
| Temperature | °C | Heat stress prediction |
| PM2.5 forecast | μg/m³ | Air quality outlook |
| PM10 forecast | μg/m³ | Coarser particulate outlook |

**Wind direction averaging:** within each 6-hour bucket, the mean wind direction is computed by vector decomposition to avoid the circular mean artefact at the 0°/360° boundary:

$$\bar{\theta} = \text{atan2}\!\left(\frac{1}{N}\sum \sin\theta_i,\; \frac{1}{N}\sum \cos\theta_i\right)$$

**City-level amortisation:** a single forecast fetch is performed per city per sweep (using the centroid of the first selected cell as a representative location). All cells in the city share this forecast. This reduces API calls from O(N) to O(1) per sweep.

This is an **operational approximation, not a cell-specific forecast**. The underlying weather model grid (typically coarser than ~9 km) is in any case larger than an H3 res-8 cell, so a per-cell fetch would not produce per-cell variation. But intra-city forecast gradients can still be significant — coastal cities under sea-breeze, basin cities during inversion, and any city under a localised storm cell — and the single-point fetch loses that signal. The agent is presented with this context explicitly labelled as "city-level forecast — not cell-specific", so cross-cell forecast differences should not be inferred. A future enhancement may sample 3–9 points across the bbox for cities where intra-city gradients matter.

---

## 4. Agent Architecture

### 4.1 H3 Expert Agent — Cell-Level Reasoning

The H3 Expert Agent is an LLM-backed reasoning agent that receives the assembled context for one H3 cell and produces a structured cross-domain insight. The agent operates in a **tool-calling loop** with a budget of at most 10 tool calls per cell.

**Context structure presented to the agent:**

1. Cell metadata (location, known features)
2. Latest signals (7-day window, all domains)
3. Domain assessments (risk level per domain, latest per day)
4. All-day 30-day baseline with percentile ranks and provenance notes
5. Circadian baseline (if sufficient history)
6. Data staleness flags (domains with no reading in > 24h marked ⚠)
7. Prior agent insights for this cell (last 5, with priority tier and outcome verdict)
8. Neighbour context (risk levels of surrounding ring-1 cells)
9. 48-hour forecast (shared city-level)

**Agent tool inventory:**

| Tool | Semantic | Policy |
|------|---------|--------|
| `get_signal_history` | Time-series retrieval for a specific (domain, signal) pair | Optional — call when current signal is anomalous relative to baseline |
| `get_neighbor_context` | Assessment summary for k-ring neighbours | **Recommended** before asserting that a phenomenon is spatially isolated |
| `get_city_summary` | City-wide risk distribution for contextualisation | Optional — useful when assessing whether a cell's risk is typical for the city |
| `get_packets_for_domain` | Outcome history of prior decision packets in this cell | **Required** when the same domain has prior `refuted` insights — informs whether to repeat the claim |
| `get_domain_cross_correlation` | City-wide statistical co-occurrence between two domains (§5) | **Required before any cross-domain claim** in the hypothesis chain |
| `submit_insight` | Mandatory terminal call — structured output to knowledge store | Required exactly once per cell |

**Tool-call policy details.**

- The agent has a hard budget of **at most 10 tool calls per cell**, exclusive of the mandatory `submit_insight` terminal call.
- A tool call that returns an error counts against the budget but the error message is fed back to the agent so it can decide whether to retry, switch tool, or downgrade confidence.
- **Failed tool calls are logged** to a `tool_trace_id`-keyed log (one log per insight). The log entry records: tool name, arguments, success/failure, latency, and the error class if failed.
- Tools marked **Required** in the table above are enforced *post-hoc*: if `submit_insight` is called and the hypothesis chain asserts a cross-domain mechanism, the writer checks the tool trace for at least one `get_domain_cross_correlation` call and stamps `tool_policy_compliance: "ok" | "violated"` on the insight. Violations do not block the write but are surfaced in evaluation.

**Context compression and prompt-overflow guards.**

A full 17-domain × 7-day context for a single cell can exceed an LLM's input budget. The context assembler applies the following compression in order:

1. **Domain prioritisation.** Domains with elevated assessments (high/severe) are listed first and verbosely; domains at low/moderate get a one-line summary; domains with no recent reading are dropped from the context with a `⚠ stale` marker.
2. **Signal deduplication.** When multiple signals carry the same value across many hours (typical for OSM structural signals), only the latest value is included, with a "unchanged for N hours" annotation.
3. **Unit normalisation.** All concentrations to µg/m³, all distances to km, all speeds to km/h, all temperatures to °C. Units are stated in every numeric line so the agent never has to guess.
4. **Stale-signal filtering.** Signals older than the domain's 2× cadence are tagged `⚠ stale (Xh)` so the agent down-weights them; if older than 5× cadence they are dropped entirely.
5. **Token-budget guard.** If the assembled context exceeds 75% of the model's context window, the assembler drops the lowest-priority domains in order until under budget, and emits a `context_truncated: true` flag on the insight.

**Per-insight provenance recording.**

Every insight written by the H3 Expert Agent carries (or will carry — see Appendix A planned fields) the full set of fields needed to reproduce it: `agent_model`, `agent_prompt_version` (git sha or semver of the system prompt at run time), `tool_trace_id`, `context_hash` (sha256 of the assembled context bundle), and `evidence_refs_json` (the specific signal/assessment/insight row keys that supported the finding). The reproducibility flow is documented end-to-end in §14.

### 4.2 Hypothesis Framing (not Causal Attribution)

The system adopts an explicit **epistemically conservative posture**: agent outputs are framed as **testable hypotheses**, not causal claims. The distinction matters because:

1. All signals are proxies — LST (land surface temperature) is not body temperature; interpolated PM2.5 is not a measurement at the cell centroid.
2. Sensor networks are sparse — the model cannot observe the ground truth directly.
3. Temporal resolution is coarse — daily satellite passes cannot detect intra-day events.

Each submitted insight includes a `hypothesis_chain` — a list of testable propositions, each with a `testable_by` field stating the observable evidence that would confirm or refute the proposition (e.g. "confirmed by field officer site visit within 48h", "refuted if AQ normalises within 24h of rainfall").

Confidence scores map to priority tiers by thresholding:

| Tier | Confidence range | Meaning |
|------|-----------------|---------|
| high | ≥ 0.75 | Strong signal, multiple corroborating domains |
| medium | 0.45–0.74 | Moderate signal or limited corroboration |
| low | < 0.45 | Weak signal, high uncertainty — informational only |

**Confidence is an ordinal prioritisation score, not a calibrated probability.** A confidence of 0.75 does not mean "75% probability the hypothesis is true" — it is the LLM's subjective compositive of signal strength, corroboration count, and data quality, distilled to a single number for triage. Until empirical calibration is performed (§9), confidence should be used as a *triage aid* — what to look at first — not as a likelihood that the field finding will match the agent's claim.

A separate `confidence_type` field is added to each insight to make this explicit:

| `confidence_type` | What it means |
|-------------------|---------------|
| `ordinal` | Subjective LLM score, suitable only for ranking |
| `heuristic_composite` | Rule-based composite (used by the cause classifier in §4.4) |
| `calibrated` | Empirically calibrated against confirmed/refuted outcomes — **not yet active** in any deployment |

Once a sufficient outcome history accumulates (the evaluation framework targets reliability curves at confidence-bin level), some sub-components may transition from `ordinal` to `calibrated`. Reproducibility fields in the schema (Appendix A) record the agent model, prompt version, and tool call trace that produced each confidence value, so post-hoc recalibration is possible.

### 4.3 Outcome Tracking and Feedback Loop

A single binary "confirmed / refuted" verdict is too coarse for the system's structure. A field officer may confirm elevated dust but refute construction as the cause; or confirm a known waste site but refute active burning; or find the right department was notified but no action was taken because resources were unavailable. AirOS therefore splits the outcome into **four orthogonal sub-verdicts**:

| Sub-verdict | What it certifies | Possible values |
|-------------|-------------------|------------------|
| **Condition verdict** | Was the hypothesised condition observed? (e.g. "elevated PM2.5", "active burning") | `confirmed` / `refuted` / `partially_confirmed` / `unverifiable` |
| **Cause verdict** | Was the top-ranked cause hypothesis (§4.4) the correct attribution? | `confirmed` / `refuted` / `partially_confirmed` / `unverifiable` |
| **Routing verdict** | Was the department in `routed_to` the correct owner for the action? | `correct` / `incorrect` / `joint_responsibility` / `unknown` |
| **Action verdict** | Was an action taken in response, and what was the result? | `taken` / `not_required` / `escalated` / `not_taken_resource_limited` / `not_taken_other` |

In v1 deployments, only the **condition verdict** is collected (matching the original `confirmed`/`refuted`/`unverifiable` set, with `partially_confirmed` added). The other three are reserved for forward integration with the external Grievance Redressal System (GRS) once it is wired up — that system carries the institutional record of routing and action, AirOS does not duplicate it.

Closed insights are included in the agent's prior context on subsequent runs, labelled with each sub-verdict that is populated. This creates an **outcome feedback loop**: the agent learns, in-context, whether its prior hypotheses for this cell were borne out at each layer (condition, cause, routing, action). Over time, accumulated verdicts provide empirical ground truth for evaluating the system's false positive / false negative rates **at each layer separately** — and for calibrating cause-classifier weights independently of agent insight confidence.

**Limitation:** this feedback loop depends on field officers consistently closing insights. If the dashboard is not used operationally — and grievance tracking happens entirely in the external GRS — AirOS will need a GRS-integration path that pulls condition/cause/action verdicts back from the external system, or the loop stays open and the agent's calibration remains unverified.

### 4.4 Cause Classifier — POI-Aware Deterministic Scorer

The H3 Expert Agent produces a domain-attributed insight (e.g. "elevated PM2.5") but does not, by itself, attribute the **emission source**. AirOS layers a deterministic **Cause Classifier** on top of every air-domain insight to enumerate ranked, evidence-backed source hypotheses for that cell. This is run as a structured post-processing step inside `InsightPacketGenerator`, so its output rides along on the decision packet alongside the agent's free-text finding.

**Hypothesis space (mutually non-exclusive, ranked by confidence):**

| Cause | Driving signals |
|------|----------------|
| `construction_dust` | `PM25_PM10_RATIO < 0.5` (coarse-dominant), elevated `PM10`, `CONSTRUCTION_RISK_INDEX` (Sentinel-2 BSI change), `POI_CONSTRUCTION_COUNT` (OSM-tagged active sites in cell) |
| `waste_burning` | `PM25_PM10_RATIO > 0.8` (fine combustion), `FRP` from satellite, `WASTE_SITE` flag, `POI_WASTE_FACILITY_COUNT`, `POI_CREMATORIUM_COUNT`, elevated `SO2` |
| `traffic_resuspension` | `ROAD_DENSITY` (m/km²), `MAJOR_ROAD_RATIO`, `NO2` (tailpipe marker), `POI_FUEL_STATION_COUNT`, `POI_TRANSIT_TERMINAL_COUNT` (diesel idling) |
| `industrial_emission` | Elevated `SO2`, elevated `NO2`, `POI_INDUSTRIAL_COUNT`, `POI_KILN_COUNT`, fine-particle ratio |
| `meteorological_trapping` | Low `WIND_SPEED_KMH` (< 5 km/h near-calm), high `HUMIDITY_PCT`, low `VENTILATION_INDEX` (basin enclosure), high `AVG_BUILDING_HEIGHT_M` + `BUILT_INTENSITY` (urban canyon — §D.13), elevated `AQI` without a strong local source signal |
| `regional_transport` | `UPWIND_PM25_LOAD` (or `UPWIND_PM10_LOAD`) significantly exceeds own PM, wind in the 5–30 km/h transport band, few local emission-source POIs. Triggers when the cell is being "fed" pollution from upwind cells rather than producing it locally — methodology §D.1. |

**Scoring mechanics.** Each cause has a hand-tuned scoring function that sums weighted contributions from its driving signals (typical weights: 0.10–0.35 per piece of evidence). The classifier loads all signals for the cell with a per-signal `MAX(hour_bucket)` query (different domains update at different cadences), so a cell with stale `CONSTRUCTION_RISK_INDEX` but fresh `POI_CONSTRUCTION_COUNT` still receives credit. Each cause's confidence is capped at 1.0 and surfaced with the specific evidence strings that contributed (e.g. `"5 OSM-tagged construction sites in cell"`). Causes scoring below 0.05 are dropped.

**Evidence-strength labels.** Each piece of evidence is classified into one of four bands so the LLM and the human reviewer can weight them differently:

| Label | Meaning | Example |
|-------|---------|---------|
| `static` | Structural fact, slow-changing | `POI_INDUSTRIAL_COUNT > 5`, `ROAD_DENSITY > 25000` |
| `recent` | Aggregated measurement in last 24 h | Elevated `PM10` over 24 h, `NO2` average elevated |
| `active` | Direct observation of an active event | `FRP > 10 MW`, `WASTE_SITE = 1` with overlapping FRP detection |
| `forecast` | Predicted future condition | Forecast `WIND_SPEED_KMH < 5` for next 6 h |

A `POI_WASTE_FACILITY_COUNT > 0` is **`static`** evidence (a facility exists); it is **not** evidence that the facility is currently emitting. Mistaking static for active evidence is one of the most common attribution errors and the labelling makes it explicit.

**Why deterministic, not LLM-driven?** The cause classifier is intentionally rule-based: (a) it runs over hundreds of cells per sweep at near-zero cost; (b) its weights are auditable and adjustable as more ground truth becomes available; (c) its evidence strings can be inspected and disputed by human reviewers without an LLM in the loop. The LLM's role is upstream (does this cell warrant an insight at all?) and downstream (can it propose actions consistent with the classifier's hypotheses?), not in the rule-based attribution itself.

**Versioning.** Every classifier weight set is versioned: `classifier_version` (e.g. `cause-classifier-v0.3`) and `weight_config_version` are written to each decision packet alongside the cause output. This is essential — when weights are revised in response to outcome data, historical packets must still be interpretable against the rules in force at the time. Reproducibility of a packet means being able to re-run the *exact* classifier version against the *exact* signal snapshot that produced it.

**Routing.** The top-ranked cause is looked up in `data/config/department_routing.yaml`, which maps `{city × cause}` to a primary department (e.g. `bbmp_solid_waste` for waste burning in Bangalore) plus CCs and an action template. The packet emits `routed_to`, `routing_cc`, and `routing_action` fields that downstream Grievance Redressal Systems (GRS) consume via integration.

**Tie-breaker — joint responsibility.** If the top two causes are within a small confidence margin, single-department routing creates institutional risk: the wrong department is asked to act, the right one is unaware. The packet generator therefore checks:

$$\text{conf}_{1} - \text{conf}_{2} < 0.15 \implies \text{emit } \texttt{secondary\_review\_by}$$

When this holds, the packet carries an additional `secondary_review_by` field naming the second-ranked cause's primary department, and an `attribution_uncertain: true` flag. The GRS integration is responsible for deciding whether this becomes a joint ticket, a parallel notification, or a primary-with-CC arrangement.

**Exposure-weighted ranking.** Within a priority tier, packets are no longer ordered by `confidence` alone — they are ordered by an `exposure_score`:

$$\text{exposure\_score} = \texttt{POPULATION} \times \text{latest air signal}$$

where the air signal is `AQI` if available, falling back to `2 × PM25` (a rough US EPA breakpoint approximation). Tier still wins absolutely — a `high` insight always outranks a `medium` — but within a tier, dense residential cells with bad air outrank equally-confident insights in empty industrial fringes. Cells with no population data sort to the bottom of their tier. The score is dimensionless and used only for ordering; it is emitted on every packet (`packet_payload.exposure_score`) so dispatchers see *who* is hurt, not just *how bad* the air is. This is the operational payoff of the GHSL_POP census layer (§D.21).

**Limitations.** (a) Confidence values are heuristic, not calibrated to a confirmed-event rate (no outcome data yet — calibration is part of §9). (b) Several causes can score moderately for the same cell — by design, since urban events are often multi-source. (c) The classifier has no temporal model: it scores the latest snapshot, not a trajectory; persistent vs. flash sources are not distinguished. (d) Missing signals (e.g. CPCB not returning PM2.5 this sweep) reduce the discriminative power of the ratio-based causes but do not invalidate the POI-only evidence path. (e) The PM2.5/PM10 ratio is a diagnostic **clue**, not a fingerprint — meteorology, humidity, measurement error, regional transport, and source mixing can shift the ratio in ways that break the rule-of-thumb thresholds. Ratio evidence should be triangulated with at least one POI or assessment signal before high confidence is asserted.

### 4.5 Cell Dossier — LLM Deep-Dive Context

When an operator opens an insight in the dashboard, they can ask follow-up questions to an LLM scoped to that single cell. To prevent the conversation from starting from a thin context (just the agent's finding text), AirOS assembles a **cell dossier** that is injected into the LLM system prompt before any user message:

1. **Cell metadata** — area name, land-use class, centroid.
2. **Cause hypotheses** — full classifier output (cause, confidence, evidence strings).
3. **POI summary** — counted breakdown of OSM categories in the cell (e.g. `INDUSTRIAL: 56, CONSTRUCTION: 5, FUEL_STATION: 1`).
4. **Latest signals grouped by domain** — every signal currently in the knowledge store for this cell (~50 signals across 17 domains).
5. **7-day pollution trend** — first/last/min/max for `PM25`, `PM10`, `AQI`, `NO2`, `SO2`, and the `PM25_PM10_RATIO`.

**Evidence-quality labels — required on every fact.**

Richer context can make the LLM sound more certain than the underlying data supports. To counter this, **every numerical line in the dossier carries an inline quality label** with three fields: `data_quality` tag (§2.1), distance/age proxy, and `DATA_CONFIDENCE`. The format is:

```
PM2.5:              42.6 µg/m³  · model_estimate · nearest station 11.4 km · confidence 0.42
PM10:               97.3 µg/m³  · model_estimate · nearest station 11.4 km · confidence 0.42
POI_INDUSTRIAL_COUNT:    56     · osm_structural · last refreshed 68 days ago · confidence 0.88
FRP (waste/fire):    no detection in last 24h · event-driven absence — NOT proof of no burning
NTL_RADIANCE:       33.3 nW/cm²/sr · satellite_derived (VIIRS) · 28 days old · confidence 0.55
TERRAIN_CLASS:       1 (plain)   · derived (terrain_classifier) · stable · confidence 0.90
```

The label format is enforced by the dossier formatter — there is no "label-free" path through the rendering code. Consequences:

- The LLM cannot treat a stale OSM count as equivalent to a real-time station reading.
- Synthetic-fallback signals are visibly flagged (`synthetic_fallback` tag) and the LLM is told never to base a high-confidence assertion on them.
- "Absence" signals from event-driven domains (fire, waste, crowd) are explicitly labelled `event-driven absence — NOT proof of no event`, since the FIRMS satellite pass cadence cannot detect events between passes.

**Output structure constraint.** The LLM is instructed to structure its reply as: (i) most-likely cause with cited evidence numbers; (ii) alternative hypothesis with the falsifying conditions; (iii) the specific field check that would discriminate between the two; (iv) data gaps that limit confidence. This is a deliberate constraint: instead of a free-form chat, the LLM operates as a **counter-hypothesis machine** that pressure-tests the classifier's top answer using the full signal context.

**Dossier versioning and freshness.** The dossier is rebuilt per-question (not cached) and stamped with the assembly timestamp + a `dossier_version` (sha256 of the assembled text). The UI displays the timestamp alongside the conversation so two questions asked five minutes apart can be reconciled if the underlying signals changed between them. The dossier is read-only — the LLM cannot mutate state via this path. Its purpose is **explanation depth**, not autonomous action.

### 4.6 Similarity-bias mitigation

A naive top-N scheduler over the agent's per-cell findings produces a **clustering bias**: cells in the same neighbourhood share the same upstream IDW estimates, the same city-broadcast weather, and the same per-cell baseline, so they generate near-identical findings in a single sweep. Five separate failure modes stack up:

1. **City-broadcast signals masquerade as cell-level signals.** Weather (`WIND_*`, `HUMIDITY_PCT`, `TEMPERATURE_C`, `PRECIP_MM`, `PRESSURE_HPA`) and heat (`HEAT_INDEX_C`, `UHI`) come from a single OpenMeteo city-centroid call per sweep. Their values are identical across every cell in the city. Naive prompting causes the agent to write `"air-heat compound stress"` findings — but "heat" is constant for every cell, so the compound label is structurally meaningless.
2. **IDW spatial smoothing.** With ~5 CPCB stations per Indian city, every cell's PM2.5 is a distance-weighted average of the same stations. Adjacent cells produce nearly identical estimates → nearly identical findings.
3. **Per-cell-only baselines.** Anomaly scoring as `(latest − 7d_avg)/7d_avg` is *cell-vs-its-own-past*. On a city-wide event day, every cell trips the same percentage spike at the same time.
4. **No spatial diversity at scheduler / packet level.** Pure top-N-by-score concentrates promoted cells in the highest-density cluster.
5. **Same-sweep correlation.** All findings from one sweep share the same upstream observations, the same heat broadcast, the same scheduler call — so the variance expected from independent draws isn't there.

The mitigation is a layered stack — five independent guards, each handling a different failure mode:

| # | Mitigation | Where it lives | What it fixes |
|---|-----------|---------------|---------------|
| 1 | **Spatial diversity thinning** at packet promotion | `airos/os/insight_packets.py::_spatially_thin()` with `_SPATIAL_DIVERSITY_K = 2` | Promotes the highest-ranked cell per ~1.5 km cluster; defers neighbours to the next sweep so downstream GRS receives one packet per neighbourhood, not five (failure #4). |
| 2 | **Inbox cluster collapse** for near-duplicates | `airos/network/dashboard/components/inbox_panel.py::_cluster_similar()` | Groups insights by `(city, area, hour, pattern)` where pattern is a *semantic* signature (`compound`, `pm25_spike`, `flood`, `heat`, `fire`, `water`); collapses to a single `Nx Area, City` row with click-through to the top-ranked constituent cell (failure #4 at UI level). |
| 3 | **City-relative anomaly annotation** | `airos/agents/h3_expert.py::_city_pct_median()` | For each per-cell trend the agent sees, the dossier appends `· city-median +X% (this cell ±Y pp vs city)`. Forces the agent to reason about *excess over city baseline*, not absolute percentage spike. Memoised per-agent-instance (failure #3). |
| 4 | **City-broadcast suppression** | `airos/os/cell_dossier.py::_CITY_BROADCAST_SIGNALS` + agent system prompt `h3-expert-v0.7-hard-constraint-first` + inbox weather banner | Signals from city-centroid APIs are tagged `(city-wide)` in the dossier; the agent prompt forbids using them as compound legs in `domains_involved` or finding labels; the inbox renders a single city-weather banner instead of repeating the same context across every per-cell finding (failures #1, #5). |
| 5 | **Post-generation validator** | `airos/agents/validators.py::validate_post_generation()` | Deterministic safety net. After the LLM returns structured output, strips `weather`/`heat` (when only city-broadcast heat signals are elevated — `HEAT_INDEX_C`/`UHI` rather than cell-resolved `LST`) from `domains_involved`, rewrites compound labels (e.g. `air-heat-noise compound stress` → `air-noise compound stress`), demotes `tier=high` to `medium` when fewer than 2 cell-resolved domains remain, and stamps `post_validator_flags` for auditability. Closes the residual ~25% of cases where LLM compliance slips. |

**Verification — Pune Haveli Subdistrict cluster.** The trigger case was 4–5 cells in Haveli Subdistrict producing `"Persistent air-heat-X compound stress: PM2.5 spike (↑~390%)"` findings within a single sweep. After the layered fixes:

* Same input data, prompt `v0.7` + validator: 2/4 cells return `priority_tier=low` with explicit `"part of city-wide episodic event"` framing and `domains_involved=['air']` only; 1/4 returns `tier=medium`; 1/4 retained the compound label until the validator stripped it.
* Inbox: previously 5 separate `🔴 high` rows; now 1 collapsed row (`Nx Haveli Subdistrict, Pune`) plus a city-weather banner showing the constant signals once.
* GRS packets: previously 5 high-priority compound packets, now 0–1 packets (low tier does not meet the default `min_confidence=0.5` × `priority_tier ∈ {high, medium}` promotion gate).
* The agent now cites the city-median annotation in its narrative explicitly — e.g. *"Air elevation (+17% vs city median) is consistent with city-wide pattern, not a local hotspot"* — which is the desired honest framing.

**What this does NOT do.** Adjacent cells with genuinely distinct cell-resolved signals (a real local hotspot in a CBD, a single waste-burning POI) still surface separately. The mitigation only collapses *similar* findings; it does not erase real spatial heterogeneity. The IDW data limitation (5 stations cannot distinguish ~1,500 cells) remains — denser sensor coverage is the only data-side fix.

---

## 5. Cross-Domain Co-occurrence Statistics

### 5.1 Motivation

The H3 Expert Agent is designed to produce cross-domain insights — hypotheses that link elevated risk in one domain to a mechanism in another (e.g. "waste burning is causing air quality deterioration"). Without statistical grounding, such linkages may be spurious — two domains may co-occur in a cell by chance, or because both respond to a shared confounder (e.g. hot, dry weather elevates both heat and fire risk independently).

### 5.2 Lift Score

The `get_domain_cross_correlation` tool computes a **lift score** over the full city population of cells:

$$\text{lift}(A, B) = \frac{P(A \cap B)}{P(A) \cdot P(B)} = \frac{n_{AB} / n_{\text{total}}}{(n_A / n_{\text{total}}) \cdot (n_B / n_{\text{total}})}$$

where:
- $n_A$ = cells with domain A at or above the risk threshold (default: "high")
- $n_B$ = cells with domain B at or above the threshold
- $n_{AB}$ = cells with both domains elevated (inner join)
- $n_{\text{total}}$ = total assessed cells in the city

The lift is computed from the **latest assessment per cell** (most recent day bucket per domain per cell) using a configurable lookback window (default 30 days).

**Interpretation (softened — lift is a weak prior, not strong evidence):**

| Lift | Interpretation |
|------|---------------|
| > 3.0 | Strong co-location or co-elevation signal — useful for prioritising investigation; **not** proof of shared mechanism |
| 1.5–3.0 | Moderate co-occurrence — may support a hypothesis when local cell-level evidence also exists |
| 0.7–1.5 | Weak or near-independent association under the current thresholding scheme |
| < 0.7 | Lower-than-expected co-occurrence — domains tend not to co-elevate together |

Lift can be inflated by purely **structural** drivers — two domains may co-elevate because they share spatial clusters (industrial zones) or because they share a common confounder (hot/dry weather elevates both heat and fire). Lift cannot distinguish "A causes B" from "A and B share a parent". The interpretation table above is therefore positioned as **prioritisation guidance, not causal evidence**.

**Statistical guard:** lift is suppressed when $n_{AB} < 5$ to prevent spurious large values from tiny samples (the formula can produce arbitrarily large lift when $n_A, n_B \ll n_{\text{total}}$).

**Usage:** the agent is instructed to call this tool *before* asserting a cross-domain causal link in its hypothesis chain. A lift > 1.5 strengthens the hypothesis as a **direction worth investigating**; lift ≈ 1.0 suggests the co-occurrence in the current cell may be coincidental. The tool result is explicitly labelled as a city-wide prior, not proof for the specific cell under analysis.

**Spatial vs. temporal vs. lagged lift.** The current implementation computes *spatial lift*: the latest assessment per cell within a configurable lookback (default 30 days). This mixes assessments from different days within the lookback window — flood risk from yesterday and air risk from today can be treated as co-occurring even though they were not contemporaneous. Three variants are worth distinguishing as future work:

| Variant | Definition | What it measures |
|---------|------------|------------------|
| **Spatial lift** (current) | Latest assessment per cell, any time in lookback | Geographic clustering of risk |
| **Temporal lift** (future) | Both assessments fall in the same day bucket | Contemporaneous co-elevation |
| **Lagged lift** (future) | A elevated at time $t$, B elevated within $[t, t + \Delta]$ | Hypothesis-suggestive ordering |

Only lagged lift moves meaningfully toward a causal claim (and even then only as a Granger-style "predicts" relationship, not true causation). The current spatial lift should be read as a **co-location** statistic.

**Limitations of lift as a metric:**
- Symmetric — cannot identify the direction of influence.
- Does not control for confounders.
- The "elevated" threshold is a discretisation that discards magnitude.
- The current implementation does not control for time alignment (above).

More sophisticated measures (mutual information, Granger causality, structural causal models) would be more rigorous but require longer time series and denser spatial sampling than the current deployment can guarantee. Lift is adopted as a practical, interpretable, low-data-requirement statistic that the LLM agent can reason about in natural language.

---

## 6. Spatial Coverage and Sampling Bias

### 6.1 The Clustering Problem

A naïve risk-first scheduling policy — always analyse the cells with the highest current risk score — produces severe **spatial clustering** of insights. High-risk cells tend to be geographically proximate (industrial zones, flood-prone areas), and risk scores are persistent over days. Without intervention, the same 5–10% of cells accumulate all insights while the remaining 90–95% of the city's grid receives no analysis.

This is methodologically problematic for two reasons:
1. **Selection bias:** the system builds a detailed model of known hotspots and a null model of the rest of the city.
2. **Discovery failure:** genuinely anomalous but moderate-risk cells in under-analysed areas are never detected.

### 6.2 Two-Pool Sweep

The `run_top_risk_cells()` scheduler function addresses this with a **two-pool cell selection policy**:

**Risk pool** (default: 70% of budget):
- Cells with the highest current risk score (`max_risk_score` derived from assessment risk levels) that have not received an insight in the past 6 hours.
- Ordered by (max_risk_score DESC, domain_count DESC).
- Ensures the system maintains strong coverage of active hotspots.

**Coverage pool** (default: 30% of budget):
- Cells with assessments that either (a) have never received an insight, or (b) have the oldest last insight.
- Ordered by (never_analysed ASC, last_insight_at ASC, max_risk_score DESC) — never-analysed cells come first.
- Ensures the system progressively builds baseline understanding across the full city grid.

The two pools are merged (risk cells first), deduplicated, and the same 6-hour cooldown exclusion applies to both pools.

**Expected convergence (per-city budget):** with `top_n=10` per scheduler run, `coverage_ratio=0.3`, and the default 15-minute sweep interval (`sweep_interval=900s` in Appendix B), 3 coverage cells are visited per sweep × 96 sweeps/day = **288 coverage visits/day per city**. For a 1,580-cell city (Bangalore at res 8), full first-pass coverage requires approximately **5.5 days**. After first-pass, the coverage pool shifts to a rolling revisit schedule proportional to cell age.

`top_n` is interpreted **per city per scheduler run**, not globally. In a 6-city deployment with `top_n=10` and a 15-minute interval, the total daily insight budget is approximately 6 × 10 × 96 = ~5,760 cells analysed/day before deduplication and the 6-hour cooldown. Empirically (cooldown + risk-pool concentration), insight production stabilises at ~480–800/day.

---

## 7. City-Level Pattern Synthesis

### 7.1 The Aggregation Problem

Cell-level insights are the primary analytical product, but city administrators need summaries at a higher level of abstraction: "What is happening in the city today?" rather than "What is happening in cell 886016921bfffff?" The City Pattern Agent addresses this.

### 7.2 Methodology

After each cell sweep, the City Pattern Agent reads all insights generated in the sweep window (default: last 2 hours). It computes:

1. **Domain frequency distribution** — which domains appear most frequently across insights. This surfaces the dominant risk type city-wide.

2. **Pairwise domain co-occurrence** — how often two domains appear together in the same insight (a cell-level measure, distinct from the city-wide lift in §5). High co-occurrence within insights indicates that the agent is repeatedly finding correlated risk patterns in individual cells.

3. **Cross-domain lift** (§5) for the top domain pairs — statistical grounding for pairwise frequency.

4. **Hotspot cells** — cells appearing in two or more insights within the sweep window. Repeated flagging indicates persistent, unresolved conditions.

5. **City-wide risk distribution** — count of cells at each risk level across all domains (last 24h), providing denominator context.

6. **Signal-derived denominators (per candidate theme)** — *raw* evidence counts that are independent of the LLM agent. For each theme the agent emits, the input bundle must include the corresponding signal-level support:
   - **Cells with elevated assessments** in the theme's domain(s) over the lookback window (count, from `h3_assessments`).
   - **Cells with the theme's diagnostic signal pattern** — e.g. for `construction_dust`: cells with `PM10 > threshold` AND `PM25_PM10_RATIO < 0.5` AND `POI_CONSTRUCTION_COUNT > 0`. The pattern is the same boolean expression the cause classifier (§4.4) uses.
   - **Cells that satisfy both** (intersection) — the strongest signal-derived support.

This context is passed to an LLM synthesis agent with a structured output schema requiring, for each theme:
- title, description, affected domains, recommended city-level action, priority
- **`n_insights`** — count of agent insights supporting the theme (LLM-derived)
- **`n_cells_with_assessment`** — count of cells with elevated assessments in the relevant domain(s)
- **`n_cells_with_signal_pattern`** — count of cells matching the diagnostic signal pattern
- **`n_cells_intersection`** — cells in both (the most defensible denominator)
- supporting evidence (specific insight IDs + signal-pattern cell IDs)
- confidence and a data quality note

**Validity gate (LLM-on-LLM hedge).** A theme is valid only if `(n_insights ≥ 2) OR (n_cells_intersection ≥ 5)`. This forces every theme to be backed by **either** insight-level corroboration **or** raw signal-level evidence, preventing the City Pattern Agent from amplifying a single noisy H3 Expert Agent output into a city-wide claim. A theme that has many insights but `n_cells_intersection = 0` is automatically downgraded to "interpretive — not supported by raw evidence" in the output.

Example: instead of *"12 insights mention construction dust"*, the agent must emit *"12 insights mention construction dust, supported by 71 cells with elevated PM10 + coarse PM2.5/PM10 ratio, of which 29 also have construction POIs — intersection cells: [list]."* The administrator sees the raw denominator alongside the interpretation.

---

## 8. Data Integrity and Honest Framing

### 8.1 What the System Claims and Does Not Claim

AirOS occupies an explicit epistemic position that differs from typical ML-based urban analytics:

| Claim | Status |
|-------|--------|
| "Risk is elevated in this cell" | ✓ Reported — based on signals relative to thresholds |
| "The risk is caused by X" | ✗ Not claimed — framed as a testable hypothesis |
| "This reading is anomalous" | ✓ Reported with percentile rank and N-guard |
| "The anomaly is statistically significant" | ✗ Not claimed — no hypothesis test is run |
| "A and B are causally linked" | ✗ Not claimed — lift score provided as correlation proxy |
| "The forecast will materialise" | ✗ Not claimed — forecast is a model output, labelled as such |

### 8.2 Known Limitations — Five Kinds of Uncertainty

A precise discussion of system limits requires distinguishing **what kind** of uncertainty is in play. Conflating them produces both overclaiming ("the model is correct, the data is just noisy") and underclaiming ("the system can't be trusted at all"). AirOS limitations decompose into five orthogonal categories:

**1. Measurement uncertainty** — error in the raw observation itself.

- Sensor error: CPCB station drift, calibration variance between vendors.
- Satellite retrieval error: atmospheric correction artefacts in Sentinel-2 indices, cloud false-positives in NDVI loss detection.
- Model output as "observation": OpenMeteo forecasts and air-quality models are themselves uncertain at source; treating them as ground truth (as IDW does) doubles down on that uncertainty.

**2. Spatial uncertainty** — error introduced when mapping observations to H3 cells.

- IDW cannot capture sub-kilometre concentration gradients near point sources (roads, factories). A cell flagged as "high PM2.5" may have an actual concentration distribution that varies by 50–200% within its 0.74 km² area.
- Polygon centroid assignment loses information for large features (industrial estates, campuses). §1.2 caveat.
- Satellite pixel-to-cell aggregation: when a Sentinel-5P NO2 pixel (~7 km) is larger than the H3 cell (~1 km), the cell-level value is over-smoothed.

**3. Temporal uncertainty** — error introduced by staleness or cadence mismatch.

- Satellite revisit: Sentinel-2 has a 5–12 day revisit cycle per tile (depending on orbit geometry and cloud cover). "Daily" domains (heat, flood, green, waste) may actually reflect observations from several days prior in cloudy periods. The staleness flag (> 24h since last reading) surfaces this to the agent.
- Cross-domain time alignment: lift (§5) and cross-domain insights treat assessments within a 30-day window as "co-occurring" even though they may be days apart. Temporal lift (§5.2 future work) would fix this.
- Baseline regime drift: 30-day baselines cross seasonal regimes (monsoon vs. inversion) and produce uninterpretable rank scores at transitions.

**4. Model uncertainty** — error in the rules, weights, and assumptions inside AirOS itself.

- IDW assumes spatial stationarity and isotropy — urban environments violate both.
- The cause classifier's weights (§4.4) are hand-tuned, not empirically calibrated against confirmed outcomes.
- LLM reasoning opacity: the H3 Expert Agent uses a large language model whose internal reasoning is not fully auditable. The structured output is inspectable, but the inference path from context to conclusion is a black box. This is partially mitigated by the tool-calling architecture (each tool call is logged) but the final synthesis step remains opaque.
- Lift is symmetric, cannot identify direction, does not control for confounders (§5).
- Percentile rank assumes i.i.d. samples; in practice readings are temporally autocorrelated, so the effective sample size is smaller than the nominal $n$.

**5. Operational uncertainty** — error introduced by what happens (or doesn't) outside AirOS.

- Outcome loop dependency: the feedback mechanism (§4.3) only improves system calibration if officers close insights. If the dashboard is read-only and GRS integration is incomplete, the loop never closes and confidence calibration cannot be validated.
- Coverage pool convergence time: as computed in §6.2, full first-pass city coverage requires ~5.5 days at the default budget. During this period, the majority of cells have no insight history, and circadian baselines for those cells are empty.
- Department routing acceptance: a packet routed to a department is a hypothesis of ownership; if the department rejects it (jurisdiction dispute, resource limit), the action verdict is `not_taken` and the system has no way of distinguishing "wrong target" from "right target, no capacity".
- Driver source absence: when a connector returns no data (CPCB rate-limit, EARTHDATA token expiry), downstream signals silently degrade. Conformance warnings catch the known cases; unknown failures may produce confident-looking insights from stale or partial data.

This 5-way decomposition is also the structure used by the evaluation framework (§9): each metric should attribute residual error to one of these five buckets so improvement work can target the right layer.

---

## 9. Evaluation Framework (Proposed)

Each evaluation dimension below defines numerator, denominator, exclusions, and stratification dimensions. Where ground truth is required, the source of ground truth is named explicitly.

### 9.1 Closure rate

- **Numerator:** insights with `outcome_status ∈ {confirmed, refuted, partially_confirmed}` in the period.
- **Denominator:** insights created in the period.
- **Exclude:** insights still `open` at evaluation time.
- **Stratify by:** city, priority tier, domain.
- **Interpretation:** a high confirmation rate is misleading if closure rate is low — most insights may simply never be reviewed.

### 9.2 Condition confirmation rate

- **Numerator:** insights with `condition_verdict = confirmed`.
- **Denominator:** insights with `condition_verdict ∈ {confirmed, refuted, partially_confirmed}`.
- **Exclude:** `unverifiable`, still-open.
- **Stratify by:** domain, priority tier, confidence bin (e.g. 0.4–0.5, 0.5–0.6, …, 0.9–1.0), data-quality mix, cause classifier top-cause.

### 9.3 Cause confirmation rate (separate from §9.2)

- **Numerator:** packets with `cause_verdict = confirmed`.
- **Denominator:** packets with `cause_verdict ∈ {confirmed, refuted, partially_confirmed}`.
- **Stratify by:** top cause, classifier version, evidence band (was it `static`-dominant or `recent`-dominant evidence?).
- **Why separate from condition:** field officer can confirm elevated PM2.5 but refute the construction-dust cause attribution. Cause and condition fail at different rates.

### 9.4 Confidence calibration

Once a sufficient outcome history accumulates, plot reliability curves: for each confidence bin (width 0.1), what fraction of insights in that bin were `confirmed`? A well-calibrated system has the empirical confirmation rate within ±0.1 of the bin midpoint. Report Expected Calibration Error (ECE) per domain and priority tier.

### 9.5 Domain recall — retrospective

- **Numerator:** known field events (from a ground-truth event log) where AirOS produced a high-priority insight in the same cell or k=1 ring within `[event_time − 6h, event_time + 24h]`.
- **Denominator:** known field events with at least one assessed cell in their spatial extent.
- **Stratify by:** spatial precision band (same cell / ring-1 / ring-2 / outside-ring-2) and temporal band (`< 1 h`, `1–6 h`, `6–24 h`, `> 24 h`).
- **Required ground truth:** event log from a GRS or municipal complaints database — usually incomplete; report coverage of the ground-truth log alongside recall.

### 9.6 Routing effectiveness

- **Numerator:** packets where `routing_verdict = correct`.
- **Denominator:** packets where `routing_verdict ∈ {correct, incorrect, joint_responsibility}`.
- **Also report:** median time from packet creation → first action; median time → closure.
- **Critical caveat:** routing correctness depends on the `department_routing.yaml` mapping being correct for the city; misrouting due to a stale config is distinct from misrouting due to a wrong cause hypothesis.

### 9.7 Cross-domain lift validity

- **Test:** do domain pairs with high lift (> 1.5) produce more confirmed cross-domain insights than pairs with low lift?
- **Procedure:** stratify cross-domain insights by the lift of the domain pair at the time of insight generation; compare confirmation rates.
- **Goal:** validate (or refute) the operational rationale for using lift as a hypothesis-strengthening signal.

### 9.8 Circadian baseline improvement

- **Test:** do cells with a *high-confidence* circadian baseline ($n_{\text{circ}} \geq 100$) produce lower refutation rates than cells relying only on the all-day baseline?
- **If yes:** circadian is doing work. If no, the activation threshold is too low or the same-hour window is wrong.

### 9.9 Coverage-pool efficiency

- **Test:** do cells reached via the coverage pool eventually produce insights at the same confirmation rate as risk-pool cells?
- **If no:** the risk-first policy is more efficient despite its clustering bias, and the coverage_ratio could be lowered. If yes, coverage is finding genuine cases the risk pool misses.

---

## 10. Relationship to Established Methods

| AirOS component | Related literature |
|-----------------|-------------------|
| H3 spatial grid | Uber H3 (Brodsky, 2018); hexagonal binning for spatial analysis (Carr et al., 1987) |
| IDW interpolation | Shepard (1968); Cressie (1990) *Statistics for Spatial Data* |
| Diurnal baseline adjustment | Similar to seasonal-trend decomposition (Cleveland et al., 1990 STL) applied at hourly granularity |
| LLM-based reasoning agents | ReAct (Yao et al., 2023); tool-augmented LLMs; chain-of-thought prompting |
| Association rule lift | Brin et al. (1997) *Beyond Market Baskets*; standard market basket analysis |
| Two-pool sampling | Analogous to ε-greedy exploration in multi-armed bandits; exploration-exploitation trade-off |
| Outcome tracking | Calibration literature (Guo et al., 2017); human-in-the-loop ML systems |
| Urban heat island | Oke (1982); Voogt & Oke (2003) for LST-based UHI detection |

---

## 11. Design Principles

The following principles govern design decisions throughout the system:

1. **Data honesty over completeness.** An empty baseline is preferable to a statistically unreliable one. N-guards and staleness flags make data absence explicit rather than hiding it behind a number.

2. **Hypotheses, not conclusions.** The agent produces testable claims with falsifiability conditions, not authoritative findings. This respects the epistemic gap between satellite-derived proxies and ground truth.

3. **Human review is load-bearing.** The system does not automate government decisions. Decision authority remains with human officers. The technology reduces the cognitive load of monitoring without displacing accountability.

4. **Backward compatibility over freshness.** New columns in the knowledge store are added as nullable with defaults; old data continues to work without migration. This allows incremental deployment without requiring a full re-ingest.

5. **Fail silent on enrichment, fail loud on core.** Forecast fetch failure, circadian baseline suppression, and cross-correlation query errors all return empty results rather than errors. The agent runs with less context rather than not at all. Schema migrations and DB connectivity failures are not silent.

6. **Coverage before depth.** The two-pool sweep intentionally sacrifices some depth (re-analysing the same hotspots) for breadth (city-wide baseline). A system that understands 100% of its city at moderate depth is more useful to administrators than one that understands 5% of it deeply.

---

## 12. Domain Maturity Matrix

Not every domain is equally trustworthy. A reviewer who treats the 17 active domains as uniformly reliable will be misled. AirOS classifies each domain by a two-dimensional maturity rating: **production readiness** (how good is the data pipeline?) and **evidentiary strength** (how directly does the signal support an action?).

| Domain | Production readiness | Evidentiary strength | Notes |
|--------|----------------------|----------------------|-------|
| `air` | Production-ready observational | High when station within 5 km; **degrades sharply** for cells > 10 km from any station — `NEAREST_OBS_KM` and `DATA_CONFIDENCE` make this explicit |
| `weather` | Production-ready model output | Medium — model output at coarse resolution; **not** cell-specific despite cell-level storage |
| `roads` | Production-ready structural | High — OSM road geometry is well-mapped in Indian cities |
| `buildings` | Production-ready structural | Medium — informal/temporary structures missed; `building:levels` mostly absent |
| `drains` | Production-ready structural | Low–Medium — OSM drain coverage outside arterial waterways is highly uneven and community-dependent |
| `pois` | Production-ready structural | Medium — coverage strong for `INDUSTRIAL`, `EATERY`, `SCHOOL`, `HOSPITAL`; weak for `KILN`, `CREMATORIUM`, `WASTE_FACILITY` (treat low counts as absence-of-evidence, not evidence-of-absence) |
| `terrain` | Production-ready structural | High for elevation/slope; lower for derived classification |
| `fire` | Production-ready event-driven | High when FRP detected; **event-driven** — zero rows ≠ absence |
| `heat` | Production-ready proxy | Medium — MODIS LST is **surface** UHI, not human heat exposure |
| `nightlights` | Production-ready when token configured; **synthetic fallback otherwise** | Medium when real; **low** when synthetic — synthetic mode is literature-derived city-wide averages, clearly flagged in `data_source` |
| `green` | Production-ready proxy | Medium — strong seasonality, cloud false-positives in change detection |
| `water` | Production-ready proxy | Medium — only meaningful for cells containing water bodies |
| `construction` | Production-ready proxy | Medium — BSI + NO2 confounded by dry-season agriculture, demolition, road dust; must be triangulated with `POI_CONSTRUCTION_COUNT` |
| `waste` | Production-ready proxy / event-driven | Low–Medium — FIRMS filter for waste burning is a **hypothesis, not a classification**; agricultural and roadside fires can match the signature |
| `noise` | **Pilot-stage proxy** (when synthetic) / production-ready (when sensor API connected) | Low when synthetic — it's a structural exposure *estimate*, not a measurement. In synthetic mode the ingestor now dual-emits `EST_NOISE_RISK_INDEX` with `data_quality=synthetic_fallback` so the estimate-vs-observation distinction is visible at the signal level. |
| `flood` | **Pilot-stage proxy** (current synthetic incidents/assets) | Low — `flood_risk_score` is a structural proxy identifying *flood-prone* cells, not detecting *currently-flooded* cells |
| `crowd` | **Deployment-dependent** (requires upstream CV pipeline) | Variable — privacy, consent, and bias caveats apply; AirOS does not own the upstream pipeline |

**Maturity bands** are defined as:

| Band | Meaning |
|------|---------|
| **Production-ready observational** | Real measurement, low latency, well-served coverage |
| **Production-ready structural** | Slow-changing OSM/structural data with known coverage limits |
| **Production-ready proxy** | Derived measurement that approximates the quantity of interest (e.g. MODIS LST for surface heat, BSI for construction) |
| **Production-ready event-driven** | Real measurements but inherently sparse — zero rows is meaningful |
| **Pilot-stage proxy** | Functional but operationally limited; needs upgrade before high-stakes claims |
| **Deployment-dependent** | Production-ready *if* an external dependency is satisfied |
| **Synthetic / demo only** | Literature-derived or estimated; clearly flagged in `data_source`; should not be load-bearing for action |

**Operational consequence:** the cause classifier and city pattern agent should weight evidence by maturity. A construction-dust attribution backed by `POI_CONSTRUCTION_COUNT` (production-ready structural) is more dependable than one backed only by elevated `NOISE_RISK_INDEX` (synthetic pilot-stage). The agent system prompt is updated quarterly to reflect maturity revisions.

---

## 13. Operational Governance

Section 11.3 says "human review is load-bearing." This section specifies what that means concretely. Without operational governance, an LLM-backed urban intelligence system either drifts toward overclaiming (no one rejects bad insights) or toward irrelevance (no one reads good ones).

### 13.1 Roles

| Role | Responsibility | Where in AirOS |
|------|----------------|----------------|
| **Ward officer** | Open/Close insights for cells in their ward; submit field verdicts | Inbox dialog, "Close" tab |
| **Zone supervisor** | Review high-priority packets before routing to external GRS | Tasks tab (when authentication enabled) |
| **Department lead** | Receive routed packets via GRS integration; close routing/action verdicts | External GRS (not AirOS UI) |
| **City analyst** | Read city patterns; flag false themes | Overview / City Pattern panel |
| **System operator** | Monitor data audit panel; act on staleness alerts | Data Sources & Data Audit panels |

These roles are **not yet enforced** in AirOS — there is no authentication and any user can perform any action. Authentication and role-based authorisation are tracked as a separate pre-production requirement.

### 13.2 Review and Dispute Handling

- **Editing.** A reviewer cannot edit an insight's finding text (immutable). They can attach a verdict (§4.3) and a free-text reviewer note.
- **Rejection.** An insight closed `refuted` at the condition level is included in the agent's prior context as a negative signal for the same cell. Refutation rates by domain/tier feed §9.4 confidence calibration.
- **Merging.** Two insights on the same cell within a short window are not auto-merged; each closes independently. This is deliberate — merging would obscure which agent run made which claim.
- **Department disputes.** When a department rejects routing as out-of-scope (`routing_verdict = incorrect`), the packet is returned to the system with the verdict recorded. The cause classifier's department mapping is reviewed if the same misrouting repeats. AirOS does **not** automatically re-route — that decision sits with the GRS operator.

### 13.3 Closure and the GRS Boundary

In v1, AirOS captures only the **condition verdict** in its own database. The other three (cause, routing, action) are reserved for the external Grievance Redressal System. The boundary is:

- AirOS owns: insight generation, cause classification, packet creation, condition verdict.
- GRS owns: ticket assignment, departmental workflow, action tracking, escalation.
- Integration: AirOS pushes packets to GRS via a one-way `routed_to` payload; GRS pushes `routing_verdict`, `action_verdict`, and final closure back via a webhook (planned).

A packet is "operationally closed" only when both AirOS condition verdict and GRS action verdict are populated. Until the GRS integration is live, packets sit in `condition_only` state and the operational efficacy of routing cannot be measured.

### 13.4 What "False Positive" Means at Each Layer

A common error in evaluation is treating "this insight was wrong" as a single concept. At each layer the failure mode is different:

| Layer | False-positive mode | Likely fix |
|-------|---------------------|------------|
| Signal | Sensor noise, satellite artefact | Per-domain `data_quality` filter, IDW with more contributors |
| Assessment | Wrong threshold for the regime | Calibrate thresholds per city/season |
| Insight | Agent saw a pattern that isn't there | Strengthen prompts; tighten N-guards; require lift > threshold for cross-domain |
| Cause hypothesis | Right pattern, wrong attribution | Adjust classifier weights; add evidence-strength labels |
| Routing | Right cause, wrong department | Revise routing config |
| Action | Right packet, no action taken | Outside AirOS scope — GRS or capacity issue |

The four-way outcome split in §4.3 makes this stratification possible. Evaluation that lumps all layers together (e.g. "what fraction of packets were 'correct'") cannot tell which layer needs work.

---

## 14. Reproducibility and Audit Trail

A methodology that cannot be reproduced cannot be evaluated, audited, or improved. AirOS treats every artefact in the knowledge store — from the rawest signal to the most synthesized city pattern — as something that must be traceable back to its inputs. This section walks through what is recorded, why, and how a reviewer (internal or external) can re-derive an output from its provenance.

### 14.1 What "reproduce" means at each layer

| Layer | What it means to reproduce | Required provenance |
|-------|----------------------------|---------------------|
| **Signal** | Replay the connector against the upstream API/file at the recorded `source_observed_at` and verify the same value, unit, and assignment | `raw_source_id`, `source_observed_at`, `ingested_at`, `ingest_run_id`, `geometry_assignment_method`, `spatial_support_json`, `confidence_method_version`, `data_quality` |
| **Assessment** | Re-run the assessment thresholds against the cited input signals and verify the same risk level | `assessment_version`, `threshold_version`, `input_signal_refs_json` |
| **Insight** | Re-build the agent context from the cited signals/assessments/prior-insights, replay the same agent model with the same system prompt, and obtain a substantively equivalent finding (LLM outputs are not bit-identical, but the hypothesis chain and confidence should be within a small distance) | `agent_model`, `agent_prompt_version`, `tool_trace_id`, `context_hash`, `evidence_refs_json`, `confidence_type` |
| **Cause hypothesis / packet** | Re-run the deterministic classifier at the cited weight version against the cited signal snapshot and verify the same ranked causes | `classifier_version`, `weight_config_version`, `evidence_refs_json` (signals only), `attribution_uncertain` flag |
| **City pattern** | Re-load the insights + assessments cited by the pattern and replay the synthesis agent | `source_insight_ids_json`, `source_assessment_snapshot_id`, `agent_model`, `prompt_version` |

The combined effect: given any decision packet, a reviewer can walk **backward** through:

```
packet → source_insight_id → insight
       → classifier_version + weight_config_version → re-run deterministic classifier
       
insight → evidence_refs_json → set of (signal_row_keys, assessment_row_keys, prior_insight_ids)
        → context_hash → verify the assembled context matches the bytes that were sent to the LLM
        → agent_model + agent_prompt_version + tool_trace_id → replay the LLM call

signal → ingest_run_id + raw_source_id + source_observed_at → re-fetch the upstream observation
       → geometry_assignment_method + spatial_support_json → replay IDW / centroid / line-clip math
```

Every arrow is a foreign-key-like reference. There are no implicit joins.

### 14.2 The `context_hash` and why it matters

The H3 Expert Agent receives a substantial assembled-context bundle (latest signals, baselines, neighbour context, forecast, prior insights). Two different agent runs against the "same" cell can disagree if the underlying signals changed between runs — and they always change to some extent because the freshest signals arrive continuously.

`context_hash` is the sha256 of the **exact byte sequence sent to the LLM**, including unit annotations, stale-signal markers, and order. It serves three purposes:

1. **Distinguish "different finding" from "different input"** — if two insights for the same cell on the same day have different findings, the `context_hash` tells you whether the inputs were the same (real disagreement) or different (one had fresher data).
2. **Detect prompt-template drift** — if `agent_prompt_version` is unchanged but the assembled context format changed (e.g. unit normalisation was added), the hash reflects this.
3. **Replay precondition** — to truly replay an insight, the reviewer must reconstruct the same byte sequence. The hash is the verification that the reconstruction matches what was actually sent.

### 14.3 The `tool_trace_id` log

Each H3 Expert Agent run writes a tool-call log keyed by `tool_trace_id`. Each entry has:

```
{
  "trace_id":  "tt_a1b2c3...",
  "insight_id": "ins_xyz",
  "calls": [
    {
      "seq":      1,
      "tool":     "get_signal_history",
      "args":     {"domain": "air", "signal": "PM25", "hours": 24},
      "result_summary": "24 rows; min 28, max 312, latest 287",
      "latency_ms":  47,
      "ok":          true
    },
    {
      "seq":      2,
      "tool":     "get_domain_cross_correlation",
      "args":     {"domain_a": "air", "domain_b": "heat"},
      "result_summary": "lift=2.4, n_AB=12",
      "latency_ms":  62,
      "ok":          true
    },
    ...
    { "seq": 10, "tool": "submit_insight", "ok": true }
  ],
  "policy_compliance": "ok"   // see §4.1 — does this trace satisfy required-tool policy?
}
```

The trace is the **only** authoritative record of what the agent "knew" before calling `submit_insight`. Evaluators and post-hoc auditors should treat the trace as the ground truth of the agent's reasoning steps; the structured insight is the output, the trace is the process.

### 14.4 Coverage of the reproducibility fields

The reproducibility contract above is **populated by the writer code** as of the latest revision. Every new row written after the writer migration carries the fields described in §14.1. For pre-existing rows that pre-date the migration, the new columns are `NULL` — methodology §14.4 explicitly accepts this: the **earliest auditable insight** for any deployment is the first one written after the migration, and historical rows cannot be retroactively annotated without re-running the agent against the original context.

Specifically, as of this revision:

| Layer | Field | Coverage |
|-------|-------|----------|
| `h3_signals` | `ingest_run_id` | ✓ populated by `ingestor.run()` via a `ContextVar` (one run id per sweep) |
| `h3_signals` | `ingested_at` | ✓ populated by `write_signals` |
| `h3_signals` | `confidence_method_version` | ✓ populated (constant `"v1"` until the formula is revised) |
| `h3_signals` | `geometry_assignment_method` | ✓ populated by every domain ingestor (`idw` / `point` / `line_clip` / `raster` / `hybrid_polygon` / `centroid` / `proximity_model` / `derived`) |
| `h3_signals` | `raw_source_id`, `source_observed_at` | ◐ optional — passed only when the connector knows the upstream id and observation timestamp; remaining `NULL` for synthetic/derived signals |
| `h3_signals` | `spatial_support_json` | ◐ schema ready, per-row IDW contributor details not yet exposed by the IDW domains (~3 hrs each to wire — deferred) |
| `h3_assessments` | `assessment_version`, `threshold_version`, `input_signal_refs_json` | ◐ schema ready, writer parameters added, but no caller passes them yet — the assessment-thresholds config is still inline in the per-domain rules registry |
| `h3_insights` | `agent_model`, `agent_prompt_version`, `tool_trace_id`, `context_hash`, `confidence_type` | ✓ populated by the H3 Expert Agent for every new insight |
| `h3_insights` | `evidence_refs_json` | ◐ schema ready; the agent does not yet record per-evidence row keys — deferred |
| `h3_insights` | `tool_policy_compliance` | ✓ post-hoc check: cross-domain claims must have called `get_domain_cross_correlation` |
| `h3_insights` | `context_truncated` | ✓ flagged when the 60K-char soft budget is exceeded |
| `h3_insights` | `condition_verdict`, `cause_verdict`, `routing_verdict`, `action_verdict` | ✓ schema + writer + dashboard four-way UI live; population depends on what the operator chooses to record (condition is mandatory, the other three are optional) |
| `h3_packets` | `classifier_version`, `weight_config_version`, `attribution_uncertain`, `secondary_review_by` | ✓ populated by `InsightPacketGenerator` for every new air-domain packet |
| `city_patterns` | `source_insight_ids_json`, `source_assessment_snapshot_id`, `agent_model`, `prompt_version` | ◐ schema ready, City Pattern Agent currently captures source insight ids implicitly in `summary_json`; explicit columns to be wired in a follow-up |
| `tool_traces` | `trace_id`, `calls_json`, `policy_compliance` | ✓ populated for every agent run with per-call detail (seq, tool, args, result_summary, latency_ms, ok) |

**Symbol key:** ✓ fully populated; ◐ partially populated (schema present, per-domain or per-caller wiring pending).

### 14.5 Operational implication

Reproducibility is not a separate engineering project — it is the precondition for the evaluation framework in §9. Closure rate, condition confirmation rate, cause confirmation rate, and confidence calibration all require stratification by `agent_model`, `classifier_version`, `confidence_type`, and `data_quality`. With the fields above populated, those stratifications are now possible — the evaluation framework can run as soon as outcome data accumulates via the four-way verdict UI.

The remaining ◐ fields are not blockers for §9 metrics; they would improve **finer-grained** evaluation (per-classifier-weight-version calibration, per-IDW-contributor confidence error decomposition) but are deferred until first-pass calibration shows where the deepest gains lie.

---

## Appendix A: Knowledge Store Schema (Relevant Tables)

Schema is shown with a per-field coverage marker:

- **(no marker)** — pre-existing field, fully populated
- **✓** — Tranche A/B/C/D-introduced field that is now populated by the writer
- **◐** — schema present, partial population (see §14.4 for which callers are still pending)

```
h3_signals
  (h3_id, city_id, domain, signal, hour_bucket)  -- dedup key
  value REAL, unit TEXT, source TEXT, level INTEGER
  observed_at TEXT, data_quality TEXT             -- real_station | satellite_derived | model_estimate | osm_structural | derived | synthetic_fallback | unknown  (see §2.1)
  ingest_run_id TEXT                              ✓ links to the sweep that produced this row
  raw_source_id TEXT                              ◐ connector-specific source row id (e.g. CPCB station_id) — passed only when the connector exposes it
  source_observed_at TEXT                         ◐ timestamp at the source — passed only when the connector exposes it
  ingested_at TEXT                                ✓ when this row landed
  confidence_method_version TEXT                  ✓ version of the DATA_CONFIDENCE formula (currently "v1")
  geometry_assignment_method TEXT                 ✓ idw | point | line_clip | raster | raster_idw_hybrid | hybrid_polygon | centroid | proximity_model | derived
  spatial_support_json TEXT                       ◐ {nearest_obs_km, contributing_count, weights[]} — per-row IDW contributor data not yet exposed

h3_assessments
  (h3_id, city_id, domain, day_bucket)           -- dedup key
  risk_level TEXT, primary_index TEXT, primary_value REAL,
  dominant_issue TEXT, assessed_at TEXT
  assessment_version TEXT                         ◐ writer accepts; no caller passes yet (thresholds still inline in rules registry)
  threshold_version TEXT                          ◐ ditto
  input_signal_refs_json TEXT                     ◐ ditto

h3_insights
  insight_id TEXT PRIMARY KEY (UUID)
  h3_id, city_id, agent_type, created_at
  finding TEXT, confidence REAL
  priority_tier TEXT                              -- high | medium | low (derived from confidence)
  domains_involved TEXT                           -- comma-separated
  hypothesis_chain_json TEXT                      -- [{proposition, testable_by, confidence}, ...]
  recommended_actions_json TEXT
  uncertainty_notes_json TEXT
  outcome_status TEXT                             -- open | confirmed | refuted | partially_confirmed | unverifiable
  closed_by TEXT, closed_at TEXT
  condition_verdict TEXT                          ✓ confirmed | refuted | partially_confirmed | unverifiable (mirrors outcome_status)
  cause_verdict TEXT                              ✓ same enum (§4.3); optional in v1 — populated when officer chooses
  routing_verdict TEXT                            ✓ correct | incorrect | joint_responsibility | unknown; optional
  action_verdict TEXT                             ✓ taken | not_required | escalated | not_taken_*; optional
  agent_model TEXT                                ✓ e.g. claude-haiku-4-5
  agent_prompt_version TEXT                       ✓ semver of the system prompt — currently "h3-expert-v0.5"
  tool_trace_id TEXT                              ✓ points to tool_traces row for this insight
  context_hash TEXT                               ✓ sha256 of the assembled context bundle
  confidence_type TEXT                            ✓ ordinal | heuristic_composite | calibrated (always "ordinal" until calibration runs)
  evidence_refs_json TEXT                         ◐ schema present; agent does not yet emit per-evidence row keys
  context_truncated INTEGER DEFAULT 0             ✓ flagged when the 60K-char soft budget was exceeded
  tool_policy_compliance TEXT                     ✓ ok | violated (post-hoc check on cross-domain tool calls)

h3_packets
  packet_id TEXT PRIMARY KEY
  packet_json TEXT                                -- full enriched payload (includes cause_hypotheses, primary_cause, routed_to, etc.)
  evidence_json TEXT, safety_gates_json TEXT, blocked_uses_json TEXT
  outcome_status TEXT                             -- pending | dispatched | verified | resolved
  classifier_version TEXT                         ✓ e.g. cause-classifier-v0.3
  weight_config_version TEXT                      ✓ from data/config/cause_classifier_weights.yaml
  attribution_uncertain INTEGER DEFAULT 0         ✓ true when top-2 cause confidences within 0.15
  secondary_review_by TEXT                        ✓ secondary department when attribution uncertain

city_patterns
  pattern_id TEXT PRIMARY KEY (UUID)
  city_id TEXT, created_at TEXT
  lookback_hours INTEGER, n_insights INTEGER, theme_count INTEGER
  summary_json TEXT                               -- {executive_summary, themes: [...], emerging_risks, data_quality_note}
                                                  --   each theme now carries n_insights, n_cells_with_signal_pattern,
                                                  --   n_cells_intersection, validity (validated|interpretive) — §7.2
  source_insight_ids_json TEXT                    ◐ schema present; currently captured implicitly inside summary_json
  source_assessment_snapshot_id TEXT              ◐ ditto
  agent_model TEXT                                ◐ ditto
  prompt_version TEXT                             ◐ ditto

tool_traces                                       -- new in Tranche A (methodology §14.3)
  trace_id TEXT PRIMARY KEY
  insight_id TEXT                                 ✓ FK to h3_insights
  city_id TEXT, h3_id TEXT
  calls_json TEXT                                 ✓ [{seq, tool, args, result_summary, latency_ms, ok}, ...]
  policy_compliance TEXT                          ✓ ok | violated | unknown
  created_at TEXT

poi_points                                        -- new in §D.16; multi-tag added in Tranche C.3
  (poi_id, city_id) PRIMARY KEY
  h3_id, category, name, latitude, longitude
  secondary_tags_json TEXT                        ✓ JSON list of additional matching categories (multi-tag, §D.16)
  osm_tags_json TEXT, fetched_at TEXT
```

## Appendix B: Scheduler Configuration

| Parameter | Default | Scope | Effect |
|-----------|---------|-------|--------|
| `top_n` | 10 | per city per scheduler run | Maximum cells analysed in a single sweep for one city |
| `coverage_ratio` | 0.3 | per scheduler run | Fraction of `top_n` allocated to the coverage pool (rest goes to risk pool) |
| `sweep_interval` | 900s (15 min) | global | Time between consecutive scheduler runs |
| `cooldown` | 6h | per cell | Minimum time before a cell can be re-analysed |
| `lookback_days` (risk pool) | 7 | per cell | Assessment recency window used for the risk score |
| `lookback_hours` (city pattern) | 2 | per city | Sweep window for city pattern synthesis |
| `min_confidence_promote` | 0.5 | per insight | Threshold below which an insight is not promoted to a decision packet |

## Appendix C: Forecast Channels (OpenMeteo)

| API | Endpoint | Key variables |
|-----|----------|--------------|
| Weather | `api.open-meteo.com/v1/forecast` | `windspeed_10m`, `winddirection_10m`, `precipitation_probability`, `temperature_2m` |
| Air Quality | `air-quality-api.open-meteo.com/v1/air-quality` | `pm2_5`, `pm10` |

Both are fetched at hourly resolution and aggregated into 6-hour buckets. No API key is required. The system falls back gracefully (empty forecast dict) if the API is unreachable.

---

## Appendix D: Per-Domain Ingestion Catalog

This appendix describes, for every active domain, **what is fetched, how raw observations are transformed into per-cell signals, and the caveats a reviewer must hold in mind**. The catalog is the operational ground truth — driver class declarations (`signal_names`, `data_sources`) and ingestor source files are the authoritative implementation.

### What is a "domain"?

A domain is a coherent class of signals sharing one ingest function, one cadence, one provenance family, and one entry in `data/config/drivers_registry.yaml`. The registry is the **single source of truth**; the helper `airos.os.sdk.driver_loader.list_domains(kind=...)` is the only enumeration AirOS code reads from. Every other historical list (`ALL_DOMAINS` in the ingestor, the inbox UI filter, etc.) is now derived from the registry.

Domains fall into two kinds, distinguished by each driver's `produces_assessments` class attribute:

* **Assessment domains (`kind="assessment"`)** — drivers that emit per-cell `risk_level` rows into `h3_assessments`. These are the domains a sweep can produce an *insight* about. Currently 10: `air`, `construction`, `crowd`, `fire`, `flood`, `green`, `heat`, `noise`, `waste`, `water`. They show up in the inbox domain filter.
* **Context domains (`kind="context"`)** — drivers that emit signals into `h3_signals` but do not produce assessments. They are the structural / static / city-broadcast layers the agent uses to reason about *why* an assessment domain is elevated, never the basis for an insight by themselves. Currently 8: `buildings`, `census`, `drains`, `nightlights`, `pois`, `roads`, `terrain`, `weather`. They never appear as a primary domain in `domains_involved`; the cause classifier and the agent prompt (v0.7) both enforce this.

Adding a new domain is now a five-step workflow:

1. Add the driver class somewhere under `airos/drivers/store/drivers/` with `domain`, `cadence_hours`, `produces_assessments`, and `signal_names`.
2. Implement the ingest function and wire it into `_DOMAIN_FN` in `airos/drivers/store/ingestor.py`.
3. Register the driver in `data/config/drivers_registry.yaml`.
4. Add a per-domain Appendix D section here.
5. (If it is an assessment domain) add cause-routing entries in `data/config/department_routing.yaml` per city you want it to dispatch in.

Steps 4 and 5 are inherently per-domain; the other three are mechanical and could be wrapped in an onboarding CLI.

### D.1 air

| Aspect | Detail |
|--------|--------|
| Sources | **CPCB** (Central Pollution Control Board station network via data.gov.in) for cell-level IDW; **AQICN** as a **city-level reference only** (one value per city, never IDW'd into cell signals); **OpenMeteo Air Quality** 3×3 grid as a NO2/SO2/PM10 backfill when no CPCB stations fall in the bbox |
| Attributes extracted per station | PM2.5, PM10, NO2, SO2, CO, O3, station lat/lon, timestamp, station_id |
| Cell mapping | **IDW** with the 4 nearest CPCB stations (or all if < 4), inverse-square weighting, 50 m floor. AQICN is **excluded** from cell-level IDW — its single value is too coarse to interpolate. Each cell's resulting signal carries a `data_quality` tag (`real_station` if a CPCB station contributed, `model_estimate` if only the OpenMeteo grid did) |
| Derived signals | `PM25_PM10_RATIO = round(PM25 / PM10, 3)` computed per-cell after IDW; serves as the **single most diagnostic discriminator** for coarse-dust vs. fine-combustion sources — though see §4.4 limitations (ratio is a clue, not a fingerprint) |
| **Wind-aware airborne aggregation** | Each ingest sweep also computes two transport-aware signals from the IDW-ed PM values + the latest weather + terrain signals: `UPWIND_PM25_LOAD` / `UPWIND_PM10_LOAD` and `VENTILATION_INDEX`. The upwind load sums PM from k≤2 H3 neighbours that lie in the upwind direction (bearing matches `WIND_DIR_DEG` ±45°), weighted by `exp(-d/L)` where `L = wind_speed_kmh × 0.5 hr`, with a `cos(angular_offset)` factor so cells exactly upwind dominate over edge-of-cone cells. Ventilation index is `wind_speed × exp(-(FLOW_ACCUMULATION - 1)/50)` — basin cells with high `FLOW_ACCUMULATION` get low ventilation, capturing topographic pollution trapping. |
| Signals written | `PM25`, `PM10`, `NO2`, `SO2`, `AQI`, `PM25_PM10_RATIO`, `UPWIND_PM25_LOAD`, `UPWIND_PM10_LOAD`, `VENTILATION_INDEX`, `NEAREST_OBS_KM`, `DATA_CONFIDENCE` |
| Cadence | 15 minutes |
| **Airborne transport — what IS modelled** | (a) **Upwind k≤2 PM aggregation** — incoming pollution from cells within ~2 km in the current wind direction, with distance and angular weighting. (b) **Topographic enclosure** via `VENTILATION_INDEX` — cells at basin outlets accumulate pollution under stable conditions. (c) **`regional_transport` cause hypothesis** — when `UPWIND_PM25_LOAD > 1.5× own PM2.5` AND wind is in the 5–30 km/h transport band AND local emission-source POIs are few, the cause classifier raises this hypothesis with up to 0.90 confidence. |
| **Airborne transport — what is NOT modelled** | (a) **Gaussian plume / mesoscale dispersion** (CALPUFF, AERMOD, WRF-Chem) — needs stack heights, emission rates, atmospheric stability classes; out of scope. (b) **Vertical mixing** — boundary-layer height and inversion strength are not modelled; pollution is treated as ground-level only. (c) **Transport beyond ~2 km / k=2 ring** — long-range trans-boundary pollution requires upper-air trajectory data (HYSPLIT-class) we don't have. (d) **Emission rates** — POI counts are presence indicators, not source-strength estimates; we cannot model "this kiln emits X kg/hr". (e) **Urban canyon / building-induced flow** — OpenMeteo's wind grid is too coarse (~9 km) to resolve sub-city wind variation. |
| Caveats | CPCB rate-limits aggressively; the connector uses `curl -4` (IPv4-forced) to bypass Python SSL/IPv6 timeouts. Stations can be > 10 km from a cell — `NEAREST_OBS_KM` surfaces this, `DATA_CONFIDENCE` shrinks proportionally. **Do not mix AQICN city-wide values with CPCB station values** in cross-cell comparison: AQICN is a sanity check on city-wide AQI, not station-level evidence. When CPCB has no station in the bbox, `UPWIND_PM25_LOAD` is null but `UPWIND_PM10_LOAD` populates from the OpenMeteo backfill — PM10 carries similar transport semantics so the regional-transport detection still works. |

### D.2 weather

| Aspect | Detail |
|--------|--------|
| Source | **OpenMeteo Weather API** (open access, no key) |
| Attributes extracted | Temperature (2 m), humidity, pressure, wind speed (10 m), wind direction, precipitation, all at hourly resolution |
| Cell mapping | **3 × 3 grid** of API calls across the city bbox, then IDW interpolation to every H3 cell |
| Signals written | `TEMPERATURE_C`, `HUMIDITY_PCT`, `PRESSURE_HPA`, `WIND_SPEED_KMH`, `WIND_DIR_DEG`, `PRECIP_MM`, `NEAREST_OBS_KM`, `DATA_CONFIDENCE` |
| Cadence | 1 hour |
| Caveats | OpenMeteo's underlying model is coarser than the H3 cell — finer-than-grid variation is interpolation artefact. The agent is **explicitly instructed not to infer micro-weather from interpolated model values**. Wind direction is **vector-averaged** (§3.3) to avoid 0°/360° discontinuity. |

### D.3 air quality forecast horizon

| Aspect | Detail |
|--------|--------|
| Source | **OpenMeteo Air Quality API** |
| Use | 48-hour forward forecast (PM2.5, PM10) plus weather (wind, precip, temp) — assembled into 6-hour buckets and presented to the H3 Expert Agent as horizon channels (§3.3). One fetch per city per sweep amortises cost (§3.3 city-level amortisation). |

### D.4 fire

| Aspect | Detail |
|--------|--------|
| Source | **NASA FIRMS** (Fire Information for Resource Management System) — VIIRS 375 m + MODIS active-fire detections |
| Attributes extracted per detection | latitude, longitude, FRP (fire radiative power, MW), confidence, brightness temperature, acquisition timestamp |
| Cell mapping | Point assignment by detection lat/lon → H3 cell. Per-cell aggregate: sum of FRP, count, and `NEAREST_OBS_KM` |
| Signals written | `FRP` (MW), `NEAREST_OBS_KM`, `DATA_CONFIDENCE` |
| Cadence | 1 hour (FIRMS data latency is ~3 hours from satellite pass) |
| Caveats | **Event-driven domain**: 0 rows ≠ data failure — there are simply no active fires. The auditor suppresses zero-row warnings for this domain (`_EVENT_DRIVEN_DOMAINS`). VIIRS 375 m has 375 m × 375 m pixel — sub-pixel fires that radiate below the detection threshold are missed. Cloud cover can mask detections entirely. |

### D.5 flood

| Aspect | Detail |
|--------|--------|
| Sources | **OpenMeteo precipitation** observations (real, free) + **synthetic incidents** and **synthetic assets** for v1 deployments |
| Attributes extracted | Hourly precipitation per OpenMeteo grid point; incident records (location, type, severity) where available |
| Cell mapping | IDW from rainfall observations; drainage capacity overlay from OSM drains; **upstream-rainfall accumulation** via the terrain-derived `FLOW_DIRECTION`/`FLOW_ACCUMULATION` signals (§D.17). `FLOOD_RISK_SCORE` is a weighted combination of own-cell `RAINFALL`, **`UPSTREAM_RAINFALL`** (sum of own-cell rainfall over upstream cells, weighted by accumulation), `drain_capacity`, terrain slope, and historical incident density |
| Signals written | `FLOOD_RISK_SCORE` (0–1), `RAINFALL` (mm/hr), `UPSTREAM_RAINFALL` (mm/hr-equivalent — runoff arriving from upstream cells), `DATA_CONFIDENCE` |
| Cadence | 1 hour |
| **Maturity** | **Pilot-stage proxy** (see §12). `flood_risk_score` is a *flood-proneness* proxy, **not flood detection**. The synthetic incident/asset inputs are placeholders pending integration with municipal asset registers and field complaint logs. Production deployments must replace the synthetic feeds before using flood packets for actionable routing. |
| **Flow routing — what is modelled** | Each cell drains to its steepest-downhill H3 neighbour (hex D6 analog of the standard D8 grid algorithm) based on the terrain ingestor's `ELEVATION_M`. `FLOW_ACCUMULATION` is the count of cells whose runoff transitively reaches this cell. `UPSTREAM_RAINFALL` for a cell is the rainfall-weighted contribution of its upstream basin. This **does** capture: cells at the bottom of natural drainage basins accumulating runoff during rain events; flood-proneness elevated by topographic convergence even where local rainfall is moderate. |
| **Flow routing — what is NOT modelled** | (a) **Storm drains / culverts / pumping stations** — invisible to SRTM, so the model doesn't know that engineered infrastructure may divert or absorb runoff. (b) **Time-of-concentration** — `UPSTREAM_RAINFALL` is treated as instantaneous; travel time across an upstream basin is not modelled. (c) **1D-2D hydraulic simulation** — water depth, velocity, and pooling are not computed. For predictive urban-flood modelling, use specialised tools (HEC-RAS, MIKE URBAN, SWMM) with surveyed drainage networks; AirOS's flood domain remains a **prioritisation signal**, not a hydrodynamic prediction. (d) **Sub-cell hydrology** — within an ~1 km² H3 cell, street-level flow paths and low points exist that the model cannot resolve. |
| Caveats | The pipeline uses `run_flood_pipeline` directly (not `build_flood_risk_dashboard`, which strips raw `rainfall_mm_per_hr` and `flood_risk_score`). `UPSTREAM_RAINFALL` is computed *only* using upstream cells that themselves have a RAINFALL reading in the current sweep — cells with stale upstream data contribute 0 and the resulting `UPSTREAM_RAINFALL` is correspondingly under-estimated, not zero-imputed. |

### D.6 heat

| Aspect | Detail |
|--------|--------|
| Sources | **NASA MODIS LST** (land surface temperature, daytime), **OpenMeteo** temperature 3×3 grid, **OSM green cover** polygons |
| Attributes extracted | LST raster (MODIS Aqua/Terra, ~1 km resolution); air temperature time series; green-cover polygons for per-cell vegetation fraction |
| Cell mapping | LST: raster pixel → H3 cell, mean over pixels. Temperature: IDW from the 3×3 grid. Green cover: polygon-cell intersection by area |
| Derived signals | `UHI = LST − T_air_neighborhood_mean`. `HEAT_RISK_SCORE` is a normalised combination of LST z-score, UHI magnitude, green deficit, and population density proxy |
| Signals written | `LST` (°C), `UHI` (°C), `HEAT_RISK_SCORE` (0–1), `DATA_CONFIDENCE` |
| Cadence | 6 hours |
| Caveats | MODIS LST passes are at fixed UTC times (Aqua ~01:30 and 13:30, Terra ~10:30 and 22:30 local-equivalent). Reported LST is the most recent valid pass — could be up to a day old in cloudy conditions. |

### D.7 water

| Aspect | Detail |
|--------|--------|
| Source | **Sentinel-2** via Copernicus Data Space Ecosystem (CDSE Sentinel Hub) |
| Attributes extracted | MNDWI (Modified Normalised Difference Water Index), NDTI (turbidity), CI (chlorophyll), FAI (floating algal index) — composited from B3/B8/B11 bands |
| Cell mapping | Raster pixel → H3 cell, mean per cell |
| Signals written | `WATER_QUALITY_INDEX` (0–1, composite), `OPTICAL_WATER_CLARITY_INDEX`, `DATA_CONFIDENCE` |
| Cadence | 7 days (Sentinel-2 revisit) |
| Caveats | Only meaningful for cells containing water bodies; dry cells are filtered or carry near-zero confidence. Cloud cover can void an entire 7-day sweep. |

### D.8 green

| Aspect | Detail |
|--------|--------|
| Source | **Sentinel-2 NDVI** (CDSE) |
| Attributes extracted | NDVI (B8 − B4)/(B8 + B4) raster; historical NDVI from 90 d prior for change detection |
| Cell mapping | Raster pixel → H3 cell, mean. Change index = current_NDVI − prior_NDVI |
| Signals written | `GREEN_COVER_CHANGE_INDEX` (signed; negative = vegetation loss), `DATA_CONFIDENCE` |
| Cadence | 30 days |
| Caveats | Strong seasonality — pre/post-monsoon comparisons require the prior window to be season-matched (currently approximated as ±90 d). Cloud + atmospheric correction error can produce false-positive vegetation-loss signals. |

### D.9 construction

| Aspect | Detail |
|--------|--------|
| Sources | **Sentinel-2 BSI** (Bare Soil Index, used as build-up/bare-soil proxy), **Sentinel-5P NO2** (point source for traffic-driven nox), both via CDSE Sentinel Hub |
| Attributes extracted | BSI raster current + 90 d prior for change; NO2 column density |
| Cell mapping | Raster pixel → H3 cell, mean. Risk index is a normalised composite of (BSI change positive) × (NO2 z-score) |
| Signals written | `CONSTRUCTION_RISK_INDEX` (0–1), `DATA_CONFIDENCE` |
| Cadence | 14 days |
| Caveats | BSI rises both when land is cleared for construction **and** during dry-season agricultural fallow. The agent must read this alongside `POI_CONSTRUCTION_COUNT` (D.16) to distinguish urban construction from rural bare-soil. Sentinel-5P has ~7 km nadir resolution — coarser than H3 res 8. |

### D.10 noise

| Aspect | Detail |
|--------|--------|
| Source | **Operator-supplied noise sensor API** if `NOISE_API_URL` is configured; otherwise **synthetic estimate** derived from `MAJOR_ROAD_RATIO`, `POI_TRANSIT_TERMINAL_COUNT`, and `CONSTRUCTION_RISK_INDEX` |
| Cell mapping | IDW from sensors (when present); rule-based per-cell otherwise |
| Signals written | `dB` (A-weighted), `NOISE_RISK_INDEX` (0–1), `DATA_CONFIDENCE` |
| Cadence | 1 hour |
| **Maturity** | **Pilot-stage proxy** when synthetic; production-ready when sensor API is connected. Synthetic mode should not be load-bearing for high-stakes claims (§12). |
| Caveats | Synthetic mode is **structural exposure estimate, not actual measurement** — a cell with no traffic at 2 AM still scores moderate-to-high if its structural features are noisy. Driver conformance warns explicitly when synthetic mode is active. **In synthetic mode the ingestor dual-emits** `NOISE_RISK_INDEX` (back-compat, `source=proximity_model`) **and** `EST_NOISE_RISK_INDEX` (`source=noise_synth`, `data_quality=synthetic_fallback`) so consumers can pick the right semantic when reading. New code should prefer the `EST_` variant; the legacy name will eventually be retired once all consumers migrate. |

### D.11 waste

| Aspect | Detail |
|--------|--------|
| Source | **NASA FIRMS VIIRS/MODIS** filtered for low-FRP, persistent biomass-burning signatures consistent with municipal solid-waste open burning |
| Attributes extracted | Fire detection points + known waste-site polygon overlay |
| Cell mapping | Point → H3 cell; binary `SITE` flag if any known waste site centroid falls in the cell |
| Signals written | `SITE` (0/1), `NEAREST_OBS_KM`, `DATA_CONFIDENCE` |
| Cadence | 6 hours |
| Caveats | **Event-driven** (zero rows = no burn detection, suppressed in auditor). `SITE` is a **static** evidence band (see §4.4) — it indicates the presence of a registered facility, not active burning. The "waste burning" attribution from FIRMS low-FRP signatures is a **hypothesis, not a classification**: agricultural stubble burning, roadside fires, and small industrial fires can match the same signature. The cause classifier requires either an overlapping FIRMS detection (active band) or corroborating ratio/SO2 evidence before treating waste-burning attribution as high-confidence. |

### D.12 crowd

| Aspect | Detail |
|--------|--------|
| Source | **CCTV observation store** (Parquet at `data/processed/observation_store.parquet`) — produced by an upstream computer-vision pipeline that the AirOS deployment does not own |
| Attributes extracted | Camera ID, lat/lon, count timestamp, person count, gathering-alert flag |
| Cell mapping | IDW from camera observations |
| Signals written | `GATHERING_ALERT` (0/1), `DATA_CONFIDENCE` |
| Cadence | 5 minutes (when CV pipeline is running) |
| Caveats | **Event-driven** — most cells return zero. If the observation store is missing, the driver emits a conformance warning and the auditor suppresses checks for this domain. |
| **Privacy & ethics** | Crowd monitoring via CCTV carries privacy, consent, and bias risks even when AirOS only ingests aggregate counts. AirOS does not own the upstream pipeline and assumes that **lawful data-collection authority** exists at the deployment site and that **only aggregate (non-identifiable) counts** are passed through. The methodology of the upstream CV pipeline (face detection, demographic inference, retention) is **out of scope** for this document but must be governed independently before crowd signals are used in any public-facing or enforcement context. |

### D.13 buildings (OSM + GHSL)

| Aspect | Detail |
|--------|--------|
| Sources | **OSM Overpass** (`{building: True}` filter via osmnx) — footprints & tags. **GHSL R2023A 100 m built-volume / built-surface** (JRC, CC-BY 4.0) — satellite-derived urban mass, independent of OSM tag coverage |
| Attributes extracted | OSM: building polygon, `building:levels` (number of floors), `building` tag value (commercial/retail). GHSL: per-pixel built volume in m³ and built surface in m² |
| Cell mapping | OSM polygons → centroid (hybrid; large polygons area-weighted, methodology §1.2-B). GHSL pixels (100 m, Mollweide ESRI:54009) → pixel-center → H3 res-8 cell; values summed per cell |
| Signals written (OSM, `source="osm"`) | `BUILDING_COUNT`, `BUILDING_DENSITY`, `AVG_FLOORS`, `AVG_FLOORS_OBSERVED` (nullable), `FLOORS_MISSING_RATIO`, `COMMERCIAL_RATIO`, `DATA_CONFIDENCE` |
| Signals written (GHSL, `source="ghsl"`) | `BUILT_VOLUME_M3` (sum), `BUILT_SURFACE_M2` (sum), `AVG_BUILDING_HEIGHT_M` (= volume / surface), `BUILT_INTENSITY` (= surface / cell area), `DATA_CONFIDENCE` (0.85) |
| Cadence | 90 days (OSM); the GHSL fetch runs in the same sweep |
| Verification (Bangalore) | Top cells by `BUILT_VOLUME_M3` resolve to Koramangala / HSR, Marathahalli/Whitefield IT, Indiranagar, Bellandur, MG Road CBD, Yeshwanthpur. Tallest cells (`AVG_BUILDING_HEIGHT_M`) are Whitefield ITPL (26.3 m), Marathahalli IT (23.3 m), Bellandur (21.6 m), Manyata Tech Park Hebbal (20.6 m). |
| Used by | Cause classifier `meteorological_trapping.urban_canyon` term (tall + dense built mass restricts street-level mixing). Dashboard exposure layers. |
| Caveats | OSM `building:levels` is missing on ~97.5 % of Bangalore footprints — `FLOORS_MISSING_RATIO` makes this honest. GHSL `AVG_BUILDING_HEIGHT_M` is *built-mass average*, not max — a cell with 1 skyscraper + many low-rise reads as moderate. The 100 m raster cannot distinguish individual buildings; for floor counts use OSM `AVG_FLOORS_OBSERVED`. GHSL serves zipped GeoTIFFs via `/vsizip//vsicurl/`; tile bounds for India are pinned in `airos/drivers/connectors/ghsl/raster.py`. |

### D.14 roads (OSM)

| Aspect | Detail |
|--------|--------|
| Source | **OSM Overpass + osmnx graph** for the city bbox |
| Attributes extracted | Road LineStrings, `highway` tag (`primary`, `secondary`, `residential`, …), intersection nodes |
| Cell mapping | LineStrings projected to UTM, intersected with H3 cell polygons via STRtree, summed by segment length. Intersections counted per cell |
| Derived signals | `ROAD_DENSITY = ROAD_LENGTH_M / cell_area_km²`, `MAJOR_ROAD_RATIO = length(highway ∈ {primary, secondary, trunk, motorway}) / total length` |
| Signals written | `ROAD_LENGTH_M`, `ROAD_DENSITY` (m/km², not 0–1), `MAJOR_ROAD_RATIO` (0–1), `INTERSECTION_COUNT`, `DATA_CONFIDENCE` |
| Cadence | 90 days |
| Caveats | **`ROAD_DENSITY` is in m/km², not a normalised 0–1 ratio** — typical Bangalore cell values are 5,000–30,000. This unit gotcha is surfaced explicitly to the agent in the dossier (§4.5) and used by the cause classifier with absolute thresholds (§4.4). Confusing the unit is the most common source of misinterpretation. |

### D.15 drains (OSM)

| Aspect | Detail |
|--------|--------|
| Source | **OSM Overpass** with `waterway ∈ {drain, canal, stream, ditch}` |
| Attributes extracted | Waterway LineStrings + tunnel/cover tags for open-vs-covered determination |
| Cell mapping | Line clip + sum (as roads). Open-drain ratio = open length / total drain length |
| Signals written | `DRAIN_LENGTH_M`, `OPEN_DRAIN_RATIO` (0–1), `FLOOD_DRAIN_CAPACITY` (heuristic from length × major-channel weighting), `WATERWAY_COUNT`, `DATA_CONFIDENCE` |
| Cadence | 90 days |
| Caveats | OSM drain coverage outside arterial waterways is highly variable — community-contributed and uneven. `FLOOD_DRAIN_CAPACITY` is a structural proxy, not a hydraulic capacity model. |

### D.16 pois (OSM)

| Aspect | Detail |
|--------|--------|
| Source | **OSM Overpass** with a tag-union query covering `amenity`, `landuse`, `man_made`, `building`, `industrial`, `shop` |
| Attributes extracted | OSM feature geometry + all relevant tags + OSM object id |
| Cell mapping | Polygon centroid → H3 cell. Each feature is run through a deterministic classifier with priority-ordered tag matching — output is **one** of 11 categories or `None` (drop) |
| Categories | `INDUSTRIAL`, `CONSTRUCTION`, `FUEL_STATION`, `KILN`, `EATERY`, `CREMATORIUM`, `WASTE_FACILITY`, `MARKET`, `TRANSIT_TERMINAL`, `HOSPITAL`, `SCHOOL` |
| Signals written | One `POI_{CATEGORY}_COUNT` signal per category per cell, plus `DATA_CONFIDENCE` |
| Side table | `poi_points` stores `(poi_id, city_id, h3_id, category, name, lat, lon)` for every classified feature, used by the dashboard map to render source locations |
| Cadence | 90 days |
| Caveats | Bangalore's first ingestion produced **0 kilns** — OSM has none tagged inside the bbox, although kilns exist on city outskirts. Coverage is best for `INDUSTRIAL`, `EATERY`, `SCHOOL`, `HOSPITAL`; weakest for `KILN`, `CREMATORIUM`, `WASTE_FACILITY`. Treat low counts as "absence-of-evidence not evidence-of-absence". |

### D.17 terrain

| Aspect | Detail |
|--------|--------|
| Sources | **Open-Elevation API** (SRTM-backed, free); local **SRTM 30 m DEM** tile cache (`srtm.py`); **Copernicus DEM GLO-30** (planned direct integration) |
| Attributes extracted | Elevation raster |
| Cell mapping | Pixel → H3 cell, mean elevation. Slope and aspect computed from cell-neighbourhood gradients. Ruggedness index = std-dev of elevation within k=1 ring |
| **Flow routing** | After elevation is computed for every cell, the ingestor builds a **hex-D6 flow graph**: each cell drains to its steepest-downhill neighbour (or to itself for sinks where no neighbour is lower). The resulting `FLOW_DIRECTION` is a small integer 0–5 indexing the chosen H3 neighbour (or -1 for sinks). `FLOW_ACCUMULATION` is then the count of cells whose runoff transitively reaches this cell, computed by topological traversal of the flow graph. Output: every cell knows its drainage parent and how big its upstream basin is. |
| Derived signals | `TERRAIN_CLASS` is agent-derived in a separate post-processing step (flat / rolling / hilly / steep) |
| Signals written | `ELEVATION_M`, `SLOPE_DEG`, `ASPECT_DEG`, `RUGGEDNESS_INDEX`, `TERRAIN_CLASS`, **`FLOW_DIRECTION`**, **`FLOW_ACCUMULATION`**, `DATA_CONFIDENCE` |
| Cadence | 90 days |
| Caveats | SRTM is 30 m horizontal, 1–10 m vertical accuracy — fine for urban-scale terrain context but inadequate for hydraulic flood modelling. The flow graph is **purely topographic** — it cannot see storm drains, culverts, or pumping stations that engineered urban drainage networks rely on. Use `FLOW_ACCUMULATION` as a prioritisation signal (which cells are at the bottom of basins), not as a runoff predictor. See §D.5 caveats for what the flood pipeline does and does not model. |

### D.18 nightlights

| Aspect | Detail |
|--------|--------|
| Source | **NASA Black Marble VNP46A2** (VIIRS DNB monthly composite, 500 m) — `EARTHDATA_TOKEN` required for live; falls back to **EOG VIIRS Monthly Composite** then to **synthetic literature-based estimates** for Indian cities |
| Attributes extracted | DNB radiance (nW/cm²/sr) per pixel |
| Cell mapping | Pixel → H3 cell, mean. `NTL_LIT_FRACTION` = fraction of pixels in cell above a 0.5 nW threshold |
| Derived signals | `ECONOMIC_ACTIVITY_INDEX` is a normalised radiance score; `ACTIVITY_CLASS` is a tier (1–4) for inbox filtering |
| Signals written | `NTL_RADIANCE`, `NTL_LIT_FRACTION`, `ECONOMIC_ACTIVITY_INDEX`, `ACTIVITY_CLASS`, `DATA_CONFIDENCE` |
| Cadence | 30 days |
| **Maturity** | Production-ready when `EARTHDATA_TOKEN` configured; **synthetic-fallback only** otherwise. Synthetic mode should not participate in high-confidence insights. The dossier and the LLM system prompt include the source band so the agent will avoid attributing patterns to "low economic activity" when the underlying source is a literature estimate. |
| Caveats | VIIRS DNB at 500 m is coarser than H3 res 8 (~1 km cell), so multiple cells often inherit identical radiance. Synthetic fallback is **derived from city-wide literature averages**, not from observation — when active, `DATA_CONFIDENCE` drops below 0.3 and the source string identifies it. Treat synthetic values as **structural context only**, never as actionable evidence. |

### D.19 cross-cutting: data_confidence and nearest_obs_km

Almost every domain writes a `DATA_CONFIDENCE` signal in `[0, 1]`. The convention:

- **0.85–0.95**: structural OSM data (buildings, roads, drains) — coverage gaps but no temporal staleness.
- **0.6–0.85**: well-served IDW with a station within ~5 km, or recent satellite pass < 24 h.
- **0.3–0.6**: IDW with `NEAREST_OBS_KM` > 10, or satellite pass 1–7 days old.
- **< 0.3**: model-only / synthetic estimate, or station > 20 km away.

`NEAREST_OBS_KM` is written **alongside** confidence by IDW domains (air, weather, fire, waste, crowd) so the agent can see the raw distance, not just the derived confidence. The H3 Expert Agent is instructed to discount a signal whose `NEAREST_OBS_KM` is large or whose `DATA_CONFIDENCE` is low.

### D.20 insight generation — when does a cell get an insight?

A cell becomes a candidate for the H3 Expert Agent when:

1. **The scheduler selects it** in the current sweep — via the two-pool policy (§6.2): risk pool (cells with high current `max_risk_score` and no insight in the last 6 h) or coverage pool (cells never analysed or oldest last-analysed).
2. **The 6-hour cooldown** has elapsed since the last insight on this cell.
3. **At least one domain** has a non-empty assessment in the last 7 days.

The agent then runs the loop described in §4. The scheduler emits **at most `top_n` insights per city per sweep** (default 10) at a default 15-minute interval (`sweep_interval=900s`). The cooldown + risk-pool concentration mean insight production is much less than the theoretical maximum — empirically it stabilises at ~480–800/day across a 6-city deployment, not the 5,760/day upper bound.

After insights land, `InsightPacketGenerator` (§4.4) promotes the high-priority ones (`tier ∈ {high, medium}`, confidence ≥ 0.5) to decision packets. Each air-domain packet carries the full cause classifier output and routing block. This is the bridge from "agent finding" to "department-routed work item" that downstream Grievance Redressal Systems consume.

### D.21 census (GHSL_POP)

| Aspect | Detail |
|--------|--------|
| Source | **GHSL R2023A 100 m residential population grid** (`GHS_POP_E2020_GLOBE_R2023A_54009_100`, JRC, CC-BY 4.0). Same JRC tile store as the GHSL built products (§D.13) — a single connector serves both. |
| Attributes extracted | People per 100 m × 100 m pixel (float, 2020 reference year, modelled from census + Landsat/Sentinel built layers) |
| Cell mapping | Pixel center reprojected Mollweide → WGS84 → H3 res-8 cell. Pixel values are summed across the cell. |
| Signals written | `POPULATION`, `POPULATION_DENSITY_PER_KM2`, `VULNERABLE_POPULATION_EST`, `DATA_CONFIDENCE` (0.80) |
| Cadence | 365 days (epoch updates ship every ~5 years). |
| `VULNERABLE_POPULATION_EST` derivation | `POPULATION × 0.18` — coarse multiplier from NFHS-5 (~11.5 % under-5 + ~6.5 % over-65 in urban India). The `_EST` suffix flags this as a placeholder until age-stratified strata are available. |
| Verification (Bangalore) | Top-population cells resolve to classically dense Old Bangalore residential — Vijayanagar (63.2 k people), Rajajinagar, Mahalakshmi Layout, Malleshwaram, Hanumanthnagar. Bbox total = 13.68 M, matching the Bangalore urban agglomeration (~13 M). |
| Why GHSL_POP and not WorldPop | WorldPop's HTTPS endpoint does **not** honour HTTP range requests, so windowed `/vsicurl` reads fail; pulling the full 1.8 GB India raster per ingest is unworkable. GHSL serves zipped GeoTIFFs from a server that supports ranges, so the same `/vsizip//vsicurl/` pattern works for both built-mass and population. |
| Used by | Exposure layers (dashboard prioritisation), citizen view, future packet ranking. Not currently consumed by the cause classifier — population is an *exposure* signal, not a cause-attribution signal. |
| Caveats | 100 m resolution averages out slum-vs-mid-rise distinctions at our 0.74 km² H3 cell. 2020 epoch — does not reflect post-COVID migration or post-2020 development. Modelled allocation: not a substitute for ground-truth census enumeration in fine planning decisions. |
