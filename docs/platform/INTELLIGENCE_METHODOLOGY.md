# AirOS Intelligence Methodology

**A technical reference for researchers, evaluators, and implementers**

---

## Abstract

AirOS is a spatial urban intelligence system that produces human-reviewed decision support from heterogeneous environmental and infrastructure signals. This document describes the statistical and computational methodology underlying the system's reasoning layer, covering: the spatial discretisation scheme; signal ingestion and provenance tracking; three-horizon temporal context construction; agent architecture and tool design; cross-domain co-occurrence statistics; spatial coverage mechanics; city-level pattern synthesis; and the outcome feedback loop. We document known limitations, data quality constraints, and the epistemic posture the system adopts to remain honest under uncertainty.

---

## 1. Spatial Framework

### 1.1 H3 Hexagonal Discrete Global Grid

AirOS discretises urban space using Uber's H3 Hierarchical Spatial Index at **resolution 8**. Each cell covers approximately 0.74 km² with an edge-to-edge diameter of ~1 km. The choice of resolution 8 reflects a deliberate trade-off:

| Resolution | Area (km²) | Edge (km) | Rationale |
|------------|-----------|-----------|-----------|
| 7 | 5.16 | ~2.6 | Too coarse — mixes pollution micro-zones |
| **8** | **0.74** | **~1.0** | Matches typical monitoring station influence radius; aligns with ward-level governance |
| 9 | 0.11 | ~0.4 | Sub-block scale; exceeds sensor spatial accuracy for most modalities |

Hexagonal tessellation is preferred over square grids because it provides uniform adjacency (all six neighbours are equidistant from the centroid), reducing directional bias in spatial interpolation. H3's hierarchical structure enables coarsening to resolution 7 for city-wide rollups without re-projecting data.

All signals, assessments, and insights in AirOS are cell-addressed. No spatial reasoning operates at point or polygon scale — every raw observation is mapped to a cell before entering the knowledge store.

### 1.2 Raw Signal → Cell: Four Assignment Methods

**A. Point observations → Inverse Distance Weighting (IDW)**

Used for sensor modalities (AQ stations, weather stations, rain gauges, CCTV cameras). For a target cell centroid $\mathbf{c}$, the interpolated value is:

$$\hat{v}(\mathbf{c}) = \frac{\sum_{i} w_i v_i}{\sum_{i} w_i}, \quad w_i = \frac{1}{d(\mathbf{c}, \mathbf{s}_i)^2}$$

where $\mathbf{s}_i$ are sensor locations and $d$ is the great-circle distance. A minimum distance floor of 50 m prevents weight singularities when a sensor falls within a cell centroid. A `DATA_CONFIDENCE` signal and `NEAREST_OBS_KM` signal are written alongside each interpolated value; cells far from any sensor receive lower confidence.

**Limitation:** IDW assumes spatial stationarity (the signal varies smoothly in space) and isotropy (no directional preference). Urban environments violate both assumptions — a busy road may produce a PM2.5 gradient that IDW cannot capture from a sparse sensor network. The `DATA_CONFIDENCE` signal surfaces this uncertainty but does not correct for it.

**B. Polygon features → Centroid assignment**

Used for building footprints. Each polygon's centroid determines its host cell. Per-cell aggregates (building count, floor count, commercial ratio) are computed by groupby.

**C. Line features → UTM clip and sum**

Used for roads, waterways, and drainage networks. OSM LineStrings are projected to UTM (zone auto-selected by city latitude band) and intersected with H3 cell polygons using an STRtree spatial index. The summed intersection length in metres is stored as `ROAD_LENGTH_M`, `DRAIN_LENGTH_M`, etc. This method correctly handles lines that cross cell boundaries, producing proportional attribution rather than centroid-based ownership.

**D. Satellite raster → Direct cell assignment**

Used for Sentinel-2 derived indices (LST, NDVI, MNDWI, water quality index) and MODIS/VIIRS fire radiative power. Each raster pixel's centroid coordinates are mapped to an H3 cell; cells with multiple pixels receive the mean of their pixels.

---

## 2. Signal Provenance and Data Quality

### 2.1 Source Taxonomy

Every signal written to `h3_signals` carries a `data_quality` tag, automatically inferred from the source identifier at ingest time:

