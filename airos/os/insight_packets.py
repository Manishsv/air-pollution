"""Insight → Decision Packet promotion.

Reads open high-priority H3 insights and writes them to h3_packets so ward
officers can see, dispatch, and close them. Idempotent — already-promoted
insights are skipped (tracked via packet_json source_insight_id field).

Usage:
    from airos.os.insight_packets import InsightPacketGenerator
    n = InsightPacketGenerator().generate(city_ids=["bangalore"])

CLI:
    python main.py --step packets --cities bangalore
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from typing import Any, Sequence

import yaml

logger = logging.getLogger(__name__)

_PROMOTE_TIERS = {"high", "medium"}
_MIN_CONFIDENCE = 0.5

# Spatial-diversity thinning: drop any candidate cell within this many H3 rings
# of an already-promoted cell in the same sweep. At H3 res-8 (~0.74 km²),
# k=2 ≈ 1.5 km — large enough to separate neighbouring IDW-correlated cells,
# small enough to keep genuinely distinct hotspots in the same ward. Set to 0
# to disable.  Methodology §4.4 (similarity bias mitigation).
_SPATIAL_DIVERSITY_K = 2

# Urgency string from recommended_actions → risk_level mapping
_URGENCY_TO_RISK = {
    "immediate":    "severe",
    "within_4h":    "high",
    "within_24h":   "moderate",
    "within_week":  "low",
}

_ROUTING_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "config", "department_routing.yaml"
)


def _load_routing_config() -> dict:
    path = os.path.normpath(_ROUTING_CONFIG_PATH)
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Could not load department_routing.yaml: %s", exc)
        return {}


def _routing_for_cause(config: dict, aoi_id: str, cause: str) -> dict[str, Any]:
    """Return routing block for a cause given the AOI it surfaced under.

    Lookup order (Phase 1 AOI-aware routing):
      1. cities[<aoi_id>]    — city-AOI routing (municipal + state PCB)
      2. airsheds[<aoi_id>]  — airshed-AOI routing (CPCB Central + NCAP)
      3. watersheds[<aoi_id>] — watershed-AOI routing (CWC + state irrigation)
      4. corridors[<aoi_id>] — corridor-AOI routing
      5. default             — schema-level fallback

    Today the param is named `aoi_id` for clarity; callers still pass
    the `city_id` of the insight, which (in Phase 0 / 1) is the city
    the cell was ingested under, not the airshed lens that surfaced it.
    Phase 2 will refactor packet generation to emit one packet per
    (cell, AOI) tuple — at which point this function gets called with
    the surfacing AOI's id explicitly.
    """
    for section_key in ("cities", "airsheds", "watersheds", "corridors", "ports", "airports"):
        block = config.get(section_key, {}) or {}
        if aoi_id in block:
            routing = block[aoi_id].get("cause_routing", {}).get(cause)
            if routing:
                return routing
    return config.get("default", {}).get("cause_routing", {}).get(cause, {}) or {}


class InsightPacketGenerator:
    """Promote qualifying insights to decision packets."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from airos.drivers.store.schema import DB_PATH
            db_path = str(DB_PATH)
        self._db = db_path

    def generate(
        self,
        city_ids: Sequence[str] | None = None,
        tiers: Sequence[str] = tuple(_PROMOTE_TIERS),
        min_confidence: float = _MIN_CONFIDENCE,
    ) -> int:
        """Promote open insights to packets. Returns number of new packets written."""
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        try:
            if city_ids is None:
                city_ids = [r[0] for r in conn.execute(
                    "SELECT DISTINCT city_id FROM h3_insights"
                ).fetchall()]

            already_promoted = self._promoted_insight_ids(conn)
            total = 0
            for city_id in city_ids:
                total += self._promote_city(
                    conn, city_id, set(tiers), min_confidence, already_promoted
                )
            logger.info("[insight_packets] %d new packet(s) written.", total)
            return total
        finally:
            conn.close()

    # ── Internal ──────────────────────────────────────────────────────────

    def _spatially_thin(
        self, insights: list, k: int,
    ) -> list:
        """Greedy thinning: drop any insight whose cell sits within k H3 rings
        of an already-kept cell. Preserves the input order, so the highest-
        ranked cell in any cluster wins. Insights without an h3_id pass through.
        """
        if k <= 0 or not insights:
            return list(insights)
        try:
            import h3 as _h3
        except ImportError:
            return list(insights)
        excluded: set[str] = set()
        kept = []
        for ins in insights:
            cell = ins["h3_id"]
            if not cell:
                kept.append(ins)
                continue
            if cell in excluded:
                continue
            kept.append(ins)
            # Mark this cell + k-ring as covered for subsequent insights
            try:
                excluded.update(_h3.grid_disk(cell, k))
            except Exception:
                excluded.add(cell)
        return kept

    def _exposure_scores(
        self, conn, city_id: str, h3_ids: list[str],
    ) -> dict[str, float]:
        """Return `{h3_id: POPULATION × latest AQI}` for the given cells.

        Used to rank packets within a tier: high-exposure cells outrank
        empty-but-equally-polluted ones. Falls back to PM25 when AQI is
        unavailable, and to 0.0 when neither signal is present (the cell
        then sorts on confidence only — same as the pre-exposure path).
        """
        if not h3_ids:
            return {}
        placeholders = ",".join("?" * len(h3_ids))
        rows = conn.execute(
            f"""
            SELECT s.h3_id, s.signal, s.value
            FROM h3_signals s
            INNER JOIN (
                SELECT h3_id, signal, MAX(hour_bucket) AS mb
                FROM h3_signals
                WHERE city_id = ?
                  AND signal IN ('POPULATION', 'AQI', 'PM25')
                  AND value IS NOT NULL
                  AND h3_id IN ({placeholders})
                GROUP BY h3_id, signal
            ) latest ON latest.h3_id = s.h3_id
                    AND latest.signal = s.signal
                    AND latest.mb = s.hour_bucket
            WHERE s.city_id = ?
            """,
            [city_id, *h3_ids, city_id],
        ).fetchall()
        by_cell: dict[str, dict[str, float]] = {}
        for r in rows:
            by_cell.setdefault(r["h3_id"], {})[r["signal"]] = float(r["value"] or 0)
        out: dict[str, float] = {}
        for h3_id, sigs in by_cell.items():
            pop = sigs.get("POPULATION", 0.0)
            air = sigs.get("AQI")
            if air is None:
                # Approximate AQI ≈ 2 × PM25 in the elevated range (US EPA breakpoints)
                pm = sigs.get("PM25")
                air = pm * 2 if pm is not None else 0.0
            out[h3_id] = pop * float(air)
        return out

    def _promoted_insight_ids(self, conn) -> set[tuple[str, str]]:
        """Return (insight_id, aoi_id) tuples that already have a packet.

        Phase 2 — one packet per (cell, AOI) tuple: the same insight can
        be promoted multiple times (once per AOI lens that contains the
        cell). Dedup is therefore on the tuple, not on insight_id alone.

        Legacy packets without an `aoi_id` in their JSON fall back to
        their `city_id` (preserves existing dedup semantics — the city
        AOI is the de-facto AOI for old rows).
        """
        rows = conn.execute(
            "SELECT packet_json FROM h3_packets"
        ).fetchall()
        ids: set[tuple[str, str]] = set()
        for row in rows:
            try:
                p = json.loads(row["packet_json"] or "{}")
                iid = p.get("source_insight_id")
                aoi = p.get("aoi_id") or p.get("city_id")
                if iid and aoi:
                    ids.add((iid, aoi))
            except Exception:
                pass
        return ids

    def _promote_city(
        self,
        conn,
        city_id: str,
        tiers: set[str],
        min_confidence: float,
        already_promoted: set[str],
    ) -> int:
        placeholders = ",".join("?" * len(tiers))
        insights = conn.execute(
            f"""
            SELECT insight_id, h3_id, domains_involved, finding,
                   confidence, priority_tier,
                   recommended_actions_json, hypothesis_chain_json,
                   uncertainty_notes_json, created_at
            FROM h3_insights
            WHERE city_id = ?
              AND outcome_status = 'open'
              AND priority_tier IN ({placeholders})
              AND (confidence IS NULL OR confidence >= ?)
            """,
            [city_id, *tiers, min_confidence],
        ).fetchall()

        # ── Exposure-weighted ranking (methodology §4.4 / §D.21) ─────────────
        # Tier still wins (a `high` insight always outranks a `medium`),
        # but within a tier we order by exposure — `POPULATION × AQI`,
        # bounded by [0, ∞). Cells where many people live AND air is bad
        # outrank equally-confident insights in empty industrial fringes.
        # Falls back to confidence when exposure is unavailable.
        exposure_by_cell = self._exposure_scores(
            conn, city_id,
            [ins["h3_id"] for ins in insights if ins["h3_id"]],
        )
        insights = sorted(
            insights,
            key=lambda i: (
                0 if i["priority_tier"] == "high" else 1,
                -exposure_by_cell.get(i["h3_id"] or "", 0.0),
                -float(i["confidence"] or 0.0),
            ),
        )

        # ── Spatial diversity thinning ──────────────────────────────────────
        # IDW interpolation + city-broadcast weather (heat, wind, humidity)
        # mean adjacent H3 cells in the same neighbourhood produce nearly
        # identical findings each sweep — 5 cells in Haveli Subdistrict with
        # "+390% PM2.5 spike" was the symptom. After ranking, drop any cell
        # within k=2 rings (~1.5 km) of an already-promoted cell. The first
        # cell in a cluster wins; the rest are deferred to the next sweep
        # when their score has moved relative to the kept cell.
        # Set spatial_diversity_k=0 to disable (e.g. tests).
        insights = self._spatially_thin(insights, k=_SPATIAL_DIVERSITY_K)

        from airos.drivers.store.writer import write_packet
        from airos.os.cause_classifier import CauseClassifier

        classifier = CauseClassifier(db_path=self._db)
        routing_config = _load_routing_config()

        # Batch-classify all air-domain cells appearing in this city's insights
        air_h3_ids = list({
            ins["h3_id"] for ins in insights
            if ins["h3_id"]
            and "air" in (ins["domains_involved"] or "")
        })
        cause_by_cell: dict[str, list[dict]] = {}
        if air_h3_ids:
            try:
                cause_by_cell = classifier.classify_batch(city_id, air_h3_ids)
            except Exception as exc:
                logger.warning("CauseClassifier batch failed: %s", exc)

        written = 0
        # Phase 2: emit one packet per (insight, AOI) tuple. For city-only
        # cells (the common case) this is identical to the prior behaviour
        # — exactly one AOI (the city) contains the cell. For cells that
        # also fall inside an airshed/watershed/corridor AOI, we emit an
        # extra packet routed per AOI kind.
        from airos.os.aoi_registry import aois_for_cell as _aois_for_cell, get_aoi as _get_aoi

        for ins in insights:
            iid = ins["insight_id"]
            h3_id = ins["h3_id"]

            # Enumerate every AOI whose bbox contains this cell. Order
            # cities first (most specific), then larger AOIs.
            try:
                containing = _aois_for_cell(h3_id) if h3_id else []
            except Exception:
                containing = []
            # Always include the cell's ingest-city (city_id) so we never
            # lose the legacy packet path even if the registry is empty.
            if city_id not in containing:
                containing = [city_id] + containing
            # Stable kind order: city > airshed > watershed > corridor > …
            _kind_rank = {"city": 0, "airshed": 1, "watershed": 2, "corridor": 3}
            def _rank(a: str) -> int:
                try:
                    return _kind_rank.get(_get_aoi(a)["kind"], 9)
                except Exception:
                    return 9
            containing = sorted(set(containing), key=_rank)

            actions = []
            try:
                actions = json.loads(ins["recommended_actions_json"] or "[]")
            except Exception:
                pass

            urgency = _primary_urgency(actions)
            risk_level = _URGENCY_TO_RISK.get(urgency, "moderate")

            domains = (ins["domains_involved"] or "").split(",")
            primary_domain = domains[0].strip() if domains else "cross_domain"

            exposure_score = float(exposure_by_cell.get(h3_id or "", 0.0))

            # Cause classification (cell-resolved, same across AOIs)
            cause_hypotheses = cause_by_cell.get(h3_id or "", [])

            for aoi_id in containing:
                if (iid, aoi_id) in already_promoted:
                    continue
                try:
                    aoi_cfg = _get_aoi(aoi_id)
                    aoi_kind = aoi_cfg["kind"]
                except Exception:
                    aoi_kind = "city"

                packet_id = f"pkt_ins_{uuid.uuid4().hex[:12]}"
                packet_payload: dict[str, Any] = {
                    "packet_id":         packet_id,
                    "source_insight_id": iid,
                    "source":            "insight",
                    # city_id preserved for column writes and legacy reads
                    "city_id":           city_id,
                    # Phase 2 AOI scoping — the surfacing lens that owns
                    # routing for this packet.
                    "aoi_id":            aoi_id,
                    "aoi_kind":          aoi_kind,
                    "h3_id":             h3_id,
                    "domain":            primary_domain,
                    "domains_involved":  ins["domains_involved"],
                    "priority_tier":     ins["priority_tier"],
                    "finding":           ins["finding"],
                    "confidence":        ins["confidence"],
                    "recommended_actions": actions,
                    "insight_created_at": ins["created_at"],
                    "urgency":           urgency,
                    "exposure_score":    round(exposure_score, 0) if exposure_score else 0,
                }

                # Cause classification + AOI-aware routing
                attribution_uncertain = False
                secondary_review_by  = None
                if cause_hypotheses:
                    packet_payload["cause_hypotheses"] = cause_hypotheses
                    top_cause = cause_hypotheses[0]["cause"]
                    packet_payload["primary_cause"] = top_cause
                    routing = _routing_for_cause(routing_config, aoi_id, top_cause)
                    if routing:
                        packet_payload["routed_to"]      = routing.get("primary", "")
                        packet_payload["routing_cc"]     = routing.get("secondary", [])
                        packet_payload["routing_action"] = routing.get("action_template", "")

                    # Tie-breaker (methodology §4.4)
                    from airos.os.cause_classifier import (
                        CLASSIFIER_VERSION, WEIGHT_CONFIG_VERSION, ATTRIBUTION_MARGIN,
                    )
                    if len(cause_hypotheses) >= 2:
                        top_conf = float(cause_hypotheses[0].get("confidence", 0))
                        sec_conf = float(cause_hypotheses[1].get("confidence", 0))
                        if (top_conf - sec_conf) < ATTRIBUTION_MARGIN:
                            attribution_uncertain = True
                            second_cause = cause_hypotheses[1]["cause"]
                            sec_routing  = _routing_for_cause(routing_config, aoi_id, second_cause)
                            if sec_routing:
                                secondary_review_by = sec_routing.get("primary", "")
                                packet_payload["secondary_cause"]    = second_cause
                                packet_payload["secondary_review_by"] = secondary_review_by
                                packet_payload["attribution_uncertain"] = True

                # Build structured evidence from hypothesis chain
                evidence = []
                try:
                    hyp = json.loads(ins["hypothesis_chain_json"] or "[]")
                    for h in hyp:
                        evidence.append({
                            "type":       "hypothesis",
                            "statement":  h.get("proposition", ""),
                            "testable_by": h.get("testable_by", ""),
                            "confidence": h.get("confidence"),
                        })
                except Exception:
                    pass

                # Uncertainty notes → safety gates
                safety_gates = []
                try:
                    notes = json.loads(ins["uncertainty_notes_json"] or "[]")
                    for n in notes:
                        safety_gates.append({
                            "gate":   "uncertainty",
                            "status": "requires_review",
                            "note":   n.get("note", ""),
                        })
                except Exception:
                    pass

                # Lazy import — only needed when a packet actually gets written.
                from airos.os.cause_classifier import (
                    CLASSIFIER_VERSION as _CV,
                    WEIGHT_CONFIG_VERSION as _WCV,
                )
                write_packet(
                    packet_id=packet_id,
                    h3_id=h3_id,
                    city_id=city_id,
                    domain=primary_domain,
                    risk_level=risk_level,
                    confidence_score=float(ins["confidence"]) if ins["confidence"] else None,
                    field_verification_required=True,
                    packet=packet_payload,
                    evidence=evidence,
                    safety_gates=safety_gates,
                    # Tranche A: classifier reproducibility + tie-breaker (§4.4)
                    classifier_version=_CV if cause_hypotheses else None,
                    weight_config_version=_WCV if cause_hypotheses else None,
                    attribution_uncertain=attribution_uncertain,
                    secondary_review_by=secondary_review_by,
                )
                already_promoted.add((iid, aoi_id))
                written += 1

        return written


def _primary_urgency(actions: list[dict]) -> str:
    """Return the most urgent urgency value across all recommended actions."""
    order = ["immediate", "within_4h", "within_24h", "within_week"]
    found = "within_24h"
    for a in actions:
        u = a.get("urgency", "")
        if u in order and order.index(u) < order.index(found):
            found = u
    return found
