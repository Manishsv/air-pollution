# Program Reporting state demo (Phase 1)

This is a **fixture-based** Program Reporting example: it documents how a state-side demo can load the repository **`city_program_submission`** sample and produce a **`fund_release_review_packet`** using `urban_platform.applications.program_reporting.review_packets`.

## What it is

- **Declarative** deployment profile + empty provider registry + application registry stub.
- **No** automated fund release, finance system integration, evidence/photo/geo workflows, signed envelopes, or reference-catalog pull/cache.
- **Synthetic** data only (`specifications/examples/program_reporting/city_program_submission.sample.json`).

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

- `fund_release_review_packet.json` — built from the city submission fixture, schema-validated.
- `deployment_run_summary.json` — run metadata and warnings.

## Future work

- Full state–city submission transport, dashboards, catalog distribution/TTL, and expanded review workflows are **out of scope** for this demo folder.
