"""
Legacy city registry for the AIR Climate Suite.

Loads from `data/config/aoi.yaml` at import time (renamed from
cities.yaml in Phase 0 of the AOI generalisation). Existing call
sites that import `CITIES` / `PANEL_CITIES` / `get_bbox` / `get_centre`
etc. continue to work — only `kind: city` entries from the AOI registry
are exposed here. For multi-kind AOI logic (airshed / watershed /
corridor), use `airos.os.aoi_registry` instead.

Connector selection is driven by environment variables (not per-city config):
  CPCB_API_KEY    — if set, CPCB is used for air quality
  EARTHDATA_TOKEN — if set, NASA Earthdata (MODIS LST + GPM IMERG)
  Fallback: OpenMeteo for any domain whose env var is absent
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Path resolution: this file is at airos/os/city_config.py, so the repo
# root is parents[2]. The YAML was renamed cities.yaml -> aoi.yaml in
# Phase 0; we still fall back to cities.yaml for back-compat during the
# transition window.
_REPO_ROOT  = Path(__file__).resolve().parents[2]
_AOI_YML    = _REPO_ROOT / "data" / "config" / "aoi.yaml"
_LEGACY_YML = _REPO_ROOT / "data" / "config" / "cities.yaml"
_CITIES_YML = _AOI_YML if _AOI_YML.exists() else _LEGACY_YML

# CPCB API uses inconsistent city spellings — these overrides map our
# canonical city_id to the spelling the CPCB feed expects. Only listed
# when the CPCB name differs from a title-cased city_id (Bangalore →
# "Bengaluru" is the only current case; others default to city_id.title()).
_CPCB_NAME_OVERRIDES: dict[str, str] = {
    "bangalore": "Bengaluru",
}

# Map zoom default for cities whose explicit zoom isn't set in YAML.
_DEFAULT_ZOOM = 11

# Display-name suffix to strip ("Bangalore, India" → "Bangalore") so the
# inbox selectbox stays compact. Keeps backward compat with the old
# hardcoded names.
_STRIP_SUFFIX = ", India"


def _bbox_centre(bbox: dict) -> tuple[float, float]:
    """Compute the (lat, lon) midpoint of a bbox dict."""
    return (
        (bbox["lat_min"] + bbox["lat_max"]) / 2.0,
        (bbox["lon_min"] + bbox["lon_max"]) / 2.0,
    )


def _load_cities() -> dict[str, dict]:
    """Parse aoi.yaml (or legacy cities.yaml) and return only enabled
    AOIs of kind 'city'. Other kinds (airshed / watershed / corridor)
    are filtered out here and consumed via aoi_registry instead."""
    if not _CITIES_YML.exists():
        logger.warning(
            "AOI registry not found at %s — empty.", _CITIES_YML,
        )
        return {}
    raw = yaml.safe_load(_CITIES_YML.read_text()) or {}
    # Support both "cities:" (legacy) and "aois:" (new) top-level keys.
    cities_raw = raw.get("aois") or raw.get("cities", {}) or {}
    out: dict[str, dict] = {}
    for cid, cfg in cities_raw.items():
        if not cfg.get("enabled", False):
            continue
        # Filter to city-kind only; AOIs of other kinds use aoi_registry.
        if cfg.get("kind", "city") != "city":
            continue
        bbox = cfg.get("bbox") or {}
        if not bbox or not all(k in bbox for k in ("lat_min", "lon_min", "lat_max", "lon_max")):
            logger.warning("City %r missing bbox — skipping.", cid)
            continue
        display = cfg.get("display_name") or cid.title()
        if display.endswith(_STRIP_SUFFIX):
            display = display[: -len(_STRIP_SUFFIX)]
        out[cid] = {
            "display_name": display,
            "cpcb_name":    _CPCB_NAME_OVERRIDES.get(cid, cid.title()),
            "centre":       cfg.get("centre") or _bbox_centre(bbox),
            "zoom":         cfg.get("zoom", _DEFAULT_ZOOM),
            "bbox":         dict(bbox),   # copy so callers don't mutate the registry
            "timezone":     cfg.get("timezone", "Asia/Kolkata"),
        }
    if not out:
        logger.warning("No enabled cities loaded from %s", _CITIES_YML)
    return out


# Module-level dict consumed by the dashboard and ingestor. Loaded once at
# import; restart the process (scheduler / dashboard) after editing YAML.
CITIES: dict[str, dict[str, Any]] = _load_cities()


def get_city(city_id: str) -> dict:
    """Return city config. Raises KeyError for unknown city_id."""
    return CITIES[city_id.lower()]


def get_bbox(city_id: str) -> dict:
    return get_city(city_id)["bbox"]


def get_centre(city_id: str) -> tuple[float, float]:
    """Return (lat, lng) map centre for the city."""
    return get_city(city_id)["centre"]


def get_zoom(city_id: str) -> int:
    return get_city(city_id).get("zoom", _DEFAULT_ZOOM)


def get_timezone(city_id: str) -> str:
    """Return IANA timezone name for the city.

    Used for converting UTC timestamps in `h3_signals.observed_at` to local
    civil time for circadian baseline computation (methodology §3.2).
    Defaults to Asia/Kolkata (the deployment region) if missing.
    """
    try:
        return get_city(city_id).get("timezone", "Asia/Kolkata")
    except KeyError:
        return "Asia/Kolkata"


def get_cpcb_name(city_id: str) -> str:
    try:
        return get_city(city_id).get("cpcb_name", city_id.title())
    except KeyError:
        return _CPCB_NAME_OVERRIDES.get(city_id.lower(), city_id.title())


# Panel-ready list: display_name → city_id (for Streamlit selectbox).
# Rebuilt from CITIES so adding a city only requires editing the YAML.
PANEL_CITIES: dict[str, str] = {
    v["display_name"]: k for k, v in CITIES.items()
}
