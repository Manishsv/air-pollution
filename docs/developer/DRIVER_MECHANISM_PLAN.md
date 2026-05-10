# AirOS Data Source Driver Mechanism — Implementation Plan

AirOS drivers are the components that pull raw environmental data, map it to H3 cells, and write signals to the Knowledge Store. Today, all 14 domain drivers live in-tree inside `urban_platform/h3_knowledge/` and are wired directly into `ingestor.py`. This plan defines the phased work to give drivers a stable interface, a packaging standard, and a discovery/conformance mechanism — so operators can install third-party drivers without touching AirOS Core source code.

---

## Why This Matters

| Today | After this plan |
|-------|----------------|
| Adding a driver = editing `ingestor.py` | Adding a driver = `pip install airos-driver-<name>` |
| All 14 drivers are in-tree, no interface contract | Drivers implement a stable Protocol; Core never cares about internals |
| No way to ship a domain without shipping all of AirOS | Drivers are independently versioned and publishable |
| No check that a driver's output matches the schema a panel expects | Conformance gate runs before signals reach the Knowledge Store |
| No catalogue of known-good third-party drivers | `drivers_registry.yaml` + (later) hosted catalogue |

This follows the same model used by **Prometheus exporters** (any binary can be a valid exporter if it speaks the text protocol) and **OpenTelemetry receivers** (stable ReceiverFactory interface + contrib repo for community connectors).

---

## What We Are Not Building

- A compile-time kernel ABI (Linux-style). Python interface stability is contractual, not binary.
- Automated cryptographic signing of every driver package. That's OS-level. We use pip's existing PyPI trust model.
- A mandatory cloud registry. `drivers_registry.yaml` is local-first; a hosted catalogue is optional and later.

---

## Phases

---

### Phase 1 — Stable Driver Interface (Protocol)

**Goal:** Define a Python Protocol that any driver — in-tree or third-party — must satisfy. This is the "kernel ABI". It must be stable from this point forward; breaking it is a major version bump.

**Deliverables:**

#### `urban_platform/sdk/driver_protocol.py` (new file)

```python
"""
AirOS Data Source Driver Protocol
==================================
All drivers — in-tree or third-party — must satisfy this interface.
Breaking changes to this Protocol constitute a major version increment.
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable
import pandas as pd


@runtime_checkable
class H3DataSourceDriver(Protocol):
    """Stable interface every AirOS domain driver must implement."""

    # ------------------------------------------------------------------ #
    # Identity                                                             #
    # ------------------------------------------------------------------ #

    @property
    def domain(self) -> str:
        """Machine-readable domain name, e.g. 'air', 'flood', 'openaq_v2'.
        Must be unique across all installed drivers in a deployment.
        """
        ...

    @property
    def cadence_hours(self) -> float:
        """Minimum hours between fetches. The scheduler will not call fetch()
        more frequently than this. Use 0.25 for 15-minute cadence.
        """
        ...

    @property
    def produces_assessments(self) -> bool:
        """True if the driver writes h3_assessments (risk levels).
        Structural drivers (buildings, roads, drains, weather) return False.
        """
        ...

    # ------------------------------------------------------------------ #
    # Core fetch                                                           #
    # ------------------------------------------------------------------ #

    def fetch(
        self,
        city_id: str,
        bbox: dict,           # {"lat_min", "lon_min", "lat_max", "lon_max"}
        *,
        force: bool = False,  # ignore watermark, re-fetch unconditionally
    ) -> int:
        """Pull data, compute H3 signals, write to the Knowledge Store.

        Returns the number of signal rows written (0 is valid — means no
        new data was available). Must be idempotent: calling fetch() twice
        for the same hour must not double-write rows.

        Raises DriverFetchError on unrecoverable errors.
        """
        ...

    # ------------------------------------------------------------------ #
    # Conformance                                                          #
    # ------------------------------------------------------------------ #

    def conformance_check(self) -> "ConformanceResult":
        """Validate the driver's static configuration and credentials.

        Called once at driver load time (not per-fetch). Must not make
        live API calls — only check that required env vars are set,
        required files exist, and the driver's signal list matches its
        declared schema.

        Returns a ConformanceResult (ok=True/False + list of failures).
        """
        ...

    # ------------------------------------------------------------------ #
    # Metadata (optional — defaults provided by BaseDriver)               #
    # ------------------------------------------------------------------ #

    @property
    def signal_names(self) -> list[str]:
        """Canonical signal names this driver writes to h3_signals.
        Used by the conformance gate and the H3 Expert Agent system prompt.
        """
        ...

    @property
    def data_sources(self) -> list[str]:
        """Human-readable list of upstream data sources.
        Shown in dashboard provenance labels.
        """
        ...
```

