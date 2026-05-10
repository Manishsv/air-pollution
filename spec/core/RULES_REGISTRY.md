# AirOS Core — Rules Registry Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Core

---

## Purpose [INFORMATIVE]

The Rules Registry is the single source of truth for all domain thresholds — the numeric boundaries that separate `low` from `moderate`, `moderate` from `high`, and `high` from `severe`. It allows city operators to tune risk classifications without code changes, and supports city-level overrides so that what counts as "crowded" in Mumbai can differ from what counts as "crowded" in a smaller city.

Every risk-producing Driver and every App that interprets risk levels MUST read thresholds from the Rules Registry. Hardcoding threshold values in Driver or App code is non-conformant.

**Rules are operational policy.** Thresholds determine which communities are classified as high-risk, which sites are surfaced for inspection, and which officers receive alerts. Changing a threshold is a policy decision with operational consequences — not a routine configuration change. The governance requirements below reflect this.

---

## Governance Requirements [NORMATIVE]

### Versioning

Every `rules_registry.yaml` file MUST carry a top-level `version` field using SemVer format:

```yaml
version: "1.2.0"
```

A change that affects any threshold that influences risk classification or officer alert generation MUST increment the minor or major version. Editorial changes (comments, formatting) MAY increment the patch version only.

### Change History

Implementations MUST maintain an auditable history of Rules Registry changes. At minimum:

| Field | Required | Description |
|-------|----------|-------------|
| `changed_at` | YES | ISO-8601 UTC timestamp of the change |
| `changed_by` | YES | Identity of the operator who made the change |
| `version_from` | YES | Previous version string |
| `version_to` | YES | New version string |
| `keys_changed` | YES | List of `domain.key` paths that changed |
| `reason` | SHOULD | Human-readable rationale for the change |

The reference implementation records this in `data/config/rules_registry_history.yaml`. Alternative implementations MAY use a database table or version control history.

### Effective Dates

A threshold change MUST NOT take retroactive effect on already-written assessments. The version of the Rules Registry active at the time an assessment was written MUST be recorded in `h3_ingest_log` (or equivalent audit record) so that historical assessments can be interpreted in their original threshold context.

### Environment Separation

Deployments MUST maintain separate Rules Registry files for development/staging and production environments. A threshold change MUST be tested in staging before production promotion. The `RULES_REGISTRY` environment variable is the mechanism for pointing each environment at its own file.

### Disclosure

For deployments making public-sector decisions, threshold values and their rationale SHOULD be publicly disclosed. The Rules Registry YAML file (excluding any city-specific secrets) is designed to be human-readable and publishable.

---

---

## Architecture [NORMATIVE]

The Rules Registry is a two-layer system:

**Layer 1 — Built-in defaults:** A complete set of threshold defaults is embedded in the deployment. These defaults are normative — they define the canonical thresholds for each canonical domain. They are always present, even if no configuration file is provided.

**Layer 2 — YAML overrides:** An operator-editable configuration file (`rules_registry.yaml`) can override any built-in default. The override file is deep-merged with the built-in defaults at load time: any key present in the file takes precedence; missing keys fall through to the built-in default.

The resulting merged configuration is the **active registry**.

---

## Configuration File [NORMATIVE]

The Rules Registry configuration file MUST be a valid YAML file. Its location MUST be configurable via the `RULES_REGISTRY` environment variable. The default path is `data/config/rules_registry.yaml`.

A conformant implementation MUST accept an empty configuration file (no keys) and fall back entirely to built-in defaults.

### File Structure

```yaml
# rules_registry.yaml

<domain>:
  <key>: <value>
  ...
  cities:
    <city_id>:
      <key>: <value>   # city-level override for this domain key
```

**Example — partial override for air quality and crowd:**

```yaml
air:
  pm25_category_thresholds_ug_m3:
    severe: 300        # city uses a stricter severe threshold
    very_poor: 150
    poor: 100
    moderate: 60
    satisfactory: 30

crowd:
  gathering_threshold_per_km2: 400    # global default
  cities:
    mumbai:
      gathering_threshold_per_km2: 300  # Mumbai-specific override
    delhi:
      gathering_threshold_per_km2: 350
```

---

## Read Interface [NORMATIVE]

The Rules Registry MUST expose a read interface with the following signature:

```
get(domain, key, city_id=None, default=None) → value
```

**Lookup precedence:**

1. If `city_id` is provided and a city-level override exists for `(domain, key, city_id)` → return city override.
2. If a global override exists for `(domain, key)` in the YAML file → return that value.
3. If a built-in default exists for `(domain, key)` → return the built-in default.
4. Return `default` (caller-supplied fallback).

Callers MUST NOT receive an exception from `get()` for a missing key — the `default` parameter is the safety net.

---

## Hot-Reload [NORMATIVE]

The Rules Registry MUST support hot-reload: the ability to apply configuration file changes without restarting the process.

A conformant implementation MUST expose a `reload()` operation that:

1. Re-reads the configuration file from disk.
2. Re-merges it with built-in defaults.
3. Replaces the active registry with the new merged result.
4. Is thread-safe — concurrent reads MUST NOT see a partially updated registry.

The Scheduler SHOULD call `reload()` at the start of each sweep cycle. An implementation MAY use a file-watcher to trigger reload on file change.

**Reload failure:** If the configuration file is malformed YAML, `reload()` MUST leave the current active registry unchanged and log an error. It MUST NOT replace a valid registry with a broken one.

---

## Singleton Semantics [NORMATIVE]

