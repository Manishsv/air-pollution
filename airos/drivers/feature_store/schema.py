from __future__ import annotations

from pathlib import Path

import duckdb

DB_PATH: Path = Path(__file__).resolve().parents[3] / "data" / "feature_store.duckdb"

_DDL = """
CREATE TABLE IF NOT EXISTS flood_features (
    h3_id             TEXT        NOT NULL,
    city_id           TEXT        NOT NULL,
    timestamp_bucket  TIMESTAMPTZ NOT NULL,
    flood_risk_score  DOUBLE,
    rainfall_mm_hr    DOUBLE,
    incident_count    INTEGER,
    drainage_coverage DOUBLE,
    data_quality_flag TEXT,
    written_at        TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS air_features (
    h3_id             TEXT        NOT NULL,
    city_id           TEXT        NOT NULL,
    timestamp_bucket  TIMESTAMPTZ NOT NULL,
    aqi_score         DOUBLE,
    pm25_ugm3         DOUBLE,
    aqi_category      TEXT,
    data_quality_flag TEXT,
    written_at        TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS heat_features (
    h3_id               TEXT        NOT NULL,
    city_id             TEXT        NOT NULL,
    timestamp_bucket    TIMESTAMPTZ NOT NULL,
    heat_risk_score     DOUBLE,
    temp_celsius        DOUBLE,
    green_cover_deficit DOUBLE,
    uhi_delta_celsius   DOUBLE,
    data_quality_flag   TEXT,
    written_at          TIMESTAMPTZ NOT NULL
);
"""


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    for stmt in _DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
