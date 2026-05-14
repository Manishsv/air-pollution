"""Cell dossier — structured deep-dive context for one H3 cell.

Assembles everything we know about a cell so an LLM can reason about root
cause: latest signals grouped by domain, POI breakdown, recent pollution
trend, and the cause classifier's ranked hypotheses.

Used by the inbox chat tab to seed the LLM system prompt before the user
asks any question.

Usage
-----
    from airos.os.cell_dossier import build_cell_dossier
    dossier = build_cell_dossier("bangalore", "8861892527fffff")
    prompt_text = format_dossier_for_prompt(dossier)
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Signals to surface in the trend chart (most diagnostic for air quality)
_TREND_SIGNALS = ["PM25", "PM10", "AQI", "NO2", "SO2", "PM25_PM10_RATIO"]

# Group signals by domain in the prompt for readability
_DOMAIN_ORDER = [
    "air", "weather", "fire", "waste", "construction", "noise",
    "heat", "flood", "water",
    "pois", "buildings", "roads", "drains", "terrain",
    "nightlights", "green",
]

# Event-driven domains where zero / absent values are meaningful — methodology
# §4.5 dossier rule: do not show "0" for these; show "no detection in last 24h
# · event-driven absence — NOT proof of no event".
_EVENT_DRIVEN_DOMAINS = {"fire", "waste", "crowd"}
_EVENT_DRIVEN_SIGNALS = {"FRP", "SITE", "GATHERING_ALERT"}

# City-broadcast signals — come from a single city-centroid API call, so the
# value is IDENTICAL across every cell in the city for the same sweep. They
# can NOT distinguish a cell from its neighbours. The dossier marks them with
# a "city-wide" suffix and the agent prompt forbids them from compound labels.
# Methodology §4.4 (similarity-bias mitigation).
_CITY_BROADCAST_SIGNALS = {
    "WIND_SPEED_KMH", "WIND_DIR_DEG",
    "HUMIDITY_PCT", "PRESSURE_HPA",
    "TEMPERATURE_C", "TEMP_CELSIUS",
    "PRECIP_MM", "PRECIPITATION_MM_HR",
    "HEAT_INDEX_C", "UHI",   # heat domain also single-broadcast for now
}


def build_cell_dossier(
    city_id: str,
    h3_id: str,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Assemble a structured dossier for one cell."""
    if db_path is None:
        from airos.drivers.store.schema import DB_PATH
        db_path = str(DB_PATH)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        meta    = _load_metadata(conn, city_id, h3_id)
        signals = _load_latest_signals(conn, city_id, h3_id)
        trend   = _load_trend(conn, city_id, h3_id, hours=168)  # 7 days
    finally:
        conn.close()

    # Dossier build timestamp — surfaced to the UI alongside the conversation
    # so two questions five minutes apart can be reconciled if underlying
    # signals changed between them (methodology §4.5).
    built_at = datetime.now(timezone.utc).isoformat()

    # Cause hypotheses (POI-aware classifier)
    try:
        from airos.os.cause_classifier import CauseClassifier
        hypotheses = CauseClassifier(db_path=db_path).classify(city_id, h3_id)
    except Exception as exc:
        logger.warning("CauseClassifier failed for %s/%s: %s", city_id, h3_id, exc)
        hypotheses = []

    dossier = {
        "city_id":     city_id,
        "h3_id":       h3_id,
        "metadata":    meta,
        "signals":     signals,            # {domain: {signal: {value, unit, data_quality, ...}}}
        "poi_summary": _poi_summary(signals.get("pois", {})),
        "trend_7d":    trend,              # {signal: [(ts, value), ...]}
        "hypotheses":  hypotheses,
        "built_at":    built_at,
    }

    # Versioning: sha256 of the rendered dossier text — the UI displays
    # `built_at` + `dossier_version[:12]` so two questions five minutes apart
    # can be reconciled if signals changed between them. Methodology §4.5.
    try:
        rendered = format_dossier_for_prompt(dossier)
        dossier["dossier_version"] = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    except Exception:
        dossier["dossier_version"] = ""
    return dossier


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_metadata(conn, city_id: str, h3_id: str) -> dict:
    row = conn.execute(
        """
        SELECT centroid_lat, centroid_lon, area_name, land_use_class
        FROM h3_metadata
        WHERE city_id = ? AND h3_id = ?
        """,
        (city_id, h3_id),
    ).fetchone()
    if not row:
        return {}
    return {
        "centroid_lat":   row["centroid_lat"],
        "centroid_lon":   row["centroid_lon"],
        "area_name":      row["area_name"],
        "land_use_class": row["land_use_class"],
    }


