from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .schema import DB_PATH, ensure_schema


class FeatureStoreWriter:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        ensure_schema(self._conn)

    def __enter__(self) -> "FeatureStoreWriter":
        return self

    def __exit__(self, *_) -> None:
        self._conn.close()

    # ── Domain writers ─────────────────────────────────────────────────────

    def write_flood_features(
        self,
        cells_df: pd.DataFrame,
        *,
        city_id: str,
        timestamp_bucket: datetime | None = None,
        data_quality_flag: str = "real",
    ) -> int:
        bucket = timestamp_bucket or _current_bucket()
        rows = pd.DataFrame({
            "h3_id": cells_df["h3_id"],
            "city_id": city_id,
            "timestamp_bucket": bucket,
            "flood_risk_score": cells_df.get("flood_risk_score"),
            "rainfall_mm_hr": cells_df.get("rainfall_mm_per_hr"),
            "incident_count": cells_df.get("incident_count"),
            "drainage_coverage": _derive_drainage_coverage(cells_df),
            "data_quality_flag": data_quality_flag,
            "written_at": datetime.now(timezone.utc),
        })
        return self._upsert("flood_features", rows, city_id, bucket)

    def write_air_features(
        self,
        cells_df: pd.DataFrame,
        *,
        city_id: str,
        timestamp_bucket: datetime | None = None,
        data_quality_flag: str = "real",
    ) -> int:
        bucket = timestamp_bucket or _current_bucket()
        rows = pd.DataFrame({
            "h3_id": cells_df["h3_id"],
            "city_id": city_id,
            "timestamp_bucket": bucket,
            "aqi_score": cells_df.get("aqi_score"),
            "pm25_ugm3": cells_df.get("pm25_ugm3"),
            "aqi_category": cells_df.get("aqi_category"),
            "data_quality_flag": data_quality_flag,
            "written_at": datetime.now(timezone.utc),
        })
        return self._upsert("air_features", rows, city_id, bucket)

    def write_heat_features(
        self,
        cells_df: pd.DataFrame,
        *,
        city_id: str,
        timestamp_bucket: datetime | None = None,
        data_quality_flag: str = "real",
    ) -> int:
        bucket = timestamp_bucket or _current_bucket()
        rows = pd.DataFrame({
            "h3_id": cells_df["h3_id"],
            "city_id": city_id,
            "timestamp_bucket": bucket,
            "heat_risk_score": cells_df.get("heat_risk_score"),
            "temp_celsius": cells_df.get("heat_index_c"),
            "green_cover_deficit": cells_df.get("green_deficit"),
            "uhi_delta_celsius": cells_df.get("uhi_intensity"),
            "data_quality_flag": data_quality_flag,
            "written_at": datetime.now(timezone.utc),
        })
        return self._upsert("heat_features", rows, city_id, bucket)

    # ── Internal ───────────────────────────────────────────────────────────

    def _upsert(self, table: str, rows: pd.DataFrame, city_id: str, bucket: datetime) -> int:
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                f"DELETE FROM {table} WHERE city_id = ? AND timestamp_bucket = ?",
                [city_id, bucket],
            )
            self._conn.execute(f"INSERT INTO {table} SELECT * FROM rows")
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return len(rows)


def _current_bucket() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def _derive_drainage_coverage(cells_df: pd.DataFrame) -> pd.Series:
    if "drainage_coverage" in cells_df.columns:
        return cells_df["drainage_coverage"]
    if "asset_count" in cells_df.columns:
        return (1.0 - cells_df["asset_count"] * 0.05).clip(lower=0.75)
    return pd.Series([None] * len(cells_df), dtype="float64")
