# AirOS Drivers — Driver Interface Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Drivers

---

## Purpose [INFORMATIVE]

This document defines the interface that every AirOS data source driver — whether built-in or third-party — must implement. The interface is language-agnostic: the normative requirements are expressed as logical contracts, not as Python method signatures. The reference Python Protocol (`H3DataSourceDriver`) in the reference implementation is one correct realisation of this contract.

A "driver" is the unit of data acquisition and H3 mapping. One driver corresponds to one upstream data source for one domain.

---

## Driver Identity [NORMATIVE]

Every driver MUST declare the following identity fields. These fields MUST be static — they MUST NOT change between calls to `fetch`.

### `domain`

- Type: string
- A machine-readable domain identifier. MUST be unique across all drivers active in a deployment.
- MUST consist of lowercase ASCII letters, digits, and underscores only.
- SHOULD use the canonical domain name from the [Domain Catalogue](DOMAIN_CATALOGUE.md) when implementing a canonical domain.
- SHOULD use a suffix (e.g. `air_iqair`, `air_openaq`) when multiple drivers provide data for the same canonical domain.

### `cadence_hours`

- Type: positive number
- The minimum elapsed time (in hours) between successive `fetch` calls for the same city.
- The Scheduler MUST NOT call `fetch` more frequently than `cadence_hours` unless `force=true`.
- Examples: `0.25` (15 minutes), `1.0` (hourly), `6.0` (every 6 hours), `2160` (quarterly ≈ 90 days).

### `produces_assessments`

- Type: boolean
- `true` if this driver writes `h3_assessments` rows (risk level classifications).
- `false` for structural context drivers (buildings, roads, drains, weather) that provide signals only.

### `signal_names`

- Type: list of strings
- The canonical signal names this driver writes to `h3_signals.signal`.
- MUST include `DATA_CONFIDENCE`.
- Used by the conformance gate to verify output. See [Conformance](CONFORMANCE.md).

### `data_sources`

- Type: list of human-readable strings
- Descriptions of the upstream data sources used by this driver.
- Used in dashboard provenance labels and evidence bundles.

---

## Required Operations [NORMATIVE]

### `fetch(city_id, bbox, force=false) → integer`

The primary operation. Pulls data from the upstream source, maps it to H3 cells, and writes signals to the Knowledge Store.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `city_id` | string | City partition key (e.g. `bangalore`) |
| `bbox` | object | Bounding box: `{lat_min, lon_min, lat_max, lon_max}` |
| `force` | boolean | If true, ignore the cadence watermark and fetch unconditionally |

**Returns:** integer — the number of `h3_signals` rows written. Zero is a valid return value meaning no new data was available. `-1` is a reserved sentinel meaning "fetch was skipped because the cadence watermark has not elapsed" (only valid when `force=false`). MUST NOT return any other negative number.

**MUST:**
- Call `record_ingest(city_id, domain, rows_written, status)` before returning, whether the fetch succeeds, partially succeeds, or fails.
- Respect the cadence watermark (read `h3_ingest_log`) unless `force=true`.
- Write only to `h3_signals`, `h3_assessments`, and `h3_metadata` — never to `h3_insights`, `h3_packets`, or any App table.
- Write at H3 resolution 8 only.
- Write a `DATA_CONFIDENCE` signal row for every cell it writes any other signal for.
- Be idempotent: two calls for the same `(city_id, hour_bucket)` MUST NOT produce duplicate rows.

**MUST NOT:**
- Read from `h3_signals` or `h3_assessments` as input to the fetch computation. Exception: structural context Drivers (domains: `buildings`, `roads`, `drains`, `weather`) MAY read prior rows from `h3_signals` where `domain` matches their own declared `domain` identity field — i.e. signals that this driver itself wrote — for change detection purposes. Reading signals from any other domain is prohibited for all Drivers.
- Write `h3_signals` rows for cells outside `bbox`.
- Raise an exception for transient upstream errors (network timeout, rate limit). Implement internal retry; only raise an unrecoverable error after exhausting retries.

