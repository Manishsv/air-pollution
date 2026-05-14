"""DDL constants and path config for the H3 Knowledge Store (SQLite + WAL).

Deduplication strategy
----------------------
h3_signals      — UNIQUE (h3_id, city_id, domain, signal, hour_bucket)
                  One reading per signal per cell per hour.  Newer value wins.
h3_assessments  — UNIQUE (h3_id, city_id, domain, day_bucket)
                  One assessment per domain per cell per calendar day.
h3_packets      — PRIMARY KEY (packet_id) + ON CONFLICT DO NOTHING
                  Packets are immutable once written; re-runs are safe.
h3_insights     — PRIMARY KEY (insight_id), always new UUID — no dedup needed.
h3_outcomes     — PRIMARY KEY (outcome_id), human-entered — no dedup needed.
h3_metadata     — PRIMARY KEY (h3_id, city_id) + ON CONFLICT DO UPDATE last_active.
h3_ingest_log   — Watermark table: (city_id, domain) → last_ingested_at.

SQLite notes
------------
- Timestamps stored as ISO-8601 TEXT (UTC).  strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
  is used for default values; lexicographic order equals chronological order.
- REAL replaces DOUBLE/FLOAT.  TEXT replaces VARCHAR.
- INTEGER 0/1 replaces BOOLEAN.
- gen_random_uuid() is not available — caller supplies the UUID string.
- WAL mode is set by the store at connection time.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# DB location
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]  # airos/drivers/store/schema.py → parents[3] == repo root
DB_PATH = PROJECT_ROOT / "data" / "h3" / "knowledge.sqlite"

# ---------------------------------------------------------------------------
# Time-bucket helpers (Python-side; SQLite does not have date_trunc)
# ---------------------------------------------------------------------------
# These are computed in writer.py using Python datetime arithmetic.
# Kept here as documentation — do not use as SQL expressions.
SIGNAL_BUCKET_EXPR  = "strftime('%Y-%m-%dT%H:00:00Z', hour_bucket)"   # display only
ASSESS_BUCKET_EXPR  = "substr(day_bucket, 1, 10)"                       # display only

# ---------------------------------------------------------------------------
# DDL — SQLite compatible
# ---------------------------------------------------------------------------

DDL_H3_METADATA = """
CREATE TABLE IF NOT EXISTS h3_metadata (
    h3_id               TEXT NOT NULL,
    city_id             TEXT NOT NULL,
    resolution          INTEGER NOT NULL,
    centroid_lat        REAL,
    centroid_lon        REAL,
    area_name           TEXT,
    land_use_class      TEXT,
    known_features_json TEXT,
    first_seen          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_active         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (h3_id, city_id)
);
"""

DDL_H3_SIGNALS = """
CREATE TABLE IF NOT EXISTS h3_signals (
    h3_id           TEXT NOT NULL,
    city_id         TEXT NOT NULL,
    domain          TEXT NOT NULL,
    signal          TEXT NOT NULL,
    hour_bucket     TEXT NOT NULL,
    value           REAL,
    unit            TEXT,
    source          TEXT,
    data_quality    TEXT NOT NULL DEFAULT 'unknown',
    level           INTEGER NOT NULL DEFAULT 1,
    observed_at     TEXT NOT NULL,
    fetched_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    -- Reproducibility / audit trail (Tranche A, methodology §14)
    ingest_run_id              TEXT,
    raw_source_id              TEXT,
    source_observed_at         TEXT,
    ingested_at                TEXT,
    confidence_method_version  TEXT,
    geometry_assignment_method TEXT,   -- idw | centroid | line_clip | raster | poi_classifier
    spatial_support_json       TEXT,   -- {nearest_obs_km, contributing_count, weights[]}
    PRIMARY KEY (h3_id, city_id, domain, signal, hour_bucket)
);
CREATE INDEX IF NOT EXISTS idx_h3_signals_cell ON h3_signals (h3_id, city_id, domain);
CREATE INDEX IF NOT EXISTS idx_h3_signals_time ON h3_signals (hour_bucket DESC);
"""

DDL_H3_ASSESSMENTS = """
CREATE TABLE IF NOT EXISTS h3_assessments (
    h3_id           TEXT NOT NULL,
    city_id         TEXT NOT NULL,
    domain          TEXT NOT NULL,
    day_bucket      TEXT NOT NULL,
    assessed_at     TEXT NOT NULL,
    risk_level      TEXT NOT NULL,
    primary_index   TEXT,
    primary_value   REAL,
    dominant_issue  TEXT,
    summary_json    TEXT,
    -- Reproducibility (methodology §14)
    assessment_version      TEXT,
    threshold_version       TEXT,
    input_signal_refs_json  TEXT,
    PRIMARY KEY (h3_id, city_id, domain, day_bucket)
);
CREATE INDEX IF NOT EXISTS idx_h3_assess_cell ON h3_assessments (h3_id, city_id, domain, day_bucket DESC);
"""

DDL_H3_PACKETS = """
CREATE TABLE IF NOT EXISTS h3_packets (
    packet_id                   TEXT NOT NULL,
    h3_id                       TEXT NOT NULL,
    city_id                     TEXT NOT NULL,
    domain                      TEXT NOT NULL,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    risk_level                  TEXT NOT NULL,
    confidence_score            REAL,
    field_verification_required INTEGER NOT NULL DEFAULT 0,
    packet_json                 TEXT NOT NULL,
    outcome_status              TEXT NOT NULL DEFAULT 'pending',
    evidence_json               TEXT,
    safety_gates_json           TEXT,
    blocked_uses_json           TEXT,
    -- Reproducibility (methodology §4.4, §14)
    classifier_version          TEXT,
    weight_config_version       TEXT,
    attribution_uncertain       INTEGER DEFAULT 0,
    secondary_review_by         TEXT,
    PRIMARY KEY (packet_id)
);
CREATE INDEX IF NOT EXISTS idx_h3_packets_cell   ON h3_packets (h3_id, city_id, domain);
CREATE INDEX IF NOT EXISTS idx_h3_packets_status ON h3_packets (outcome_status);
"""

DDL_H3_INSIGHTS = """
CREATE TABLE IF NOT EXISTS h3_insights (
    insight_id                  TEXT NOT NULL,
    h3_id                       TEXT NOT NULL,
    city_id                     TEXT NOT NULL,
    agent_type                  TEXT NOT NULL,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    domains_involved            TEXT,
    finding                     TEXT NOT NULL,
    confidence                  REAL,
    priority_tier               TEXT NOT NULL DEFAULT 'medium',
    hypothesis_chain_json       TEXT,
    recommended_actions_json    TEXT,
    uncertainty_notes_json      TEXT,
    outcome_status              TEXT NOT NULL DEFAULT 'open',
    closed_by                   TEXT,
    closed_at                   TEXT,
    -- Reproducibility / four-way verdicts (methodology §4.1, §4.2, §4.3, §14)
    agent_model                 TEXT,
    agent_prompt_version        TEXT,
    tool_trace_id               TEXT,
    context_hash                TEXT,
    evidence_refs_json          TEXT,
    confidence_type             TEXT,   -- ordinal | heuristic_composite | calibrated
    condition_verdict           TEXT,   -- confirmed | refuted | partially_confirmed | unverifiable
    cause_verdict               TEXT,
    routing_verdict             TEXT,
    action_verdict              TEXT,
    context_truncated           INTEGER DEFAULT 0,
    tool_policy_compliance      TEXT,   -- ok | violated
    PRIMARY KEY (insight_id)
);
CREATE INDEX IF NOT EXISTS idx_h3_insights_cell ON h3_insights (h3_id, city_id, created_at DESC);
"""

DDL_H3_OUTCOMES = """
CREATE TABLE IF NOT EXISTS h3_outcomes (
    outcome_id      TEXT NOT NULL,
    packet_id       TEXT NOT NULL,
    h3_id           TEXT NOT NULL,
    city_id         TEXT NOT NULL,
    domain          TEXT NOT NULL,
    recorded_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    outcome_type    TEXT NOT NULL,
    finding         TEXT,
    resolved_by     TEXT,
    PRIMARY KEY (outcome_id)
);
CREATE INDEX IF NOT EXISTS idx_h3_outcomes_packet ON h3_outcomes (packet_id);
CREATE INDEX IF NOT EXISTS idx_h3_outcomes_cell   ON h3_outcomes (h3_id, city_id, domain);
"""

DDL_H3_INGEST_LOG = """
CREATE TABLE IF NOT EXISTS h3_ingest_log (
    city_id              TEXT NOT NULL,
    domain               TEXT NOT NULL,
    last_ingested_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    rows_written         INTEGER,
    status               TEXT NOT NULL DEFAULT 'ok',
    error_msg            TEXT,
    conformance_ok       INTEGER,
    conformance_failures TEXT,
    PRIMARY KEY (city_id, domain)
);
"""

DDL_CITY_PATTERNS = """
CREATE TABLE IF NOT EXISTS city_patterns (
    pattern_id      TEXT NOT NULL,
    city_id         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    lookback_hours  INTEGER NOT NULL,
    n_insights      INTEGER NOT NULL,
    theme_count     INTEGER NOT NULL,
    summary_json    TEXT NOT NULL,
    -- Reproducibility (methodology §14)
    source_insight_ids_json         TEXT,
    source_assessment_snapshot_id   TEXT,
    agent_model                     TEXT,
    prompt_version                  TEXT,
    PRIMARY KEY (pattern_id)
);
CREATE INDEX IF NOT EXISTS idx_city_patterns_city
    ON city_patterns (city_id, created_at DESC);