#### `urban_platform/sdk/base_driver.py` (new file)

A concrete base class with default implementations of the optional fields, a shared `_check_interval()` watermark helper, and a default `conformance_check()` that just verifies env vars. In-tree drivers subclass this; third-party drivers may implement the Protocol directly without inheriting.

#### `urban_platform/sdk/driver_types.py` (new file)

```python
from dataclasses import dataclass, field

@dataclass
class ConformanceResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

class DriverFetchError(Exception):
    """Raised by fetch() on unrecoverable errors."""
```

**Migration of in-tree drivers:**

Refactor one in-tree driver as the reference implementation (recommended: `air`). The remaining 13 can migrate incrementally — each migration is a PR that adds `domain`, `cadence_hours`, `produces_assessments`, `fetch()`, and `conformance_check()` to the existing ingestor module and wraps it in the Protocol. No user-facing change.

**Acceptance criteria:**
- `isinstance(driver, H3DataSourceDriver)` returns `True` for all in-tree drivers
- All existing tests pass
- No change to `ingestor.py` dispatch logic yet (that is Phase 3)

---

### Phase 2 — Driver Packaging Standard

**Goal:** Define how a third-party driver is packaged so `pip install airos-driver-openaq` is all an operator needs to do.

**Deliverables:**

#### Entry point convention

Drivers declare themselves via the `airos.drivers` setuptools entry point group:

```toml
# Third-party driver's pyproject.toml
[project.entry-points."airos.drivers"]
openaq_v2 = "airos_driver_openaq.driver:OpenAQDriver"
```

Core discovers all installed drivers at startup by iterating `importlib.metadata.entry_points(group="airos.drivers")`.

#### Naming convention

| Package name | Entry point key | `domain` property |
|---|---|---|
| `airos-driver-openaq` | `openaq_v2` | `"openaq_v2"` |
| `airos-driver-iqair` | `iqair` | `"iqair"` |
| `airos-driver-pune-municipal` | `pune_waste` | `"pune_waste"` |

Namespace: `airos-driver-*` on PyPI (no enforcement — just a community convention).

#### Driver package template

Create `tools/driver-template/` — a cookiecutter-style directory that third-party authors copy:

```
airos-driver-template/
  pyproject.toml             ← entry point wired, airos-sdk dependency declared
  README.md                  ← required fields, how to publish
  src/
    airos_driver_template/
      driver.py              ← class TemplateDriver(BaseDriver): ...
      signals.yaml           ← signal_names, units, description, rules_registry defaults
      tests/
        test_conformance.py  ← assert ConformanceResult.ok
```

The `signals.yaml` file is the analog of the Linux `MODULE_LICENSE()` macro — it declares what the driver produces so the Knowledge Store can validate it without running the driver.

#### In-tree drivers as reference packages

The 14 in-tree drivers are split into their own `packages/` directories within the monorepo. They remain installable as part of the main install but can also be versioned independently:

```
packages/
  airos-driver-air/
  airos-driver-flood/
  airos-driver-heat/
  ... (14 total)
```

**Acceptance criteria:**
- `pip install airos-driver-openaq` (a test package) installs successfully
- Core discovers it via entry points without any `ingestor.py` edit
- The driver template passes its own conformance test out of the box

---

### Phase 3 — Discovery and Registry

**Goal:** Give operators control over which drivers are active. Prevent accidental activation of an untrusted driver just because it happens to be installed.

**Deliverables:**

#### `data/config/drivers_registry.yaml` (new file)

```yaml
# AirOS Driver Registry
# =====================
# Only drivers listed here (trusted: true) will be loaded at startup.
# Drivers present as entry points but absent from this file are quarantined.
#
# trust_level:
#   core    — shipped with AirOS, reviewed by maintainers
#   verified — third-party, manually vetted, pinned to a version range
#   local   — operator-built, not published to PyPI

drivers:
  air:
    package: airos-driver-air
    trust_level: core
    trusted: true

  flood:
    package: airos-driver-flood
    trust_level: core
    trusted: true

  # Example third-party driver:
  openaq_v2:
    package: airos-driver-openaq
    version_pin: ">=1.2,<2.0"
    trust_level: verified
    trusted: true
    added_by: operator@city.gov
    added_at: 2026-01-15

  # Quarantined — discovered via entry points but not trusted:
  # suspect_driver:
  #   package: airos-driver-suspect
  #   trusted: false
  #   reason: "untested with AirOS 2.x"
```

