# AirOS beginner developer guide

If you are comfortable with web forms, REST APIs, JSON request/response bodies, and simple backend functions—but AirOS words like “provider contract” feel heavy—this guide is for you. The full architecture story lives in [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md); **start here** for the web-dev mental model, then graduate to that doc.

**Templates you can copy:** [`docs/developer_templates/`](developer_templates/) (starters only; not wired into runtime).

**New:** follow the guided tutorial: [`docs/BUILD_YOUR_FIRST_AIR_OS_APP.md`](BUILD_YOUR_FIRST_AIR_OS_APP.md)

---

## 1) AirOS in one sentence

**AirOS helps you take city data, validate it against a known shape, convert it into review-ready outputs, and show it safely to officials.**

---

## 2) The simplest mental model (a “mini-app”)

Think of every AirOS vertical slice as a small product with these pieces:

| Piece | Web-dev analogy |
|-------|-----------------|
| **Input shape** | Form fields or API request body schema |
| **Sample input** | Saved “POST body” JSON in the repo (fixture) |
| **Output shape** | API response schema or “dashboard DTO” |
| **Sample output** | Example response JSON reviewers can trust in CI |
| **Builder function** | Backend handler: valid input → valid output |
| **Deployment config** | Feature flags: which inputs/outputs are turned on for a city run |
| **Optional dashboard panel** | Read-only UI that **displays** the output (no hidden rules) |

---

## 3) Translate AirOS terms

| AirOS term | Familiar web-dev term |
|------------|------------------------|
| **Provider contract** | Input form / request body / **incoming JSON shape** you allow |
| **Consumer contract** | Output form / response body / **payload your UI or API returns** |
| **Fixture** | **Sample data file** (like `fixtures/user.json` in tests) |
| **Manifest** | Central **registry of which schemas & examples exist** in the repo |
| **Registry** (deployment YAML) | **Config** listing which providers/apps are enabled for this deployment |
| **Platform object** | A **standard record type** everyone shares (like a canonical `User` DTO—but for city data) |
| **Conformance** | **CI validation**: “does this JSON match its schema, and are references wired?” |

---

## 4) Provider contract = “what we accept in”

**Example (conceptual):** a city sends “streetlight readings” as JSON. You define the allowed shape once (like an OpenAPI request schema).

Sketch (not a real repo file):

```json
{
  "asset_id": "sl_ward12_001",
  "observed_at": "2026-05-01T12:00:00Z",
  "lamp_on": true,
  "lux_estimated": 12.5
}
```

The **provider contract** is the schema that answers: “If this JSON is valid, we agree on what each field means.”

---

## 5) Consumer contract = “what we hand out”

**Example:** reviewers need a **summary payload** for a dashboard—not raw rows.

Sketch:

```json
{
  "payload_id": "streetlight_summary_demo_001",
  "generated_at": "2026-05-01T12:05:00Z",
  "warnings": ["fixture_demo_only", "human_review_required"],
  "blocked_uses": ["automatic_work_order_dispatch"],
  "summary": {
    "area_id": "ward_12",
    "lamps_reported_on": 42,
    "lamps_reported_off": 3
  }
}
```

The **consumer contract** is the schema for that response: safe for UI, explicit about warnings, and clear about **what must not happen automatically**.

---

## 6) Platform objects & reference catalogs (plain language)

- **Observation** — a **measured value** at a time (sensor reading, counter, telemetry point).
- **Event** — **something that happened** (“outage detected”, “threshold crossed”) with a time and context.
- **Entity** — a **thing** you track (asset, place, parcel). Treat as **non-PII by default** unless your program is authorized to handle identities.
- **Feature** — a **calculated value** built from observations/entities (rollups, scores, deltas)—like a computed column or materialized view field.
- **Reference catalog** — an **official code list** (“ward codes”, “program codes”, “reporting periods”) so every system uses the same IDs—like an enum table published by the state.

---

## 7) Where code and config go

| What | Where |
|------|--------|
| Input/output **schemas** | `specifications/provider_contracts/`, `specifications/consumer_contracts/`, `specifications/platform_objects/` |
| **Sample JSON** | `specifications/examples/<domain>/` |
| **Builder** (input → output) | `urban_platform/applications/<domain>/` (and connectors/processing nearby) |
| **Dashboard display** | `review_dashboard/components/` (presentation only) |
| **Runnable demo config** | `deployments/examples/<name>/` |
| **“What’s registered?”** | `specifications/manifest.json` |

**Do not** put new cross-domain or new-domain core logic in legacy `src/`—see [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md).

---

## 7.5) AirOS SDK, early skeleton

AirOS has an early SDK skeleton under `urban_platform/sdk/` to make app/adaptor development easier.

- It’s an **internal module** in this repo (not a separate package yet).
- It provides stable helpers to validate fixtures and inspect app descriptors (metadata only).
- It does **not** enable dynamic plugins.

Example:

