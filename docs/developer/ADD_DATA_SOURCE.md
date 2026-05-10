# Adding a New Data Source to AirOS

This guide walks you through adding a new data source — called a "driver" in AirOS — from scratch. By the end you will have signals appearing in the H3 Knowledge Store, a risk assessment per cell, and your domain showing up in the scheduler.

We use a fictional **Air Quality Microsensor Network** (`aqmsn`) as the worked example throughout. The same pattern applies to any domain: noise sensors, flood gauges, waste monitors, etc.

Estimated time: 2 hours for a developer familiar with Python.

---

## 1. Concepts

AirOS processes external data through four layers before it reaches the agent or dashboard.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  External world                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  Air Quality Microsensor Network API                             │   │
│  │  REST endpoint → JSON list of sensor readings (lat/lon + values) │   │
│  └────────────────────────┬─────────────────────────────────────────┘   │
└───────────────────────────┼─────────────────────────────────────────────┘
                            │ HTTP request
                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 1: Connector   urban_platform/connectors/air/aqmsn.py            │
│  Knows the API. Returns a plain list of dicts with lat/lon + readings.  │
│  No H3, no DB, no business logic.                                       │
└────────────────────────┬────────────────────────────────────────────────┘
                         │ list[dict]
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 2: Ingestor    urban_platform/h3_knowledge/air_ingestor.py       │
│  Maps lat/lon points to H3 cells (IDW or nearest-cell).                 │
│  Calls write_signals() and write_assessment() from writer.py.           │
└────────────────────────┬────────────────────────────────────────────────┘
                         │ SQL upserts
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 3: H3 Knowledge Store   data/h3/knowledge.sqlite (WAL mode)      │
│  Tables: h3_signals, h3_assessments, h3_packets, h3_insights            │
│  Deduplication: same cell + signal + hour → newer value wins.           │
└────────────────────────┬────────────────────────────────────────────────┘
                         │ SELECT queries
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 4: Agent + Dashboard                                             │
│  H3 Expert Agent reads signals to produce insights.                     │
│  Review Dashboard reads assessments to render the domain panel.         │
└─────────────────────────────────────────────────────────────────────────┘
```

Each layer has exactly one job. The connector is ignorant of H3. The ingestor is ignorant of the API. The store is ignorant of domain logic. This makes each piece testable and replaceable independently.

---

## 2. Step 1: Create the Connector

The connector's job is to call the external API and return a flat list of dicts. Each dict must contain `latitude`, `longitude`, and whatever sensor readings the source provides.

**File:** `urban_platform/connectors/air/aqmsn.py`

```python
"""
Air Quality Microsensor Network (AQMSN) connector.

Fetches real-time PM2.5 readings from low-cost microsensors across the city.
Returns a list of observation dicts ready for the air ingestor.

Environment variables:
    AQMSN_API_KEY   — API key for the AQMSN network (required)
    AQMSN_BASE_URL  — Override the default endpoint (optional)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://api.aqmsn.example.in/v2/readings"


def fetch_readings(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    *,
    timeout: int = 20,
) -> list[dict[str, Any]]:
    """Fetch current microsensor readings within a bounding box.

    Returns a list of dicts with at minimum:
        latitude    float
        longitude   float
        pm25_ugm3   float | None
        pm10_ugm3   float | None
        timestamp   ISO-8601 string
        sensor_id   str

    Returns an empty list on any error (caller skips gracefully).
    """
    api_key = os.environ.get("AQMSN_API_KEY", "")
    if not api_key:
        logger.warning("AQMSN_API_KEY not set — AQMSN connector disabled")
        return []

    base_url = os.environ.get("AQMSN_BASE_URL", _DEFAULT_URL)
    params = {
        "bbox":    f"{lat_min},{lon_min},{lat_max},{lon_max}",
        "api_key": api_key,
        "format":  "json",
    }

    try:
        resp = requests.get(base_url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("AQMSN API request failed: %s", exc)
        return []
    except ValueError as exc:
        logger.warning("AQMSN API returned invalid JSON: %s", exc)
        return []

    # Normalise each reading into a flat dict
    readings = []
    for sensor in data.get("sensors", []):
        try:
            readings.append({
                "sensor_id":  sensor["id"],
                "latitude":   float(sensor["lat"]),
                "longitude":  float(sensor["lon"]),
                "pm25_ugm3":  _safe_float(sensor.get("pm25")),
                "pm10_ugm3":  _safe_float(sensor.get("pm10")),
                "timestamp":  sensor.get("timestamp") or _now_iso(),
            })
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("Skipping malformed sensor record: %s", exc)
            continue

    logger.info("AQMSN: fetched %d sensor readings in bbox", len(readings))
    return readings


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

Key rules for connectors:
- Return an empty list (not `None`, not an exception) when the API is unavailable. The ingestor handles empty gracefully.
- Normalise field names to snake_case in the connector, not the ingestor.
- Never import anything from `urban_platform.h3_knowledge` inside a connector.

---

## 3. Step 2: Create or Update the Ingestor

The ingestor takes the connector's output and writes it to the H3 Knowledge Store. It maps lat/lon points to H3 cells, computes a risk level, and calls `write_signals()` and optionally `write_assessment()`.

For this example we are adding microsensor data as an additional source within the existing `air` domain. If you are adding a completely new domain (e.g., `microsensors`), create a new file `urban_platform/h3_knowledge/microsensor_ingestor.py` and follow the same pattern.

**File:** `urban_platform/h3_knowledge/air_ingestor.py` (or a new domain file)

```python
"""
AQMSN ingest function — maps microsensor readings to H3 cells.