#### Driver loader (`urban_platform/sdk/driver_loader.py`)

```python
def load_drivers(registry_path: Path) -> dict[str, H3DataSourceDriver]:
    """
    1. Read drivers_registry.yaml
    2. Discover all entry points in group "airos.drivers"
    3. For each discovered driver:
       a. If not in registry → log WARNING and skip (quarantine)
       b. If in registry but trusted: false → log WARNING and skip
       c. If trusted: true → instantiate, run conformance_check()
          - conformance_check ok → add to active drivers
          - conformance_check failed → log ERROR, mark driver degraded, skip
    4. Return dict[domain -> driver_instance]
    """
```

#### Changes to `ingestor.py`

Replace the `if domain == "air": _ingest_air(...)` dispatch table with:

```python
_drivers = load_drivers(DRIVERS_REGISTRY_PATH)

def run_domain(domain: str, city_id: str, *, force: bool = False) -> int:
    driver = _drivers.get(domain)
    if driver is None:
        logger.warning("No trusted driver for domain %s — skipping", domain)
        return 0
    return driver.fetch(city_id, _CITY_BBOXES[city_id], force=force)
```

The 14 `_ingest_*` functions in `ingestor.py` move into their respective driver packages and are no longer called directly.

**Acceptance criteria:**
- Removing a driver's `trusted: true` from `drivers_registry.yaml` stops it running without code changes
- Adding a new third-party driver updates only `drivers_registry.yaml` (no `ingestor.py` edit)
- All 14 in-tree domains still ingest correctly
- Quarantine warning logged for any entry-point driver not in the registry

---

### Phase 4 — Runtime Conformance Gate

**Goal:** Validate driver output against the signal schema before it reaches the Knowledge Store. This is the AirOS equivalent of Linux module signing — a driver's self-declaration is checked mechanically.

**Deliverables:**

#### Signal schema validation

Each driver's `signals.yaml` declares:

```yaml
domain: air
signals:
  - name: PM25
    unit: ug/m3
    dtype: float
    range: [0, 1000]
    nullable: true
  - name: AQI
    unit: index
    dtype: float
    range: [0, 500]
    nullable: false
  - name: DATA_CONFIDENCE
    unit: ratio
    dtype: float
    range: [0.0, 1.0]
    nullable: false
```

The conformance gate (`urban_platform/sdk/conformance.py`) wraps `write_signals()`:

```python
def validated_write_signals(driver: H3DataSourceDriver, df: pd.DataFrame, ...) -> int:
    """
    Before writing:
    1. Check df has all required columns declared in driver.signal_names
    2. Check dtypes match signals.yaml
    3. Check values within declared ranges (log WARN for violations, don't block)
    4. Check DATA_CONFIDENCE column is present and non-null
    5. Check h3_id column uses H3 resolution 8
    Write — then record conformance pass/fail to h3_ingest_log.
    """
```

Range violations produce a warning (not a block) — a sensor legitimately reporting a value outside expected range is still useful data. Missing required columns block the write.

#### Conformance dashboard panel (stretch)

A minimal tab in the review dashboard showing per-driver conformance status: last conformance check timestamp, pass/fail, failure messages, and per-signal data quality distributions. Useful during driver development and after upgrading a driver package.

#### `h3_ingest_log` schema extension

Add columns: `conformance_ok BOOLEAN`, `conformance_failures TEXT` (JSON list of failure messages). Populated by `validated_write_signals()` on every fetch.

**Acceptance criteria:**
- A driver that writes a DataFrame missing `DATA_CONFIDENCE` has its write blocked, error logged
- A driver that writes values outside declared range gets a logged WARNING but write succeeds
- `h3_ingest_log` records conformance status for every driver fetch
- A malformed third-party driver that produces strings for a float column is caught before writing

---

### Phase 5 — Community Driver Catalogue (Future)

**Goal:** Make it easy for other cities and operators to discover and share drivers. This is the analog of Red Hat's Hardware Catalogue or Ubuntu Certified.

**Scope (not on the critical path):**

