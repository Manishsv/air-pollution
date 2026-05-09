# City profile template (forward deployment)

Forward deployment engineers use a **city profile** to record **local context**—priorities, data availability, institutional maturity, and constraints—**without** encoding that context as hard-coded assumptions in the AirOS platform repository.

This document explains the **template structure**. It does **not** contain real city data.

## Where the template lives

- **Copy source:** `deployments/templates/city_profile/`
- **Files:**
  - `city_profile.yaml` — identity, boundaries summary, maturity, stakeholders, field capacity, risks, next bounded task
  - `enabled_domains.yaml` — which domains are enabled or piloted vs under evaluation + **priority ordering**
  - `data_sources.yaml` — available sources, open-data openings, municipal integrations **as planning records** (still specs-first at build time)
  - `deployment_notes.md` — free-form operational notes for the deployment squad
  - `README.md` — how to instantiate the template

## How to use it

1. **Copy** the whole `deployments/templates/city_profile/` directory to a location appropriate for **operational confidentiality**—typically a **private deployment repository**, client workspace, or secure document store **not** committed to the public AirOS repo with production details.
2. **Replace** all `PLACEHOLDER` / `TEMPLATE` / `CITY_ID_PLACEHOLDER` values with real information **only** in that private context.
3. **Keep** the public AirOS repo free of **sensitive** jurisdictional data (credentials, unpublished MoUs, personal contacts, restricted geometry exports, etc.). Reference public catalog entries (e.g. `docs/DATA_SOURCE_CATALOG.md`) when possible.
4. **Align** technical work with **specifications** under `specifications/`—the city profile is **coordination and scoping**, not a substitute for provider/domain/consumer contracts.
5. **Drive** the next engineering step from **one bounded task** at a time (`next_recommended_bounded_task` in `city_profile.yaml`), consistent with `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`.

## What agents and contributors should assume

- **No** city-specific behavior should be baked into shared code paths based solely on this template; profiles are **deployment context**.
- **New domains** still require specs, manifests, examples, conformance, and tests per `AGENTS.md`.
- Domain **maturity** tooling (`tools/ai_dev_supervisor/domain_checklists/`) is separate from city profiles; use both for planning.

## Related reading

- `docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md` — node-first topologies; city profile is only one slice of deployment context
- `docs/AGENCY_NODE_MODEL.md` — **agency node** fields (complement city profile with agency/jurisdiction/network participant views)
- `docs/CROSS_AGENCY_COORDINATION_LAYER.md` — **AirOS Network Layer** (contract-aware, domain-agnostic coordination; email as optional transport adapter)
- `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md` — city profile before city-specific work
- `docs/AI_COE_OPERATING_STRATEGY.md` — forward deployment + CoE model
- `docs/DATA_SOURCE_CATALOG.md` — source discovery and risk framing
- `specifications/ARCHITECTURE_NOTE.md` — platform layout vs deployment artifacts
