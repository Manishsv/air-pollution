from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from .schema import DB_PATH, ensure_schema

_CROSS_DOMAIN_SQL = """
WITH
  flood AS (
    SELECT h3_id, flood_risk_score, rainfall_mm_hr, incident_count,
           drainage_coverage, data_quality_flag AS flood_dqf
    FROM flood_features
    WHERE city_id = ? AND timestamp_bucket = ?
  ),
  air AS (
    SELECT h3_id, aqi_score, pm25_ugm3, aqi_category,
           data_quality_flag AS air_dqf
    FROM air_features
    WHERE city_id = ? AND timestamp_bucket = ?
  ),
  heat AS (
    SELECT h3_id, heat_risk_score, temp_celsius, green_cover_deficit,
           uhi_delta_celsius, data_quality_flag AS heat_dqf
    FROM heat_features
    WHERE city_id = ? AND timestamp_bucket = ?
  )
SELECT
    COALESCE(f.h3_id, a.h3_id, h.h3_id) AS h3_id,
    f.flood_risk_score,
    f.rainfall_mm_hr,
    f.incident_count,
    f.drainage_coverage,
    f.flood_dqf,
    a.aqi_score,
    a.pm25_ugm3,
    a.aqi_category,
    a.air_dqf,
    h.heat_risk_score,
    h.temp_celsius,
    h.green_cover_deficit,
    h.uhi_delta_celsius,
    h.heat_dqf,
    (
        COALESCE(f.flood_risk_score, 0.0) +
        COALESCE(a.aqi_score, 0.0) +
        COALESCE(h.heat_risk_score, 0.0)
    ) / NULLIF(
        CAST((f.flood_risk_score IS NOT NULL) AS INTEGER) +
        CAST((a.aqi_score IS NOT NULL) AS INTEGER) +
        CAST((h.heat_risk_score IS NOT NULL) AS INTEGER),
        0
    ) AS composite_risk_score,
    CAST((f.flood_risk_score >= 0.5) AS INTEGER) +
    CAST((a.aqi_score >= 0.5) AS INTEGER) +
    CAST((h.heat_risk_score >= 0.5) AS INTEGER) AS elevated_domain_count
FROM       flood f
FULL OUTER JOIN air  a USING (h3_id)
FULL OUTER JOIN heat h USING (h3_id)
ORDER BY composite_risk_score DESC NULLS LAST
"""

_LATEST_BUCKET_SQL = """
SELECT MAX(ts) FROM (
    SELECT MAX(timestamp_bucket) AS ts FROM flood_features WHERE city_id = ?
    UNION ALL
    SELECT MAX(timestamp_bucket) AS ts FROM air_features   WHERE city_id = ?
    UNION ALL
    SELECT MAX(timestamp_bucket) AS ts FROM heat_features  WHERE city_id = ?
)
"""


@dataclass
class CrossDomainResult:
    cells_df: pd.DataFrame
    timestamp_bucket: str
    city_id: str
    available_domains: list[str] = field(default_factory=list)


class FeatureStoreReader:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        if not db_path.exists():
            raise FileNotFoundError(f"Feature store not found: {db_path}")
        self._conn = duckdb.connect(str(db_path), read_only=True)

    def close(self) -> None:
        self._conn.close()

    # ── Bucket helpers ─────────────────────────────────────────────────────

    def latest_timestamp_bucket(self, city_id: str) -> Optional[str]:
        try:
            row = self._conn.execute(_LATEST_BUCKET_SQL, [city_id] * 3).fetchone()
            if row and row[0] is not None:
                return str(row[0])
        except Exception:
            pass
        return None

    def _resolve_bucket(self, city_id: str, timestamp_bucket: Optional[str]) -> Optional[str]:
        return timestamp_bucket or self.latest_timestamp_bucket(city_id)

    # ── Per-domain reads ───────────────────────────────────────────────────

    def read_flood_features(self, city_id: str, timestamp_bucket: Optional[str] = None) -> pd.DataFrame:
        bucket = self._resolve_bucket(city_id, timestamp_bucket)
        if not bucket:
            return pd.DataFrame()
        return self._conn.execute(
            "SELECT * FROM flood_features WHERE city_id = ? AND timestamp_bucket = ?",
            [city_id, bucket],
        ).df()

    def read_air_features(self, city_id: str, timestamp_bucket: Optional[str] = None) -> pd.DataFrame:
        bucket = self._resolve_bucket(city_id, timestamp_bucket)
        if not bucket:
            return pd.DataFrame()
        return self._conn.execute(
            "SELECT * FROM air_features WHERE city_id = ? AND timestamp_bucket = ?",
            [city_id, bucket],
        ).df()

    def read_heat_features(self, city_id: str, timestamp_bucket: Optional[str] = None) -> pd.DataFrame:
        bucket = self._resolve_bucket(city_id, timestamp_bucket)
        if not bucket:
            return pd.DataFrame()
        return self._conn.execute(
            "SELECT * FROM heat_features WHERE city_id = ? AND timestamp_bucket = ?",
            [city_id, bucket],
        ).df()

    # ── Cross-domain join ──────────────────────────────────────────────────

    def cross_domain_query(
        self,
        city_id: str,
        timestamp_bucket: Optional[str] = None,
    ) -> CrossDomainResult:
        bucket = self._resolve_bucket(city_id, timestamp_bucket)
        if not bucket:
            return CrossDomainResult(cells_df=pd.DataFrame(), timestamp_bucket="", city_id=city_id)

        df = self._conn.execute(_CROSS_DOMAIN_SQL, [city_id, bucket] * 3).df()

        available = []
        if not df.empty:
            if df["flood_risk_score"].notna().any():
                available.append("flood")
            if df["aqi_score"].notna().any():
                available.append("air")
            if df["heat_risk_score"].notna().any():
                available.append("heat")

        return CrossDomainResult(
            cells_df=df,
            timestamp_bucket=bucket,
            city_id=city_id,
            available_domains=available,
        )