"""

DDL_TOOL_TRACES = """
CREATE TABLE IF NOT EXISTS tool_traces (
    trace_id          TEXT NOT NULL,
    insight_id        TEXT,
    city_id           TEXT,
    h3_id             TEXT,
    calls_json        TEXT NOT NULL,    -- [{seq, tool, args, result_summary, latency_ms, ok}, ...]
    policy_compliance TEXT,             -- ok | violated | unknown
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (trace_id)
);
CREATE INDEX IF NOT EXISTS idx_tool_traces_insight ON tool_traces (insight_id);
"""

DDL_H3_SITING = """
CREATE TABLE IF NOT EXISTS h3_siting_candidates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id             TEXT NOT NULL,
    domain              TEXT NOT NULL,
    h3_id               TEXT NOT NULL,
    rank                INTEGER NOT NULL,
    computed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    period_days         INTEGER NOT NULL,
    avg_risk_score      REAL,
    data_confidence     REAL,
    nearest_obs_km      REAL,
    coverage_gap        REAL,
    siting_score        REAL,
    centroid_lat        REAL,
    centroid_lon        REAL,
    assessment_count    INTEGER,
    UNIQUE (city_id, domain, h3_id, period_start)
);
CREATE INDEX IF NOT EXISTS idx_siting_city_domain
    ON h3_siting_candidates (city_id, domain, computed_at DESC);
