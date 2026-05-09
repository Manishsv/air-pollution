# AirOS Rules Registry

All domain thresholds, risk classification breakpoints, and operational parameters are managed in a central configurable registry. No pipeline code contains hardcoded risk values.

---

## Architecture

```
data/config/rules_registry.yaml      ← operator-editable YAML overlay
        │
        ▼
urban_platform/rules/registry.py     ← Python RulesRegistry class
        │  • _DEFAULTS dict (33 rules across 13 domains)
        │  • deep-merge YAML over defaults on first access
        │  • per-city override lookup
        │  • in-memory cache + reload()
        ▼
urban_platform/rules/__init__.py     ← module-level singleton: `rules`
        ▼
All 14 ingestors + 9 application pipelines
        call: _rules.get(domain, key, default=<original>)
```

---

## Using the Registry

```python
from urban_platform.rules import rules

# Simple lookup (uses Python default if key absent from YAML)
threshold = rules.get("crowd", "gathering_threshold_per_km2", default=500.0)

# City-specific override (checks cities.<city_id>.<key> first)
threshold = rules.get("crowd", "gathering_threshold_per_km2",
                       city_id="mumbai", default=500.0)

# Force reload after editing rules_registry.yaml (no restart needed)
rules.reload()

# Snapshot current effective values (for audit/debugging)
snapshot = rules.snapshot()
```

---

## What's in the Registry

### Air Quality
```yaml
air:
  pm25_good_threshold_ug_m3: 12
  pm25_moderate_threshold_ug_m3: 35
  pm25_poor_threshold_ug_m3: 55
  pm25_unhealthy_threshold_ug_m3: 150
  pm25_very_unhealthy_threshold_ug_m3: 250
  pm25_score_saturation_ug_m3: 120   # normalisation ceiling for scoring
  data_confidence: 0.80
```

### Flood
```yaml
flood:
  risk_levels:
    severe: 0.75
    high: 0.50
    moderate: 0.25
  sar_weight: 0.60
  slope_weight: 0.40
  proximity_radius_km: 0.75
  soil_saturation_floor: 0.05
  data_confidence: 0.70
```

### Heat
```yaml
heat:
  score_weights:
    uhi: 0.60
    green_deficit: 0.40
  high_risk_threshold: 0.65
  intervention_min_score: 0.50
  data_confidence: 0.75
```

### Water Quality
```yaml
water:
  wqi_risk_levels:
    severe: 0.75
    poor: 0.50
    moderate: 0.25
  dominant_issue_thresholds:
    foam_scum: 0.50
    algal_bloom: 0.50
  recommendation_wqi_floor: 0.30
```

### Fire
```yaml
fire:
  frp_detection_floor_mw: 5.0
  frp_score_saturation_mw: 500.0
  in_city_alert_frp_mw: 50.0
  frp_thresholds:
    severe: 200.0
    high: 50.0
    moderate: 10.0
  data_confidence: 0.80
```

### Crowd
```yaml
crowd:
  gathering_threshold_per_km2: 500.0   # GATHERING_ALERT = 1 above this
  index_saturation_per_km2: 2000.0     # CROWD_INDEX = 1.0 at this density
  observation_window_minutes: 20       # lookback window for people_count
  data_confidence: 0.90
  # Per-city overrides example:
  # cities:
  #   mumbai:
  #     gathering_threshold_per_km2: 800.0
```

### Roads
```yaml
roads:
  data_confidence: 0.85
```

### Buildings
```yaml
buildings:
  data_confidence: 0.75
```

### Drains
```yaml
drains:
  flood_drain_saturation_m_per_km2: 10000.0  # 1.0 capacity index at this density
  data_confidence: 0.65
```

### Waste
```yaml
waste:
  burn_frp_min_mw: 1.0
  burn_frp_max_mw: 100.0
  persistence_days_min: 3
  risk_levels:
    severe: 0.75
    high: 0.50
    moderate: 0.25
```

### Noise
```yaml
noise:
  nri_risk_levels:
    severe: 0.75
    high: 0.50
    moderate: 0.25
  score_weights:
    decibel: 0.60
    receptor: 0.40
  fire_saturation_frp: 200.0
  dominant_source_thresholds:
    traffic: 0.60
    construction: 0.60
    industrial: 0.50
  recommendation_nri_floor: 0.40
```

### Construction
```yaml
construction:
  cri_risk_levels:
    severe: 0.75
    high: 0.50
    moderate: 0.25
  bsi_threshold: 0.30
  no2_threshold_ug_m3: 40.0
  recommendation_min: 0.35
```

### Green Cover
```yaml
green:
  gcci_thresholds:
    significant_gain: 0.20
    gain: 0.05
    stable: -0.05
    loss: -0.20
  recommendation_min: 0.30
```

---

## City-Level Overrides

Add city-specific overrides under a `cities:` block inside any domain:

```yaml
crowd:
  gathering_threshold_per_km2: 500.0
  cities:
    mumbai:
      gathering_threshold_per_km2: 800.0   # denser city, higher baseline
    bangalore:
      gathering_threshold_per_km2: 400.0   # more aggressive monitoring
```

The registry checks `domain_data["cities"][city_id][key]` first, then the domain default, then the Python fallback.

---

## Editing Rules

1. Edit `data/config/rules_registry.yaml`
2. Call `rules.reload()` (or restart the process)
3. New thresholds take effect on the next ingest cycle
4. No pipeline code changes required

Rules changes are not tracked in the H3 Knowledge Store — if threshold changes cause risk level reclassifications, the new assessments will overwrite the day's existing assessments on the next ingest cycle (`ON CONFLICT DO UPDATE`).
