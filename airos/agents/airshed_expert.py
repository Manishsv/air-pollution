"""Airshed-scale expert agent.

Runs at H3 res 5 (or whatever the AOI's declared resolution is) rather
than the per-cell res-8 of the standard H3ExpertAgent. Produces
*regional* insights that explain patterns spanning hundreds of km:
multi-day inversions, trans-boundary stubble-burn signatures, IGP-wide
mixing-height events. Routes to airshed-scope bodies (CPCB Central,
NCAP) rather than municipal departments.

Architectural premise (methodology §1.3 — top-down vs bottom-up):

  - Data flows BOTTOM-UP: res-8 cell signals roll up to their res-5
    parents via H3 parent-cell math.
  - Insights flow TOP-DOWN: the airshed-scale agent reasons about
    regional patterns and contextualises the cell-scale findings
    underneath it. ("This Delhi spike is consistent with the IGP
    inversion event, not a new local cause.")

The agent is intentionally narrower than H3ExpertAgent:
  - No tool calls (the dossier is pre-built and complete at the
    airshed scale; gathering more per-cell data doesn't help).
  - One LLM round-trip with forced structured output via the same
    `submit_insight` schema H3ExpertAgent uses.
  - Different prompt + dossier; same downstream write_insight path
    so the inbox treats it uniformly.

Cost: ~one LLM call per res-5 parent per sweep. Default top_n=10
(configurable via AIRSHED_INSIGHTS_TOP_N env var or
run_airshed_insights(top_n=...) param) keeps this at ~$0.05 × 10 ≈
$0.50 per airshed per sweep at current pricing.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

# ── Versioning ───────────────────────────────────────────────────────────────
AIRSHED_AGENT_PROMPT_VERSION = "airshed-expert-v0.1"

# ── Tunables ────────────────────────────────────────────────────────────────
# Default top-N. Override via AIRSHED_INSIGHTS_TOP_N env var or pass
# `top_n` directly to run_airshed_insights().
_DEFAULT_TOP_N = int(os.environ.get("AIRSHED_INSIGHTS_TOP_N", "10"))


# ── System prompt ────────────────────────────────────────────────────────────

_AIRSHED_SYSTEM_PROMPT = """\
You are the AirOS Airshed Expert Agent. You are reasoning at *regional*
scale — H3 resolution {resolution} (~250 km² per parent cell at res 5)
across the {aoi_display_name}. Your job is to identify and articulate
patterns that are NOT visible at any single cell, and to contextualise
the cell-level findings underneath.

Scale separation (methodology §1.3)
-----------------------------------
Atmospheric chemistry has a fundamental scale separation:
  - LOCAL sources explain LOCAL patterns (a kiln explains its own cell)
  - REGIONAL transport explains REGIONAL patterns (Punjab stubble burns
    explain Delhi-NCR PM2.5)
You can NOT substitute one for the other. A high PM2.5 in Delhi is
NOT explained by aggregating its neighbours' PM2.5 — it's explained
by upwind sources hundreds of km away combined with regional
meteorology (inversion, mixing height, calm wind).

Your conclusions should be ABOUT the airshed: events spanning multiple
cities, transboundary advection, regional inversions, multi-day
accumulation episodes, large-scale source clusters (stubble belts,
industrial corridors).

Your conclusions should NOT be about a single cell. Cell-level findings
are produced by the H3 Expert Agent and live in the same database;
treat them as INPUTS to your regional reasoning, never your CONCLUSION.

Audience and routing
--------------------
Your insights route to airshed-scale bodies, not municipal departments:
  - CPCB Central (Central Pollution Control Board, Delhi HQ)
  - NCAP Directorate (National Clean Air Programme)
  - MoEFCC Climate Cell
  - IMD Regional Meteorology
Recommended actions should therefore be regional:
  - "Coordinate non-attainment-city action plans across UP, Punjab,
    Haryana"
  - "Issue trans-boundary advisory; advise state PCBs in upwind states"
  - "Pre-position vulnerable-population resources across IGP"
NOT: "issue stop-work notice to a specific construction site"
(that's the city agent's job).

