# Program Reporting state demo (Phase 1)

This is a **fixture-based** Program Reporting example: it loads **two** synthetic city submissions and produces **two** review packets plus a simple **state monitoring summary** using `urban_platform.applications.program_reporting.review_packets`.

## What it is

- **Declarative** deployment profile + empty provider registry + application registry stub.
- **No** automated fund release, finance system integration, evidence/photo/geo workflows, signed envelopes, or reference-catalog pull/cache.
- **Synthetic** data only (`specifications/examples/program_reporting/city_program_submission.sample.json` and `city_program_submission_city_b.sample.json`).

## Running the fixture path

Validate:

```bash
python tools/airos_cli.py deployment validate deployments/examples/program_reporting_state_demo
```

Run (writes under `data/outputs/deployments/program_reporting_state_demo/`):

```bash
python tools/airos_cli.py deployment run deployments/examples/program_reporting_state_demo
```

Outputs:

- `fund_release_review_packets.json` — built from two city submission fixtures, schema-validated.
- `state_program_summary.json` — state-level monitoring summary (demo-only; no schema yet) including:
  - financial totals (approved/released/spent + overall utilization)
  - city financial progress rows + city program progress rows
  - action items for state reviewers (queue for authorized review vs request clarification)
- `deployment_run_summary.json` — run metadata and warnings.

## Future work

- Full state–city submission transport, dashboards, catalog distribution/TTL, and expanded review workflows are **out of scope** for this demo folder.
