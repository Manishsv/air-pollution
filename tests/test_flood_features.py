from __future__ import annotations

from urban_platform.specifications.conformance import SPEC_ROOT


def _ex(name: str) -> str:
    return str((SPEC_ROOT / "examples" / "flood" / name).resolve())


def test_build_flood_features_from_fixtures() -> None:
    from urban_platform.connectors.flood.ingest_file import (
        ingest_drainage_asset_feed_json,
        ingest_flood_incident_feed_json,
        ingest_rainfall_observation_feed_json,
    )
    from urban_platform.processing.flood.features import build_flood_feature_rows

    rain, _ = ingest_rainfall_observation_feed_json(json_path=_ex("rainfall_observation.sample.json"))
    inc, _ = ingest_flood_incident_feed_json(json_path=_ex("flood_incident.sample.json"))
    assets, _ = ingest_drainage_asset_feed_json(json_path=_ex("drainage_asset.sample.json"))

    feats, stats = build_flood_feature_rows(rainfall_obs=rain, incident_events=inc, drainage_entities=assets, generated_at="2026-05-01T18:30:00Z")

    assert len(feats) >= 1
    assert {"area_id", "generated_at", "rainfall_mm_per_hour", "incident_count", "drainage_asset_count", "data_quality_score", "source_count", "provenance_summary", "warning_flags"}.issubset(
        set(feats.columns)
    )

    # Fixtures include ward_42 in incident/asset record metadata; ensure it surfaces as an area_id.
    assert "ward_42" in set(feats["area_id"].astype(str).tolist())

    # Provenance is summarized and warnings include the low-lying proxy placeholder.
    ps = feats.iloc[0]["provenance_summary"]
    assert isinstance(ps, dict)
    assert "sources" in ps
    assert isinstance(feats.iloc[0]["warning_flags"], list)
    assert "LOW_LYING_PROXY_UNAVAILABLE" in feats.iloc[0]["warning_flags"]

    assert stats.rows_out == len(feats)

