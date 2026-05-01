from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import geopandas as gpd
import pandas as pd

from urban_platform.common.provenance_summary import build_provenance_summary

def _default_base_dir() -> Path:
    # local.py -> api -> urban_platform -> air_quality_mvp
    return Path(__file__).resolve().parents[3]


def _paths(base_dir: Optional[Path] = None) -> dict[str, Path]:
    base = Path(base_dir) if base_dir is not None else _default_base_dir()
    return {
        "base": base,
        "processed": base / "data" / "processed",
        "outputs": base / "data" / "outputs",
        "observation_store": base / "data" / "processed" / "observation_store.parquet",
        "feature_store": base / "data" / "processed" / "feature_store.parquet",
        "recs_geojson": base / "data" / "outputs" / "hotspot_recommendations.geojson",
        "audit_json": base / "data" / "outputs" / "data_audit.json",
        "metrics_json": base / "data" / "outputs" / "metrics.json",
        "decision_packets_json": base / "data" / "outputs" / "decision_packets.json",
        "source_reliability_json": base / "data" / "outputs" / "source_reliability.json",
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _time_filter(df: pd.DataFrame, start_time: Optional[datetime], end_time: Optional[datetime]) -> pd.DataFrame:
    if df.empty or "timestamp" not in df.columns:
        return df
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    out = df.copy()
    out["timestamp"] = ts
    if start_time is not None:
        out = out[out["timestamp"] >= pd.to_datetime(start_time, utc=True)]
    if end_time is not None:
        out = out[out["timestamp"] <= pd.to_datetime(end_time, utc=True)]
    return out


def get_features(
    feature_name: str | None = None,
    grid_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    *,
    base_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Query canonical long-form features from `feature_store.parquet`.

    Returns columns (when available):
      grid_id, timestamp, feature_name, value, unit, source, confidence, quality_flag, provenance
    """
    p = _paths(base_dir)
    path = p["feature_store"]
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if feature_name is not None:
        df = df[df["feature_name"].astype(str) == str(feature_name)]
    if grid_id is not None:
        df = df[df["grid_id"].astype(str) == str(grid_id)]
    df = _time_filter(df, start_time, end_time)
    return df.reset_index(drop=True)


def _variable_to_feature_name(variable: str) -> str:
    v = str(variable).strip().lower()
    if v in {"pm25", "pm2.5"}:
        return "current_pm25"
    return str(variable)


def get_observations(
    variable: str | None = None,
    grid_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    *,
    base_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Observation query over persisted artifacts.

    Preferred source: `observation_store.parquet` (canonical observation table).
    Fallback: derive from `feature_store.parquet` for backwards compatibility.
    """
    p = _paths(base_dir)
    obs_path = p["observation_store"]
    if obs_path.exists():
        df = pd.read_parquet(obs_path)
        if variable is not None:
            df = df[df["variable"].astype(str) == str(variable)]
        if grid_id is not None:
            df = df[df["grid_id"].astype(str) == str(grid_id)]
        df = _time_filter(df, start_time, end_time)
        return df.reset_index(drop=True)

    # Fallback behavior (feature store–derived)
    df = get_features(
        feature_name=_variable_to_feature_name(variable) if variable else None,
        grid_id=grid_id,
        start_time=start_time,
        end_time=end_time,
        base_dir=base_dir,
    )
    if df.empty:
        return df
    df = df.rename(columns={"feature_name": "variable"})
    return df.reset_index(drop=True)


def get_source_reliability(
    entity_id: str | None = None,
    variable: str | None = None,
    status: str | None = None,
    *,
    base_dir: Path | None = None,
) -> pd.DataFrame:
    p = _paths(base_dir)
    path = p["source_reliability_json"]
    if not path.exists():
        return pd.DataFrame()
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)
    df = pd.DataFrame(records) if records else pd.DataFrame()
    if df.empty:
        return df
    if entity_id is not None and "entity_id" in df.columns:
        df = df[df["entity_id"].astype(str) == str(entity_id)]
    if variable is not None and "variable" in df.columns:
        df = df[df["variable"].astype(str) == str(variable)]
    if status is not None and "status" in df.columns:
        df = df[df["status"].astype(str).str.lower() == str(status).lower()]
    return df.reset_index(drop=True)


def get_recommendations(
    grid_id: str | None = None,
    min_confidence: float | None = None,
    *,
    base_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Query recommendations from `hotspot_recommendations.geojson` and attach audit/metrics context.
    """
    p = _paths(base_dir)
    geo_path = p["recs_geojson"]
    if not geo_path.exists():
        return pd.DataFrame()

    gdf = gpd.read_file(geo_path)
    if gdf.empty:
        return pd.DataFrame()

    # Normalize id
    if "h3_id" in gdf.columns and "grid_id" not in gdf.columns:
        gdf = gdf.rename(columns={"h3_id": "grid_id"})

    df = pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))
    if grid_id is not None:
        df = df[df["grid_id"].astype(str) == str(grid_id)]

    # Provide a canonical confidence field when available
    if "confidence_score" in df.columns:
        df["confidence"] = pd.to_numeric(df["confidence_score"], errors="coerce")
    elif "data_quality_score" in df.columns:
        df["confidence"] = pd.to_numeric(df["data_quality_score"], errors="coerce")
    else:
        df["confidence"] = pd.NA

    if min_confidence is not None:
        df = df[pd.to_numeric(df["confidence"], errors="coerce") >= float(min_confidence)]

    # Attach audit/metrics context as attrs (not duplicated per-row)
    audit = _read_json(p["audit_json"])
    metrics = _read_json(p["metrics_json"])
    try:
        df.attrs["data_audit"] = audit
        df.attrs["metrics"] = metrics
        df.attrs["provenance_summary"] = build_provenance_summary(metrics, audit)
    except Exception:
        pass

    return df.reset_index(drop=True)


def get_entities(entity_type: str | None = None, bbox=None, *, base_dir: Path | None = None) -> pd.DataFrame:
    """
    Lightweight entity listing from persisted recommendation grid output.

    Currently supports `entity_type="grid"` (H3 cells) derived from the recommendation GeoJSON.
    """
    _ = bbox  # bbox filtering can be added once we persist geometries here
    et = (entity_type or "grid").strip().lower()
    if et not in {"grid", "h3"}:
        return pd.DataFrame()
    recs = get_recommendations(base_dir=base_dir)
    if recs.empty:
        return pd.DataFrame()
    cols = [c for c in ["grid_id", "centroid_lat", "centroid_lon", "area_sqkm"] if c in recs.columns]
    out = recs[cols].drop_duplicates().copy()
    out["entity_type"] = "grid"
    out = out.rename(columns={"grid_id": "entity_id"})
    return out.reset_index(drop=True)


def get_events(event_type: str | None = None, severity: str | None = None, start_time: datetime | None = None, end_time: datetime | None = None, *, base_dir: Path | None = None) -> pd.DataFrame:
    """
    Events are not persisted yet in the MVP; return an empty table with canonical columns.
    """
    _ = (event_type, severity, start_time, end_time, base_dir)
    return pd.DataFrame(columns=["event_id", "event_type", "spatial_unit_id", "timestamp", "severity", "confidence", "recommended_action"])


def get_decision_packets(
    h3_id: str | None = None,
    min_confidence: float | None = None,
    recommendation_allowed: bool | None = None,
    category: str | None = None,
    *,
    base_dir: Path | None = None,
) -> list[dict]:
    p = _paths(base_dir)
    path = p["decision_packets_json"]
    if not path.exists():
        return []
    packets = _read_json(path)
    if not isinstance(packets, list):
        return []

    # Ensure provenance_summary is present even for older packet files.
    audit = _read_json(p["audit_json"])
    metrics = _read_json(p["metrics_json"])
    prov_sum = build_provenance_summary(metrics, audit)

    out = []
    for pkt in packets:
        if not isinstance(pkt, dict):
            continue
        if "provenance_summary" not in pkt:
            pkt = {**pkt, "provenance_summary": prov_sum}
        if h3_id is not None and str(pkt.get("h3_id")) != str(h3_id):
            continue
        if category is not None:
            cat = (((pkt.get("prediction") or {}) or {}).get("pm25_category_india"))
            if str(cat) != str(category):
                continue
        if recommendation_allowed is not None:
            allowed = (((pkt.get("confidence") or {}) or {}).get("recommendation_allowed"))
            if bool(allowed) != bool(recommendation_allowed):
                continue
        if min_confidence is not None:
            cs = (((pkt.get("confidence") or {}) or {}).get("confidence_score"))
            try:
                if float(cs) < float(min_confidence):
                    continue
            except Exception:
                continue
        out.append(pkt)
    return out


def get_decision_packet(packet_id: str, *, base_dir: Path | None = None) -> dict | None:
    if not packet_id:
        return None
    packets = get_decision_packets(base_dir=base_dir)
    for pkt in packets:
        if str(pkt.get("packet_id")) == str(packet_id):
            return pkt
    return None


def get_spec_manifest(*, base_dir: Path | None = None) -> dict[str, Any]:
    """Return ``specifications/manifest.json`` (``base_dir`` reserved for future multi-root layouts)."""
    del base_dir  # unused; API symmetry with other getters
    from urban_platform.specifications.conformance import load_manifest

    return load_manifest()


def get_conformance_report(*, base_dir: Path | None = None) -> dict[str, Any]:
    """Return ``data/outputs/conformance_report.json`` if present, else ``{}``."""
    p = _paths(base_dir)["outputs"] / "conformance_report.json"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def validate_artifact(schema_name: str, data: Any, *, base_dir: Path | None = None) -> dict[str, Any]:
    """Validate ``data`` against a manifest schema key; ``base_dir`` unused (reserved)."""
    del base_dir
    from urban_platform.specifications.runtime_validation import validate_artifact as _validate_artifact

    return _validate_artifact(schema_name, data)