Called by the main ingestor dispatch loop in ingestor.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import h3

from urban_platform.h3_knowledge.writer import (
    write_signals,
    write_assessment,
    upsert_metadata,
    record_ingest,
)

logger = logging.getLogger(__name__)

# H3 resolution — must match the rest of the platform (resolution 8 = ~0.74 km² cells)
_H3_RESOLUTION = 8


def ingest_aqmsn(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Fetch AQMSN readings and write signals + assessments to the H3 Knowledge Store.

    Args:
        city_id:  City identifier string (e.g. "bangalore").
        bbox:     Dict with lat_min, lon_min, lat_max, lon_max.
        force:    If True, ignore watermark and always ingest.

    Returns:
        Number of signal rows written (0 on skip or error).
    """
    from urban_platform.connectors.air.aqmsn import fetch_readings

    # --- 1. Fetch raw data from the connector ---
    readings = fetch_readings(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
    )

    if not readings:
        logger.info("[%s/aqmsn] No readings returned — skipping.", city_id)
        record_ingest(city_id=city_id, domain="air", rows_written=0,
                      status="partial", error_msg="no aqmsn readings")
        return 0

    # --- 2. Map readings to H3 cells ---
    # Simple nearest-cell mapping: one reading → one H3 cell.
    # For denser sensor networks, use IDW (inverse distance weighting) from
    # urban_platform.h3_knowledge.geo_agg.idw_to_h3_cells() instead.
    signal_rows = []

    for r in readings:
        lat  = r.get("latitude")
        lon  = r.get("longitude")
        pm25 = r.get("pm25_ugm3")

        if lat is None or lon is None or pm25 is None:
            continue  # skip incomplete readings

        # Convert lat/lon to H3 cell ID at the platform resolution
        h3_id = h3.latlng_to_cell(lat, lon, _H3_RESOLUTION)

        # Register the cell's coordinates in h3_metadata (idempotent)
        upsert_metadata(
            h3_id=h3_id,
            city_id=city_id,
            resolution=_H3_RESOLUTION,
            centroid_lat=lat,
            centroid_lon=lon,
        )

        # Build the signal row — all fields shown explicitly
        signal_rows.append({
            "h3_id":       h3_id,
            "city_id":     city_id,
            "domain":      "air",
            "signal":      "PM25",
            "value":       float(pm25),
            "unit":        "µg/m³",
            "source":      "aqmsn",          # used to infer data_quality automatically
            "level":       1,
            "observed_at": r.get("timestamp") or _now_iso(),
            # data_quality is inferred from source="aqmsn" → "unknown"
            # Override explicitly if you know the quality tier:
            # "data_quality": "real_station",
        })

        # --- 3. Write per-cell assessments ---
        risk = _pm25_to_risk(pm25)
        write_assessment(
            h3_id=h3_id,
            city_id=city_id,
            domain="air",
            risk_level=risk,
            primary_index="PM25",
            primary_value=float(pm25),
            dominant_issue=f"PM2.5 {pm25:.1f} µg/m³ ({risk})",
            summary={
                "sensor_id":  r.get("sensor_id"),
                "pm25_ugm3":  pm25,
                "pm10_ugm3":  r.get("pm10_ugm3"),
                "source":     "aqmsn",
            },
        )

    if not signal_rows:
        logger.info("[%s/aqmsn] Readings had no usable PM2.5 values.", city_id)
        record_ingest(city_id=city_id, domain="air", rows_written=0, status="partial")
        return 0

    # --- 4. Write signals (upsert — deduped by h3_id + signal + hour_bucket) ---
    written = write_signals(
        signal_rows,
        city_id=city_id,
        domain="air",
        source="aqmsn",    # default source when a row doesn't specify one
    )

    logger.info("[%s/aqmsn] Wrote %d signal rows from %d sensor readings",
                city_id, written, len(readings))
    record_ingest(city_id=city_id, domain="air", rows_written=written)
    return written


def _pm25_to_risk(pm25: float) -> str:
    """Map PM2.5 (µg/m³) to a canonical risk level.

    Uses CPCB 2014 breakpoints. To make this configurable, read thresholds
    from the rules registry:

        from urban_platform.rules import rules
        thresholds = rules.get("air", "pm25_category_thresholds_ug_m3")
    """
    if pm25 >= 250:
        return "severe"
    if pm25 >= 120:
        return "high"
    if pm25 >= 90:
        return "high"
    if pm25 >= 60:
        return "moderate"
    if pm25 >= 30:
        return "low"
    return "good"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

### write_signals() field reference

Every dict in the `rows` list passed to `write_signals()` supports these fields:

| Field | Required | Type | Description |
|---|---|---|---|
| `h3_id` | Yes | str | H3 cell ID at resolution 8 |
| `signal` | Yes | str | Signal name in UPPER_SNAKE_CASE (e.g. `PM25`, `AQI`, `FRP`, `NRI`) |
| `value` | Yes | float | Numeric reading |
| `city_id` | No | str | Overrides the `city_id` parameter if different |
| `domain` | No | str | Overrides the `domain` parameter if different |
| `unit` | No | str | Unit string (e.g. `µg/m³`, `index`, `MW`, `degC`) |
| `source` | No | str | Source identifier; used to auto-infer `data_quality` |
| `level` | No | int | Signal level (1=raw, 2=derived). Default: 1 |
| `observed_at` | No | str | ISO-8601 UTC timestamp. Default: now |
| `data_quality` | No | str | Override auto-inferred quality. Values: `real_station`, `satellite_derived`, `model_estimate`, `unknown` |

### write_assessment() field reference

| Field | Required | Type | Description |
|---|---|---|---|
| `h3_id` | Yes | str | H3 cell ID |
| `city_id` | Yes | str | City identifier |
| `domain` | Yes | str | Domain name |
| `risk_level` | Yes | str | One of: `good`, `low`, `moderate`, `high`, `severe` |
| `primary_index` | No | str | Name of the leading indicator (e.g. `PM25`) |
| `primary_value` | No | float | Value of the leading indicator |
| `dominant_issue` | No | str | Short human-readable description |
| `summary` | No | dict | Additional context stored as JSON |

---

## 4. Step 3: Register the Domain in the Ingestor Dispatch

**File:** `urban_platform/h3_knowledge/ingestor.py`

Three places need updating.

### 3a. Add to ALL_DOMAINS

```python
ALL_DOMAINS = [
    "air", "fire", "heat", "flood", "water", "waste", "construction",
    "green", "noise", "weather", "buildings", "roads", "drains", "crowd",
    "aqmsn",   # <-- add this
]
```

### 3b. Add to the cadence table

```python
_DOMAIN_INTERVAL: dict[str, timedelta] = {
    # ... existing entries ...
    "aqmsn": timedelta(minutes=15),   # <-- add this
}
```

Choose a cadence appropriate to your data source's update frequency. Common values: 15 min (real-time sensors), 1 hour (API-polled feeds), 6 hours (satellite-derived).

### 3c. Add a dispatch wrapper function and register it

Add a wrapper function near the other `_ingest_*` functions:

```python
def _ingest_aqmsn(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("aqmsn", city_id, force)
    from urban_platform.h3_knowledge.air_ingestor import ingest_aqmsn
    return ingest_aqmsn(city_id, bbox, force=force)
```

Then register it in `_DOMAIN_FN`:

```python
_DOMAIN_FN: dict[str, Callable] = {
    # ... existing entries ...
    "aqmsn": _ingest_aqmsn,   # <-- add this
}
```

The `_check_interval()` call at the top of the wrapper enforces the watermark: it raises `_TooRecentError` if the domain was ingested too recently, and the main loop catches that exception and silently skips the domain. Pass `force=True` to override.

---

## 5. Step 4: Add Thresholds to the Rules Registry

**File:** `data/config/rules_registry.yaml`

Add a block for your domain. If you are adding a new source within an existing domain (like `aqmsn` within `air`), you can extend the existing `air` block or leave it as-is if the existing breakpoints are correct.

For a brand-new domain, add a new top-level block:

```yaml
domains:

  # ... existing domains ...

  # ── Air Quality Microsensor Network ───────────────────────────────────────
  # Low-cost sensors — use the same CPCB PM2.5 breakpoints as the main air domain.
  # Override here if microsensor calibration requires different thresholds.
  aqmsn:
    pm25_risk_thresholds_ug_m3:
      severe:   250
      high:     120
      moderate:  60
      low:       30
    # PM2.5 value where the normalised score saturates at 1.0
    pm25_score_saturation_ug_m3: 120.0
    # data_confidence for this source (0–1).
    # Low-cost sensors are less accurate than reference monitors.
    data_confidence: 0.60

    # Per-city overrides
    cities:
      delhi:
        pm25_risk_thresholds_ug_m3:
          severe: 200   # tighter alert for high-pollution city
```

Reading your thresholds in the ingestor:

```python
from urban_platform.rules import rules

thresholds = rules.get("aqmsn", "pm25_risk_thresholds_ug_m3", city_id=city_id)
# Returns city override if present, else global default
# Returns None if the key doesn't exist — always provide a fallback

def _pm25_to_risk(pm25: float, city_id: str) -> str:
    t = rules.get("aqmsn", "pm25_risk_thresholds_ug_m3", city_id=city_id) or {
        "severe": 250, "high": 120, "moderate": 60, "low": 30,
    }
    if pm25 >= t.get("severe", 250): return "severe"
    if pm25 >= t.get("high",   120): return "high"
    if pm25 >= t.get("moderate", 60): return "moderate"
    if pm25 >= t.get("low",     30): return "low"
    return "good"
```

Changes to `rules_registry.yaml` apply immediately when `rules.reload()` is called — no restart required.

---

## 6. Step 5: Add a Dashboard Panel (Optional)

**File:** `review_dashboard/components/aqmsn_panel.py`

The dashboard automatically picks up new assessments from any domain, but adding a dedicated panel gives you domain-specific controls and visualisations.

A minimal panel follows the same pattern as every other panel in `review_dashboard/components/`:

```python
"""
AQMSN dashboard panel — shows microsensor PM2.5 readings on the H3 map.
"""
import streamlit as st
from urban_platform.h3_knowledge.reader import read_assessments, read_signals


def render_aqmsn_panel(city_id: str) -> None:
    st.subheader("Air Quality Microsensor Network")

    # Load assessments for this city and domain
    assessments = read_assessments(city_id=city_id, domain="aqmsn")
    if assessments.empty:
        st.info("No AQMSN data available for this city.")
        return

    # Load the raw PM25 signals
    signals = read_signals(city_id=city_id, domain="aqmsn", signal="PM25")

    # --- Risk summary metrics ---
    col1, col2, col3 = st.columns(3)
    with col1:
        n_severe = len(assessments[assessments["risk_level"] == "severe"])
        st.metric("Severe cells", n_severe)
    with col2:
        n_high = len(assessments[assessments["risk_level"] == "high"])
        st.metric("High cells", n_high)
    with col3:
        avg_pm25 = signals["value"].mean() if not signals.empty else 0
        st.metric("Mean PM2.5 (µg/m³)", f"{avg_pm25:.1f}")

    # --- Map (reuse the shared H3 map helper) ---
    from review_dashboard.map_utils import render_h3_map
    render_h3_map(assessments, risk_col="risk_level", tooltip_col="dominant_issue")

    # --- Raw signal table ---
    with st.expander("Raw sensor readings"):
        st.dataframe(signals[["h3_id", "signal", "value", "unit",
                               "source", "data_quality", "observed_at"]])
```

To wire the panel into the main dashboard, import and call `render_aqmsn_panel()` from the appropriate tab in `review_dashboard/app.py`.

---

## 7. Step 6: Test It

### Run only your domain's ingestor

```bash
# Single city, single domain
python -m urban_platform.h3_knowledge.ingestor \
    --cities bangalore \
    --domains aqmsn

# Force re-ingest even if the watermark says it ran recently
python -m urban_platform.h3_knowledge.ingestor \
    --cities bangalore \
    --domains aqmsn \
    --force
```

The CLI prints a results table:

```
H3 Knowledge Store ingestor
  Cities : bangalore
  Domains: aqmsn
  Force  : False

Results:
  bangalore    aqmsn          142 rows

Total rows written: 142
```

### Check that signals appeared in the store

```python
from urban_platform.h3_knowledge.store import H3KnowledgeStore

store = H3KnowledgeStore.get()

# Check signals
rows = store.fetchdf(
    "SELECT h3_id, signal, value, unit, source, data_quality, observed_at "
    "FROM h3_signals "
    "WHERE city_id = ? AND domain = ? "
    "ORDER BY observed_at DESC LIMIT 10",
    ["bangalore", "aqmsn"],
)
print(rows)

# Check assessments
assessments = store.fetchdf(
    "SELECT h3_id, risk_level, primary_index, primary_value, dominant_issue "
    "FROM h3_assessments "
    "WHERE city_id = ? AND domain = ? "
    "ORDER BY assessed_at DESC LIMIT 10",
    ["bangalore", "aqmsn"],
)
print(assessments)

# Check ingest log
log = store.fetchdf(
    "SELECT city_id, domain, last_ingested_at, rows_written, status, error_msg "
    "FROM h3_ingest_log WHERE domain = ?",
    ["aqmsn"],
)
print(log)
```

### Run a quick end-to-end smoke test

```python
# Quick smoke test — paste into a Python REPL or a test script
import os
os.environ["AQMSN_API_KEY"] = "your-test-key-here"

from urban_platform.h3_knowledge.ingestor import run

results = run(cities=["bangalore"], domains=["aqmsn"], force=True)
print(results)
# Expected: {"bangalore": {"aqmsn": <N>}}   where N > 0
```

If `N = 0` with `status=partial`, check the ingest log for the `error_msg` column — it will tell you exactly what was skipped and why.

---

## 8. Data Quality Tags

The `data_quality` column on every signal row tells the agent how much to trust a reading. It is set automatically based on the `source` string — you do not need to set it explicitly unless you want to override the default.

### How auto-inference works

`write_signals()` calls `_infer_data_quality(source)` which does an exact match then a prefix match against the lookup table below.

```python
# From urban_platform/h3_knowledge/writer.py

_SOURCE_DATA_QUALITY: dict[str, str] = {
    # Real monitoring stations
    "cpcb":      "real_station",
    "openaq":    "real_station",
    "iudx":      "real_station",
    # Satellite / remote sensing
    "gee":       "satellite_derived",
    "firms":     "satellite_derived",
    "modis":     "satellite_derived",
    "sentinel":  "satellite_derived",
    "viirs":     "satellite_derived",
    # Numerical weather / reanalysis models
    "openmeteo": "model_estimate",
    "imd":       "model_estimate",
    "era5":      "model_estimate",
    "pipeline":  "model_estimate",
}
```

Any source not in this table gets `data_quality = "unknown"`.

### The four quality tiers

| `data_quality` | What it means | Examples |
|---|---|---|
| `real_station` | Physical sensor co-located with the measurement. Highest trust. | CPCB reference monitors, IUDX IoT sensors, OpenAQ |
| `satellite_derived` | Remote sensing product. Direct observation but at coarser resolution. | FIRMS hotspots, GEE NDVI/LST, Sentinel SAR |
| `model_estimate` | Numerical model or reanalysis output. Good coverage, lower spatial resolution. | Open-Meteo, IMD NWP, ERA5 |
| `unknown` | Source not in the lookup table. Agent treats this as lowest-trust. | Any new source until you add it |

### Adding your source to the lookup table

For the AQMSN example, `source="aqmsn"` resolves to `"unknown"` because `aqmsn` is not in the table. Since these are real sensors (even if low-cost), add it to the lookup table in `writer.py`:

```python
_SOURCE_DATA_QUALITY: dict[str, str] = {
    # Real monitoring stations
    "cpcb":      "real_station",
    "openaq":    "real_station",
    "iudx":      "real_station",
    "aqmsn":     "real_station",    # <-- add your source here
    # ...
}
```

Alternatively, override per-row in the ingestor:

```python
signal_rows.append({
    "h3_id":        h3_id,
    "signal":       "PM25",
    "value":        float(pm25),
    "source":       "aqmsn",
    "data_quality": "real_station",   # explicit override — skips auto-inference
    # ...
})
```

The H3 Expert Agent reads `data_quality` when building its analysis context and explicitly qualifies its confidence based on the tier. `real_station` signals receive higher weight in the agent's reasoning than `model_estimate` signals for the same cell and domain.