Evidence you have
-----------------
The dossier below contains:
  1. Airshed-level aggregate signals — avg / max / p95 PM2.5,
     fire counts, exposed population, % of cells at high/severe risk.
  2. Per-parent (res-{resolution}) aggregate for THIS specific
     res-{resolution} parent cell — its avg signals, child count,
     dominant land-use, etc.
  3. Top-3 most-elevated child cells inside this parent — their
     own findings (when the per-cell agent has run on them) as
     "evidence" you can cite.
  4. Regional wind and upwind PM (UPWIND_PM25_LOAD_REGIONAL) telling
     you whether this parent is a source or a receptor in the
     airshed's transport pattern.

Output structure
----------------
You produce ONE structured `submit_insight` call. The same JSON schema
as H3ExpertAgent — finding, confidence, domains_involved,
hypothesis_chain, recommended_actions, uncertainty_notes, priority_tier.

priority_tier calibration at airshed scale:
  critical — airshed in a multi-day public-health event affecting
             millions; immediate inter-state coordination required
  high     — clear airshed-wide pattern (>50% of cells in this
             parent at high/severe risk) with identifiable regional
             driver (inversion, large fire cluster upwind)
  medium   — pattern visible but localised within parent; reach
             across 1-2 districts only
  low      — no distinctive airshed signal; this parent looks like
             typical-day baseline

Forbidden
---------
- Repeating per-cell findings without adding regional context.
- Naming a specific facility, site, or street — that's cell-scale.
- Claiming causation. Use "consistent with", "suggests", "evidence
  for", never "caused by".
- Listing weather as a compound leg — it's regional ambient context,
  not a contributing source. (Same rule as the per-cell agent.)
