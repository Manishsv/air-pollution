"""Area-of-Interest (AOI) registry — Phase 0 of the AOI generalisation.

An AOI is any spatial region we want to monitor — a city, airshed,
watershed, regional economic corridor, port, airport, etc. AOIs are
*query lenses* over a single global H3 cell space, not storage
partitions: the same cell can be aggregated under multiple AOIs
without re-ingestion. See methodology §1.3 (Cells are AOI-agnostic).

This module is the canonical accessor for the AOI registry; everything
that needs to know "what AOIs exist?" or "which cells belong to AOI X?"
should call here rather than reading the YAML directly.

Public API
----------
- list_aois(kind=None, enabled_only=True) -> list[str]
- get_aoi(aoi_id) -> dict
- cells_in_aoi(aoi_id, *, db_path=None) -> list[str]
- aois_for_cell(h3_id) -> list[str]
- auto_resolution(bbox) -> int
- resolution_of(aoi_id) -> int

Phase 0 deliberately does NOT touch the database schema or the
ingestor — it only adds the read-side abstraction. Existing dashboard
queries that filter by `city_id` continue to work. Phase 1 migrates
the dashboard to use `signals_for_aoi` instead. Phase 2 drops the
`city_id` column.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

import yaml

logger = logging.getLogger(__name__)

_REPO_ROOT  = Path(__file__).resolve().parents[2]
_AOI_YML    = _REPO_ROOT / "data" / "config" / "aoi.yaml"
_LEGACY_YML = _REPO_ROOT / "data" / "config" / "cities.yaml"


# ── Auto-resolution lookup ───────────────────────────────────────────────────

# H3 average cell areas (km²) — used to keep total cells per AOI in a
# tractable range (~500-3000) regardless of AOI size.
_H3_AVG_CELL_AREA_KM2: dict[int, float] = {
    4: 1770.0,
    5:  252.0,
    6:   36.0,
    7:    5.2,
    8:    0.74,
    9:    0.11,
}


def _bbox_area_km2(bbox: dict) -> float:
    """Approximate bbox area in km² (good-enough rectangle, not great-circle).

    For Indian latitudes the cos(lat) correction matters; we use the bbox
    centroid latitude for the conversion. Good to ~5%.
    """
    import math
    dlat = float(bbox["lat_max"]) - float(bbox["lat_min"])
    dlon = float(bbox["lon_max"]) - float(bbox["lon_min"])
    lat_centre = (float(bbox["lat_min"]) + float(bbox["lat_max"])) / 2.0
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * math.cos(math.radians(lat_centre))
    return abs(dlat * km_per_deg_lat * dlon * km_per_deg_lon)


def auto_resolution(bbox: dict) -> int:
    """Suggest an H3 resolution for `bbox` that keeps the cell count in
    the tractable range (~500-3000)."""
    area = _bbox_area_km2(bbox)
    if area <       200: return 9   # ward / sub-district
    if area <     2_500: return 8   # city (current default)
    if area <    25_000: return 7   # metro region / mid-watershed
    if area <   250_000: return 6   # airshed / large watershed
    return 5                        # country-scale region


# ── Registry loader ──────────────────────────────────────────────────────────

def _load_registry() -> dict[str, dict[str, Any]]:
    """Parse aoi.yaml (or legacy cities.yaml). Returns every AOI block
    indexed by id — including those with enabled=false — so callers can
    introspect the full registry."""
    yml = _AOI_YML if _AOI_YML.exists() else _LEGACY_YML
    if not yml.exists():
        logger.warning("AOI registry not found at %s", yml)
        return {}
    raw = yaml.safe_load(yml.read_text()) or {}
    blocks = raw.get("aois") or raw.get("cities", {}) or {}
    out: dict[str, dict[str, Any]] = {}
    for aoi_id, cfg in blocks.items():
        bbox = cfg.get("bbox") or {}
        if not bbox:
            logger.warning("AOI %r missing bbox — skipping.", aoi_id)
            continue
        kind = cfg.get("kind", "city")
        resolution = cfg.get("resolution")
        if resolution is None:
            resolution = auto_resolution(bbox)
        else:
            resolution = int(resolution)
        out[aoi_id] = {
            "aoi_id":       aoi_id,
            "kind":         kind,
            "display_name": cfg.get("display_name") or aoi_id.title(),
            "country":      cfg.get("country"),
            "timezone":     cfg.get("timezone", "Asia/Kolkata"),
            "bbox":         dict(bbox),
            "resolution":   resolution,
            "member_aois":  list(cfg.get("member_aois") or []),
            "topography":   cfg.get("topography"),
            "enabled":      bool(cfg.get("enabled", False)),
            # Pass-through for any other fields callers might add
            # (e.g. routing hints) without forcing schema knowledge here.
            "_raw":         dict(cfg),
        }
    return out


# Loaded once at import; the dashboard and scheduler restart to refresh.
_REGISTRY: dict[str, dict[str, Any]] = _load_registry()


# ── Public API ───────────────────────────────────────────────────────────────

def list_aois(*, kind: str | None = None, enabled_only: bool = True) -> list[str]:
    """Return AOI ids, optionally filtered by kind and enabled flag.

    kind: 'city' | 'airshed' | 'watershed' | 'corridor' | 'port' | 'airport' | None
          None returns every kind.
    """
    out: list[str] = []
    for aoi_id, cfg in _REGISTRY.items():
        if enabled_only and not cfg["enabled"]:
            continue
        if kind is not None and cfg["kind"] != kind:
            continue
        out.append(aoi_id)
    return sorted(out)


def get_aoi(aoi_id: str) -> dict[str, Any]:
    """Return the full AOI config dict (raises KeyError if unknown)."""
    return _REGISTRY[aoi_id]


def resolution_of(aoi_id: str) -> int:
    """Return the AOI's H3 resolution (explicit or auto-derived)."""
    return _REGISTRY[aoi_id]["resolution"]