| Tag | Meaning | Typical sources |
|-----|---------|----------------|
| `real_station` | Measured by a physical sensor at or near the cell | CPCB AQ stations, weather stations, CCTV cameras |
| `satellite_derived` | Retrieved from remotely sensed imagery | Sentinel-2 (NDVI, LST, MNDWI), MODIS fire |
| `model_estimate` | Output of a spatial interpolation or numerical model | IDW-interpolated AQ, OpenMeteo forecast |
| `unknown` | Source not in the known taxonomy | Legacy or third-party data with unclassified provenance |

### 2.2 Provenance Mix in Baselines

When computing 30-day historical baselines, the system tracks the fraction of readings in each quality tier:

$$\text{provenance} = \left(\frac{n_{\text{real}}}{n}, \frac{n_{\text{sat}}}{n}, \frac{n_{\text{model}}}{n}\right)$$

This is surfaced to the reasoning agent as a note (e.g. "73% model_estimate — percentile rank less reliable"). An agent that sees a 90th-percentile reading should weight this differently depending on whether the historical distribution is drawn from real stations or from a model with known systematic biases.

---

## 3. Temporal Context Architecture

A defining feature of the AirOS intelligence layer is the assembly of **three temporal horizons** for each cell before any reasoning begins. This architecture is motivated by the observation that an anomaly is only detectable relative to a reference distribution, and the appropriate reference distribution depends on both time scale and time of day.

### 3.1 All-Day Historical Baseline (30 Days)

For each (cell, domain, signal) triple, the system computes:

$$\bar{x}_{30}, \quad P_{75}, \quad P_{90}, \quad x_{\min}, \quad x_{\max}, \quad \text{rank}(x_{\text{current}})$$

over all readings in the past 30 days regardless of time of day. The **percentile rank** of the current reading within the 30-day distribution gives a scalar anomaly score:

$$\rho = \frac{|\{v \in \mathcal{H}_{30} : v \leq x_{\text{current}}\}|}{|\mathcal{H}_{30}|} \times 100$$

**N-guard:** percentile rank is only reported when $n \geq 30$ readings are available. Below this threshold the empirical CDF is insufficiently resolved and the rank would be statistically misleading. When $n < 30$, only raw statistics (mean, max) are reported without a rank.

### 3.2 Circadian Baseline (Same Hour of Day, 30 Days)

Urban signals exhibit strong diurnal periodicity. PM2.5 at 2am is drawn from a different distribution than PM2.5 at 2pm (traffic patterns, mixing layer height, temperature inversions). Comparing a 2am reading against the all-day 30-day mean conflates the diurnal cycle with genuine anomalies.

The **circadian baseline** computes the same statistics as §3.1, but restricts the historical window to readings taken within ±2 hours UTC of the current observation time:

$$\mathcal{H}_{\text{circ}} = \{v \in \mathcal{H}_{30} : h(v) \in [h_{\text{now}} - 2, h_{\text{now}} + 2] \pmod{24}\}$$

where $h(\cdot)$ returns the UTC hour of a reading. This 5-hour window out of 24 produces approximately 21% of the readings in the all-day baseline. For a system that has been running 30 days with one reading per hour per domain, $|\mathcal{H}_{\text{circ}}| \approx 150$ readings — sufficient for reliable percentile estimation.

**Time-of-day effect detection:** when the circadian percentile rank and the all-day percentile rank differ by ≥ 20 percentage points, this is flagged as a **time-of-day effect** — the current reading is anomalous relative to its diurnal peer group but not relative to the broader distribution (or vice versa). This distinction is presented to the reasoning agent explicitly.

**Activation threshold:** the circadian baseline activates only when $n_{\text{circ}} \geq 5$. Early in a deployment (first ~15 days) the same-hour window will have too few readings, and the baseline silently suppresses rather than reporting unreliable statistics.

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

**City-level amortisation:** a single forecast fetch is performed per city per sweep (using the centroid of the first selected cell as a representative location). All cells in the city share this forecast. The error introduced by using a single point is negligible for a city of typical scale (< 100 km) because OpenMeteo's underlying model resolution (~9 km for ICON-EU, ~25 km for ERA5) is coarser than city dimensions. This reduces API calls from O(N) to O(1) per sweep.

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

| Tool | Semantic |
|------|---------|
| `get_signal_history` | Time-series retrieval for a specific (domain, signal) pair |
| `get_neighbor_context` | Assessment summary for k-ring neighbours |
| `get_city_summary` | City-wide risk distribution for contextualisation |
| `get_packets_for_domain` | Outcome history of prior decision packets in this cell |
| `get_domain_cross_correlation` | City-wide statistical co-occurrence between two domains (§5) |
| `submit_insight` | Mandatory terminal call — structured output to knowledge store |

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

