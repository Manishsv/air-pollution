# Ward Decision Catalogue — Climate Domains

## 1. Purpose

This document defines the decision support structure for AirOS climate domains
(air quality, flood, heat) at ward level and up the administrative hierarchy.

It answers: **given a signal, what decision does the system surface, to whom,
and what action does it recommend?**

This is the functional specification for decision packets, dashboard alerts,
and the escalation model. Every pipeline feature, every dashboard panel, and
every decision packet schema should be traceable to a row in this catalogue.

---

## 2. Decision anatomy

Every decision the system surfaces has five components:

| Component | Definition |
|-----------|-----------|
| **Trigger** | The signal threshold or pattern that activates the decision |
| **Probable cause** | What the system infers from the signal (source attribution) |
| **Recommended action** | What the decision holder should do, with or without escalation |
| **Escalation condition** | When the ward engineer cannot resolve it alone |
| **Evidence bundle** | What the decision packet contains to make the action auditable |

---

## 3. Administrative hierarchy

```
Ward engineer           ← lowest authority, closest to ground
    ↓ escalates
Zonal officer           ← coordinates 3–10 wards, allocates shared resources
    ↓ escalates
City commissioner       ← policy, cross-department, budget
    ↓ escalates
State / national        ← out of AirOS scope for now
```

**Design principle:** the system should always try to surface a decision at
the lowest level that has the authority to act. Escalation is triggered only
when the action required exceeds that authority or when the pattern spans
multiple wards.

---

## 4. Air quality decisions

### 4.1 Triggers

| Trigger ID | Signal | Threshold | Duration |
|------------|--------|-----------|---------|
| AQ-T1 | AQI score | > 0.60 (≈ AQI 150, Unhealthy) | Sustained ≥ 2 hours |
| AQ-T2 | AQI score | Doubles within 1 hour | Sudden spike |
| AQ-T3 | AQI score | > 0.40 (≈ AQI 100, Moderate) | 3+ consecutive days |
| AQ-T4 | PM2.5 | > 60 µg/m³ | Any reading |

### 4.2 Source attribution (probable cause by pattern)

| Pattern | Most probable cause | Confidence |
|---------|-------------------|-----------|
| Spike 5–8am, residential zone | Open waste burning / crop residue | High |
| AM + PM peaks, road corridor | Traffic emissions (idling, diesel) | High |
| Sustained, industrial zone proximity | Industrial point source | Medium |
| Post-construction-day spike | Dust from exposed earth / demolition | Medium |
| Spike with wind direction from adjacent ward | Upwind cross-ward source | Medium |
| Gradual multi-day rise, no local source | Regional / seasonal accumulation | Low |

### 4.3 Ward-level decisions

| Decision ID | Trigger | Probable cause | Recommended action | Authority |
|-------------|---------|---------------|-------------------|-----------|
| AQ-D1 | AQ-T2, 5–8am residential | Waste burning | Dispatch sanitation supervisor to locate and stop burning; issue no-burning notice | Ward engineer |
| AQ-D2 | AQ-T1, road corridor | Traffic | Coordinate with traffic police on vehicle idling at identified junction | Ward engineer + traffic police |
| AQ-D3 | AQ-T1, construction site | Dust | Order water sprinkling on site; check dust suppression compliance | Ward engineer |
| AQ-D4 | AQ-T3 (chronic) | Any | File pattern report for zonal review; recommend collection schedule review | Ward engineer → zonal |
| AQ-D5 | AQ-T1, wind source | Cross-ward | Flag to zonal officer; cannot act on source outside ward boundary | Escalate |

### 4.4 Escalation conditions

| Condition | Escalate to | Reason |
|-----------|------------|--------|
| Source is outside ward boundary | Zonal officer | Authority does not extend across ward boundary |
| Construction has city permit | Building department via commissioner | Ward engineer cannot halt permitted work |
| Chronic pattern ≥ 3 days | Zonal officer | Requires waste collection schedule change |
| Health incidents reported (hospital admissions correlating with spike) | Commissioner + health department | Public health emergency protocol |
| Industrial source with valid emission permit | Pollution control board | Regulatory action outside municipal authority |

### 4.5 Evidence bundle (per decision packet)

```
{
  "trigger_id": "AQ-T2",
  "ward_id": "bangalore_demo_w07",
  "timestamp_bucket": "2026-05-07T06:00",
  "signal": {
    "aqi_score_current": 0.74,
    "aqi_score_1hr_ago": 0.35,
    "pm25_ugm3": 87.4,
    "source_attribution": "waste_burning",
    "attribution_confidence": "high",
    "attribution_basis": "time_pattern_5am_residential"
  },
  "recommended_action": "AQ-D1",
  "action_detail": "Dispatch sanitation supervisor to H3 cluster [8a283082a657fff, ...]",
  "escalation_required": false,
  "evidence": {
    "aqi_time_series_6h": [...],
    "hotspot_h3_cells": [...],
    "wind_direction": "SW",
    "nearest_waste_collection_point": "500m NE",
    "last_collection_date": "2026-05-05"
  }
}
```

