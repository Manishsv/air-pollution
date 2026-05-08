"""DDL constants and path config for the H3 Knowledge Store (DuckDB)."""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# DB location — one file, sits next to parquet store
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "h3" / "knowledge.duckdb"

# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

DDL_H3_METADATA = """
CREATE TABLE IF NOT EXISTS h3_metadata (
    h3_id               VARCHAR NOT NULL,
    city_id             VARCHAR NOT NULL,
    resolution          INTEGER NOT NULL,
    centroid_lat        DOUBLE,
    centroid_lon        DOUBLE,
    land_use_class      VARCHAR,          -- e.g. 'residential', 'industrial', 'water', 'green'
    known_features_json VARCHAR,          -- JSON array of named features in this cell
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (h3_id, city_id)
);
"""

DDL_H3_SIGNALS = """
CREATE TABLE IF NOT EXISTS h3_signals (
    signal_id       VARCHAR NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    h3_id           VARCHAR NOT NULL,
    city_id         VARCHAR NOT NULL,
    domain          VARCHAR NOT NULL,   -- 'air','water','heat','flood','green','construction','noise','fire'
    signal          VARCHAR NOT NULL,   -- e.g. 'AQI','WQI','NRI','CRI','GCCI','LST','BSI'
    value           DOUBLE,
    unit            VARCHAR,
    source          VARCHAR,            -- 'gee','openmeteo','firms','osm','imd','cpcb','demo'
    level           INTEGER NOT NULL DEFAULT 0,  -- 0=raw observation, 1=derived feature
    observed_at     TIMESTAMPTZ NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (signal_id)
);
CREATE INDEX IF NOT EXISTS idx_h3_signals_cell   ON h3_signals (h3_id, city_id, domain);
CREATE INDEX IF NOT EXISTS idx_h3_signals_time   ON h3_signals (observed_at DESC);
"""

DDL_H3_ASSESSMENTS = """
CREATE TABLE IF NOT EXISTS h3_assessments (
    assessment_id   VARCHAR NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    h3_id           VARCHAR NOT NULL,
    city_id         VARCHAR NOT NULL,
    domain          VARCHAR NOT NULL,
    assessed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    risk_level      VARCHAR NOT NULL,   -- 'good','moderate','high','severe'
    primary_index   VARCHAR,            -- name of the headline index (e.g. 'AQI')
    primary_value   DOUBLE,
    dominant_issue  VARCHAR,            -- short label e.g. 'PM2.5 spike'
    summary_json    VARCHAR,            -- full serialised dict of all sub-scores
    PRIMARY KEY (assessment_id)
);
CREATE INDEX IF NOT EXISTS idx_h3_assess_cell  ON h3_assessments (h3_id, city_id, domain, assessed_at DESC);
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
    packet_json                 VARCHAR NOT NULL,   -- full JSON blob
    outcome_status              VARCHAR NOT NULL DEFAULT 'pending',  -- 'pending','verified','false_positive','resolved'
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
    agent_type          VARCHAR NOT NULL,  -- 'h3_expert','domain_coordinator','city_intelligence'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    domains_involved    VARCHAR,           -- comma-separated list
    finding             VARCHAR NOT NULL,  -- human-readable headline
    confidence          DOUBLE,            -- 0-1
    causal_chain_json   VARCHAR,           -- JSON list of reasoning steps / evidence references
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
    outcome_type    VARCHAR NOT NULL,  -- 'verified','false_positive','partially_correct','resolved'
    finding         VARCHAR,           -- free-text field notes
    resolved_by     VARCHAR,           -- officer / system that closed it
    PRIMARY KEY (outcome_id)
);
CREATE INDEX IF NOT EXISTS idx_h3_outcomes_packet ON h3_outcomes (packet_id);
CREATE INDEX IF NOT EXISTS idx_h3_outcomes_cell   ON h3_outcomes (h3_id, city_id, domain);
"""

ALL_DDL = [
    DDL_H3_METADATA,
    DDL_H3_SIGNALS,
    DDL_H3_ASSESSMENTS,
    DDL_H3_PACKETS,
    DDL_H3_INSIGHTS,
    DDL_H3_OUTCOMES,
]
