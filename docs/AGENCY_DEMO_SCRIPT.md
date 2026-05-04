# AirOS — agency pitch demo script (10–15 minutes)

## 1) Purpose

This is a **practical, demo-ready** walkthrough of **AirOS** as a **governed, registry-driven** layer for urban data and decision support. It uses the **published Docker image** and the **flood fixture demo** so you can show value without local Python setup, live agency feeds, or production infrastructure.

**Related:** technical Docker details and troubleshooting live in [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md).

**Optional state-level demo:** Program Reporting Phase 1 (two synthetic cities → review packets + state summary; **no** automated disbursement). Run:

```bash
python tools/airos_cli.py deployment run deployments/examples/program_reporting_state_demo
streamlit run review_dashboard/app.py
```

Then open the **Program Reporting** tab in the review dashboard. Design context: [`docs/PROGRAM_REPORTING_AND_FUND_RELEASE.md`](PROGRAM_REPORTING_AND_FUND_RELEASE.md).

---

## 2) Audience

- Agency heads and programme leadership  
- City administrators and municipal corporations  
- State urban departments  
- Pollution control boards  
- Disaster management teams  
- Technical teams and system integrators  

---

## 3) Core message (use this framing)

**AirOS does not replace agency systems.** It gives agencies a **shared, governed** way to connect data, AI, and action across **fragmented** urban institutions—**starting small** and **scaling safely**, with contracts, conformance, and review-first outputs rather than hidden automation.

---

## 4) What this demo proves (today)

- AirOS can run from **Docker** without a local Python install.  
- **AirOS Core** health can be checked (`doctor`).  
- **Specifications, contracts, examples, registries, and deployment examples** can be validated in one step (`conformance`).  
- A **registry-driven flood demo** can run from **deployment configuration** (fixture JSON only—no external APIs).  
- Outputs are **contract-shaped** JSON: dashboard payload, decision packets, field verification tasks, plus a run summary.  
- Outputs carry explicit **warnings** (e.g. fixture/demo data, decision support only, field verification required, no emergency orders).  
- The **review dashboard** can be opened against persisted outputs.  
- A **new deployment workspace** can be initialized from a **runnable example** (`deployment init --from-example`), then validated and run under a new `deployment_id`.  

---

## 5) What this demo does not claim

Say this clearly before questions:

- **Not** a production deployment or HA operations stack.  
- **Not** live agency or citizen data; the flood path uses **repository fixtures** only.  
- **Not** emergency automation, enforcement, or autonomous orders.  
- **Not** a full dynamic plugin runtime—supported demos use an **explicit allowlist**, not arbitrary registry-driven code loading.  
- **Not** cross-agency network transport or federation runtime in this demo.  

---

## 6) Demo prerequisites

- **Docker** installed and working  
- **Internet** access to pull `ghcr.io/manishsv/air-os:latest`  
- A **terminal**  
- A **web browser**  
- **10–15 minutes** (plus optional Q&A)  

---

## 7) Demo commands (run in order)

Work from a dedicated folder so cleanup is easy.

### A. Prepare folder

```bash
mkdir -p airos-demo/airos-data
cd airos-demo
```

### B. Pull image

```bash
docker pull ghcr.io/manishsv/air-os:latest
```

### C. Run health check

```bash
docker run --rm ghcr.io/manishsv/air-os:latest doctor
```

**Talking point:** This shows AirOS Core can start and **see** its required **specifications** and **deployment example** layout inside the image—basic operability before any domain run.

### D. Run conformance

```bash
docker run --rm ghcr.io/manishsv/air-os:latest conformance
```

**Talking point:** This is the **governance gate**: schemas, **provider/consumer contracts**, examples, and manifest wiring are checked together. Agencies can treat conformance as the “green light” before trusting outputs from a build or deployment.

### E. Run flood demo

```bash
docker run --rm \
  -v "$(pwd)/airos-data:/app/data" \
  ghcr.io/manishsv/air-os:latest \
  deployment run deployments/examples/flood_local_demo
```

**Talking point:** This runs a **configured deployment**: `deployment_profile` + **provider registry** + **application registry** + flood domain logic. **No external APIs** are required for this path—good for a controlled first conversation about governance before data-sharing complexity.

### F. Inspect outputs

```bash
find airos-data/outputs/deployments/flood_local_demo -maxdepth 1 -type f | sort
cat airos-data/outputs/deployments/flood_local_demo/deployment_run_summary.json
```

**Expected files:**

- `flood_risk_dashboard_payload.json`  
- `flood_decision_packets.json`  
- `flood_field_verification_tasks.json`  
- `deployment_run_summary.json`  

**Talking point:** The platform produces **review-ready** artifacts—dashboard-oriented payloads, **decision packets**, and **field verification tasks**—not automatic directives. The summary JSON includes explicit **warnings** (e.g. fixture/demo data, decision support only, field verification required, no emergency orders). Tie that to **human review** and **agency authority**.

### G. Open dashboard

```bash
docker run --rm \
  -p 8501:8501 \
  -v "$(pwd)/airos-data:/app/data" \
  --entrypoint streamlit \
  ghcr.io/manishsv/air-os:latest \
  run review_dashboard/app.py --server.address=0.0.0.0 --server.port=8501
```