### 4.6 Zonal officer view (pattern across wards)

| Pattern | Zonal decision |
|---------|---------------|
| 3+ wards spike at same time, same cause | Coordinate single enforcement sweep across wards |
| Chronic AQ-D4 filings from same zone | Escalate waste collection frequency to commissioner |
| Cross-ward wind source identified | Direct source ward engineer to act; notify affected ward |
| Industrial cluster affecting multiple wards | Engage pollution control board |

### 4.7 Commissioner / city level

| Pattern | City-level decision |
|---------|-------------------|
| City-wide AQI elevated for 3+ days | Issue public air quality advisory; activate health protocol |
| Multiple industrial complaints | Review industrial emission permits; targeted inspection |
| Waste burning is systemic | Revise city-wide waste collection schedule and frequency |
| Construction dust widespread | Mandate dust suppression standards in all active permits |

---

## 5. Flood decisions

### 5.1 Triggers

| Trigger ID | Signal | Threshold | Duration |
|------------|--------|-----------|---------|
| FL-T1 | Rainfall intensity | > 30mm/hr | Sustained ≥ 30 min |
| FL-T2 | Rainfall accumulation | > 50mm | In any 3-hour window |
| FL-T3 | Flood risk score | > 0.70 | For any ward H3 cell |
| FL-T4 | Complaint cluster | ≥ 3 waterlogging complaints | Same ward within 1 hour |
| FL-T5 | Repeat hotspot | Same location triggered | 2+ times this season |

### 5.2 Source attribution

| Pattern | Most probable cause | Confidence |
|---------|-------------------|-----------|
| Hotspot coincides with known drain asset | Drain blockage / silting | High |
| New hotspot adjacent to recent construction | Unauthorized drain obstruction | High |
| Widespread, multiple wards, heavy rain | Capacity exceeded — systemic deficit | High |
| Single-point hotspot, no rain increase | Blocked inlet / illegal dump | Medium |
| Repeat seasonal hotspot | Structural drainage deficit | High |

### 5.3 Ward-level decisions

| Decision ID | Trigger | Probable cause | Recommended action | Authority |
|-------------|---------|---------------|-------------------|-----------|
| FL-D1 | FL-T3 + FL-T4, known drain | Blockage | Dispatch desilting crew to drain segment; photograph and log | Ward engineer |
| FL-D2 | FL-T4, construction adjacent | Obstruction | Issue stop-work notice; clear obstruction; file violation | Ward engineer |
| FL-D3 | FL-T1 + FL-T3, vulnerable settlement | Overland flow | Deploy sandbags/pumps to identified points; issue advisory | Ward engineer |
| FL-D4 | FL-T5 (repeat) | Structural deficit | File capital works request for drain upgrade | Ward engineer → zonal |
| FL-D5 | FL-T2, widespread | Capacity exceeded | Close roads; coordinate with zonal for pump reallocation | Escalate |

### 5.4 Escalation conditions

| Condition | Escalate to | Reason |
|-----------|------------|--------|
| Waterlogging persists > 4 hours after crew deployed | Zonal engineer | Systemic, not a blockage — needs engineering assessment |
| Trunk drain capacity exceeded | City drainage department | Trunk infrastructure is city-maintained, not ward |
| Unauthorized construction blocking drain | Building violations department | Legal action required |
| Multiple wards affected simultaneously | Zonal officer | Pump trucks and crews must be reallocated across wards |
| Vulnerable households at imminent risk | Emergency services + welfare | Evacuation protocol |

### 5.5 Evidence bundle (per decision packet)

```
{
  "trigger_id": "FL-T3",
  "ward_id": "bangalore_demo_w12",
  "timestamp_bucket": "2026-05-07T14:00",
  "signal": {
    "flood_risk_score": 0.82,
    "rainfall_mm_per_hr": 38.5,
    "rainfall_accumulation_3h_mm": 64.2,
    "complaint_count_1h": 5,
    "source_attribution": "drain_blockage",
    "attribution_confidence": "high"
  },
  "recommended_action": "FL-D1",
  "action_detail": "Dispatch crew to drain segment D-102 (last desilt: 2026-01-15)",
  "escalation_required": false,
  "evidence": {
    "drain_asset": {
      "drain_id": "D-102",
      "length_m": 240,
      "capacity_m3_per_s": 0.8,
      "last_desilt_date": "2026-01-15",
      "condition": "silted"
    },
    "hotspot_h3_cells": [...],
    "complaint_locations": [...],
    "rainfall_time_series_3h": [...],
    "is_repeat_hotspot": true,
    "repeat_count_this_season": 2
  }
}
```

