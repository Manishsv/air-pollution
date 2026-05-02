# City profile template (no real city data)

This directory is a **blank template** for forward deployment teams. All identifiers and entries are **fictional placeholders**.

## Copy and customize

1. Copy this folder to a **private deployment** workspace or repository (recommended for real operational detail).
2. Edit `city_profile.yaml`, `enabled_domains.yaml`, and `data_sources.yaml` in that copy.
3. Use `deployment_notes.md` for narrative context (MoU status, workshop outcomes, local naming conventions) without putting secrets in git.
4. Read **`docs/CITY_PROFILE_TEMPLATE.md`** for full guidance.

## File roles

| File | Purpose |
|------|--------|
| `city_profile.yaml` | City identity, boundaries availability, maturity, stakeholders, field capacity, risks, next bounded task |
| `enabled_domains.yaml` | Enabled / pilot domains and **priority** ordering |
| `data_sources.yaml` | Data sources, open-data opportunities, planned authorized integrations |
| `deployment_notes.md` | Human-readable deployment log and constraints |

## Conformance and code

- Filling a city profile does **not** replace **specifications**, **manifest** entries, or **conformance**. It only documents **local** deployment intent.
- Do **not** commit production credentials, restricted datasets, or sensitive stakeholder PII into the public AirOS repository.