A deployment MUST have exactly one active Rules Registry instance per process. The registry MUST be initialized lazily on first access and cached for all subsequent reads. Drivers and Apps MUST obtain the registry via the standard module import, not by constructing new instances.

---

## Canonical Built-in Defaults [NORMATIVE]

The following tables define the built-in default thresholds for each canonical domain. These are the values used when no override is present.

### `air` — Air Quality

| Key | Default value |
|-----|--------------|
| `pm25_category_thresholds_ug_m3` | `{severe: 250, very_poor: 120, poor: 90, moderate: 60, satisfactory: 30}` |
| `pm10_category_thresholds_ug_m3` | `{severe: 430, very_poor: 350, poor: 250, moderate: 100, satisfactory: 50}` |
| `aqi_risk_levels` | `{severe: 401, very_poor: 301, poor: 201, moderate: 101, satisfactory: 51, good: 0}` — floor thresholds for the 6-level `air` domain vocabulary (AQI value ≥ threshold → that level) |
| `min_data_confidence_for_advisory` | `0.5` |

### `fire` — Fire Detection

| Key | Default value |
|-----|--------------|
| `fire_score_risk_levels` | `{severe: 0.75, high: 0.5, moderate: 0.25, low: 0.0}` |
| `frp_mw_thresholds` | `{severe: 100, high: 50, moderate: 10}` |

### `flood` — Flood Risk

| Key | Default value |
|-----|--------------|
| `flood_risk_index_levels` | `{severe: 0.75, high: 0.5, moderate: 0.25, low: 0.0}` |
| `rainfall_accumulation_24h_mm_high` | `64.5` |
| `rainfall_accumulation_24h_mm_moderate` | `35.5` |

### `heat` — Urban Heat

| Key | Default value |
|-----|--------------|
| `heat_risk_score_levels` | `{severe: 0.75, high: 0.5, moderate: 0.25, low: 0.0}` |
| `score_weights` | `{uhi_norm: 0.6, green_deficit: 0.4}` — weights used in the `HEAT_RISK_SCORE` composite formula. The `heat` Driver MUST read these via `rules.get("heat", "score_weights")` rather than hardcoding 0.6/0.4. |

### `water` — Water Quality

| Key | Default value |
|-----|--------------|
| `water_quality_index_levels` | `{severe: 0.75, poor: 0.5, moderate: 0.25, good: 0.0}` |

### `waste` — Waste / Illegal Dumping

| Key | Default value |
|-----|--------------|
| `waste_risk_index_levels` | `{severe: 0.75, high: 0.5, moderate: 0.25, low: 0.0}` |
| `persistence_days_high_threshold` | `7` |

### `construction` — Construction Activity

| Key | Default value |
|-----|--------------|
| `construction_risk_index_levels` | `{severe: 0.75, high: 0.5, moderate: 0.25, low: 0.0}` |

### `green` — Green Cover

| Key | Default value |
|-----|--------------|
| `ndvi_green_threshold` | `0.3` |
| `green_cover_risk_levels` | `{severe: 0.1, high: 0.2, moderate: 0.35, low: 1.0}` — **ceiling thresholds**: a cell with `GREEN_COVER_FRACTION ≤ value` is assigned that risk level. This is the inverse of other domains; `severe` maps to the lowest fraction (most degraded). |

### `noise` — Noise

| Key | Default value |
|-----|--------------|
| `noise_risk_index_levels` | `{severe: 0.75, high: 0.5, moderate: 0.25, low: 0.0}` |
| `laeq_residential_limit_db` | `55` |
| `laeq_commercial_limit_db` | `65` |

### `crowd` — Crowd / Gatherings

| Key | Default value |
|-----|--------------|
| `gathering_threshold_per_km2` | `500` — density at which `GATHERING_ALERT = 1.0` and `risk_level = high` |
| `high_density_threshold_per_km2` | `1000` — density at which `risk_level = critical` |
| `crowd_risk_levels` | `{no_alert: 0, elevated: gathering_threshold, high: high_density_threshold, critical: above_high_density}` — see Domain Catalogue for full vocabulary |

---

## City-Level Override Semantics [NORMATIVE]

City-level overrides MUST shadow the global default for the specified `(domain, key)` pair when `city_id` is provided in the `get()` call.

A city-level override MUST NOT affect reads where `city_id` is not provided. Global defaults remain intact for all other cities.

An operator MAY override any key at the city level. There is no restriction on which keys may be city-scoped.

---

## Adding New Threshold Keys [NORMATIVE]

Third-party Drivers and Apps that need domain-specific thresholds SHOULD add those keys to the Rules Registry rather than hardcoding them. The convention for third-party keys is:

```
<domain>.<package_or_org>.<key_name>
```

Example: `air.my_org.secondary_pm25_limit`

Third-party keys that are not in the built-in defaults MUST provide their own `default` in the `get()` call — they MUST NOT assume the registry has a built-in for them.

---

## What the Rules Registry Does Not Own [INFORMATIVE]

The Rules Registry owns **thresholds** — the numeric breakpoints that separate risk levels. It does not own:

- Signal formulas or composite index calculations (those are Driver logic)
- H3 grid resolution or spatial parameters (those are the Spatial Model)
- Ingest cadences (those are the Scheduler)
- Agent reasoning instructions (those are the Agent Interface)

A risk formula that embeds numeric thresholds inline rather than reading them from `rules.get()` is non-conformant, even if the embedded value happens to match the current registry default.
