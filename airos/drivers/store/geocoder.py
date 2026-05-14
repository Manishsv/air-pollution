"""Reverse-geocode H3 cell centroids → human-readable area names.

Strategy
--------
Uses Nominatim (OpenStreetMap, free, no API key).  Rate limit: 1 req/s.

The result — suburb / neighbourhood / city district — is stored in
``h3_metadata.area_name`` so every panel (map tooltip, cell dropdown,
cell detail header) can display it without repeated API calls.

Caching
-------
A coordinate cache (lat/lon rounded to 3 decimal places ≈ 110 m grid)
deduplicates Nominatim calls. The grid is **deliberately finer than an H3
res-8 cell** (~1 km wide) so each cell receives its own Nominatim lookup —
otherwise neighbouring cells with different true locations collide on the
same cache key and inherit a single (often wrong) area name.

Earlier versions used 2-decimal precision (~1.1 km grid), which collided
with the cell scale and produced systematic mislabelling. If you see
"area X" labels appearing on cells visibly distant from area X on the
map, re-run with ``--overwrite`` after this fix.

Usage
-----
    # Geocode all cities (skip already-named cells):
    python main.py --step geocode-h3

    # Single city only:
    python main.py --step geocode-h3 --city bangalore

    # Force re-geocode even if area_name already set:
    python main.py --step geocode-h3 --overwrite

    # From Python:
    from airos.drivers.store.geocoder import geocode_all_cells
    results = geocode_all_cells(city_id="bangalore")
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# OSM address fields, in preference order — first non-empty value wins
_OSM_FIELDS = [
    "suburb",
    "neighbourhood",
    "quarter",
    "city_district",
    "district",
    "county",
    "state_district",
]

# Nominatim ToS: ≤ 1 request/second; be conservative
_RATE_LIMIT_SEC = 1.1
_USER_AGENT     = "airos-urban-platform/1.0"

# Coordinate precision for cache key: 3 dp ≈ 110 m grid.
# Must be finer than H3 res 8 cell width (~1 km) so each cell receives its
# own Nominatim lookup. A coarser grid caused systematic mislabelling
# (multiple cells sharing one name) and was fixed in this revision.
_COORD_PRECISION = 3


def _best_area(address: dict) -> str:
    """Pick the most human-useful area label from a Nominatim address dict."""
    for field in _OSM_FIELDS:
        val = address.get(field, "").strip()
        if val:
            return val
    return ""


def _make_cache_key(lat: float, lon: float) -> tuple[float, float]:
    """Round coordinates to reduce unique API calls for nearby cells."""
    return (round(lat, _COORD_PRECISION), round(lon, _COORD_PRECISION))


def _nominatim_reverse(lat: float, lon: float, cache: dict) -> str:
    """Reverse-geocode with an in-memory coordinate cache.

    Args:
        lat, lon: Cell centroid.
        cache:    Mutable dict mapping (rounded_lat, rounded_lon) → name.
                  A sentinel value of None means 'already tried, got nothing'.

    Returns:
        Area name string, or '' on failure.
    """
    key = _make_cache_key(lat, lon)
    if key in cache:
        return cache[key] or ""

    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent=_USER_AGENT)
        location   = geolocator.reverse(
            f"{lat},{lon}", language="en", exactly_one=True, timeout=10
        )
        name = ""
        if location and location.raw:
            name = _best_area(location.raw.get("address", {}))
        cache[key] = name or None   # None = tried but empty
        time.sleep(_RATE_LIMIT_SEC)
        return name
    except ImportError:
        logger.error("geopy not installed. Run: pip install geopy")
        cache[key] = None
        return ""
    except Exception as exc:
        logger.debug("Nominatim error at (%.4f, %.4f): %s", lat, lon, exc)
        cache[key] = None
        time.sleep(_RATE_LIMIT_SEC)
        return ""


def geocode_all_cells(
    city_id: Optional[str] = None,
    overwrite: bool = False,
) -> dict[str, dict[str, int]]:
    """Reverse-geocode H3 cell centroids for one or all cities.

    Args:
        city_id:   If given, process only this city.  Otherwise all cities.
        overwrite: If True, re-geocode cells that already have an area_name.

    Returns:
        {city: {"done": N, "cached": C, "failed": K}}
    """
    from airos.drivers.store.store import H3KnowledgeStore

    store = H3KnowledgeStore.get()

    # Fetch cells to process
    if overwrite:
        where = "WHERE centroid_lat IS NOT NULL AND centroid_lon IS NOT NULL"
    else:
        where = (
            "WHERE centroid_lat IS NOT NULL AND centroid_lon IS NOT NULL "
            "AND (area_name IS NULL OR area_name = '')"
        )

    params: list = []
    if city_id:
        where += " AND city_id = ?"
        params.append(city_id)

    df = store.fetchdf(
        f"SELECT h3_id, city_id, centroid_lat, centroid_lon "
        f"FROM h3_metadata {where} ORDER BY city_id, centroid_lat, centroid_lon",
        params if params else None,
    )

    if df.empty:
        logger.info("No cells to geocode (all already named, or no metadata).")
        return {}

    total = len(df)
    # Estimate: unique cache keys ≈ 50 % of total; each takes 1.1 s
    estimated_api = int(total * 0.55)
    logger.info(
        "Geocoding %d cells — estimated ~%d API calls (~%.0f min with cache)…",
        total, estimated_api, estimated_api * _RATE_LIMIT_SEC / 60,
    )

    coord_cache: dict[tuple[float, float], Optional[str]] = {}
    results: dict[str, dict[str, int]] = {}
    api_calls = done = cached_hits = failed = 0

    for pos, (_, row) in enumerate(df.iterrows()):
        cid = str(row["city_id"])
        hid = str(row["h3_id"])
        lat = float(row["centroid_lat"])
        lon = float(row["centroid_lon"])

        if cid not in results:
            results[cid] = {"done": 0, "cached": 0, "failed": 0}

        key = _make_cache_key(lat, lon)
        was_cached = key in coord_cache

        name = _nominatim_reverse(lat, lon, coord_cache)

        if name:
            store.execute(
                "UPDATE h3_metadata SET area_name = ? WHERE h3_id = ? AND city_id = ?",
                [name, hid, cid],
            )
            results[cid]["done"] += 1
            done += 1
            if was_cached:
                results[cid]["cached"] += 1
                cached_hits += 1
        else:
            results[cid]["failed"] += 1
            failed += 1

        if not was_cached:
            api_calls += 1

        logger.debug(
            "[%d/%d] %s → %s%s",
            pos + 1, total, hid, name or "(no name)",
            " [cache]" if was_cached else "",
        )

        # Progress every 100 cells
        if (pos + 1) % 100 == 0:
            logger.info(
                "Progress %d/%d — %d named (%d from cache), %d failed, %d API calls",
                pos + 1, total, done, cached_hits, failed, api_calls,
            )

    logger.info(
        "Geocoding complete: %d named (%d from cache), %d failed, %d API calls",
        done, cached_hits, failed, api_calls,
    )
    return results


def geocode_summary(city_id: Optional[str] = None) -> pd.DataFrame:
    """Return a coverage summary: how many cells have area_name vs total."""
    from airos.drivers.store.store import H3KnowledgeStore

    store  = H3KnowledgeStore.get()
    params = [city_id] if city_id else None
    where  = "WHERE city_id = ?" if city_id else ""

    return store.fetchdf(
        f"""
        SELECT
            city_id,
            count(*)                                                                    AS total_cells,
            sum(CASE WHEN area_name IS NOT NULL AND area_name != '' THEN 1 ELSE 0 END) AS named_cells,
            sum(CASE WHEN area_name IS NULL OR area_name = ''       THEN 1 ELSE 0 END) AS unnamed_cells
        FROM h3_metadata
        {where}
        GROUP BY city_id
        ORDER BY city_id
        """,
        params,
    )
