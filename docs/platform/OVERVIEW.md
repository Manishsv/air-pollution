# AirOS — Platform Overview

AirOS is a spatial urban intelligence operating system that transforms raw environmental and infrastructure feeds into structured, human-reviewed decision packets for city managers, ward officers, and department engineers. It is not a dashboard or a reporting tool — it is the operating layer underneath any city-facing application built on top of it.

---

## What AirOS Actually Is

AirOS has three defining characteristics that distinguish it from a typical analytics platform:

**1. Spatial-first (H3 hexagonal grid)**
All signals, assessments, and insights are anchored to H3 resolution-8 hexagonal cells (≈ 0.74 km² each, ~1 km edge-to-edge). Every raw observation — a sensor reading, a satellite pixel, a crowd count, a road segment — is translated into a per-cell signal before any analysis happens. The city is always addressed as a grid, not as a list of records.

**2. Specs-first (contracts before code)**
Every data source, domain, and application is governed by machine-readable specifications (provider contracts, domain specs, consumer contracts). No connector ships without a provider contract. No dashboard panel ships without a consumer contract. Conformance is checked on every commit.

**3. Human review is mandatory**
AirOS does not issue government decisions. It produces decision packets — structured evidence bundles with confidence scores, safety gates, and "when not to act" guidance — that a human officer reviews before any action is taken. Every output is labelled with its source, its uncertainty, and the conditions under which it should not be acted upon.

---

## Architecture in One Picture

```
┌─────────────────────────────────────────────────────┐
│                   Data Sources                       │
│  OSM · Sentinel-2 · CPCB/AQICN · OpenMeteo          │
│  MODIS/VIIRS · CCTV cameras · Municipal feeds       │
└───────────────────┬─────────────────────────────────┘
                    │  connectors/
                    ▼
┌─────────────────────────────────────────────────────┐
│           H3 Knowledge Ingestors                     │
│  14 domain ingestors (air, flood, heat, water,       │
│  fire, noise, construction, green, waste, weather,   │
│  buildings, roads, drains, crowd)                    │
│                                                      │
│  Raw feeds → IDW interpolation / centroid assign /   │
│  line-clip → per-H3-cell signals at res 8           │
└───────────────────┬─────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────┐
│           H3 Knowledge Store (SQLite)                │
│  h3_signals       (one row per cell/signal/hour)    │
│  h3_assessments   (one row per cell/domain/day)     │
│  h3_metadata      (cell registry)                   │
│  h3_packets       (decision packets)                │
│  h3_insights      (agent findings)                  │
│  h3_ingest_log    (watermark per domain)            │
└───────────────────┬─────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────┐
│           H3 Expert Agent                            │
│  LLM-backed reasoning agent that reads temporal      │
│  context (30d baseline, circadian window, 48h        │
│  forecast) and produces a cross-domain insight with  │
│  testable hypotheses and confidence-derived tier     │
└───────────────────┬─────────────────────────────────┘
                    │  (run_top_risk_cells: risk pool + coverage pool)
                    ▼
┌─────────────────────────────────────────────────────┐
│           City Pattern Agent                         │
│  Second-pass sweep synthesiser — reads all cell      │
│  insights from the last sweep, identifies city-wide  │
│  themes, computes cross-domain co-elevation stats,   │
│  and writes a structured summary to city_patterns    │
└───────────────────┬─────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────┐
│           Review Dashboard (Streamlit)               │
│  Inbox (priority tiers, outcome tracking, close tab) │
│  City Map (insights-only toggle) · Infrastructure    │
│  panel · Ward decisions · Expert agent chat          │
└─────────────────────────────────────────────────────┘
```

---

## The H3 Knowledge Store

This is the central database. Everything in AirOS flows into and out of it.

### Tables

| Table | Dedup key | What it holds |
|-------|-----------|---------------|
| `h3_signals` | `(h3_id, city_id, domain, signal, hour_bucket)` | One row per cell/signal/hour. Newer value wins on conflict. Accumulates history across hours/days. Includes `data_quality` field (real_station / satellite_derived / model_estimate / unknown), auto-inferred from source name. |
| `h3_assessments` | `(h3_id, city_id, domain, day_bucket)` | Risk level per cell per domain per day. Newer assessment wins within the same day. |
| `h3_metadata` | `(h3_id, city_id)` | Cell centroid lat/lon, first_seen, last_active. |
| `h3_packets` | `packet_id` | Decision packets (idempotent — duplicate packet_id ignored). |
| `h3_insights` | append-only | Agent findings. Key columns: `finding`, `confidence`, `priority_tier` (high/medium/low, derived from confidence), `hypothesis_chain_json` (testable propositions with `testable_by` field), `outcome_status` (open/confirmed/refuted/unverifiable), `closed_by`, `closed_at`. |
| `h3_ingest_log` | `(city_id, domain)` | Last ingest timestamp per domain — gates the cadence check. |
| `h3_siting_candidates` | `(city_id, domain, h3_id, period_start)` | Recommended sensor siting locations. |
| `h3_analysis_requests` | `request_id` | Queue of human-triggered expert agent runs. |
| `city_patterns` | `pattern_id` | City-level pattern summaries produced by the City Pattern Agent after each sweep. Holds executive summary, themed findings, and evidence JSON. |