### 4.3 Outcome Tracking and Feedback Loop

Field officers close insights through the review dashboard with one of three verdicts:

| Verdict | Meaning |
|---------|---------|
| `confirmed` | Field verification found the hypothesised condition |
| `refuted` | Field visit found no evidence of the condition |
| `unverifiable` | Condition could not be assessed (access, timing, etc.) |

Closed insights are included in the agent's prior context on subsequent runs, labelled with their verdict. This creates an **outcome feedback loop**: the agent learns, in-context, whether its prior hypotheses for this cell were borne out. Over time, accumulated verdicts provide empirical ground truth for evaluating the system's false positive and false negative rates.

**Limitation:** this feedback loop depends on field officers consistently closing insights. If the dashboard is not used operationally, the loop remains open and the agent cannot distinguish confirmed from unverified hypotheses.

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

**Interpretation:**

| Lift | Interpretation |
|------|---------------|
| > 3.0 | Very strong co-occurrence — warrants hypothesis of shared mechanism |
| 1.5–3.0 | Moderate co-occurrence — worth investigating |
| 0.7–1.5 | Near-independent — co-occurrence in any single cell may be coincidental |
| < 0.7 | Anti-correlated — domains tend not to co-elevate |

**Statistical guard:** lift is suppressed when $n_{AB} < 5$ to prevent spurious large values from tiny samples (the formula can produce arbitrarily large lift when $n_A, n_B \ll n_{\text{total}}$).

**Usage:** the agent is instructed to call this tool *before* asserting a cross-domain causal link in its hypothesis chain. A lift > 1.5 strengthens the hypothesis; lift ≈ 1.0 suggests the co-occurrence in the current cell may be coincidental. The tool result is explicitly labelled as a city-wide prior, not proof for the specific cell under analysis.

**Limitations of lift as a metric:**
- Lift does not distinguish correlation from causation.
- It is symmetric — it cannot identify the direction of influence.
- It does not control for confounders (shared drivers like weather).
- The threshold for "elevated" risk is a discretisation that discards magnitude information.

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

**Expected convergence:** with a budget of 10 cells per sweep, coverage_ratio=0.3, and a 30-minute sweep interval, 3 coverage cells are visited per sweep. At 48 sweeps/day, this gives 144 coverage visits/day. For a 1,580-cell city (Bangalore at res 8), full first-pass coverage requires approximately 11 days — after which the coverage pool shifts to maintaining a rolling revisit schedule proportional to cell age.

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

This context is passed to an LLM synthesis agent with a structured output schema requiring:
- An executive summary (2–3 sentences)
- 2–5 themes, each with: title, description, affected domains, estimated cell count, confidence, supporting evidence, recommended city-level action, and priority
- A data quality note

The agent is instructed that a theme requires ≥ 3 cells or ≥ 2 independent insights to be considered valid, preventing spurious patterns from single-cell anomalies.

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

### 8.2 Known Limitations

**Spatial interpolation error:** IDW cannot capture sub-kilometre concentration gradients near point sources (roads, factories). A cell flagged as "high PM2.5" may have an actual concentration distribution that varies by 50–200% within its 0.74 km² area.

**Satellite temporal resolution:** Sentinel-2 has a 5–12 day revisit cycle per tile (depending on orbit geometry and cloud cover). "Daily" domains (heat, flood, green, waste) may actually reflect observations from several days prior in cloudy periods. The staleness flag (> 24h since last reading) surfaces this to the agent.

**Missing signal correlation structure:** the 30-day baseline assumes i.i.d. readings for percentile calculation. In practice, readings are temporally autocorrelated (hourly PM2.5 from a station tracks weather patterns). This means the effective sample size for the percentile rank is smaller than the nominal $n$.

**Lift as a correlation proxy:** as noted in §5.4, lift is symmetric, cannot identify causal direction, and does not control for confounders. Weather is a common confounder for several domain pairs (wind affects both PM2.5 dispersion and flood risk via rainfall).

**LLM reasoning opacity:** the H3 Expert Agent uses a large language model whose internal reasoning is not fully auditable. While the structured output (hypothesis chain, confidence, recommended actions) is inspectable, the inference path from context to conclusion is a black box. This is partially mitigated by the tool-calling architecture — each tool call is logged and interpretable — but the final synthesis step remains opaque.

