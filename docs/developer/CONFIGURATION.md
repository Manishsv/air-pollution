# AirOS Configuration Reference

This document covers every configuration file and environment variable in AirOS. Configuration is split across three places:

- `.env` — runtime secrets and feature flags (copied from `.env.example`)
- `data/config/rules_registry.yaml` — domain thresholds and scoring weights, editable without restarting anything
- `data/config/camera_registry.json` — CCTV camera locations for the crowd domain

---

## 1. Overview

```
.env                             ← LLM provider, API keys, scheduler settings
data/config/rules_registry.yaml  ← PM2.5 breakpoints, FRP levels, NDVI thresholds, …
data/config/camera_registry.json ← latitude/longitude for each CCTV camera
```

To get started:

```bash
cp .env.example .env
# Edit .env with your settings
```

The scheduler, ingestors, dashboard, and agents all read from `.env` at startup via `python-dotenv`. The rules registry is loaded at import time and can be reloaded at runtime without restarting any process (see Section 5).

---

## 2. LLM Provider

All agent calls go through `urban_platform/agents/llm_config.py`. No provider SDK is imported directly anywhere else — switching providers requires only `.env` changes.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | Provider preset name. One of: `ollama`, `openai`, `groq`, `together`, `openrouter`, `lmstudio`, `custom` |
| `LLM_BASE_URL` | *(provider default)* | Base URL of the OpenAI-compatible endpoint. Overrides the preset default. |
| `LLM_API_KEY` | `ollama` | API key. For local Ollama the value is ignored — any non-empty string works. |
| `LLM_MODEL` | *(provider default)* | Model name as the provider expects it. |
| `LLM_MAX_TOKENS` | `4096` | Maximum tokens per agent response. |
| `LLM_TEMPERATURE` | `0.1` | Sampling temperature. Low values (0.0–0.2) produce consistent analytical output. |
| `LLM_TIMEOUT` | `120` | HTTP timeout in seconds for each LLM request. |

### Provider reference table

| Provider | `LLM_PROVIDER` | Default base URL | Default model | API key needed? | Notes |
|---|---|---|---|---|---|
| Ollama (local) | `ollama` | `http://localhost:11434/v1` | `gpt-oss:20b-cloud` | No | Fully local — no network, no cost |
| OpenAI | `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` | Yes (`sk-…`) | `gpt-4o` for best quality |
| Groq | `groq` | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | Yes (`gsk_…`) | Free tier available; fastest hosted option |
| Together AI | `together` | `https://api.together.xyz/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | Yes | Open models at scale |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` | `google/gemini-flash-1.5` | Yes (`sk-or-…`) | One key for 200+ models incl. Claude, GPT, Gemini |
| LM Studio | `lmstudio` | `http://localhost:1234/v1` | *(set in UI)* | No | Start LM Studio → Local Server tab |
| Custom | `custom` | *(set `LLM_BASE_URL`)* | *(set `LLM_MODEL`)* | Maybe | Any server exposing `/v1/chat/completions` (vLLM, text-generation-webui, etc.) |

### .env snippets per provider

**Ollama — no API key, no cost**

```bash
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2
# First time: ollama pull llama3.2
```

Tool-calling models that work well with AirOS: `llama3.2`, `llama3.1`, `qwen2.5`, `mistral-nemo`, `gpt-oss:20b-cloud`.

**Groq — fastest hosted option, free tier**

```bash
LLM_PROVIDER=groq
LLM_API_KEY=gsk_your_key_here
LLM_MODEL=llama-3.3-70b-versatile
# LLM_BASE_URL is set automatically
```

**OpenAI**

```bash
LLM_PROVIDER=openai
LLM_API_KEY=sk-your_key_here
LLM_MODEL=gpt-4o-mini
```

**OpenRouter — single key for any model**

```bash
LLM_PROVIDER=openrouter
LLM_API_KEY=sk-or-your_key_here
LLM_MODEL=anthropic/claude-opus-4-5
```

**Custom endpoint (vLLM, text-generation-webui, etc.)**

```bash
LLM_PROVIDER=custom
LLM_BASE_URL=http://your-server:8000/v1
LLM_API_KEY=your-key-if-required
LLM_MODEL=mistralai/Mistral-7B-Instruct-v0.3
```

---

## 3. Scheduler

The scheduler runs as `python main.py --step scheduler`. It wakes on `SWEEP_INTERVAL_SEC`, checks each domain's watermark, and runs any domains that are due. After each ingest sweep it optionally runs the H3 Expert Agent on the top N cells.

| Variable | Default | Description |
|---|---|---|
| `SWEEP_INTERVAL_SEC` | `900` | Seconds between scheduler wake-ups. 900 = 15 minutes. This is how often the scheduler checks for due domains — individual domains have their own minimum cadences enforced via watermarks. |
| `SCHEDULER_CITIES` | `bangalore,hyderabad,mumbai,delhi,chennai,pune` | Comma-separated list of city IDs to include in each sweep. |
| `SCHEDULER_DOMAINS` | *(all domains)* | Comma-separated list of domain names to include. Omit to run all 14 domains. |
| `SCHEDULER_AGENT` | `true` | Set to `false` to disable the automatic post-ingest agent run. Useful when running the agent separately or when LLM is not configured. |
| `SCHEDULER_TOP_N` | `10` | Maximum cells the agent analyses per city per sweep. Higher values increase LLM cost and latency. |

