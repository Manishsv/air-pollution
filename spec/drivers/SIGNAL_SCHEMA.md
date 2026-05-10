# AirOS Drivers — Signal Schema Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Drivers

---

## Purpose [INFORMATIVE]

This document defines the schema for a signal row — the atomic unit of data in the AirOS Knowledge Store. Every piece of environmental or infrastructure data that flows through the platform is expressed as one or more signal rows.

---

## Signal Row [NORMATIVE]

A signal row represents a single measured or derived quantity for a single H3 cell at a single hour.

```
SignalRow {
  h3_id:        string    REQUIRED  — H3 resolution-8 cell identifier
  city_id:      string    REQUIRED  — city partition key
  domain:       string    REQUIRED  — domain name (see Domain Catalogue)
  signal:       string    REQUIRED  — signal name within the domain
  hour_bucket:  string    REQUIRED  — "YYYY-MM-DDTHH:00:00Z"
  value:        float     REQUIRED  — measured or derived value; MUST NOT be null or NaN
  unit:         string    OPTIONAL  — unit of measure
  source:       string    OPTIONAL  — upstream source identifier
  data_quality: string    OPTIONAL  — provenance tier (see below)
  observed_at:  string    OPTIONAL  — ISO-8601 observation timestamp
}
```

A Driver submits a list of `SignalRow` objects to the `write_signals` operation. Each row is stored independently; the deduplication key is `(h3_id, city_id, domain, signal, hour_bucket)`.

---

## The DATA_CONFIDENCE Signal [NORMATIVE]

`DATA_CONFIDENCE` is a special required signal that every domain MUST write for every cell it produces any other signal for.

| Property | Value |
|----------|-------|
| Signal name | `DATA_CONFIDENCE` |
| Unit | ratio |
| Range | [0.0, 1.0] — 0 = no confidence, 1 = maximum confidence |
| Null allowed | NO |

**Interpretation:**
- `≥ 0.8` — high confidence. Derived from a nearby real sensor or high-quality satellite pass.
- `0.5 – 0.79` — moderate confidence. Interpolated value or partially clouded satellite.
- `0.3 – 0.49` — low confidence. Heavily interpolated, distant sensor, or coarse model estimate.
- `< 0.3` — very low confidence. Cell is far from any observation. SHOULD NOT be surfaced as actionable without explicit operator acknowledgement.

**Confidence decomposition [NORMATIVE]:** Different sources of uncertainty are operationally distinct. The `DATA_CONFIDENCE` scalar is the overall summary, but Drivers SHOULD also write a `DATA_CONFIDENCE_REASONS` signal (as a JSON string value) recording the primary reasons for the confidence level. The reasons vocabulary is:

| Reason key | Meaning |
|------------|---------|
| `sensor_distance_km` | Distance to nearest real observation (IDW drivers) |
| `cloud_fraction` | Cloud cover fraction (satellite drivers) |
| `data_age_hours` | Hours since original observation |
| `source_reliability` | Known reliability grade of the upstream source |
| `interpolation_method` | Assignment method used (A/B/C/D) |
| `completeness_fraction` | Fraction of expected records present (administrative data) |

Apps and agents that read `DATA_CONFIDENCE_REASONS` can provide more precise uncertainty notes than apps that read only the scalar.

**Conformance gate:** A batch of signal rows that contains no `DATA_CONFIDENCE` row for every `h3_id` in the batch is BLOCKING non-conformant and will be rejected by the write interface. See [Conformance](CONFORMANCE.md).

---

## Data Quality Provenance Tiers [NORMATIVE]

The `data_quality` field classifies the origin of a signal value. It MUST be one of:

| Value | Meaning |
|-------|---------|
| `real_station` | Directly measured by a physical sensor (AQI station, noise sensor, rain gauge) |
| `satellite_derived` | Derived from satellite imagery (Sentinel-2, MODIS, VIIRS) |
| `model_estimate` | Output of a numerical model or forecast (OpenMeteo, interpolation far from sensors) |
| `unknown` | Provenance not determinable |

The `data_quality` value SHOULD be inferred automatically from the source identifier when not explicitly set. The mapping is deployment-defined; the reference implementation infers it from source name keywords (e.g. "openmeteo" → `model_estimate`, "sentinel" → `satellite_derived`, "cpcb" → `real_station`).

A signal with `data_quality = model_estimate` or `unknown` SHOULD have `DATA_CONFIDENCE ≤ 0.7`.

---

## Signal Naming Convention [NORMATIVE]

Signal names MUST:
- Be uppercase ASCII with underscores (e.g. `PM25`, `FLOOD_RISK_INDEX`, `DATA_CONFIDENCE`)
- Be unique within a domain (two signals in the same domain MUST NOT share a name)
- Be declared in the Driver's `signals.yaml` before the Driver ships

Signal names SHOULD:
- Be concise and self-describing
- Follow the existing canonical names for established signals (e.g. always use `PM25`, never `PM2_5` or `pm25`)
- Not include units in the name (units go in the `unit` field)

---

## `signals.yaml` Declaration [NORMATIVE]

Every Driver MUST ship a `signals.yaml` file that declares all signals the Driver writes. This file is the machine-readable contract between the Driver and the conformance gate.

**Required fields per signal:**

```yaml
domain: <domain_name>

signals:
  - name: MY_SIGNAL           # REQUIRED: uppercase, unique within domain
    unit: index               # REQUIRED: unit string or "none"
    dtype: float              # REQUIRED: float | int | str
    nullable: false           # REQUIRED: whether this signal can be absent for some cells/hours
    description: "..."        # REQUIRED: one-line human-readable description
    range: [min, max]         # OPTIONAL: expected value range; violations → warning
```

**`DATA_CONFIDENCE` entry is REQUIRED:**

```yaml
  - name: DATA_CONFIDENCE
    unit: ratio
    dtype: float
    nullable: false
    range: [0.0, 1.0]
    description: "Confidence in signal values for this cell. 0 = no confidence, 1 = maximum."
```

**Optional fields per signal:**

| Field | Description |
|-------|-------------|
| `data_quality_tier` | Expected `data_quality` value for this signal |
| `assignment_method` | Which of the four spatial assignment methods is used (A/B/C/D) |
| `aggregation_function` | How multiple raw values are merged into one cell value when using Method B or D: `sum` / `mean` / `max` / `min` / `count`. REQUIRED when `assignment_method` is `B` or `D`. |
| `upstream_variable` | Name of the variable in the upstream API response |

---

## Composite Index Signals [INFORMATIVE]

Many domains produce a composite risk index that summarises multiple raw signals into a single 0–1 score (e.g. `HEAT_RISK_SCORE`, `FLOOD_RISK_INDEX`, `WATER_QUALITY_INDEX`). These are standard signal rows — there is no special schema for composite indices.

The convention is:
- Composite index signal names end in `_INDEX`, `_SCORE`, or `_RISK_INDEX`
- Range is always [0.0, 1.0] with higher values indicating higher risk
- The formula for the composite MUST be documented in the domain spec YAML

---

## NEAREST_OBS_KM [INFORMATIVE]

Drivers that use IDW interpolation (Method A) SHOULD write a `NEAREST_OBS_KM` signal recording the distance from the cell centroid to the nearest real observation. This enables Apps to distinguish cells near a sensor (high-quality interpolation) from cells far from any sensor (extrapolated estimate).

If written, `NEAREST_OBS_KM` MUST have `unit: km` and `dtype: float`.