**Outcome loop dependency:** the feedback mechanism (§4.3) only improves system calibration if field officers close insights. In deployments where the dashboard is used primarily for reading rather than recording verdicts, the loop never closes and the agent's confidence calibration cannot be empirically validated.

**Coverage pool convergence time:** as computed in §6.2, full first-pass city coverage requires approximately 11 days at a 10-cell budget. During this period, the majority of cells have no insight history, and the agent's circadian and outcome baselines for those cells are empty.

---

## 9. Evaluation Framework (Proposed)

The following evaluation dimensions are appropriate for rigorous assessment of an urban intelligence system of this type:

**Spatial precision:** for insights with confirmed verdicts, what is the geographic precision of the H3 cell boundary relative to the actual location of the identified condition? This requires field verification with GPS coordinates.

**Domain recall:** what fraction of confirmed field events (e.g. reported flood incidents, fire incidents, AQ exceedances) are surfaced as high-priority insights before or during the event? This requires a ground-truth event log.

**Hypothesis confirmation rate:** of all insights closed by field officers, what fraction are `confirmed`? Stratified by domain, priority tier, and data quality mix.

**Cross-domain lift validity:** do pairs with high lift produce more confirmed cross-domain insights than pairs with low lift? This tests whether lift is a useful predictor of cross-domain co-occurrence at the cell level.

**Circadian baseline improvement:** do cells with a mature circadian baseline (≥ 30 same-hour readings) produce lower false positive rates (refuted insights) than cells relying only on the all-day baseline?

**Coverage pool efficiency:** do cells selected via the coverage pool eventually produce insights at the same confirmation rate as risk-pool cells? If not, the risk-first policy is more efficient despite its clustering bias.

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

## Appendix A: Knowledge Store Schema (Relevant Tables)

```
h3_signals
  (h3_id, city_id, domain, signal, hour_bucket)  -- dedup key
  value REAL, unit TEXT, source TEXT, level TEXT,
  observed_at TEXT, data_quality TEXT             -- real_station | satellite_derived | model_estimate | unknown

h3_assessments
  (h3_id, city_id, domain, day_bucket)           -- dedup key
  risk_level TEXT, primary_index TEXT, primary_value REAL,
  dominant_issue TEXT, assessed_at TEXT

h3_insights
  insight_id TEXT PRIMARY KEY (UUID)
  h3_id, city_id, agent_type, created_at
  finding TEXT, confidence REAL
  priority_tier TEXT                              -- high | medium | low (derived from confidence)
  domains_involved TEXT                           -- comma-separated
  hypothesis_chain_json TEXT                      -- [{proposition, testable_by}, ...]
  recommended_actions_json TEXT
  uncertainty_notes_json TEXT
  outcome_status TEXT                             -- open | confirmed | refuted | unverifiable
  closed_by TEXT, closed_at TEXT

city_patterns
  pattern_id TEXT PRIMARY KEY (UUID)
  city_id TEXT, created_at TEXT
  lookback_hours INTEGER, n_insights INTEGER, theme_count INTEGER
  summary_json TEXT                               -- {executive_summary, themes: [...], emerging_risks, data_quality_note}
```

## Appendix B: Scheduler Configuration

| Parameter | Default | Effect |
|-----------|---------|--------|
| `top_n` | 10 | Total cells analysed per sweep |
| `coverage_ratio` | 0.3 | Fraction of budget allocated to coverage pool |
| `sweep_interval` | 900s (15 min) | Time between sweeps |
| `cooldown` | 6h | Minimum time before a cell is re-analysed |
| `lookback_days` (risk pool) | 7 | Assessment recency for risk score |
| `lookback_hours` (city pattern) | 2 | Sweep window for city pattern synthesis |

## Appendix C: Forecast Channels (OpenMeteo)

| API | Endpoint | Key variables |
|-----|----------|--------------|
| Weather | `api.open-meteo.com/v1/forecast` | `windspeed_10m`, `winddirection_10m`, `precipitation_probability`, `temperature_2m` |
| Air Quality | `air-quality-api.open-meteo.com/v1/air-quality` | `pm2_5`, `pm10` |

Both are fetched at hourly resolution and aggregated into 6-hour buckets. No API key is required. The system falls back gracefully (empty forecast dict) if the API is unreachable.
