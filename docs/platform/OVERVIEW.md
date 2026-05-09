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
│  Claude-backed reasoning agent that reads all        │
│  signals for a requested cell and produces a         │
│  cross-domain insight with causal chain              │
└───────────────────┬─────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────┐
│           Review Dashboard (Streamlit)               │
│  Per-domain tabs · H3 cell explorer · Infrastructure │
│  panel · Ward decisions · Expert agent chat          │
└─────────────────────────────────────────────────────┘
```

---

## The H3 Knowledge Store

This is the central database. Everything in AirOS flows into and out of it.

### Tables

| Table | Dedup key | What it holds |
|-------|-----------|---------------|
| `h3_signals` | `(h3_id, city_id, domain, signal, hour_bucket)` | One row per cell/signal/hour. Newer value wins on conflict. Accumulates history across hours/days. |
| `h3_assessments` | `(h3_id, city_id, domain, day_bucket)` | Risk level per cell per domain per day. Newer assessment wins within the same day. |
| `h3_metadata` | `(h3_id, city_id)` | Cell centroid lat/lon, first_seen, last_active. |
| `h3_packets` | `packet_id` | Decision packets (idempotent — duplicate packet_id ignored). |
| `h3_insights` | append-only | Agent findings with causal chains. |
| `h3_ingest_log` | `(city_id, domain)` | Last ingest timestamp per domain — gates the cadence check. |
| `h3_siting_candidates` | `(city_id, domain, h3_id, period_start)` | Recommended sensor siting locations. |
| `h3_analysis_requests` | `request_id` | Queue of human-triggered expert agent runs. |

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
| `urban_platform/agents/h3_expert.py` | H3 Expert Agent (Claude-backed) |
| `review_dashboard/app.py` | Streamlit dashboard entry point |
| `review_dashboard/components/` | Per-domain dashboard panels |
