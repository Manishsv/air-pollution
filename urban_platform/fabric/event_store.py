from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from urban_platform.decision_support.explainability import sanitize_for_json


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_event_id(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:16]


def _severity_from_pm25_category(cat: str) -> str:
    c = (cat or "").strip().lower()
    if c in {"severe", "very poor"}:
        return "critical"
    if c in {"poor"}:
        return "high"
    if c in {"moderate"}:
        return "medium"
    if c in {"good", ""}:
        return "low"
    return "medium"


def _as_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        v = float(x)
        if pd.isna(v):
            return None
        return v
    except Exception:
        return None


def _packet_ts(pkt: dict) -> str:
    ts = str(pkt.get("timestamp") or "")
    if ts:
        return ts
    return _now_iso()


def build_events_from_packets(
    packets: Iterable[dict],
    *,
    warnings_as_flags: bool = True,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pkt in packets:
        if not isinstance(pkt, dict):
            continue
        packet_id = str(pkt.get("packet_id") or "")
        h3_id = str(pkt.get("h3_id") or "")
        ts = _packet_ts(pkt)

        pred = pkt.get("prediction") or {}
        conf = pkt.get("confidence") or {}
        prov = pkt.get("provenance") or {}

        confidence_score = _as_float(conf.get("confidence_score"))
        confidence_level = str(pkt.get("confidence_level") or "").strip().lower()
        actionability_level = str(pkt.get("actionability_level") or "")
        recommended_action = str(pkt.get("recommended_action") or "")
        recommendation_allowed = bool(conf.get("recommendation_allowed", True))
        recommendation_block_reason = str(conf.get("recommendation_block_reason") or "")

        cat = str(pred.get("pm25_category_india") or "")
        warning_flags = str(prov.get("warning_flags") or "")
        flags = warning_flags if warnings_as_flags else ""

        prov_sum = pkt.get("provenance_summary") or {}

        # 1) forecast_pm25_high
        if (cat or "").strip().lower() in {"poor", "very poor", "severe"}:
            rows.append(
                {
                    "event_id": _stable_event_id("forecast_pm25_high", h3_id, ts, packet_id),
                    "event_type": "forecast_pm25_high",
                    "spatial_unit_id": h3_id,
                    "timestamp": ts,
                    "severity": _severity_from_pm25_category(cat),
                    "confidence": confidence_score,
                    "actionability_level": actionability_level,
                    "recommended_action": recommended_action,
                    "source_packet_id": packet_id,
                    "source_h3_id": h3_id,
                    "status": "new",
                    "provenance_summary": prov_sum,
                    "warning_flags": flags,
                }
            )

        # 2) low_confidence_forecast
        low_conf = (confidence_level == "low") or (confidence_score is not None and confidence_score < 0.4)
        if low_conf:
            rows.append(
                {
                    "event_id": _stable_event_id("low_confidence_forecast", h3_id, ts, packet_id),
                    "event_type": "low_confidence_forecast",
                    "spatial_unit_id": h3_id,
                    "timestamp": ts,
                    "severity": "medium",
                    "confidence": confidence_score,
                    "actionability_level": actionability_level,
                    "recommended_action": "Verify before action",
                    "source_packet_id": packet_id,
                    "source_h3_id": h3_id,
                    "status": "new",
                    "provenance_summary": prov_sum,
                    "warning_flags": flags,
                }
            )

        # 3) recommendation_blocked
        if (not recommendation_allowed) or (str(actionability_level).strip().lower() == "blocked"):
            msg = recommended_action or recommendation_block_reason or "Blocked"
            rows.append(
                {
                    "event_id": _stable_event_id("recommendation_blocked", h3_id, ts, packet_id),
                    "event_type": "recommendation_blocked",
                    "spatial_unit_id": h3_id,
                    "timestamp": ts,
                    "severity": "high",
                    "confidence": confidence_score,
                    "actionability_level": actionability_level,
                    "recommended_action": msg,
                    "source_packet_id": packet_id,
                    "source_h3_id": h3_id,
                    "status": "new",
                    "provenance_summary": prov_sum,
                    "warning_flags": flags,
                }
            )

        # 4) sensor_gap_detected (simple heuristic from audit_context/provenance)
        audit_ctx = pkt.get("audit_context") or {}
        avg_dist = _as_float(audit_ctx.get("avg_nearest_station_distance_km"))
        station_used = None
        try:
            station_used = int(prov.get("station_count_used")) if prov.get("station_count_used") is not None else None
        except Exception:
            station_used = None
        gap = (avg_dist is not None and avg_dist >= 10.0) or (station_used is not None and station_used <= 1)
        if gap:
            rows.append(
                {
                    "event_id": _stable_event_id("sensor_gap_detected", h3_id, ts, packet_id),
                    "event_type": "sensor_gap_detected",
                    "spatial_unit_id": h3_id,
                    "timestamp": ts,
                    "severity": "medium",
                    "confidence": confidence_score,
                    "actionability_level": "verify_only",
                    "recommended_action": "Consider adding / validating nearby sensor coverage",
                    "source_packet_id": packet_id,
                    "source_h3_id": h3_id,
                    "status": "new",
                    "provenance_summary": prov_sum,
                    "warning_flags": flags,
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # normalize timestamp for downstream filtering
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df


def build_events_from_source_reliability(reliability_df: pd.DataFrame, *, as_of: str | None = None) -> pd.DataFrame:
    if reliability_df is None or reliability_df.empty:
        return pd.DataFrame()
    ts = as_of or _now_iso()
    df = reliability_df.copy()
    # degraded sources only
    if "status" in df.columns:
        bad = df["status"].astype(str).str.lower().isin(["degraded", "suspect", "offline"])
        df = df[bad].copy()
    if df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for r in df.to_dict(orient="records"):
        entity_id = str(r.get("entity_id") or "")
        var = str(r.get("variable") or "")
        st = str(r.get("status") or "unknown").lower()
        sev = "medium" if st == "degraded" else ("high" if st == "suspect" else "critical" if st == "offline" else "medium")
        rows.append(
            {
                "event_id": _stable_event_id("source_reliability_degraded", entity_id, var, ts),
                "event_type": "source_reliability_degraded",
                "spatial_unit_id": entity_id,  # source-centric events use the entity_id as the unit
                "timestamp": ts,
                "severity": sev,
                "confidence": _as_float(r.get("reliability_score")),
                "actionability_level": "verify_only" if st in {"degraded", "suspect"} else "blocked",
                "recommended_action": f"Investigate source {entity_id} ({var}) status={st}",
                "source_packet_id": None,
                "source_h3_id": None,
                "status": "new",
                "provenance_summary": {},
                "warning_flags": str(r.get("reliability_issues") or ""),
            }
        )
    out = pd.DataFrame(rows)
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    return out


def build_event_store(
    *,
    decision_packets: list[dict] | None,
    reliability_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    packets = decision_packets or []
    packet_events = build_events_from_packets(packets)
    rel_events = build_events_from_source_reliability(reliability_df) if reliability_df is not None else pd.DataFrame()
    out = pd.concat([packet_events, rel_events], ignore_index=True) if not packet_events.empty or not rel_events.empty else pd.DataFrame()
    if out.empty:
        return out
    # de-dupe by event_id (stable)
    out = out.drop_duplicates(subset=["event_id"]).copy()
    return out.reset_index(drop=True)


def persist_event_store(
    event_df: pd.DataFrame,
    *,
    base_path: Path | str,
    write_json: bool = True,
) -> dict[str, Path]:
    base = Path(base_path).resolve()
    processed = base / "data" / "processed"
    outputs = base / "data" / "outputs"
    processed.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)

    parquet_path = processed / "event_store.parquet"
    if event_df is None or event_df.empty:
        # Write empty schema so downstream reads are stable.
        empty = pd.DataFrame(
            columns=[
                "event_id",
                "event_type",
                "spatial_unit_id",
                "timestamp",
                "severity",
                "confidence",
                "actionability_level",
                "recommended_action",
                "source_packet_id",
                "source_h3_id",
                "status",
                "provenance_summary",
                "warning_flags",
            ]
        )
        empty.to_parquet(parquet_path, index=False)
    else:
        event_df.to_parquet(parquet_path, index=False)

    out: dict[str, Path] = {"event_store_parquet": parquet_path}

    if write_json:
        json_path = outputs / "event_store.json"
        records = []
        try:
            if event_df is not None and not event_df.empty:
                tmp = event_df.copy()
                tmp["timestamp"] = tmp["timestamp"].astype(str)
                records = tmp.to_dict(orient="records")
        except Exception:
            records = []
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(sanitize_for_json(records), f, indent=2, default=str, allow_nan=False)
        out["event_store_json"] = json_path

    return out