"""

DDL_H3_SITING_LOG = """
CREATE TABLE IF NOT EXISTS h3_siting_log (
    city_id         TEXT NOT NULL,
    domain          TEXT NOT NULL,
    computed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    period_days     INTEGER NOT NULL,
    candidates      INTEGER,
    status          TEXT NOT NULL DEFAULT 'ok',
    error_msg       TEXT,
    PRIMARY KEY (city_id, domain)
);
"""

DDL_H3_ANALYSIS_REQUESTS = """
CREATE TABLE IF NOT EXISTS h3_analysis_requests (
    request_id      TEXT NOT NULL,
    h3_id           TEXT NOT NULL,
    city_id         TEXT NOT NULL,
    requested_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TEXT,
    completed_at    TEXT,
    insight_id      TEXT,
    error_msg       TEXT,
    PRIMARY KEY (request_id)
);
CREATE INDEX IF NOT EXISTS idx_analysis_req_cell
    ON h3_analysis_requests (h3_id, city_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_req_status
    ON h3_analysis_requests (status, requested_at);
"""

# Minimum gap between completed analysis and next request (enforced in writer)
ANALYSIS_COOLDOWN_HOURS = 6

DDL_AUDIT_ISSUES = """
CREATE TABLE IF NOT EXISTS audit_issues (
    issue_id        TEXT NOT NULL,
    city_id         TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT '',
    h3_id           TEXT,
    check_name      TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'warning',
    message         TEXT NOT NULL,
    detail_json     TEXT,
    detected_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    resolved_at     TEXT,
    PRIMARY KEY (issue_id)
);
CREATE INDEX IF NOT EXISTS idx_audit_issues_city
    ON audit_issues (city_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_issues_domain
    ON audit_issues (city_id, domain, severity);
"""

DDL_POI_POINTS = """
CREATE TABLE IF NOT EXISTS poi_points (
    poi_id      TEXT NOT NULL,        -- OSM osmid or generated UUID
    city_id     TEXT NOT NULL,
    h3_id       TEXT NOT NULL,
    category    TEXT NOT NULL,        -- primary (most-specific) category — back-compat
    secondary_tags_json TEXT,         -- JSON list of additional matching categories (§D.16)
    name        TEXT,
    latitude    REAL NOT NULL,
    longitude   REAL NOT NULL,
    osm_tags_json TEXT,
    fetched_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (poi_id, city_id)
);
CREATE INDEX IF NOT EXISTS idx_poi_points_cell  ON poi_points (city_id, h3_id);
CREATE INDEX IF NOT EXISTS idx_poi_points_cat   ON poi_points (city_id, category);
"""

ALL_DDL = [
    DDL_H3_METADATA,
    DDL_H3_SIGNALS,
    DDL_H3_ASSESSMENTS,
    DDL_H3_PACKETS,
    DDL_H3_INSIGHTS,
    DDL_H3_OUTCOMES,
    DDL_H3_INGEST_LOG,
    DDL_CITY_PATTERNS,
    DDL_H3_SITING,
    DDL_H3_SITING_LOG,
    DDL_H3_ANALYSIS_REQUESTS,
    DDL_AUDIT_ISSUES,
    DDL_POI_POINTS,
    DDL_TOOL_TRACES,
]
