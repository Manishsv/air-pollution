"""Airshed-scale ingest orchestrator (Phase 4).

For every enabled AOI of kind ∈ {airshed, watershed, corridor, port,
airport}, runs the AOI's declared subset of ingest domains at the
AOI's declared H3 resolution across its full bbox.

This is the path that fills the IGP-North airshed with hex coverage
between member cities — Punjab/Haryana/UP/Bihar cells at res 5
(~250 km² each) that wouldn't be ingested by the per-city sweeps.

Domain subset
-------------
Picked per-AOI from `airos.os.aoi_registry.domains_for_aoi()`:
  airshed defaults  → [air, weather, fire, heat, water]
  watershed         → [water, weather, flood, fire, terrain]
  corridor          → [air, weather, fire, construction]
Fine-grain OSM signals (buildings, roads, POIs) are *not* ingested at
airshed resolution — they remain as composition from member-AOI cells.

Resolution
----------
Derived from the AOI's bbox area via auto_resolution() unless the YAML
declares one explicitly. IGP-North (~1.2 M km²) auto-resolves to res 5.

Currently implemented domains
-----------------------------
- air  — CPCB stations across the bbox (no city-name filter), IDW
         to the AOI's resolution.
- fire — FIRMS satellite hotspots, point-aggregated to the AOI's
         resolution.
Weather, heat, water remain TBD — they use city-centroid broadcasts
today (one point per city), which can't fill an airshed-scale grid
without re-engineering the connectors. Tracked as Phase 4+ followup.

Methodology §1.3 (AOIs as lenses; resolution by kind), §D.1 (wind-
aware airborne aggregation).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Domains the airshed-ingest path can drive today. Anything outside
# this set is silently skipped even if the AOI declares it — the
# corresponding driver doesn't yet honour resolution + bbox_only mode.
_AIRSHED_INGEST_SUPPORTED: frozenset[str] = frozenset({"air", "fire"})


def _run_airshed_domain(
    domain: str, aoi_id: str, bbox: dict, *, resolution: int, force: bool,
) -> int:
    """Dispatch one (AOI, domain) ingest call with airshed-mode kwargs.

    Returns rows written; 0 on skip or failure (logged).
    """
    if domain == "air":
        from airos.drivers.store.ingestor import _ingest_air
        return _ingest_air(
            aoi_id, bbox,
            force=force, resolution=resolution, bbox_only=True,
        )
    if domain == "fire":
        from airos.drivers.store.ingestor import _ingest_fire
        return _ingest_fire(
            aoi_id, bbox,
            force=force, resolution=resolution, bbox_only=True,
        )
    logger.debug(
        "[airshed/%s] domain %r not supported by airshed ingest yet — skipping",
        aoi_id, domain,
    )
    return 0


def ingest_airshed(aoi_id: str, *, force: bool = False) -> dict[str, int]:
    """Run airshed-scale ingest for a single AOI. Returns rows-per-domain."""
    from airos.os.aoi_registry import get_aoi, domains_for_aoi, resolution_of

    cfg = get_aoi(aoi_id)
    if not cfg.get("enabled"):
        return {}
    if cfg.get("kind") == "city":
        return {}   # city ingest already runs through the standard path

    bbox = cfg["bbox"]
    resolution = resolution_of(aoi_id)
    domains = domains_for_aoi(aoi_id)
    # Restrict to currently-supported set
    supported = [d for d in domains if d in _AIRSHED_INGEST_SUPPORTED]
    skipped = [d for d in domains if d not in _AIRSHED_INGEST_SUPPORTED]
    if skipped:
        logger.info(
            "[airshed/%s] declared domains %s, supported %s, skipping %s",
            aoi_id, domains, supported, skipped,
        )

    out: dict[str, int] = {}
    for domain in supported:
        try:
            n = _run_airshed_domain(domain, aoi_id, bbox,
                                    resolution=resolution, force=force)
            out[domain] = n
            logger.info("[airshed/%s] domain=%s res=%d rows_written=%d",
                        aoi_id, domain, resolution, n)
        except Exception as exc:
            logger.warning("[airshed/%s] domain=%s ingest failed: %s",
                           aoi_id, domain, exc)
            out[domain] = 0
    return out


def run_airshed_ingest_sweep(*, force: bool = False) -> dict[str, dict[str, int]]:
    """Iterate every enabled non-city AOI and run its airshed ingest.

    Returns {aoi_id: {domain: rows_written}}.
    """
    from airos.os.aoi_registry import list_aois, get_aoi

    summary: dict[str, dict[str, int]] = {}
    for aoi_id in list_aois():
        cfg = get_aoi(aoi_id)
        if cfg.get("kind") == "city":
            continue
        rows = ingest_airshed(aoi_id, force=force)
        if rows:
            summary[aoi_id] = rows
    return summary