"""


# ── Tool schema (just submit_insight — no exploration tools) ─────────────────

def _get_submit_insight_tool() -> dict:
    """Reuse the exact same submit_insight tool spec as H3ExpertAgent so
    the downstream write_insight path is uniform."""
    from airos.agents.h3_expert import AGENT_TOOLS
    for t in AGENT_TOOLS:
        fn = t.get("function") or {}
        if fn.get("name") == "submit_insight":
            return t
    raise RuntimeError("submit_insight tool not found in h3_expert.AGENT_TOOLS")


# ── Dossier builder ──────────────────────────────────────────────────────────

def _build_airshed_parent_dossier(
    parent_h3: str, aoi_id: str, db_path: str,
) -> dict[str, Any]:
    """Build the data block the airshed agent reasons over.

    Includes:
      - The parent cell's centroid + an aggregate of child signals
      - The latest UPWIND_PM25_LOAD_REGIONAL for this parent
      - Top-3 most-elevated child cells (by PM2.5) with summary
      - Up to 3 of the most-recent open child insights (top tier)
      - The airshed's overall summary stats (so the agent has the
        big picture before reasoning about this one parent).
    """
    import h3
    parent_res = h3.get_resolution(parent_h3)
    children = list(h3.cell_to_children(parent_h3, parent_res + 3))
    # Sample-bound: a res-5 parent has 7^3 = 343 res-8 children; for
    # parent_res+3 (which equals 8 when parent_res=5) we get exactly
    # that. Cap to avoid huge IN clauses.
    children = children[:2000]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" * len(children))
        # Latest PM25 per child + the worst risk_level
        pm_rows = conn.execute(
            f"""
            SELECT s.h3_id, s.value AS pm25, m.area_name,
                   m.centroid_lat, m.centroid_lon
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT h3_id, MAX(hour_bucket) AS hb FROM h3_signals
                WHERE signal = 'PM25' AND value IS NOT NULL
                  AND h3_id IN ({placeholders})
                GROUP BY h3_id
            ) latest ON latest.h3_id = s.h3_id AND latest.hb = s.hour_bucket
            WHERE s.signal = 'PM25' AND s.value IS NOT NULL
            """,
            children,
        ).fetchall()

        # Latest regional upwind for the parent itself
        upwind_row = conn.execute(
            """
            SELECT value FROM h3_signals
            WHERE h3_id = ? AND signal = 'UPWIND_PM25_LOAD_REGIONAL'
              AND value IS NOT NULL
            ORDER BY hour_bucket DESC LIMIT 1
            """,
            (parent_h3,),
        ).fetchone()

        # Top child insights (high/medium open)
        ins_rows = conn.execute(
            f"""
            SELECT i.h3_id, i.finding, i.priority_tier, i.confidence,
                   i.created_at, m.area_name
            FROM h3_insights i
            LEFT JOIN h3_metadata m ON m.h3_id = i.h3_id
            WHERE i.h3_id IN ({placeholders})
              AND i.outcome_status = 'open'
              AND i.priority_tier IN ('critical', 'high', 'medium')
            ORDER BY
                CASE i.priority_tier
                    WHEN 'critical' THEN 0
                    WHEN 'high'     THEN 1
                    WHEN 'medium'   THEN 2
                END,
                i.created_at DESC
            LIMIT 5
            """,
            children,
        ).fetchall()
    finally:
        conn.close()

    pm_values = [r["pm25"] for r in pm_rows if r["pm25"] is not None]
    pm_stats = None
    if pm_values:
        pm_sorted = sorted(pm_values)
        pm_stats = {
            "n_cells": len(pm_values),
            "min":     round(pm_sorted[0], 1),
            "p50":     round(pm_sorted[len(pm_sorted) // 2], 1),
            "p95":     round(pm_sorted[min(len(pm_sorted) - 1,
                                            int(len(pm_sorted) * 0.95))], 1),
            "max":     round(pm_sorted[-1], 1),
            "mean":    round(sum(pm_values) / len(pm_values), 1),
        }

    # Top 3 contributors by PM2.5
    top_children = sorted(pm_rows, key=lambda r: r["pm25"] or 0, reverse=True)[:3]
    top_children_out = [{
        "h3_id":     r["h3_id"],
        "area_name": r["area_name"] or "unnamed",
        "pm25":      round(r["pm25"], 1) if r["pm25"] is not None else None,
        "lat":       float(r["centroid_lat"]) if r["centroid_lat"] is not None else None,
        "lon":       float(r["centroid_lon"]) if r["centroid_lon"] is not None else None,
    } for r in top_children]

    child_insights_out = [{
        "h3_id":         r["h3_id"],
        "area_name":     r["area_name"] or "unnamed",
        "finding":       r["finding"],
        "priority_tier": r["priority_tier"],
        "confidence":    r["confidence"],
        "created_at":    r["created_at"],
    } for r in ins_rows]

    parent_lat, parent_lon = h3.cell_to_latlng(parent_h3)
    return {
        "parent_h3":            parent_h3,
        "parent_resolution":    parent_res,
        "parent_centroid":      (parent_lat, parent_lon),
        "child_pm25_stats":     pm_stats,
        "regional_upwind_pm25": round(float(upwind_row["value"]), 1) if upwind_row else None,
        "top_children_by_pm25": top_children_out,
        "child_insights":       child_insights_out,
        "aoi_id":               aoi_id,
    }


def _format_dossier_for_prompt(d: dict, aoi_summary: dict) -> str:
    parts = [
        f"## Airshed: {d['aoi_id']}",
        f"## Parent cell: `{d['parent_h3']}` at res {d['parent_resolution']}",
        f"Centroid: {d['parent_centroid'][0]:.3f}°N, {d['parent_centroid'][1]:.3f}°E",
        "",
        "### Airshed-wide context (whole AOI)",
    ]
    if aoi_summary:
        for k in ("avg_pm25", "max_pm25", "p95_pm25", "fire_count_24h",
                  "high_risk_cells_pct", "population_exposed_high"):
            v = aoi_summary.get(k)
            if v is None:
                continue
            parts.append(f"- {k}: {v}")
    if d.get("regional_upwind_pm25") is not None:
        parts.append(
            f"- UPWIND_PM25_LOAD_REGIONAL for this parent: "
            f"{d['regional_upwind_pm25']} µg/m³-equiv (airshed-scale upwind sum)"
        )

    if d.get("child_pm25_stats"):
        s = d["child_pm25_stats"]
        parts += [
            "",
            "### PM2.5 across child cells inside this parent",
            f"- n_cells with PM2.5: {s['n_cells']}",
            f"- min / p50 / mean / p95 / max: "
            f"{s['min']} / {s['p50']} / {s['mean']} / {s['p95']} / {s['max']} µg/m³",
        ]

    if d.get("top_children_by_pm25"):
        parts += ["", "### Top child cells by current PM2.5"]
        for c in d["top_children_by_pm25"]:
            parts.append(
                f"- {c['area_name']} (`{c['h3_id'][:10]}…`): "
                f"{c['pm25']} µg/m³"
            )

    if d.get("child_insights"):
        parts += ["", "### Open child-cell insights (evidence — these are findings from the per-cell agent)"]
        for ins in d["child_insights"]:
            parts.append(
                f"- [{ins['priority_tier']}] {ins['area_name']} "
                f"(`{ins['h3_id'][:10]}…`, conf {ins['confidence']:.2f}):"
            )
            parts.append(f"  {ins['finding']}")

    parts += [
        "",
        "Reason about the regional pattern. Cell-level findings are EVIDENCE, "
        "not your conclusion. Your insight is about the airshed.",
    ]
    return "\n".join(parts)


# ── The agent ────────────────────────────────────────────────────────────────

def _run_one_airshed_parent(
    parent_h3: str, aoi_id: str, *, db_path: str,
) -> dict[str, Any] | None:
    """Run the airshed agent once for one res-N parent cell. Returns the
    insight dict (with insight_id) when one is written, else None."""
    from airos.agents.llm_client import LLMClient, user_msg
    from airos.agents.llm_config import load_config
    from airos.agents.h3_expert import AGENT_TOOLS
    from airos.os.aoi_registry import get_aoi
    from airos.os.airshed_compositor import airshed_summary_stats
    from airos.drivers.store.writer import write_insight

    try:
        aoi_cfg = get_aoi(aoi_id)
    except KeyError:
        logger.warning("airshed agent: unknown AOI %r", aoi_id)
        return None

    dossier = _build_airshed_parent_dossier(parent_h3, aoi_id, db_path)
    aoi_summary = airshed_summary_stats(aoi_id, db_path=db_path)
    context_text = _format_dossier_for_prompt(dossier, aoi_summary)

    system_text = _AIRSHED_SYSTEM_PROMPT.format(
        resolution=dossier["parent_resolution"],
        aoi_display_name=aoi_cfg["display_name"],
    )

    cfg = load_config()
    client = LLMClient(cfg)
    submit_tool = _get_submit_insight_tool()

    try:
        resp = client.chat_with_tools(
            [user_msg(context_text)],
            [submit_tool],
            system=system_text,
            tool_choice={"type": "function", "function": {"name": "submit_insight"}},
        )
    except Exception as exc:
        logger.warning("[airshed-agent] %s/%s LLM call failed: %s",
                       aoi_id, parent_h3, exc)
        return None

    if not resp.has_tool_calls:
        logger.info("[airshed-agent] %s/%s no tool call returned", aoi_id, parent_h3)
        return None

    payload = None
    for tc in resp.tool_calls:
        if tc.name == "submit_insight":
            payload = tc.arguments
            break
    if payload is None:
        return None

    # Reuse the same post-generation validator so airshed insights get
    # the same city-broadcast strip + persistence-duration guards.
    try:
        from airos.agents.validators import validate_post_generation
        payload = validate_post_generation(
            payload, dossier_signals=None,
            h3_id=parent_h3, city_id=aoi_id,
        )
    except Exception as exc:
        logger.debug("airshed post-validator skipped: %s", exc)

    # Persist
    try:
        insight_id = write_insight(
            h3_id=parent_h3,
            city_id=aoi_id,                # AOI scope, not a member city
            agent_type="airshed_expert",
            domains_involved=payload.get("domains_involved", []),
            finding=payload.get("finding", "Airshed analysis completed without structured finding."),
            confidence=float(payload.get("confidence", 0.3)),
            hypothesis_chain=payload.get("hypothesis_chain", []),
            recommended_actions=payload.get("recommended_actions") or [],
            uncertainty_notes=payload.get("uncertainty_notes") or [],
            priority_tier=payload.get("priority_tier"),
            agent_model=getattr(client.config, "model", None),
            agent_prompt_version=AIRSHED_AGENT_PROMPT_VERSION,
            confidence_type="ordinal",
        )
    except Exception as exc:
        logger.warning("[airshed-agent] write_insight failed: %s", exc)
        return None

    payload["insight_id"] = insight_id
    payload["aoi_id"] = aoi_id
    payload["h3_id"]  = parent_h3
    logger.info("[airshed-agent] insight %s for %s/%s · tier=%s conf=%.2f",
                insight_id, aoi_id, parent_h3,
                payload.get("priority_tier"), float(payload.get("confidence", 0)))
    return payload


# ── Top-N selection ──────────────────────────────────────────────────────────

def _top_n_parents_by_exposure(
    aoi_id: str, top_n: int, *, db_path: str,
) -> list[str]:
    """Pick the N res-`resolution_of(aoi)` parent cells with the highest
    aggregated POPULATION × PM2.5 across their child cells inside the
    AOI bbox. Falls back to ranking by PM2.5 alone if no population
    data has been ingested.
    """
    import h3
    from airos.os.aoi_registry import bbox_of, resolution_of
    target_res = resolution_of(aoi_id)
    bbox = bbox_of(aoi_id)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT s.h3_id, s.signal, s.value
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT s2.h3_id AS h3_id, s2.signal AS signal,
                       MAX(s2.hour_bucket) AS hb
                FROM h3_signals s2
                INNER JOIN h3_metadata m2 ON m2.h3_id = s2.h3_id
                WHERE s2.signal IN ('PM25', 'POPULATION')
                  AND s2.value IS NOT NULL
                  AND m2.centroid_lat BETWEEN ? AND ?
                  AND m2.centroid_lon BETWEEN ? AND ?
                GROUP BY s2.h3_id, s2.signal
            ) latest ON latest.h3_id = s.h3_id AND latest.signal = s.signal
                    AND latest.hb = s.hour_bucket
            WHERE s.value IS NOT NULL
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
    finally:
        conn.close()

    # Per-cell PM25 and POPULATION
    pm_by_cell:  dict[str, float] = {}
    pop_by_cell: dict[str, float] = {}
    for r in rows:
        if r["signal"] == "PM25":
            pm_by_cell[r["h3_id"]] = float(r["value"])
        elif r["signal"] == "POPULATION":
            pop_by_cell[r["h3_id"]] = float(r["value"])

    # Roll up child → parent (skip cells already coarser than target)
    parent_score: dict[str, float] = {}
    for cell, pm in pm_by_cell.items():
        try:
            native_res = h3.get_resolution(cell)
            if native_res < target_res:
                continue
            parent = (cell if native_res == target_res
                      else h3.cell_to_parent(cell, target_res))
            exposure = pm * (pop_by_cell.get(cell) or 1.0)   # falls back to PM-only
            parent_score[parent] = parent_score.get(parent, 0.0) + exposure
        except Exception:
            continue

    if not parent_score:
        return []

    return [p for p, _ in sorted(parent_score.items(),
                                  key=lambda kv: -kv[1])[:top_n]]


# ── Entry point ──────────────────────────────────────────────────────────────

def run_airshed_insights(
    aoi_id: str | None = None,
    *,
    top_n: int | None = None,
    db_path: str | None = None,
) -> dict[str, int]:
    """Run the airshed agent on every enabled non-city AOI (or the one
    specified by `aoi_id`). For each, picks the top-N res-`AOI` parent
    cells by aggregated population-weighted PM2.5 and runs one LLM
    call per parent.

    Returns {aoi_id: insight_count}.

    Skips silently when AIRSHED_INSIGHTS_DISABLED=1 in the env.
    """
    if os.environ.get("AIRSHED_INSIGHTS_DISABLED") == "1":
        logger.info("[airshed-agent] disabled via AIRSHED_INSIGHTS_DISABLED=1")
        return {}

    if db_path is None:
        from airos.drivers.store.schema import DB_PATH
        db_path = str(DB_PATH)

    target_top_n = int(top_n) if top_n is not None else _DEFAULT_TOP_N

    from airos.os.aoi_registry import list_aois, get_aoi
    target_aois = ([aoi_id] if aoi_id
                   else [a for a in list_aois()
                         if get_aoi(a)["kind"] in
                            ("airshed", "watershed", "corridor")])

    out: dict[str, int] = {}
    for aoi in target_aois:
        try:
            parents = _top_n_parents_by_exposure(aoi, target_top_n, db_path=db_path)
        except Exception as exc:
            logger.warning("[airshed-agent] %s top-N selection failed: %s", aoi, exc)
            continue
        if not parents:
            logger.info("[airshed-agent] %s: no parents to rank — skipping", aoi)
            out[aoi] = 0
            continue
        n_written = 0
        for parent in parents:
            try:
                result = _run_one_airshed_parent(parent, aoi, db_path=db_path)
                if result and result.get("insight_id"):
                    n_written += 1
            except Exception as exc:
                logger.warning("[airshed-agent] %s/%s failed: %s",
                               aoi, parent, exc)
        out[aoi] = n_written
        logger.info("[airshed-agent] %s: %d insights written (top_n=%d)",
                    aoi, n_written, target_top_n)
    return out