### 5.6 Zonal officer view

| Pattern | Zonal decision |
|---------|---------------|
| 3+ wards requesting pump trucks simultaneously | Triage and allocate shared pump resources by severity |
| Same drain segment triggers across ward boundary | Commission cross-ward drain inspection |
| Repeat FL-D4 filings from same zone | Prioritise zone for drain upgrade capital works budget |
| Major rainfall event forecast | Pre-position crews and pumps at known hotspots |

### 5.7 Commissioner / city level

| Pattern | City-level decision |
|---------|-------------------|
| Systemic capacity failures across city | Commission drainage master plan review |
| Repeat vulnerable settlement flooding | Emergency resettlement or flood-proof infrastructure |
| Unauthorized construction patterns | Strengthen building permit enforcement citywide |
| Trunk drain failure | Emergency capital works; inter-department coordination |

---

## 6. Heat decisions

### 6.1 Triggers

| Trigger ID | Signal | Threshold | Duration |
|------------|--------|-----------|---------|
| HT-T1 | Apparent temperature | > 40°C | Sustained ≥ 3 hours |
| HT-T2 | Heat risk score | > 0.75 | For ward |
| HT-T3 | UHI delta | > 4°C vs city average | Any reading |
| HT-T4 | Early-season heat | Apparent temp > 38°C | Before June (low acclimatisation) |
| HT-T5 | Consecutive hot days | Heat risk > 0.60 | 3+ consecutive days |

### 6.2 Source attribution

| Pattern | Most probable cause | Confidence |
|---------|-------------------|-----------|
| High UHI delta + low NDVI | Structural urban heat island (green cover deficit) | High |
| Spike on peak construction day | Heat absorption from exposed surfaces | Medium |
| Localised hotspot near industrial unit | Process heat from industrial activity | Medium |
| Sustained ward-wide, no localised source | Systemic: albedo + density + no green cover | High |
| Night-time temperatures not dropping | Heat stored in dense built fabric | High |

### 6.3 Ward-level decisions

| Decision ID | Trigger | Probable cause | Recommended action | Authority |
|-------------|---------|---------------|-------------------|-----------|
| HT-D1 | HT-T1 + HT-T4 | Any | Activate nearest cooling centre (school, community hall); announce to ward | Ward engineer |
| HT-D2 | HT-T1, construction sites | Surface heat | Issue mandatory rest advisory 12–3pm; deploy water stations at sites | Ward engineer |
| HT-D3 | HT-T1, outdoor vendor zone | Exposure | Deploy mobile water distribution; coordinate with market association | Ward engineer |
| HT-D4 | HT-T3 (high UHI delta) | Green deficit | Initiate ward tree-planting request; flag for cool zone designation | Ward engineer → zonal |
| HT-D5 | HT-T5 (chronic) | Systemic | ASHA worker check-ins for elderly and infants; coordinate with PHC | Ward engineer + health |

### 6.4 Escalation conditions

| Condition | Escalate to | Reason |
|-----------|------------|--------|
| Heat wave forecast ≥ 3 days | Commissioner — heat action plan | City-wide protocol activation |
| Construction site non-compliance with rest advisory | Labour department | Enforcement requires labour authority |
| Heat stroke cases reported | Hospital + health department | Medical emergency coordination |
| Cooling centre at capacity | Zonal officer | Need additional space authorised |
| Structural UHI requires green cover intervention | Parks department + budget | Capital works beyond ward authority |

### 6.5 Evidence bundle (per decision packet)

```
{
  "trigger_id": "HT-T1",
  "ward_id": "delhi_demo_w03",
  "timestamp_bucket": "2026-05-07T13:00",
  "signal": {
    "apparent_temperature_c": 43.2,
    "heat_risk_score": 0.81,
    "uhi_delta_c": 5.1,
    "green_cover_deficit": 0.68,
    "source_attribution": "uhi_green_deficit",
    "attribution_confidence": "high"
  },
  "recommended_action": "HT-D1",
  "action_detail": "Activate cooling centre at Ward Community Hall (capacity 120); deploy 3 water stations at outdoor vendor zone",
  "escalation_required": false,
  "evidence": {
    "apparent_temp_time_series_6h": [...],
    "cooling_centres": [
      {"name": "Ward Community Hall", "capacity": 120, "distance_m": 400, "status": "available"}
    ],
    "outdoor_worker_estimate": 340,
    "vulnerable_household_count": 85,
    "nearest_phc": "PHC Rajajinagar, 1.2km"
  }
}
```