Open: **http://localhost:8501**

**Talking point:** The dashboard is a **review surface**. Domain meaning and safety live in **contracts**, **domain specs**, and **registry-linked applications**—not in ad-hoc UI logic. Keep this terminal **running** while people browse; use `docker ps` to confirm the port mapping.

**Note:** `--entrypoint streamlit` is required because the default image entrypoint is the **AirOS CLI** (`python tools/airos_cli.py`). See [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md) for detail.

### H. Initialize a new runnable deployment from the example

Use a **second terminal**, or stop the dashboard container first (`Ctrl+C`).

```bash
rm -rf airos-runtime
mkdir -p airos-runtime/deployments airos-runtime/data

docker run --rm \
  -v "$(pwd)/airos-runtime/deployments:/app/deployments/local" \
  -v "$(pwd)/airos-runtime/data:/app/data" \
  ghcr.io/manishsv/air-os:latest \
  deployment init \
    --from-example flood_local_demo \
    --deployment-id demo_city_flood \
    --deployment-name "Demo City Flood" \
    --output-dir deployments/local/demo_city_flood \
    --force
```

### I. Validate copied deployment

```bash
docker run --rm \
  -v "$(pwd)/airos-runtime/deployments:/app/deployments/local" \
  -v "$(pwd)/airos-runtime/data:/app/data" \
  ghcr.io/manishsv/air-os:latest \
  deployment validate deployments/local/demo_city_flood
```

### J. Run copied deployment

```bash
docker run --rm \
  -v "$(pwd)/airos-runtime/deployments:/app/deployments/local" \
  -v "$(pwd)/airos-runtime/data:/app/data" \
  ghcr.io/manishsv/air-os:latest \
  deployment run deployments/local/demo_city_flood
```

**Talking point:** This shows how a city or agency can **start from a known-good template**, keep **contracts and fixtures aligned**, then progressively replace demo fixtures with **authorized** real providers under the same registry model—without skipping conformance.

Optional inspection:

```bash
find airos-runtime/data/outputs/deployments/demo_city_flood -maxdepth 1 -type f | sort
```

---

## 8) Agency-specific pitch variations (short)

### Disaster management

AirOS helps turn **rainfall, incidents, drainage assets**, and similar signals into **review packets** and **field verification tasks**—so coordination stays evidence-led and human-accountable.

### Municipal corporations

AirOS can help align **ward-level risk**, **assets**, **service context**, and **field work** across domains when each is expressed through **contracts** and **deployment registries**—without forcing one legacy system to own everything.

### Pollution control boards

AirOS can combine **AQ observations**, **weather**, **land use / fire proxies**, and future traffic/industry signals into **reviewable** hotspot-style intelligence—with explicit provenance and safety language, not covert automation.

### State urban departments

AirOS **standardizes contracts and review workflows** across cities while respecting that **each node** may own data and decisions—reducing bespoke integration drift without pretending one monolith runs all cities.

### System integrators / developers

AirOS exposes a **governed integration model**: **provider contracts**, **consumer contracts**, **registries**, **deployment profiles**, **conformance**, and a **CLI**—so integrations are explainable, testable, and auditable.

---

## 9) Questions to ask after the demo

- Which **domain** should we pilot first (flood, air quality, mobility, …)?  
- Which **datasets** can be shared first under an open-data or pilot MoU—without sensitive personal or enforcement data?  
- Which outputs must stay **review-only** in the first 30–90 days?  
- Which **agency** has **decision authority** for actions suggested by analytics?  
- What **field verification workflow** already exists (WhatsApp, ticketing, GIS teams)?  
- What data must **never leave** the agency boundary (resident PII, restricted enforcement files)?  
- What would **prove value** in 30 days (fewer duplicate dashboards, faster incident packets, clearer audit trail)?  

---

## 10) Troubleshooting during the demo

- **Image pull fails:** check network/VPN; retry `docker pull ghcr.io/manishsv/air-os:latest`.  
- **Dashboard cannot be reached:** ensure the Streamlit `docker run` is **still running**; include **`-p 8501:8501`** and **`--entrypoint streamlit`**; run `docker ps`.  
- **`--from-example` not recognized:** image may be stale—`docker pull` again or remove and re-pull the image (see [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md)).  
- **Outputs missing on disk:** ensure **`-v "$(pwd)/airos-data:/app/data"`** (or `airos-runtime/data`) is on every run that should persist files.  
- **Port 8501 in use:** stop the other process or map a different host port, e.g. `-p 8502:8501`, and open `http://localhost:8502`.  

---

## 11) Cleanup

```bash
cd ..
rm -rf airos-demo
```

---

## 12) Further reading

- [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md) — Docker quickstart, dashboard entrypoint, troubleshooting  
- [`docs/DEPLOYMENT_QUICKSTART.md`](DEPLOYMENT_QUICKSTART.md) — clone + venv path for engineers  
- [`docs/PLUGIN_AND_REGISTRY_ARCHITECTURE.md`](PLUGIN_AND_REGISTRY_ARCHITECTURE.md) — registries and contracts  
- [`docs/URBAN_CONTEXT_INDIA.md`](URBAN_CONTEXT_INDIA.md) — why governance and open-data-first phases matter  