def cells_in_aoi(aoi_id: str, *, db_path: str | None = None) -> list[str]:
    """Return the H3 cell ids whose centroid falls inside this AOI's
    bbox. Reads from h3_metadata (the cells we already know about).

    This is the canonical "what cells belong to AOI X?" lookup. The
    answer is purely spatial — no `city_id` column is consulted —
    which is what makes AOIs into query lenses rather than storage
    partitions.
    """
    cfg = _REGISTRY[aoi_id]
    bbox = cfg["bbox"]
    if db_path is None:
        try:
            from airos.drivers.store.schema import DB_PATH
            db_path = str(DB_PATH)
        except Exception:
            return []
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT h3_id FROM h3_metadata
                WHERE centroid_lat BETWEEN ? AND ?
                  AND centroid_lon BETWEEN ? AND ?
                """,
                (bbox["lat_min"], bbox["lat_max"],
                 bbox["lon_min"], bbox["lon_max"]),
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("cells_in_aoi(%s) query failed: %s", aoi_id, exc)
        return []
    return [r[0] for r in rows]


def aois_for_cell(h3_id: str, *, kind: str | None = None) -> list[str]:
    """Return every AOI whose bbox contains this cell's centroid.

    A single cell can belong to a city AOI + an airshed AOI + a
    watershed AOI simultaneously — that's the point of the lens model.
    """
    import h3
    try:
        lat, lon = h3.cell_to_latlng(h3_id)
    except Exception:
        return []
    out: list[str] = []
    for aoi_id, cfg in _REGISTRY.items():
        if kind is not None and cfg["kind"] != kind:
            continue
        bb = cfg["bbox"]
        if (bb["lat_min"] <= lat <= bb["lat_max"]
                and bb["lon_min"] <= lon <= bb["lon_max"]):
            out.append(aoi_id)
    return out


def bbox_of(aoi_id: str) -> dict[str, float]:
    """Return the AOI's WGS84 bbox dict."""
    return _REGISTRY[aoi_id]["bbox"]


def reload_registry() -> None:
    """Force a re-read of aoi.yaml. Useful in tests; production callers
    restart the process to pick up registry changes."""
    global _REGISTRY
    _REGISTRY = _load_registry()
