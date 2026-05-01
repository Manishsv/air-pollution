from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import warnings

from urban_platform.fabric.observation_store import build_observation_table
from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file
from urban_platform.standards.validators import validate_observations


@dataclass(frozen=True)
class IngestStats:
    total_lines: int
    valid_lines: int
    invalid_lines: int
    observations_written: int


def _schema_validator() -> Any:
    schema_path = SPEC_ROOT / "provider_contracts" / "video_camera_people_count_feed.v1.schema.json"
    return validator_for_schema_file(str(schema_path))


def _iter_jsonl_lines(path: Path) -> Iterable[tuple[int, str]]:
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            s = (line or "").strip()
            if not s:
                continue
            yield i, s


def _obs_id(device_id: str, timestamp: str, observed_property: str, source: str) -> str:
    # Deterministic id (avoid duplicates on re-ingest).
    import hashlib

    raw = f"{device_id}|{timestamp}|{observed_property}|{source}"
    return "obs_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _to_observations(feed: dict[str, Any]) -> pd.DataFrame:
    """
    Convert provider feed payload -> canonical Observation rows (standards schema),
    then later we map to the fabric observation_store table.
    """
    provider_id = str(feed.get("provider_id") or "unknown")
    source_name = str(feed.get("source_name") or "unknown")
    source = f"{provider_id}:{source_name}"
    records = feed.get("records") or []

    rows: list[dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        device_id = str(r.get("entity_id") or "")
        ts = str(r.get("timestamp") or "")
        prop = str(r.get("observed_property") or "")
        rows.append(
            {
                "observation_id": _obs_id(device_id, ts, prop, source),
                "entity_id": device_id,
                "entity_type": "camera",
                "observed_property": prop,
                "value": r.get("value"),
                "unit": r.get("unit"),
                "timestamp": ts,
                "source": source,
                "quality_flag": r.get("quality_flag"),
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    # Drop rows with unparseable timestamps (common when someone pastes an example payload).
    df = df[df["timestamp"].notna()].copy()
    if df.empty:
        return pd.DataFrame()
    validate_observations(df)
    return df


def ingest_video_camera_people_count_jsonl(
    *,
    base_path: Path | str,
    jsonl_path: Path | str | None = None,
) -> IngestStats:
    """
    Phase-1 file ingestion:
    - reads JSONL lines from `data/edge/video_camera_people_count.jsonl`
    - validates each line against the provider contract schema
    - converts records to canonical observations
    - appends into `data/processed/observation_store.parquet`
    """
    base = Path(base_path).resolve()
    edge_path = Path(jsonl_path).resolve() if jsonl_path is not None else (base / "data" / "edge" / "video_camera_people_count.jsonl")
    processed_path = base / "data" / "processed" / "observation_store.parquet"
    processed_path.parent.mkdir(parents=True, exist_ok=True)

    v = _schema_validator()

    total = valid = invalid = 0
    obs_tables: list[pd.DataFrame] = []

    for _line_no, s in _iter_jsonl_lines(edge_path):
        total += 1
        try:
            feed = json.loads(s)
        except Exception:
            invalid += 1
            continue
        try:
            v.validate(feed)
        except Exception:
            invalid += 1
            continue

        valid += 1
        obs = _to_observations(feed)
        if obs.empty:
            continue
        table = build_observation_table(obs, grid=None)
        obs_tables.append(table)

    if not obs_tables:
        return IngestStats(total_lines=total, valid_lines=valid, invalid_lines=invalid, observations_written=0)

    incoming = pd.concat(obs_tables, ignore_index=True)

    if processed_path.exists():
        existing = pd.read_parquet(processed_path)
        # Avoid pandas FutureWarning about concat dtype inference with all-NA columns:
        # align incoming columns to the existing table schema.
        incoming_aligned = incoming.reindex(columns=existing.columns)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning, message="The behavior of DataFrame concatenation*")
            combined = pd.concat([existing, incoming_aligned], ignore_index=True)
    else:
        combined = incoming

    if "observation_id" in combined.columns:
        combined = combined.drop_duplicates(subset=["observation_id"], keep="last")
    if "timestamp" in combined.columns:
        combined = combined[pd.to_datetime(combined["timestamp"], utc=True, errors="coerce").notna()].copy()

    combined.to_parquet(processed_path, index=False)
    return IngestStats(
        total_lines=total,
        valid_lines=valid,
        invalid_lines=invalid,
        observations_written=int(len(incoming)),
    )