```python
from urban_platform.sdk import assert_fixture_valid, get_app_descriptor

assert_fixture_valid(
    "consumer_city_program_submission",
    "specifications/examples/program_reporting/city_program_submission.sample.json",
)

app = get_app_descriptor("program_reporting_review")
```

## Developer inspection commands

Read-only CLI helpers backed by the SDK:

```bash
python tools/airos_cli.py contracts list
python tools/airos_cli.py contracts show consumer_city_program_submission
python tools/airos_cli.py fixtures validate consumer_city_program_submission specifications/examples/program_reporting/city_program_submission.sample.json
python tools/airos_cli.py apps list
python tools/airos_cli.py apps show program_reporting_review
python tools/airos_cli.py apps explain program_reporting_review
python tools/airos_cli.py apps explain flood_risk_review
```

## Reference catalog discovery (read-only, local fixtures)

Reference catalogs provide shared codes and reference data (administrative units, program codes, reporting periods) so submissions and review outputs align consistently.

This repo currently exposes **local example catalogs only** (no live sync / pull / cache / signatures / federation).

```bash
python tools/airos_cli.py catalogs list
python tools/airos_cli.py catalogs show administrative_units_demo_in
```

## App scaffolding (safe)

Create a local starter folder for a new app (templates only; not registered or executable):

```bash
python tools/airos_cli.py apps scaffold heat_risk_review --domain-id heat_risk
python tools/airos_cli.py apps validate apps/heat_risk_review
python tools/airos_cli.py apps package apps/heat_risk_review --output-dir dist/apps
python tools/airos_cli.py apps inspect-package dist/apps/heat_risk_review-v1.zip
python tools/airos_cli.py catalog add-package dist/apps/heat_risk_review-v1.zip
python tools/airos_cli.py catalog list
python tools/airos_cli.py catalog show heat_risk_review
python tools/airos_cli.py adapters list
python tools/airos_cli.py adapters show openaq_air_quality_adapter
```

---

## 8) Toy example: “streetlight monitoring” (snippets only)

Imagine a city portal posts lamp status. You normalize to a generic **Observation**-like record, then build a **summary** for officials.

**Incoming (provider-shaped):**

```python
incoming = {
    "asset_id": "sl_ward12_001",
    "observed_at": "2026-05-01T12:00:00Z",
    "lamp_on": True,
}
```

**Backend builder (conceptual):**

```python
def build_streetlight_summary(readings: list[dict], *, generated_at: str) -> dict:
    on = sum(1 for r in readings if r.get("lamp_on") is True)
    off = sum(1 for r in readings if r.get("lamp_on") is False)
    return {
        "payload_id": "streetlight_summary_demo_001",
        "generated_at": generated_at,
        "warnings": ["fixture_demo_only", "human_review_required"],
        "blocked_uses": ["automatic_work_order_dispatch"],
        "summary": {"lamps_on": on, "lamps_off": off},
    }
```

This repo does **not** include a full streetlight vertical slice unless you add specs + conformance later—the point is the **shape of the work**, not a new feature.

---

## 9) Ten-step recipe (new vertical slice)

1. **Define input** — write a provider JSON Schema under `specifications/provider_contracts/`.
2. **Add sample input** — `specifications/examples/<domain>/…sample.json` (synthetic only).
3. **Define output** — consumer JSON Schema under `specifications/consumer_contracts/`.
4. **Add sample output** — example JSON that validates against that schema.
5. **Register in manifest** — add schema + example entries to `specifications/manifest.json`.
6. **Write builder** — pure Python in `urban_platform/applications/<domain>/` producing the consumer shape.
7. **Write tests** — load fixtures, assert `assert_conforms(...)` where the repo already does this.
8. **Add deployment example** — YAML under `deployments/examples/` when you have a runnable demo path.
9. **Run conformance** — `python main.py --step conformance` (and supervisor as in [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md)).
10. **Add dashboard panel** — read outputs, show human text + safety; hide raw JSON in expanders.

Starter files: [`docs/developer_templates/`](developer_templates/).

---

## 10) Common mistakes (avoid these)

- **Putting business logic in Streamlit** — UI should **render** payloads; rules live in builders/processing.
- **Skipping examples** — without fixtures, reviewers and CI cannot see what “good” looks like.
- **Forgetting manifest entries** — conformance won’t treat your schema/example as first-class.
- **Using raw JSON as the main UI** — officials need labels, next steps, and safety; JSON belongs in **technical** expanders.
- **Using real personal data in examples** — public repo examples must stay **synthetic**.
- **Writing outputs that sound like automated orders** — use **review support** language, `warnings`, and `blocked_uses` so nothing reads like an enforcement or disbursement decision.

---

## Next steps

- Deep dive: [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md)
- Specs-first culture: [`docs/SPECS_FIRST_DEVELOPMENT.md`](SPECS_FIRST_DEVELOPMENT.md)
- Copy-paste starters: [`docs/developer_templates/README.md`](developer_templates/README.md)
