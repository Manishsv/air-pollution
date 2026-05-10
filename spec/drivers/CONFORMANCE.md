# AirOS Drivers — Conformance Gate Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Drivers

---

## Purpose [INFORMATIVE]

The conformance gate is the enforcement layer between Drivers and the Knowledge Store. It runs automatically when a Driver calls `write_signals`. Its job is to catch output that violates the signal schema contract before bad data enters the store and propagates to App reasoning.

The gate distinguishes **blocking** failures (the write is rejected) from **non-blocking** warnings (the write proceeds but the problem is logged and recorded in `h3_ingest_log`).

This separation reflects a deliberate asymmetry: data that is structurally wrong (missing required signals) must never enter the store; data that is questionable (values outside expected ranges, some signals absent for a plausible reason) is better stored with a warning than silently dropped.

**Scope and limits [INFORMATIVE]:** The conformance gate validates **structure and schema** — it does not validate truth. A sensor reporting plausible values that are physically incorrect (due to calibration error, sensor drift, or vendor data quality issues) will pass the conformance gate. Implementations SHOULD supplement the conformance gate with:
- Sensor drift detection (comparing values to historical baseline distributions)
- Cross-source sanity checks (comparing values from overlapping data sources)
- Vendor schema change detection (alerting when upstream field names or units change)
- Missingness monitoring (alerting when a previously reliable source stops producing data)

These additional checks are outside the scope of this specification but are important for operational reliability.

---

## Definitions [NORMATIVE]

**Batch:** a single call to `write_signals`. All gate rules are evaluated per batch. A batch contains all signal rows submitted in one `write_signals` invocation — typically one domain × one city × one fetch cycle.

---

## Gate Rules [NORMATIVE]

### Rule 1 — DATA_CONFIDENCE must be present for every cell [BLOCKING]

For every distinct `h3_id` in the batch, at least one row with that `h3_id` and `signal = DATA_CONFIDENCE` MUST be present. If any `h3_id` in the batch has no corresponding `DATA_CONFIDENCE` row, the entire batch MUST be rejected and zero rows MUST be written.

**Rationale:** Every cell in the Knowledge Store must carry confidence metadata. An App that reads signals for a cell without `DATA_CONFIDENCE` cannot weight evidence by reliability — a core requirement of the AirOS reasoning model. A single `DATA_CONFIDENCE` row covering only one cell does not satisfy this requirement for the remaining cells in the batch.

**Error message pattern:**
```
[<domain>] DATA_CONFIDENCE signal is absent for <n> h3_id(s): [<sample ids>].
Every cell written must have a DATA_CONFIDENCE row so downstream
reasoning can weight signals by reliability.
```

**Recorded in:** `h3_ingest_log.conformance_ok = false`, `conformance_failures = [<message>]`

---

### Rule 2 — Declared signals absent from rows [NON-BLOCKING]

If the Driver declares `signal_names` (via `signals.yaml` or the driver identity contract) and one or more declared signal names are absent from the submitted rows, a WARNING is logged.

**Rationale:** A signal being absent may be legitimately explainable — no fire events in a fire-free period, cloudy sky preventing satellite observation, API returning partial data. This is a warning, not a block. Repeated absences for the same signal may indicate a driver bug and SHOULD be investigated.

**Warning message pattern:**
```
[<domain>] Declared signal(s) absent from rows: [<signals>].
May be legitimate (no events this hour) or a driver bug.
```

---

### Rule 3 — H3 resolution mismatch [BLOCKING]

If any `h3_id` in the submitted rows is not at the deployment's standard resolution (resolution 8), the entire batch MUST be rejected and zero rows MUST be written.

**Rationale:** Signals at the wrong resolution cannot join with assessments, neighbours, or city-level rollups. Storing them would silently corrupt spatial analysis.

**Error message pattern:**
```
[<domain>] <n> h3_id(s) are not resolution 8 (sample: [<ids>]).
All signals must be written at H3 resolution 8.
```

**Recorded in:** `h3_ingest_log.conformance_ok = false`, `conformance_failures = [<message>]`

---

### Rule 4 — Null or NaN values [NON-BLOCKING]

Rows with `value = null` or `value = NaN` are silently skipped by the write operation (they are never persisted). If a significant fraction of rows have null values, a WARNING is logged.

**Warning message pattern:**
```
[<domain>] <n>/<total> rows have null/NaN value.
These rows will be skipped by write_signals().
```

---

### Rule 5 — Value range violations [NON-BLOCKING]

If a Driver's `signals.yaml` declares a `range: [min, max]` for a signal, and submitted values fall outside that range, a WARNING is logged. The write proceeds — legitimate sensor readings sometimes exceed expected ranges (e.g. PM2.5 during wildfire smoke events).

**Warning message pattern:**
```
[<domain>] <n> rows for signal <name> have values outside
declared range [<min>, <max>]: <samples>.
```

---

## Conformance Check at Load Time [NORMATIVE]

In addition to the per-fetch gate described above, the Driver Interface requires a `conformance_check()` call at load time. This is a static check (no data submitted) that validates the driver's configuration. See [Driver Interface](DRIVER_INTERFACE.md#conformance_check--conformanceresult) for the contract.

A Driver that fails `conformance_check()` MUST NOT be loaded into the active driver pool. The Scheduler MUST NOT call `fetch` on it.

---

## Gate Result Recording [NORMATIVE]

The outcome of every conformance gate evaluation MUST be recorded in `h3_ingest_log` for the `(city_id, domain)` pair:

| Field | Value |
|-------|-------|
| `conformance_ok` | `true` if no blocking failures occurred; `false` otherwise |
| `conformance_failures` | JSON array of **all** messages from this run — both blocking failures and non-blocking warnings. Failures are prefixed `[FAIL]`; warnings are prefixed `[WARN]`. |

This record MUST be written even when the write is blocked (rows_written = 0).

---

## Gate Bypass [NORMATIVE]

The conformance gate MUST NOT be bypassable in production deployments. An implementation MAY expose a `skip_conformance` flag for use in test harnesses and driver development — but this flag MUST be explicitly disabled in production.

**"Explicitly disabled" is defined as:** the `skip_conformance` flag MUST default to `false`. Enabling it MUST require an environment variable (e.g. `AIROS_SKIP_CONFORMANCE=true`) that is absent from all production deployment manifests, container images, and CI pipeline configurations that feed human-reviewed decision support. A deployment where the variable is set to `true` in any environment that writes to a live Knowledge Store is non-conformant.

**Rationale:** A conformance bypass in production removes the safety guarantee that all signals in the Knowledge Store carry confidence metadata. This would invalidate the reasoning model.

---

## Compliance Levels [INFORMATIVE]

This table summarises what each rule means for a Driver claiming AirOS Drivers spec conformance:

| Rule | Severity | Conformance claim requires |
|------|----------|--------------------------|
| DATA_CONFIDENCE present per cell | BLOCKING | Driver MUST write DATA_CONFIDENCE for every h3_id it writes any other signal for |
| Declared signals match rows | WARNING | Driver SHOULD write all declared signals or provide documentation of when they are legitimately absent |
| H3 resolution = 8 | BLOCKING | Driver MUST write at resolution 8; non-resolution-8 rows are rejected |
| No null values | WARNING | Driver SHOULD filter null values before submitting |
| Values within declared range | WARNING | Driver SHOULD validate upstream data before mapping to H3 |
