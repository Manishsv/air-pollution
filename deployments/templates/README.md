# Deployment templates (placeholders only)

These files are **templates** for forward deployment teams. They contain **no real city/agency data**, **no secrets**, and **no credentials**.

## How to use

1. Copy `deployments/templates/` into a **private deployment repository** or secure configuration workspace.
2. Replace placeholder values (`TEMPLATE`, `PLACEHOLDER`, `EXAMPLE`) with deployment-specific details.
3. Validate your deployment config before running anything:

```bash
python tools/deployment_runner/validate_deployment.py --deployment <path>
```

4. Keep operational profiles (endpoints, MoUs, staff roles, restricted datasets) out of the public AirOS repository unless explicitly authorized.

## Deployment registries are overlays

AirOS Core can ship **core/default** registries, and a deployment can supply **deployment-scoped overlay registries** that enable only a **subset** of providers, applications, domains, and network adapters relevant to that city/agency/state.

Deployment registries may reference **private/internal providers** or internal infrastructure by **configuration references only** (e.g. `configuration_ref: DEPLOYMENT_LOCAL:...`) without committing sensitive details to this repo.

## Templates in this folder

- `deployment_profile.yaml` — what this deployment is, who owns it, what is enabled
- `provider_registry.yaml` — enabled provider plugins (no secrets; contracts + module references only)
- `application_registry.yaml` — enabled application/consumer plugins (presentation panels optional)
- `network_adapter_registry.yaml` — enabled transport adapters (email/webhook/file drop/event bus; no credentials)
- `agency_node_profile.yaml` — agency node identity, contracts supported, policies referenced
- `network_participant_profile.yaml` — participant endpoints and authorization policy references (no endpoint secrets)
- `jurisdiction_profile.yaml` — jurisdiction identifiers and geometry references (no sensitive geometry dumps)
- `data_sharing_policy.yaml` — envelope-level sharing policy references (domain-agnostic)

See also:

- `docs/PLUGIN_AND_REGISTRY_ARCHITECTURE.md`
- `docs/CITY_PROFILE_TEMPLATE.md`
- `docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`