### 6.6 Zonal officer view

| Pattern | Zonal decision |
|---------|---------------|
| Multiple wards activating cooling centres simultaneously | Coordinate capacity; open additional sites if needed |
| Chronic HT-D4 filings (green deficit) from same zone | Prioritise zone for tree planting programme |
| Labour non-compliance widespread | Coordinate labour department sweep across zone |
| Heat wave forecast | Pre-position water distribution vehicles; brief ward engineers |

### 6.7 Commissioner / city level

| Pattern | City-level decision |
|---------|-------------------|
| City-wide heat wave (≥ 3 days forecast) | Activate city heat action plan; school closures; public advisory |
| Systemic UHI in multiple zones | Green cover master plan; albedo standards for new construction |
| Heat-related hospital admissions rising | Health emergency protocol; additional ambulance deployment |
| Industrial process heat contributing | Industrial zone review; buffer zone enforcement |

---

## 7. Cross-domain decisions

Some decisions require signals from more than one domain. These are the highest-value
interventions because they reveal systemic problems invisible in any single domain.

| Decision ID | Trigger | Insight | Recommended action | Level |
|-------------|---------|---------|-------------------|-------|
| XD-D1 | High AQI + High flood risk + High heat (same ward) | Ward under compounding climate stress | Elevate ward to priority intervention list; multi-department briefing | Commissioner |
| XD-D2 | Flood event → AQI spike next day | Contaminated debris burning post-flood | Coordinate sanitation + air enforcement simultaneously | Ward engineer + zonal |
| XD-D3 | Heat spike → AQI spike (same location) | Industrial process releasing both heat and emissions | Joint inspection: pollution control + labour | Zonal → commissioner |
| XD-D4 | Flood risk high + Economic vulnerability high | Informal market ward at compounded risk | Prioritise drain upgrade + economic continuity support | Commissioner |
| XD-D5 | Heat risk + Outdoor worker density | Livelihood at risk from heat | Targeted enforcement of rest mandates + wage protection advisory | Ward engineer |

---

## 8. Decision packet schema (common fields)

All decision packets, regardless of domain, share this base structure:

```
{
  // Identity
  "packet_id":          string (UUID),
  "domain":             "air" | "flood" | "heat" | "cross_domain",
  "decision_id":        string (e.g. "AQ-D1"),
  "trigger_id":         string (e.g. "AQ-T2"),

  // Spatial + temporal
  "ward_id":            string,
  "city_id":            string,
  "timestamp_bucket":   ISO-8601 string,
  "generated_at":       ISO-8601 string,

  // Signal
  "signal":             { domain-specific key-value scores },
  "source_attribution": string,
  "attribution_confidence": "high" | "medium" | "low",

  // Decision
  "recommended_action": string (decision ID),
  "action_detail":      string (human-readable instruction),
  "urgency":            "immediate" | "within_4h" | "within_24h" | "plan",
  "escalation_required": boolean,
  "escalate_to":        string | null,

  // Evidence
  "evidence":           { domain-specific supporting data },
  "data_sources":       [ { source, freshness, quality_flag } ],
  "computation_trace":  { pipeline steps, model versions },

  // Lifecycle
  "status":             "open" | "acknowledged" | "actioned" | "escalated" | "resolved",
  "actioned_by":        string | null,
  "actioned_at":        ISO-8601 | null,
  "outcome_observation": string | null
}
```

---

## 9. What the dashboard needs to show

For the ward engineer:
- **Active decisions for my ward** — sorted by urgency, with one-tap acknowledge and action log
- **Signal trend** — last 6 hours for each domain, so the engineer sees whether things are improving
- **Source attribution** — plain language: "Likely waste burning at coordinates X based on time pattern"
- **Action history** — what was done, when, and whether it resolved the issue

For the zonal officer:
- **Ward heat map** — which wards in my zone have open decisions, by severity
- **Resource conflicts** — two wards both requesting same pump truck at the same time
- **Pattern view** — same cause triggering across multiple wards = systemic, not isolated
- **Escalation queue** — decisions that ward engineers have flagged for zonal action

For the commissioner:
- **City-wide risk summary** — how many wards are at each severity level, by domain
- **Systemic patterns** — causes that appear in 5+ wards = policy decision, not operational
- **Intervention ROI** — which wards have the highest impact from a given budget allocation
- **Outcome tracking** — decisions actioned vs. signal improvement (did it work?)