def _load_latest_signals(conn, city_id: str, h3_id: str) -> dict[str, dict[str, dict]]:
    """Per-signal latest reading, grouped by domain.

    Returns {domain: {signal: {value, unit, data_quality, observed_at,
                               spatial_support_json}}} — the per-line metadata
    needed for evidence-quality labels in the dossier (methodology §4.5).
    """
    rows = conn.execute(
        """
        SELECT s.domain, s.signal, s.value, s.unit, s.data_quality,
               s.observed_at, s.spatial_support_json
        FROM h3_signals s
        INNER JOIN (
            SELECT signal, MAX(hour_bucket) AS max_bucket
            FROM h3_signals
            WHERE city_id = ? AND h3_id = ?
            GROUP BY signal
        ) latest
          ON s.signal = latest.signal AND s.hour_bucket = latest.max_bucket
        WHERE s.city_id = ? AND s.h3_id = ?
        """,
        (city_id, h3_id, city_id, h3_id),
    ).fetchall()

    grouped: dict[str, dict[str, dict]] = {}
    # First pass: per-cell DATA_CONFIDENCE per domain (so we can attach to siblings)
    dc_by_domain: dict[str, float] = {}
    nearest_obs_by_domain: dict[str, float] = {}
    for r in rows:
        if r["signal"] == "DATA_CONFIDENCE":
            dc_by_domain[r["domain"]] = r["value"]
        if r["signal"] == "NEAREST_OBS_KM":
            nearest_obs_by_domain[r["domain"]] = r["value"]

    for r in rows:
        dom = r["domain"]
        sig = r["signal"]
        grouped.setdefault(dom, {})[sig] = {
            "value":              r["value"],
            "unit":               r["unit"],
            "data_quality":       r["data_quality"] or "unknown",
            "observed_at":        r["observed_at"],
            "spatial_support_json": r["spatial_support_json"],
            # Domain-level enrichment so each signal line can show DC + distance
            "_domain_data_confidence": dc_by_domain.get(dom),
            "_domain_nearest_obs_km":  nearest_obs_by_domain.get(dom),
        }
    return grouped


# ── Helpers for evidence-quality label rendering ────────────────────────────

def _age_label(observed_at: str | None) -> str:
    """Human-friendly age of an observation timestamp (ISO-8601)."""
    if not observed_at:
        return "age unknown"
    try:
        ts = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        secs = int(age.total_seconds())
        if secs < 0:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m old"
        if secs < 86400:
            return f"{secs // 3600}h old"
        return f"{secs // 86400}d old"
    except Exception:
        return "age unknown"


def _quality_label_suffix(meta: dict) -> str:
    """Render the per-line `· data_quality · age/distance · confidence` suffix.

    Methodology §4.5 — every numerical line in the dossier carries this so the
    LLM cannot treat a stale OSM count as equivalent to a real-time reading.
    """
    parts: list[str] = []
    dq = meta.get("data_quality") or "unknown"
    parts.append(dq)
    age = _age_label(meta.get("observed_at"))
    if age:
        parts.append(age)
    nearest = meta.get("_domain_nearest_obs_km")
    if nearest is not None and dq in ("real_station", "model_estimate"):
        try:
            parts.append(f"nearest obs {float(nearest):.1f} km")
        except Exception:
            pass
    dc = meta.get("_domain_data_confidence")
    if dc is not None:
        try:
            parts.append(f"confidence {float(dc):.2f}")
        except Exception:
            pass
    return " · " + " · ".join(parts)


def _format_value(meta: dict) -> str:
    """Render `value unit` with sensible precision."""
    v = meta.get("value")
    if v is None:
        return "—"
    try:
        s = f"{float(v):.3g}"
    except Exception:
        s = str(v)
    unit = meta.get("unit")
    return f"{s} {unit}".strip() if unit else s


def _load_trend(conn, city_id: str, h3_id: str, *, hours: int) -> dict[str, list]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:00:00Z")
    placeholders = ",".join("?" * len(_TREND_SIGNALS))
    rows = conn.execute(
        f"""
        SELECT signal, hour_bucket, value
        FROM h3_signals
        WHERE city_id = ? AND h3_id = ?
          AND signal IN ({placeholders})
          AND hour_bucket >= ?
        ORDER BY signal, hour_bucket
        """,
        [city_id, h3_id, *_TREND_SIGNALS, cutoff],
    ).fetchall()
    trend: dict[str, list] = {s: [] for s in _TREND_SIGNALS}
    for r in rows:
        trend[r["signal"]].append((r["hour_bucket"], r["value"]))
    return {s: t for s, t in trend.items() if t}


def _poi_summary(poi_signals: dict) -> dict[str, int]:
    """Distil pois domain signals into {category: count} (nonzero only).

    Accepts either the new shape `{signal: {value, unit, ...}}` or the old
    flat shape `{signal: value}` for back-compat with callers built against
    the pre-Tranche-B dossier.
    """
    out: dict[str, int] = {}
    for k, meta in poi_signals.items():
        if not k.startswith("POI_"):
            continue
        v = meta.get("value") if isinstance(meta, dict) else meta
        if not v:
            continue
        cat = k[len("POI_"):].removesuffix("_COUNT")
        try:
            n = int(v)
        except Exception:
            continue
        if n > 0:
            out[cat] = n
    return dict(sorted(out.items(), key=lambda x: -x[1]))