**Domain cadences** (minimum gap between ingests, enforced independently of `SWEEP_INTERVAL_SEC`):

| Domain | Cadence | Source |
|---|---|---|
| air, fire, weather, crowd | 15 min | Near-real-time sensors / cameras |
| heat | 30 min | Open-Meteo centroid broadcast |
| flood, water, waste | 1 hour | Satellite revisit / hourly models |
| construction, green, noise | 6 hours | Satellite-derived, slow-changing |
| buildings, roads, drains | 90 days | OSM structural data |

Run only specific cities and domains:

```bash
# In .env
SCHEDULER_CITIES=bangalore,hyderabad
SCHEDULER_DOMAINS=air,fire,heat,weather
```

---

## 4. Data Source API Keys

AirOS uses a tiered model: several domains work with no API keys at all, others unlock higher-quality real sensor data when keys are provided.

### Domains that work without any API keys

| Domain | Free data source | Quality |
|---|---|---|
| weather | Open-Meteo (openmeteo.com) | Model estimate — wind, humidity, pressure, temperature, precipitation |
| heat | Open-Meteo centroid broadcast | Model estimate — reasonable city-scale proxy |
| air | Open-Meteo air quality variables | Model estimate — coarser than CPCB stations |
| buildings | OpenStreetMap (via Overpass API) | OSM structural footprints |
| roads | OpenStreetMap (via Overpass API) | OSM road network |
| drains | OpenStreetMap (via Overpass API) | OSM drainage network |
| noise | OSM + construction proximity model | Synthetic proximity model (no real sensors) |

### Optional API keys and what they unlock

| Key variable | Where to get it | Unlocks |
|---|---|---|
| `CPCB_API_KEY` | data.gov.in developer portal | **air** — real CPCB monitoring station data (PM2.5, PM10, NO2, SO2, CO, O3). Without this key the air domain falls back to Open-Meteo. |
| `FIRMS_API_KEY` | firms.modaps.eosdis.nasa.gov | **fire**, **waste** — NASA VIIRS/MODIS hotspot detections with Fire Radiative Power. Without this, fire and waste domains have no data and are skipped. |
| `GEE_PROJECT` + `GEE_SERVICE_ACCOUNT` + `GOOGLE_APPLICATION_CREDENTIALS` | Google Cloud Console | **heat** (MODIS LST), **flood** (GPM IMERG rainfall), **water** (Sentinel-2 water clarity), **construction** (SAR change detection), **green** (Sentinel-2 NDVI). Without GEE, these domains fall back to Open-Meteo or synthetic models. |
| `AQICN_TOKEN` | aqicn.org/api | **air** — AQICN-aggregated real station data (CPCB stations via aqicn proxy). Alternative to direct CPCB key. |

Setting up Google Earth Engine service account credentials:

```bash
# 1. Create service account in Google Cloud Console
# 2. Grant it "Earth Engine Resource Writer" role
# 3. Download JSON key file
GEE_PROJECT=your-gcp-project-id
GEE_SERVICE_ACCOUNT=airclimate-gee@your-project.iam.gserviceaccount.com
GOOGLE_APPLICATION_CREDENTIALS=/path/to/gee-service-account-key.json
```

### Web search (optional — used by the H3 Expert Agent)

The agent can cross-reference its findings against recent news and city reports. Web search is disabled by default.

| Variable | Value | Notes |
|---|---|---|
| `WEB_SEARCH_PROVIDER` | `none` | Default. Agent works without web search. |
| `WEB_SEARCH_PROVIDER` | `duckduckgo` | Free, no key. `pip install duckduckgo-search`. |
| `WEB_SEARCH_PROVIDER` | `tavily` | `pip install tavily-python`. Key from tavily.com. |
| `WEB_SEARCH_PROVIDER` | `brave` | Key from brave.com/search/api. No extra package. |
| `WEB_SEARCH_PROVIDER` | `serpapi` | `pip install google-search-results`. Key from serpapi.com. |
| `WEB_SEARCH_API_KEY` | your key | Required for tavily, brave, serpapi. Not needed for duckduckgo. |

```bash
# DuckDuckGo — free, no key needed
WEB_SEARCH_PROVIDER=duckduckgo

# Tavily — best results for urban/news queries
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_API_KEY=tvly-your_key_here
```

---

## 5. Rules Registry

`data/config/rules_registry.yaml` is the single source of truth for all domain thresholds, scoring weights, and detection floors. Changing this file affects how risk levels are computed across every domain.

### Structure

