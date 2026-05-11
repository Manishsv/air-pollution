# Getting Started with AirOS

AirOS is an open urban intelligence platform that ingests sensor, satellite, and forecast data across 14 city domains (air, flood, heat, water, fire, noise, and more), analyses it cell by cell on an H3 hexagonal grid, and surfaces decision-ready insights through a review dashboard and LLM-backed agents. It is designed for city teams, civic-tech developers, and researchers who want a structured way to monitor urban conditions and support human decision-making — without replacing it.

---

## The Four Components

**AirOS Core (the OS)** is the runtime foundation. It manages an H3 Knowledge Store (SQLite in WAL mode), a Rules Registry that holds configurable thresholds per domain, and a Scheduler that orchestrates ingest runs and agent sweeps on a cadence you control. A conformance layer checks incoming data against those rules before it is committed to the store. You rarely touch the Core directly — it runs in the background, keeping data clean and up to date.

**AirOS Data Sources (Drivers)** are the connectors and ingestors that bring data into the Knowledge Store. Each of the 14 supported domains has its own ingestor (`airos/drivers/store/*_ingestor.py`) and, where needed, a raw connector (`airos/drivers/connectors/`). Weather and air quality forecasts come from OpenMeteo and require no API key. Optional integrations — real AQ sensor data via AQICN, satellite-derived layers (heat, flood, green space) via Google Earth Engine — activate when you supply the corresponding keys in `.env`.

**AirOS Decision Support System (the App)** is the intelligence layer. An H3 Expert Agent (backed by an LLM you choose) analyses each grid cell by synthesising signals across all active domains and writes a structured observation into the Knowledge Store. A City Pattern Agent runs a sweep across the highest-risk cells and produces a city-level summary. Both outputs surface in a Streamlit review dashboard that lets city analysts examine conditions, compare domains, and export findings. The agents inform; humans decide.

**AirOS Network** is the design for cross-instance communication between AirOS deployments — for example, sharing flood alerts between a city and its upstream watershed authority. The network uses a domain-agnostic contract envelope so any deployment can relay structured observations to any other. The specification is complete; runtime implementation is on the roadmap (it does not run today).

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11 | 3.12 may work but is not tested |
| pip | any recent | comes with Python |
| venv | built-in | used to isolate dependencies |
| Ollama | latest | **optional** — only needed for local LLM; see Configuration |

You do not need Docker, Node.js, or a database server for a local development setup.

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url> AirStack
cd AirStack

# 2. Create and activate a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

That is all. SQLite databases are created automatically on first run.

---

## Configuration

Copy the example environment file and open it in your editor:

```bash
cp .env.example .env
```

The most important section is the LLM configuration. Pick one of the three options below and fill in the corresponding lines.

### Option A — Ollama (free, local, no internet required)

Best for development and privacy-sensitive work. You need [Ollama](https://ollama.com) installed and a model pulled before starting.

```bash
# Pull a model first (one-time)
ollama pull llama3

# Then in .env:
LLM_PROVIDER=ollama
LLM_API_KEY=ollama
LLM_MODEL=llama3
```

### Option B — Groq (free cloud tier, fast)

Groq offers a generous free tier. Get a key at [console.groq.com](https://console.groq.com).

```bash
LLM_PROVIDER=groq
LLM_API_KEY=your-groq-api-key
LLM_MODEL=llama3-8b-8192
```

### Option C — OpenAI

```bash
LLM_PROVIDER=openai
LLM_API_KEY=your-openai-api-key
LLM_MODEL=gpt-4o-mini
```

Other supported providers: `together`, `openrouter`. The interface is identical — set `LLM_PROVIDER`, `LLM_API_KEY`, and `LLM_MODEL`.

### Optional keys

```bash
# Real air quality sensor data (AQICN)
AQICN_TOKEN=your-token

# Satellite-derived layers — heat, flood, green space (Google Earth Engine)
GEE_PROJECT=your-gee-project-id
```

Leave these blank if you do not have them. AirOS will fall back to OpenMeteo forecasts and skip satellite domains gracefully.

---

## Running for the First Time

The easiest entry point is the review dashboard. It reads whatever is already in the Knowledge Store and requires no LLM call.

```bash
streamlit run airos/network/dashboard/app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

On first run the Knowledge Store will be empty, so the dashboard will show placeholder states for each domain panel. That is expected — you need to run the pipeline at least once to populate it.

---

## Running the Full Pipeline

The full pipeline runs ingest for all active domains and then triggers an agent sweep over the highest-risk H3 cells.

```bash
python main.py --step scheduler
```

This will:
1. Call each domain ingestor in sequence, pulling data from OpenMeteo (and any other sources you configured).
2. Write H3-level observations into the Knowledge Store.
3. If `SCHEDULER_AGENT=true` in your `.env`, invoke the H3 Expert Agent on the top `SCHEDULER_TOP_N` cells (default 10).
4. Write agent summaries back into the store.

A typical full run takes 30–90 seconds depending on network speed and LLM latency.

### Other useful commands

```bash
# Run the agent directly on a specific city, top 5 risk cells
python -m airos.agents.h3_expert --city bangalore --top-risk 5

# Run conformance checks only (no ingest, no agents)
python main.py --step conformance
```

### Scheduler environment variables

```bash
SCHEDULER_AGENT=true     # set to false to skip the agent sweep
SCHEDULER_TOP_N=10       # how many cells per sweep
```

---

## Verifying It Works

After a successful pipeline run, reload the dashboard at [http://localhost:8501](http://localhost:8501). You should see:

- **Domain panels** (Air, Heat, Flood, etc.) populated with cell-level readings and colour-coded risk tiers.
- **Agent observations** in the right-hand panel, one entry per analysed cell, showing the cross-domain synthesis the LLM produced.
- **City summary** at the top if a City Pattern Agent sweep completed.

If a domain panel is blank, check the terminal output from `main.py` — it will tell you which ingestor failed and why (usually a missing API key or a network timeout).

If agent observations are missing, confirm that `SCHEDULER_AGENT=true` is set in `.env` and that your LLM provider credentials are correct. Running `python -m airos.agents.h3_expert --city bangalore --top-risk 2` directly will give you detailed output including any LLM errors.

---

## Next Steps

Once the system is running, here is where to go depending on what you want to do next:

| Goal | Document |
|---|---|
| Tune thresholds, switch LLM provider, add a city | [Configuration Guide](docs/developer/CONFIGURATION.md) |
| Add a new data source or domain | [Add a Data Source](docs/developer/ADD_DATA_SOURCE.md) |
| Build a new decision support app on top of AirOS | [Build Your First AirOS App](docs/developer/BUILD_YOUR_FIRST_AIR_OS_APP.md) |
| Understand how the agents reason | [Intelligence Methodology](docs/platform/INTELLIGENCE_METHODOLOGY.md) |
| Understand the full system architecture | [Architecture Overview](docs/platform/OVERVIEW.md) |
| Deploy AirOS to a city | [Deployment Quickstart](docs/developer/DEPLOYMENT_QUICKSTART.md) |

If you are new to the codebase and want a map of all available guides, start at [docs/developer/START_HERE.md](docs/developer/START_HERE.md).