- A `drivers.airos.city` hosted YAML listing known community drivers with: domain, package name, PyPI URL, tested AirOS version range, submitter, city deployments confirmed, and an "AirOS Compatible" badge
- A GitHub Actions workflow in the `airos-drivers-contrib` repo that runs `conformance_check()` against a minimal test store on every PR — passing this is the "certification" gate for the community list
- A `airos driver search <keyword>` CLI command that queries the catalogue
- Version pinning recommendations in `drivers_registry.yaml` when installing from the catalogue

This phase does not block any of Phases 1–4.

---

## File Map — What Gets Created or Changed

| File | Action | Phase |
|------|--------|-------|
| `urban_platform/sdk/__init__.py` | Create | 1 |
| `urban_platform/sdk/driver_protocol.py` | Create | 1 |
| `urban_platform/sdk/base_driver.py` | Create | 1 |
| `urban_platform/sdk/driver_types.py` | Create | 1 |
| `urban_platform/sdk/driver_loader.py` | Create | 3 |
| `urban_platform/sdk/conformance.py` | Create | 4 |
| `urban_platform/h3_knowledge/ingestor.py` | Refactor dispatch table | 3 |
| `urban_platform/h3_knowledge/writer.py` | Wrap write_signals with gate | 4 |
| `urban_platform/h3_knowledge/schema.py` | Add conformance columns to h3_ingest_log | 4 |
| `data/config/drivers_registry.yaml` | Create | 3 |
| `tools/driver-template/` | Create | 2 |
| `packages/airos-driver-air/` … × 14 | Create | 2 |
| `docs/developer/ADD_DATA_SOURCE.md` | Update: add packaging section | 2 |
| `docs/developer/DRIVER_CERTIFICATION.md` | Create: conformance spec | 4 |
| `review_dashboard/components/conformance_panel.py` | Create | 4 (stretch) |

---

## Sequencing and Priorities

```
Phase 1 (Interface)  ──► Phase 2 (Packaging)  ──► Phase 3 (Discovery)  ──► Phase 4 (Gate)
     ▲                                                                            │
     │                                              Phase 5 (Catalogue) ◄────────┘
     │                                              (can start in parallel after P3)
     │
     └── Phase 1 can ship as a PR with no runtime impact.
         Phase 2 is additive. Phase 3 is the first runtime change.
         Phase 4 is the conformance guarantee.
```

**Recommended order for a small team:**

1. **Phase 1** — one PR, ~2 days. Zero runtime risk. Establishes the contract that all later phases depend on.
2. **Phase 3 (loader only)** — implement `driver_loader.py` and `drivers_registry.yaml` without packaging, by having in-tree drivers register themselves directly. This unlocks the registry control before the full packaging migration.
3. **Phase 2** — migrate in-tree drivers to packages. Can be done one domain at a time as background work.
4. **Phase 4** — adds the conformance gate. Safe to ship because the gate only blocks writes with genuinely missing required columns, which should never happen for in-tree drivers.
5. **Phase 5** — community, after the above are stable.

---

## Stability Commitment

Once Phase 1 ships, the `H3DataSourceDriver` Protocol is the public API surface for all third-party drivers. Breaking changes require:

1. A deprecation notice in the release notes
2. A minor version bump (for additions) or major version bump (for removals/renames)
3. A migration guide in `docs/developer/`

Specifically, these fields are **stable from Phase 1 onward:**

- `domain: str`
- `cadence_hours: float`
- `produces_assessments: bool`
- `fetch(city_id, bbox, *, force) -> int`
- `conformance_check() -> ConformanceResult`

These fields are **advisory and may evolve:**

- `signal_names: list[str]`
- `data_sources: list[str]`

---

## How This Compares to the Linux Model

| Linux kernel | AirOS (this plan) |
|---|---|
| LKML review = certification | `conformance_check()` pass + community catalogue PR review |
| `MODULE_LICENSE()` macro | `signals.yaml` declaration in each driver package |
| Module signing (`CONFIG_MODULE_SIG`) | `drivers_registry.yaml` allowlist (local) + PyPI trust (distribution) |
| DKMS — out-of-tree, kernel-version-aware | `airos.drivers` entry points + `version_pin` in registry |
| Red Hat HCL / Ubuntu Certified | Phase 5 community catalogue at `drivers.airos.city` |
| Intentional ABI instability (Linus's law) | Stable Protocol from Phase 1; breaking = major version |

The key difference: Linux deliberately breaks out-of-tree modules because in-kernel code is the highest-quality path. AirOS inverts this — third-party drivers are a first-class deployment path, so the Protocol must be stable.
