from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file
from urban_platform.standards.validators import validate_observations


@dataclass(frozen=True)
class FloodIngestResult:
    provider_valid: bool
    provider_schema: str
    records_in: int
    normalized_rows: int


def _read_json(path: Path | str) -> dict[str, Any]:
    p = Path(path).resolve()
    with open(p, encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("Provider feed JSON must be an object at the top level")
    return obj


def _validator(schema_file: str) -> Any:
    return validator_for_schema_file(str((SPEC_ROOT / "provider_contracts" / schema_file).resolve()))


def _source_string(feed: dict[str, Any]) -> str:
    provider_id = str(feed.get("provider_id") or "unknown")
    source_name = str(feed.get("source_name") or "unknown")
    return f"{provider_id}:{source_name}"


def _sha_id(prefix: str, raw: str) -> str:
    return f"{prefix}_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _point_geometry(lat: float | None, lon: float | None) -> dict[str, Any] | None:
    if lat is None or lon is None:
        return None
    return {"type": "Point", "coordinates": [float(lon), float(lat)]}


def ingest_rainfall_observation_feed_json(*, json_path: Path | str) -> tuple[pd.DataFrame, FloodIngestResult]:
    """
    Read a rainfall provider feed JSON, validate it against the provider contract, and normalize into
    canonical Observation records.

    Normalized shape matches `urban_platform.standards.schemas.Observation` required columns and preserves
    provenance fields as extra columns (allowed).
    """
    feed = _read_json(json_path)
    schema_file = "rainfall_observation_feed.v1.schema.json"
    v = _validator(schema_file)
    v.validate(feed)

    source = _source_string(feed)
    license_str = feed.get("license")
    provider_source_metadata = feed.get("source_metadata")
    records = feed.get("records") or []

    rows: list[dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        ts = str(r.get("observation_time") or "")
        prop = str(r.get("observed_property") or "")
        ent = str(r.get("entity_id") or "")
        lat = r.get("latitude")
        lon = r.get("longitude")
        geom = r.get("geometry") or _point_geometry(lat if isinstance(lat, (int, float)) else None, lon if isinstance(lon, (int, float)) else None)

        obs_id = _sha_id("obs", f"{ent}|{ts}|{prop}|{source}")
        rows.append(
            {
                # Canonical required columns
                "observation_id": obs_id,
                "entity_id": ent if ent else _sha_id("entity", f"{lat}|{lon}|{source}"),
                "observed_property": prop,
                "value": r.get("value"),
                "unit": r.get("unit"),
                "timestamp": ts,
                "source": source,
                "quality_flag": r.get("quality_flag"),
                # Preserved context (extras allowed)
                "geometry": geom,
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "provenance": r.get("provenance"),
                "license": license_str,
                "feed_source_metadata": provider_source_metadata,
                "record_source_metadata": r.get("source_metadata"),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df, FloodIngestResult(provider_valid=True, provider_schema=schema_file, records_in=int(len(records)), normalized_rows=0)

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df[df["timestamp"].notna()].copy()
    if df.empty:
        return df, FloodIngestResult(provider_valid=True, provider_schema=schema_file, records_in=int(len(records)), normalized_rows=0)

    validate_observations(df)
    return df, FloodIngestResult(provider_valid=True, provider_schema=schema_file, records_in=int(len(records)), normalized_rows=int(len(df)))


def ingest_flood_incident_feed_json(*, json_path: Path | str) -> tuple[pd.DataFrame, FloodIngestResult]:
    """
    Read a flood incident provider feed JSON, validate it against the provider contract, and normalize into
    canonical Event records.

    This uses the platform `Event` concept for incidents. Provenance/quality fields are preserved as extras.
    """
    feed = _read_json(json_path)
    schema_file = "flood_incident_feed.v1.schema.json"
    v = _validator(schema_file)
    v.validate(feed)

    source = _source_string(feed)
    license_str = feed.get("license")
    provider_source_metadata = feed.get("source_metadata")
    records = feed.get("records") or []

    rows: list[dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        ts = str(r.get("incident_time") or "")
        incident_type = str(r.get("incident_type") or "")
        incident_id = str(r.get("incident_id") or "")
        ent = str(r.get("entity_id") or "")
        lat = r.get("latitude")
        lon = r.get("longitude")
        spatial_unit_id = ent if ent else (incident_id if incident_id else _sha_id("point", f"{lat}|{lon}|{source}"))

        event_id = incident_id if incident_id else _sha_id("evt", f"{incident_type}|{ts}|{spatial_unit_id}|{source}")
        rows.append(
            {
                "event_id": event_id,
                "event_type": incident_type,
                "spatial_unit_id": spatial_unit_id,
                "timestamp": pd.to_datetime(ts, utc=True, errors="coerce"),
                "severity": r.get("severity"),
                "confidence": None,
                "recommended_action": "Field verification required before operational action.",
                # Preserved context (extras allowed)
                "quality_flag": r.get("quality_flag"),
                "provenance": r.get("provenance"),
                "description": r.get("description"),
                "status": r.get("status"),
                "reported_by": r.get("reported_by"),
                "geometry": r.get("geometry") or _point_geometry(lat if isinstance(lat, (int, float)) else None, lon if isinstance(lon, (int, float)) else None),
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "license": license_str,
                "source": source,
                "feed_source_metadata": provider_source_metadata,
                "record_source_metadata": r.get("source_metadata"),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty and "timestamp" in df.columns:
        df = df[df["timestamp"].notna()].copy()
    return df, FloodIngestResult(provider_valid=True, provider_schema=schema_file, records_in=int(len(records)), normalized_rows=int(len(df)))


def ingest_drainage_asset_feed_json(*, json_path: Path | str) -> tuple[pd.DataFrame, FloodIngestResult]:
    """
    Read a drainage asset provider feed JSON, validate it against the provider contract, and normalize into
    canonical Entity records.

    Assets are represented as `Entity` rows (entity_type derived from asset_type) with geometry + attributes.
    """
    feed = _read_json(json_path)
    schema_file = "drainage_asset_feed.v1.schema.json"
    v = _validator(schema_file)
    v.validate(feed)

    source = _source_string(feed)
    license_str = feed.get("license")
    provider_source_metadata = feed.get("source_metadata")
    records = feed.get("records") or []

    rows: list[dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        asset_id = str(r.get("asset_id") or "")
        entity_id = str(r.get("entity_id") or asset_id or "")
        asset_type = str(r.get("asset_type") or "drainage_asset")
        lat = r.get("latitude")
        lon = r.get("longitude")
        geom = r.get("geometry") or _point_geometry(lat if isinstance(lat, (int, float)) else None, lon if isinstance(lon, (int, float)) else None)

        rows.append(
            {
                "entity_id": entity_id if entity_id else _sha_id("entity", f"{asset_id}|{asset_type}|{source}"),
                "entity_type": asset_type,
                "geometry": geom,
                "attributes": {
                    "asset_id": asset_id,
                    "asset_status": r.get("asset_status"),
                    "capacity": r.get("capacity"),
                    "capacity_unit": r.get("capacity_unit"),
                    "last_inspected_at": r.get("last_inspected_at"),
                    "quality_flag": r.get("quality_flag"),
                    "provenance": r.get("provenance"),
                    "license": license_str,
                    "feed_source_metadata": provider_source_metadata,
                    "record_source_metadata": r.get("source_metadata"),
                },
                "source": source,
                "confidence": None,
            }
        )

    df = pd.DataFrame(rows)
    return df, FloodIngestResult(provider_valid=True, provider_schema=schema_file, records_in=int(len(records)), normalized_rows=int(len(df)))


def _main() -> int:
    ap = argparse.ArgumentParser(description="Flood file ingestion (provider-contract validated).")
    ap.add_argument("--rainfall", type=str, default="", help="Path to rainfall_observation.sample.json")
    ap.add_argument("--incident", type=str, default="", help="Path to flood_incident.sample.json")
    ap.add_argument("--assets", type=str, default="", help="Path to drainage_asset.sample.json")
    args = ap.parse_args()

    if args.rainfall:
        df, stats = ingest_rainfall_observation_feed_json(json_path=args.rainfall)
        print(f"[rainfall] {stats} columns={list(df.columns)} rows={len(df)}")
    if args.incident:
        df, stats = ingest_flood_incident_feed_json(json_path=args.incident)
        print(f"[incident] {stats} columns={list(df.columns)} rows={len(df)}")
    if args.assets:
        df, stats = ingest_drainage_asset_feed_json(json_path=args.assets)
        print(f"[assets] {stats} columns={list(df.columns)} rows={len(df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