**Error handling:** On unrecoverable error, the driver MUST call `record_ingest` with `status=error` and then raise a `DriverFetchError` (or equivalent). The Scheduler catches this, logs it, and moves on — a single Driver failure MUST NOT abort the ingest run for other domains.

---

### `conformance_check() → ConformanceResult`

A static validation of the driver's configuration, called once at load time.

**MUST:**
- Complete in under 2 seconds.
- Not make live network calls to upstream APIs.
- Check that all required environment variables or configuration files are present (not necessarily valid — only presence is checked here).
- Return a `ConformanceResult` with `ok=true` if the driver is ready to fetch, `ok=false` with a list of `failures` if it is not.

**SHOULD:**
- Return `warnings` for non-blocking issues (optional credentials missing, degraded confidence expected).

A driver that returns `ok=false` from `conformance_check` MUST NOT be added to the active driver pool. The Scheduler MUST NOT call `fetch` on a driver that failed conformance.

---

## `ConformanceResult` Shape [NORMATIVE]

```
ConformanceResult {
  ok:        boolean          — true if driver is ready to fetch
  failures:  list of string   — blocking problems; ok MUST be false if non-empty
  warnings:  list of string   — non-blocking observations; ok may still be true
}
```

---

## Driver Discovery [NORMATIVE]

Drivers are discovered and trusted through the **Driver Registry** — a deployment-controlled configuration file (`drivers_registry.yaml` in the reference implementation).

Discovery MUST follow this precedence:

1. **Built-in drivers** — declared in the registry with a direct class/module reference. Loaded first.
2. **Third-party drivers** — declared in the registry with a package reference. Discovered via the runtime's package entry point mechanism (Python: `importlib.metadata.entry_points(group="airos.drivers")`).

**Trust rule [NORMATIVE]:** A driver that is discovered (via entry point or any other mechanism) but is NOT listed in the Driver Registry with `trusted: true` MUST be quarantined — logged as a warning, not loaded. The deployment operator MUST explicitly opt in to each driver.

**Entry point convention (Python reference):**
```toml
[project.entry-points."airos.drivers"]
my_domain = "my_package.driver:MyDriver"
```

---

## Driver Registry Format [NORMATIVE]

The Driver Registry MUST declare, for each active driver:

| Field | Required | Description |
|-------|----------|-------------|
| `trusted` | YES | Boolean. Only `true` drivers are loaded. |
| `trust_level` | YES | `core` / `verified` / `local` |
| `builtin_class` or `package` | YES | Location of the driver class |
| `cadence_hint` | NO | Human-readable cadence for documentation |
| `notes` | NO | Operator notes |

For third-party (non-built-in) drivers, the following additional fields are RECOMMENDED:

| Field | Description |
|-------|-------------|
| `version_pin` | Version range string (e.g. `>=1.2,<2.0`) |
| `added_by` | Identifier of the operator who added this driver |
| `added_at` | ISO-8601 date when the driver was added |

---

## Driver Package Convention [INFORMATIVE]

Third-party drivers SHOULD be published as installable packages following this convention:

- **Package name:** `airos-driver-<domain>` (e.g. `airos-driver-openaq`)
- **Entry point group:** `airos.drivers`
- **Entry point key:** the `domain` identifier
- **Bundled `signals.yaml`:** declares all signals written by the driver (see [Signal Schema](SIGNAL_SCHEMA.md))
- **Bundled conformance test:** at minimum, runs `conformance_check()` and verifies `isinstance(driver, H3DataSourceDriver)`

A driver template is available at `tools/driver-template/` in the reference implementation.

---

## Stability Guarantee [NORMATIVE]

The Driver Interface (the fields and operations defined in this document) is stable from version 1.0.0. Implementations of this interface MUST be guaranteed forward compatibility within a major version:

- Adding new optional fields to driver identity → minor version bump
- Changing the signature of `fetch` or `conformance_check` → major version bump
- Removing any required field or operation → major version bump + migration guide

An implementation that satisfies Driver Interface v1.y.z is guaranteed to work with any Core that implements the same major version of the Knowledge Store (v1.x.x), provided y ≤ x (i.e., the Core's minor version is at least as recent as the driver's minor version). Compatibility across major versions is not guaranteed and requires an explicit migration guide.
