from __future__ import annotations

import hashlib
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .schema import DOMAIN_VARIABLE_MAPS, OBSERVATION_COLUMNS, RAW_DATA_ROOT

logger = logging.getLogger(__name__)


def _obs_id(station_id: str, timestamp: str, variable: str) -> str:
    key = f"{station_id}|{timestamp}|{variable}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _parquet_path(root: Path, domain: str, city_id: str, obs_date: date) -> Path:
    return root / domain / city_id / f"{obs_date.isoformat()}.parquet"


def melt_to_narrow(
    wide_df: pd.DataFrame,
    domain: str,
    city_id: str,
    fetched_at: Optional[datetime] = None,
) -> pd.DataFrame:
    """Convert a wide connector DataFrame to the narrow observation schema."""
    if wide_df is None or wide_df.empty:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)

    var_map = DOMAIN_VARIABLE_MAPS.get(domain, {})
    if not var_map:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)

    raw_now = fetched_at or datetime.now(timezone.utc)
    now = pd.Timestamp(raw_now).tz_localize("UTC") if raw_now.tzinfo is None else pd.Timestamp(raw_now).tz_convert("UTC")
    rows = []

    for _, row in wide_df.iterrows():
        raw_ts = row["timestamp"]
        ts = pd.Timestamp(raw_ts).tz_localize("UTC") if pd.Timestamp(raw_ts).tzinfo is None else pd.Timestamp(raw_ts).tz_convert("UTC")
        base = {
            "domain": domain,
            "city_id": city_id,
            "station_id": str(row.get("station_id", "")),
            "latitude": float(row.get("latitude", float("nan"))),
            "longitude": float(row.get("longitude", float("nan"))),
            "timestamp": ts,
            "source": str(row.get("data_source", "unknown")),
            "quality_flag": str(row.get("quality_flag", "unknown")),
            "fetched_at": now,
        }
        for col, (variable_label, unit) in var_map.items():
            raw_val = row.get(col)
            if raw_val is None or (isinstance(raw_val, float) and pd.isna(raw_val)):
                continue
            obs = {
                **base,
                "variable": variable_label,
                "value": float(raw_val),
                "unit": unit,
            }
            obs["observation_id"] = _obs_id(base["station_id"], str(ts), variable_label)
            rows.append(obs)

    if not rows:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)

    df = pd.DataFrame(rows, columns=OBSERVATION_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    return df


class ObservationStoreWriter:
    def __init__(self, root: Path = RAW_DATA_ROOT) -> None:
        self._root = root

    def write(
        self,
        wide_df: pd.DataFrame,
        domain: str,
        city_id: str,
        fetched_at: Optional[datetime] = None,
    ) -> int:
        """Melt wide_df, merge with existing daily partition, dedup, write atomically."""
        try:
            narrow = melt_to_narrow(wide_df, domain, city_id, fetched_at)
            if narrow.empty:
                return 0

            narrow["_obs_date"] = narrow["timestamp"].dt.date
            written = 0
            for obs_date, group in narrow.groupby("_obs_date"):
                group = group.drop(columns=["_obs_date"])
                written += self._write_partition(group, domain, city_id, obs_date)
            return written
        except Exception as exc:
            logger.warning("ObservationStoreWriter.write failed: %s", exc)
            return 0

    def _write_partition(
        self,
        new_rows: pd.DataFrame,
        domain: str,
        city_id: str,
        obs_date: date,
    ) -> int:
        path = _parquet_path(self._root, domain, city_id, obs_date)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, new_rows], ignore_index=True)
        else:
            combined = new_rows.copy()

        combined = (
            combined
            .sort_values("fetched_at", ascending=False)
            .drop_duplicates(subset=["station_id", "timestamp", "variable"])
            .reset_index(drop=True)
        )

        tmp = path.with_suffix(".tmp.parquet")
        combined.to_parquet(tmp, index=False, compression="snappy")
        os.replace(tmp, path)  # atomic on POSIX and Windows

        return len(new_rows)