```yaml
_meta:
  version: "1.0"
  last_reviewed: "2026-05-09"
  reviewed_by: "Urban Operations Team"

domains:
  air:
    pm25_category_thresholds_ug_m3:
      severe:       250
      very_poor:    120
      poor:          90
      moderate:      60
      satisfactory:  30
    pm25_score_saturation_ug_m3: 120.0

  fire:
    frp_risk_levels_mw:
      severe:   100.0
      high:      30.0
      moderate:  10.0
      low:        5.0
    frp_score_saturation_mw: 500.0
    frp_detection_floor_mw:    5.0

  noise:
    nri_risk_levels:
      severe:   0.75
      high:     0.50
      moderate: 0.25
    # ... etc
```

### Viewing the current registry

```python
from urban_platform.rules import rules
print(rules.get("air", "pm25_category_thresholds_ug_m3"))
# {'severe': 250, 'very_poor': 120, 'poor': 90, 'moderate': 60, 'satisfactory': 30}
```

### Editing thresholds

Open `data/config/rules_registry.yaml` in any text editor. Changes take effect as follows:

- **Without restart:** call `rules.reload()` from a Python session or the dashboard.
- **With restart:** the updated file is loaded automatically at startup.

```python
# Apply changes live without restarting the scheduler
from urban_platform.rules import rules
rules.reload()
```

### City-level overrides

Add a `cities:` block under any domain to override specific values for a city. Values not listed under a city fall back to the global domain default.

```yaml
domains:
  crowd:
    gathering_threshold_per_km2: 500   # global default

    cities:
      mumbai:
        gathering_threshold_per_km2: 300   # denser population — lower threshold
      delhi:
        gathering_threshold_per_km2: 400

  air:
    pm25_category_thresholds_ug_m3:
      severe:       250                   # global default (CPCB standard)

    cities:
      delhi:
        pm25_category_thresholds_ug_m3:
          severe: 200                     # Delhi alert system uses a lower floor
```

Reading a city-specific value in code:

```python
from urban_platform.rules import rules

# Returns city override if present, else global default
threshold = rules.get("crowd", "gathering_threshold_per_km2", city_id="mumbai")
```

---

## 6. City Profile

Each city in AirOS is identified by a lowercase string `city_id`. The set of active city IDs is defined in `urban_platform/h3_knowledge/ingestor.py` under `_CITY_BBOXES`. Each entry maps a city ID to its bounding box (lat/lon min/max).

### Adding a new city

**Step 1.** Add the city's bounding box to `_CITY_BBOXES` in `urban_platform/h3_knowledge/ingestor.py`:

```python
_CITY_BBOXES: dict[str, dict] = {
    # ... existing cities ...
    "ahmedabad": {
        "lat_min": 22.924, "lon_min": 72.462,
        "lat_max": 23.121, "lon_max": 72.703,
    },
}
```

**Step 2.** Add the city ID to `ALL_CITIES` (it is derived from `_CITY_BBOXES.keys()` automatically if you use the dict directly).

**Step 3.** Activate the city in `.env`:

```bash
SCHEDULER_CITIES=bangalore,hyderabad,mumbai,delhi,chennai,pune,ahmedabad
```

**Step 4.** (Optional) Add city-level threshold overrides in `data/config/rules_registry.yaml` under the relevant domains.

### How city_id is used

- Every signal row and assessment row in the H3 Knowledge Store carries a `city_id` column. All queries are city-scoped.
- The dashboard filters by `city_id` at the top-level city selector.
- The rules registry resolves city-specific overrides using `city_id` as the lookup key.
- Notification recipients can be city-specific: `ALERT_RECIPIENTS_BANGALORE=…`

---

## 7. Camera Registry

`data/config/camera_registry.json` provides the geographic location of each CCTV camera. The crowd ingestor uses this to map camera observations to H3 cells.

### Format

```json
[
  {
    "entity_id":     "cam_blr_mg_road_01",
    "city_id":       "bangalore",
    "latitude":      12.9758,
    "longitude":     77.6005,
    "location_name": "MG Road junction — northbound",
    "active":        true
  },
  {
    "entity_id":     "cam_hyd_hitech_01",
    "city_id":       "hyderabad",
    "latitude":      17.4435,
    "longitude":     78.3772,
    "location_name": "HITEC City main entrance",
    "active":        true
  }
]
```

### Fields

| Field | Type | Description |
|---|---|---|
| `entity_id` | string | Unique camera identifier. Must match the `entity_id` in the observation store (`data/processed/observation_store.parquet`). |
| `city_id` | string | Must match an entry in `_CITY_BBOXES`. |
| `latitude` | float | Camera location latitude (WGS-84). |
| `longitude` | float | Camera location longitude (WGS-84). |
| `location_name` | string | Human-readable description shown in the dashboard. |
| `active` | bool | Set to `false` to exclude a camera from ingest without deleting the record. |

### How it works

The crowd ingestor reads this file at each 15-minute sweep, joins camera coordinates with the observation store (which contains `entity_id` → `people_count` readings), and maps each camera to its H3 cell using `h3.latlng_to_cell()`. Multiple cameras in the same H3 cell have their counts aggregated. Only cells with at least one active camera that reported in the window receive signals.

To add a new camera: add an entry to `camera_registry.json` and ensure the camera publisher writes `entity_id`-tagged rows to `data/processed/observation_store.parquet`.
