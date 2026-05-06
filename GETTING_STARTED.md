## Getting started (bridge doc)

This is a **short bridge document**. The canonical onboarding docs are:

- **Start here (repo orientation)**: [`docs/START_HERE.md`](docs/START_HERE.md)
- **Beginner developer guide**: [`docs/BEGINNER_DEVELOPER_GUIDE.md`](docs/BEGINNER_DEVELOPER_GUIDE.md)
- **Pilot runtime (Core API + store + dashboard API mode)**: [`docs/PILOT_RUNTIME_QUICKSTART.md`](docs/PILOT_RUNTIME_QUICKSTART.md)
- **CLI deployment demos (fixtures → outputs)**: [`docs/DEPLOYMENT_QUICKSTART.md`](docs/DEPLOYMENT_QUICKSTART.md)

### Legacy local air-pollution pipeline note

AirOS previously had a top-level `src/` package. That package has been removed; the legacy AQ implementation lives under:

- `urban_platform/applications/air_pollution/legacy_pipeline.py`

For current code layout and migration notes, see:

- [`specifications/ARCHITECTURE_NOTE.md`](specifications/ARCHITECTURE_NOTE.md)

