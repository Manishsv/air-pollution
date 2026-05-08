"""DDL constants and path config for the H3 Knowledge Store (DuckDB).

Deduplication strategy
----------------------
h3_signals      — UNIQUE (h3_id, city_id, domain, signal, hour_bucket)
                  One reading per signal per cell per hour.  Newer value wins.
h3_assessments  — UNIQUE (h3_id, city_id, domain, day_bucket)
                  One assessment per domain per cell per calendar day.
h3_packets      — PRIMARY KEY (packet_id) + ON CONFLICT DO NOTHING
                  Packets are immutable once written; re-runs are safe.
h3_insights     — PRIMARY KEY (insight_id), always new UUID — no dedup needed,
                  agents only run on schedule.
h3_outcomes     — PRIMARY KEY (outcome_id), human-entered — no dedup needed.
h3_metadata     — PRIMARY KEY (h3_id, city_id) + ON CONFLICT DO UPDATE last_active.
h3_ingest_log   — Watermark table: (city_id, domain) → last_ingested_at.
                  Ingestor checks this before re-fetching data.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# DB location
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "h3" / "knowledge.duckdb"

# ---------------------------------------------------------------------------
# Time-bucket helpers (used in writer upserts)
# ---------------------------------------------------------------------------
# Truncate observed_at to the hour → one signal row per cell per hour per signal
SIGNAL_BUCKET_EXPR  = "date_trunc('hour', observed_at::TIMESTAMPTZ)"
# Truncate assessed_at to the day → one assessment row per cell per day per domain
ASSESS_BUCKET_EXPR  = "date_trunc('day',  assessed_at::TIMESTAMPTZ)"

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

DDL_H3_METADATA = """
CREATE TABLE IF NOT EXISTS h3_metadata (
    h3_id               VARCHAR NOT NULL,
    city_id             VARCHAR NOT NULL,
    resolution          INTEGER NOT NULL,
    centroid_lat        DOUBLE,
    centroid_lon        DOUBLE,
    land_use_class      VARCHAR,
    known_features_json VARCHAR,
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (h3_id, city_id)
);
"""

# hour_bucket is stored explicitly so the UNIQUE index is fast and unambiguous
DDL_H3_SIGNALS = """
CREATE TABLE IF NOT EXISTS h3_signals (
    h3_id           VARCHAR NOT NULL,
    city_id         VARCHAR NOT NULL,
    domain          VARCHAR NOT NULL,
    signal          VARCHAR NOT NULL,
    hour_bucket     TIMESTAMPTZ NOT NULL,   -- floor(observed_at, 1h)
    value           DOUBLE,
    unit            VARCHAR,
    source          VARCHAR,
    level           INTEGER NOT NULL DEFAULT 1,
    observed_at     TIMESTAMPTZ NOT NULL,   -- most recent raw timestamp in this bucket
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (h3_id, city_id, domain, signal, hour_bucket)
);
CREATE INDEX IF NOT EXISTS idx_h3_signals_cell ON h3_signals (h3_id, city_id, domain);
CREATE INDEX IF NOT EXISTS idx_h3_signals_time ON h3_signals (hour_bucket DESC);
"""

# day_bucket stored explicitly; one row per (cell, domain, day)
DDL_H3_ASSESSMENTS = """
CREATE TABLE IF NOT EXISTS h3_assessments (
    h3_id           VARCHAR NOT NULL,
    city_id         VARCHAR NOT NULL,
    domain          VARCHAR NOT NULL,
    day_bucket      DATE NOT NULL,          -- floor(assessed_at, 1d)
    assessed_at     TIMESTAMPTZ NOT NULL,   -- most recent assessment time in this bucket
    risk_level      VARCHAR NOT NULL,
    primary_index   VARCHAR,
    primary_value   DOUBLE,
    dominant_issue  VARCHAR,
    summary_json    VARCHAR,
    PRIMARY KEY (h3_id, city_id, domain, day_bucket)
);
CREATE INDEX IF NOT EXISTS idx_h3_assess_cell ON h3_assessments (h3_id, city_id, domain, day_bucket DESC);
"""

DDL_H3_PACKETS = """
CREATE TABLE IF NOT EXISTS h3_packets (
    packet_id                   VARCHAR NOT NULL,
    h3_id                       VARCHAR NOT NULL,
    city_id                     VARCHAR NOT NULL,
    domain                      VARCHAR NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    risk_level                  VARCHAR NOT NULL,
    confidence_score            DOUBLE,
    field_verification_required BOOLEAN NOT NULL DEFAULT FALSE,
    packet_json                 VARCHAR NOT NULL,
    outcome_status              VARCHAR NOT NULL DEFAULT 'pending',
    PRIMARY KEY (packet_id)
);
CREATE INDEX IF NOT EXISTS idx_h3_packets_cell   ON h3_packets (h3_id, city_id, domain);
CREATE INDEX IF NOT EXISTS idx_h3_packets_status ON h3_packets (outcome_status);
"""

DDL_H3_INSIGHTS = """
CREATE TABLE IF NOT EXISTS h3_insights (
    insight_id          VARCHAR NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    h3_id               VARCHAR NOT NULL,
    city_id             VARCHAR NOT NULL,
    agent_type          VARCHAR NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    domains_involved    VARCHAR,
    finding             VARCHAR NOT NULL,
    confidence          DOUBLE,
    causal_chain_json   VARCHAR,
    PRIMARY KEY (insight_id)
);
CREATE INDEX IF NOT EXISTS idx_h3_insights_cell ON h3_insights (h3_id, city_id, created_at DESC);
"""

DDL_H3_OUTCOMES = """
CREATE TABLE IF NOT EXISTS h3_outcomes (
    outcome_id      VARCHAR NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    packet_id       VARCHAR NOT NULL,
    h3_id           VARCHAR NOT NULL,
    city_id         VARCHAR NOT NULL,
    domain          VARCHAR NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome_type    VARCHAR NOT NULL,
    finding         VARCHAR,
    resolved_by     VARCHAR,
    PRIMARY KEY (outcome_id)
);
CREATE INDEX IF NOT EXISTS idx_h3_outcomes_packet ON h3_outcomes (packet_id);
CREATE INDEX IF NOT EXISTS idx_h3_outcomes_cell   ON h3_outcomes (h3_id, city_id, domain);
"""

# Watermark table — ingestor records the last successful run per (city, domain)
DDL_H3_INGEST_LOG = """
CREATE TABLE IF NOT EXISTS h3_ingest_log (
    city_id         VARCHAR NOT NULL,
    domain          VARCHAR NOT NULL,
    last_ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    rows_written    INTEGER,
    status          VARCHAR NOT NULL DEFAULT 'ok',   -- 'ok','partial','error'
    error_msg       VARCHAR,
    PRIMARY KEY (city_id, domain)
);
"""

ALL_DDL = [
    DDL_H3_METADATA,
    DDL_H3_SIGNALS,
    DDL_H3_ASSESSMENTS,
    DDL_H3_PACKETS,
    DDL_H3_INSIGHTS,
    DDL_H3_OUTCOMES,
    DDL_H3_INGEST_LOG,
]
