from __future__ import annotations

from pathlib import Path

import pandas as pd

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file


def _example(path: str) -> Path:
    return (SPEC_ROOT / "examples" / "flood" / path).resolve()


def test_flood_provider_examples_validate_against_provider_contracts() -> None:
    v_rain = validator_for_schema_file(str((SPEC_ROOT / "provider_contracts" / "rainfall_observation_feed.v1.schema.json").resolve()))
    v_inc = validator_for_schema_file(str((SPEC_ROOT / "provider_contracts" / "flood_incident_feed.v1.schema.json").resolve()))
    v_ast = validator_for_schema_file(str((SPEC_ROOT / "provider_contracts" / "drainage_asset_feed.v1.schema.json").resolve()))

    import json

    v_rain.validate(json.loads(_example("rainfall_observation.sample.json").read_text(encoding="utf-8")))
    v_inc.validate(json.loads(_example("flood_incident.sample.json").read_text(encoding="utf-8")))
    v_ast.validate(json.loads(_example("drainage_asset.sample.json").read_text(encoding="utf-8")))


def test_flood_ingestion_normalizes_without_losing_provenance() -> None:
    from urban_platform.connectors.flood.ingest_file import (
        ingest_drainage_asset_feed_json,
        ingest_flood_incident_feed_json,
        ingest_rainfall_observation_feed_json,
    )

    obs, _ = ingest_rainfall_observation_feed_json(json_path=_example("rainfall_observation.sample.json"))
    assert isinstance(obs, pd.DataFrame)
    assert len(obs) >= 1
    assert {"observation_id", "entity_id", "observed_property", "value", "unit", "timestamp", "source", "quality_flag"}.issubset(set(obs.columns))
    assert "provenance" in obs.columns
    assert obs["provenance"].notna().any()

    events, _ = ingest_flood_incident_feed_json(json_path=_example("flood_incident.sample.json"))
    assert isinstance(events, pd.DataFrame)
    assert len(events) >= 1
    assert {"event_id", "event_type", "spatial_unit_id", "timestamp", "severity", "confidence", "recommended_action"}.issubset(set(events.columns))
    assert "provenance" in events.columns

    entities, _ = ingest_drainage_asset_feed_json(json_path=_example("drainage_asset.sample.json"))
    assert isinstance(entities, pd.DataFrame)
    assert len(entities) >= 1
    assert {"entity_id", "entity_type", "geometry", "attributes", "source", "confidence"}.issubset(set(entities.columns))
    assert entities["attributes"].apply(lambda x: isinstance(x, dict) and "provenance" in x).any()

