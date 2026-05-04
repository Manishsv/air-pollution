# <deployment_example_name>

## What this is

- **Domain**: `<domain_name>`
- **Deployment ID**: `<deployment_id>`
- **Data**: Fixture / demo only (`specifications/examples/...`).
- **Safety**: Outputs are **review support only** — not automated orders, enforcement, or disbursement.

## Files

| File | Role |
|------|------|
| `deployment_profile.yaml` | Enables domains + points at registries |
| `provider_registry.yaml` | Which incoming provider contracts could be enabled |
| `application_registry.yaml` | Which outputs (consumer contracts / builders) are declared |

## Validate (does not run connectors)

```bash
python tools/airos_cli.py deployment validate deployments/examples/<deployment_example_name>
```

## Run (if wired in the allowlisted POC runner)

```bash
python tools/airos_cli.py deployment run deployments/examples/<deployment_example_name>
```

Replace `<deployment_example_name>` and `<deployment_id>` after you copy this template.