# ── Formatting for LLM prompt ─────────────────────────────────────────────────

def format_dossier_for_prompt(dossier: dict) -> str:
    """Render the dossier as plain text for inclusion in an LLM system prompt."""
    lines: list[str] = []

    meta = dossier.get("metadata") or {}
    lines.append(f"## Cell {dossier['h3_id']} ({dossier['city_id']})")
    if meta.get("area_name"):
        lines.append(f"Area: {meta['area_name']}")
    if meta.get("land_use_class"):
        lines.append(f"Land use class: {meta['land_use_class']}")
    if meta.get("centroid_lat") and meta.get("centroid_lon"):
        lines.append(
            f"Centroid: {float(meta['centroid_lat']):.4f}°N, "
            f"{float(meta['centroid_lon']):.4f}°E"
        )

    # Cause hypotheses first — most directly relevant to root-cause questions
    hyps = dossier.get("hypotheses") or []
    if hyps:
        lines.append("\n## Cause hypotheses (POI-aware classifier)")
        for h in hyps[:5]:
            conf = h.get("confidence", 0)
            lines.append(f"- **{h['cause']}** — confidence {conf:.2f}")
            for ev in h.get("evidence", [])[:4]:
                lines.append(f"    • {ev}")

    # POI breakdown — the new structural context
    pois = dossier.get("poi_summary") or {}
    if pois:
        lines.append("\n## POIs in this cell (OSM)")
        for cat, n in pois.items():
            lines.append(f"- {cat}: {n}")

    # Signal snapshot grouped by domain — every numerical line now carries
    # an evidence-quality label suffix (data_quality · age · distance · confidence)
    # so the LLM cannot treat a stale OSM count as equivalent to a real-time
    # station reading. Methodology §4.5.
    sigs = dossier.get("signals") or {}
    if sigs:
        lines.append("\n## Latest signals by domain")
        lines.append(
            "_Note: signals marked **(city-wide)** come from a single "
            "city-centroid API call. The value is IDENTICAL across every cell "
            "in this city today and CANNOT distinguish this cell from its "
            "neighbours. Use them only as ambient context, never as a "
            "differentiating term in compound findings (methodology §4.4)._"
        )
        for dom in _DOMAIN_ORDER:
            if dom not in sigs:
                continue
            # POIs already summarised above
            if dom == "pois":
                continue
            # Filter out DATA_CONFIDENCE/NEAREST_OBS_KM — those are surfaced
            # as part of the per-line suffix instead of as standalone lines.
            domain_sigs = {
                k: m for k, m in sigs[dom].items()
                if k not in ("DATA_CONFIDENCE", "NEAREST_OBS_KM")
            }
            if not domain_sigs:
                continue
            lines.append(f"\n### {dom}")
            for sig_name, meta in sorted(domain_sigs.items()):
                if not isinstance(meta, dict):
                    # Back-compat with the old flat shape
                    meta = {"value": meta}
                v = meta.get("value")
                # Event-driven absence — fire/waste/crowd zero values are
                # NOT proof of no event (FIRMS satellite pass cadence etc.)
                if (
                    (dom in _EVENT_DRIVEN_DOMAINS or sig_name in _EVENT_DRIVEN_SIGNALS)
                    and (v is None or (isinstance(v, (int, float)) and v == 0))
                ):
                    lines.append(
                        f"- {sig_name}: no detection in last 24h · "
                        f"event-driven absence — NOT proof of no event"
                    )
                    continue
                if v is None:
                    continue
                value_str = _format_value(meta)
                suffix    = _quality_label_suffix(meta)
                # Synthetic-fallback signals get a leading warning glyph
                prefix = ""
                if meta.get("data_quality") == "synthetic_fallback":
                    prefix = "⚠ "
                # City-broadcast tag — same value for every cell in this city
                if sig_name in _CITY_BROADCAST_SIGNALS:
                    suffix = f"{suffix} · **(city-wide)**"
                lines.append(f"- {sig_name}: {prefix}{value_str}{suffix}")

    # 7-day trend — show first, last, min, max for each pollutant signal
    trend = dossier.get("trend_7d") or {}
    if trend:
        lines.append("\n## 7-day trend (key pollution signals)")
        for sig, points in trend.items():
            if not points:
                continue
            vals = [p[1] for p in points if p[1] is not None]
            if not vals:
                continue
            last_ts, last_v = points[-1]
            last_str = f"{last_v:.2f}" if last_v is not None else "n/a"
            lines.append(
                f"- {sig}: latest {last_str} at {last_ts}  "
                f"(7d min {min(vals):.2f} / max {max(vals):.2f}, "
                f"{len(points)} samples)"
            )

    return "\n".join(lines)