### H3 Resolution

All data is stored at **resolution 8** (DEFAULT_H3_RES):

| Resolution | Area | Edge-to-edge | Used for |
|------------|------|--------------|----------|
| 7 | 5.16 km² | ~2.6 km | City-wide rollups |
| **8** | **0.74 km²** | **~1.0 km** | **All AirOS signals** |
| 9 | 0.11 km² | ~0.4 km | Not currently used |
| 10 | 0.015 km² | ~0.14 km | Not currently used |

---

## The Rules Registry

All domain thresholds and risk classification rules are centralised in a configurable registry — no hardcoded values in pipeline code.

```
data/config/rules_registry.yaml     ← operator-editable YAML overlay
urban_platform/rules/registry.py    ← Python defaults + YAML merge + city overrides
```

The registry supports:
- **Domain-level defaults** (e.g. `air.pm25_good_threshold_ug_m3: 12`)
- **City-level overrides** (e.g. `crowd.cities.mumbai.gathering_threshold_per_km2: 800`)
- **Live reload** without restart (`rules.reload()`)

Every pipeline reads thresholds via `_rules.get(domain, key, default=<original_value>)` — the default always matches the original hardcoded value so behaviour is identical with an empty YAML file.

---

## Raw Data → H3 Cell: Four Methods

### A. Point observations → IDW interpolation
*Used for: AQI sensors, rain gauges, weather stations, CCTV cameras*

Sensors report at discrete GPS points. IDW (Inverse Distance Weighting, 1/d²) interpolates values to all H3 cell centroids. Assumptions: spatial stationarity, isotropy, 50m minimum distance floor. Cells far from any sensor receive a lower `DATA_CONFIDENCE` and a `NEAREST_OBS_KM` signal.

### B. Polygon features → centroid assignment
*Used for: building footprints*

Building polygon → centroid → `h3.latlng_to_cell(lat, lon, 8)`. One cell owns each building. Stats (count, floors, commercial ratio) aggregate by groupby.

### C. Line features → clip and sum
*Used for: roads, waterways/drains*

OSM LineStrings cross cell boundaries. For each cell, we find candidate lines via STRtree, project both line and cell to UTM (EPSG:32643 or 32644 by city latitude band), compute `line.intersection(cell_polygon)`, and sum `.length` in metres for true metric distances.

### D. Satellite grid → direct assignment
*Used for: Sentinel-2 (LST, NDVI, MNDWI, water quality), MODIS fire*

Each satellite pixel/derived cell has a centroid lat/lon → `h3.latlng_to_cell()` → cells with multiple pixels average their values.

---

## Ingest Cadence

| Domain | Cadence | Source | Produces assessments? |
|--------|---------|--------|-----------------------|
| air | hourly | CPCB / AQICN API | yes |
| weather | hourly | OpenMeteo API | no |
| fire | every 3h | MODIS / VIIRS | yes |
| noise | hourly | noise sensor API | yes |
| construction | every 6h | construction API | yes |
| crowd | every 15 min | CCTV observation store | yes (gathering alerts) |
| heat | daily | Sentinel-2 GEE | yes |
| flood | daily | Sentinel-2 GEE | yes |
| water | daily | Sentinel-2 GEE | yes |
| green | daily | Sentinel-2 GEE | yes |
| waste | daily | Sentinel-2 GEE | yes |
| buildings | quarterly | OSM Overpass | no |
| roads | quarterly | OSM Overpass | no |
| drains | quarterly | OSM Overpass | no |

**Versioning:** signals dedup on `(h3_id, city_id, domain, signal, hour_bucket)`. Each ingest run writes to the current hour's bucket. History across hours/quarters accumulates — older rows are never deleted, just superseded in the "latest" query. Re-ingesting roads quarterly writes a new snapshot row (different `hour_bucket`); the previous quarter's row remains in the store.

---

## Structural vs Risk Domains

**Structural domains** (buildings, roads, drains, weather) provide context — they do not produce `h3_assessments`. The H3 Expert Agent reads them to modulate risk reasoning:
- High road density → traffic emission source
- Low drain density + high rainfall → elevated flood concern
- Low building count → low exposure despite poor air quality

**Risk domains** (air, fire, flood, heat, water, waste, noise, construction, crowd) produce both signals and assessments. Assessments have a `risk_level` (good / moderate / high / severe) that the dashboard and agent use to prioritise attention.

---

## Agent Intelligence Layer

The agent layer sits between the H3 Knowledge Store and the review dashboard. It has two tiers.

### Tier 1 — H3 Expert Agent (cell-level)

The H3 Expert Agent runs for one H3 cell at a time. For each cell it assembles **three temporal horizons**:

| Horizon | What | How |
|---------|------|-----|
| Past | 30-day all-day baseline (mean, p75, p90, provenance mix) | SQL over `h3_signals` |
| Past (circadian) | Same-hour-of-day baseline (±2h UTC window, 30 days) | SQL filtered to same hour-of-day; removes diurnal cycle so 2am readings are compared against other 2am readings |
| Present | Latest 7-day signals + staleness flags | Existing `h3_signals` query |
| Future | 48-hour weather + AQ forecast (wind, precip, temp, PM2.5, PM10) | OpenMeteo API, fetched once per city per sweep and shared across all cells |

The agent has **six tools**:

| Tool | Purpose |
|------|---------|
| `get_signal_history` | Time-series for a specific domain/signal |
| `get_neighbor_context` | Risk assessments in the surrounding k-ring |
| `get_city_summary` | City-wide risk distribution and top insights |
| `get_packets_for_domain` | Outcome history of prior decision packets |
| `get_domain_cross_correlation` | City-wide lift score between two domains (validates cross-domain hypotheses before submission) |
| `submit_insight` | Structured output written to `h3_insights` |

Insights use **testable hypotheses** (not causal chains) — each proposition includes a `testable_by` field stating what evidence would confirm or refute it. Confidence maps to a `priority_tier` (high ≥ 0.75, medium 0.45–0.74, low < 0.45). Outcomes are tracked: field officers close insights with `confirmed`, `refuted`, or `unverifiable` verdicts. The agent reads prior outcomes on subsequent runs.

**Cell selection — two-pool sweep:** `run_top_risk_cells()` splits its budget into a **risk pool** (70% of budget — highest-risk cells, 6h cooldown) and a **coverage pool** (30% — cells never analysed or with the oldest insight, ordered never-analysed first). This prevents the agent from clustering on the same hot-spot cells repeatedly and ensures city-wide baseline coverage builds over time.

### Tier 2 — City Pattern Agent (sweep-level)

After each cell sweep that produces new insights, the **City Pattern Agent** runs once per city. It reads all insights from the last 2 hours and synthesises:

- **Domain frequency** — which domains appear most across insights
- **Co-occurrence pairs** — which domain combinations appear in the same insight
- **Cross-domain co-elevation** — lift scores from `get_domain_cross_correlation` for the top pairs
- **Hotspot cells** — cells appearing in multiple insights
- **City risk distribution** — cell counts by risk level across all domains (last 24h)

Output is a structured JSON (executive summary + 2–5 themed findings with evidence, confidence, city-level actions) written to `city_patterns`. This is the first layer of analysis above the individual-cell level.

---

## Safety Posture

AirOS does not authorize or automate government decisions. Every output is:
- Labelled with data source, confidence score, and uncertainty
- Accompanied by "when not to act" guidance
- Gated by named safety gates that must be checked before escalation
- Listed with blocked uses (what the packet must not be used for)

The review dashboard is explicitly a decision support tool. Officers review evidence packets and record their own decisions. AirOS records outcomes but never initiates them.

---

## Key Files

| Path | Role |
|------|------|
| `urban_platform/h3_knowledge/store.py` | SQLite store, WAL mode, threading lock |
| `urban_platform/h3_knowledge/schema.py` | All DDL, table definitions |
| `urban_platform/h3_knowledge/writer.py` | Upsert helpers for all table types |
| `urban_platform/h3_knowledge/ingestor.py` | Orchestrator, cadence checks, domain dispatch |
| `urban_platform/h3_knowledge/geo_agg.py` | STRtree spatial index, IDW, line-clip |
| `urban_platform/h3_knowledge/*_ingestor.py` | Per-domain ingest logic |
| `urban_platform/rules/registry.py` | Rules registry singleton |
| `data/config/rules_registry.yaml` | Operator threshold overrides |
| `data/config/camera_registry.json` | CCTV camera → lat/lon registry |
| `urban_platform/agents/h3_expert.py` | H3 Expert Agent — cell-level cross-domain reasoning |
| `urban_platform/agents/city_pattern_agent.py` | City Pattern Agent — sweep-level synthesis across cells |
| `urban_platform/connectors/weather/open_meteo_forecast.py` | 48-hour weather + AQ forecast (OpenMeteo, no key required) |
| `review_dashboard/app.py` | Streamlit dashboard entry point |
| `review_dashboard/components/` | Per-domain dashboard panels |

---

## Further Reading

- **Intelligence methodology (academic)**: [`INTELLIGENCE_METHODOLOGY.md`](INTELLIGENCE_METHODOLOGY.md) — spatial framework, temporal context, agent architecture, lift scores, coverage sampling, limitations, evaluation framework
- **Federation and Network Layer**: [`FEDERATED_DEPLOYMENT_ARCHITECTURE.md`](FEDERATED_DEPLOYMENT_ARCHITECTURE.md), [`AGENCY_NODE_MODEL.md`](AGENCY_NODE_MODEL.md)
- **Specs-first development**: `specifications/ARCHITECTURE_NOTE.md`, [`../developer/DOMAIN_DEVELOPMENT_PLAYBOOK.md`](../developer/DOMAIN_DEVELOPMENT_PLAYBOOK.md)
- **Multi-container deployment**: [`CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md`](CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md)
