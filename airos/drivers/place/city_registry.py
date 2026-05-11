"""City registry — single source of truth for city ids, bboxes and metadata.

All city configuration lives in  data/config/cities.yaml.
Everything else in the codebase imports from here — nothing hardcodes bboxes.

Public API
----------
get_city(city_id)       -> CityConfig | None
all_cities()            -> list[CityConfig]          # enabled only
all_city_ids()          -> list[str]                 # enabled only
get_bbox(city_id)       -> dict | None               # {lat_min, lon_min, lat_max, lon_max}

CityConfig fields
-----------------
  id           str   — registry key (e.g. "bangalore")
  display_name str   — human label   (e.g. "Bengaluru, India")
  country      str   — ISO 3166-1 alpha-2
  timezone     str   — IANA tz string
  enabled      bool  — False cities are loaded but excluded from all_cities()
  bbox         dict  — {lat_min, lon_min, lat_max, lon_max}
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Location of the YAML file — relative to this module's package root
_YAML_PATH = Path(__file__).resolve().parents[3] / "data" / "config" / "cities.yaml"


@dataclass(frozen=True)
class CityConfig:
    id:           str
    display_name: str
    country:      str
    timezone:     str
    enabled:      bool
    bbox:         dict = field(hash=False, compare=False)

    @property
    def lat_min(self) -> float: return self.bbox["lat_min"]
    @property
    def lon_min(self) -> float: return self.bbox["lon_min"]
    @property
    def lat_max(self) -> float: return self.bbox["lat_max"]
    @property
    def lon_max(self) -> float: return self.bbox["lon_max"]


@lru_cache(maxsize=1)
def _load() -> dict[str, CityConfig]:
    """Parse cities.yaml once and cache the result for the process lifetime."""
    try:
        import yaml  # PyYAML — already a project dependency via pyyaml
    except ImportError:
        logger.error(
            "PyYAML not installed — city registry unavailable. "
            "Run: pip install pyyaml"
        )
        return {}

    if not _YAML_PATH.exists():
        logger.error("City registry not found at %s", _YAML_PATH)
        return {}

    with open(_YAML_PATH) as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    cities: dict[str, CityConfig] = {}
    for city_id, cfg in (raw.get("cities") or {}).items():
        try:
            cities[city_id] = CityConfig(
                id=city_id,
                display_name=cfg.get("display_name", city_id),
                country=cfg.get("country", ""),
                timezone=cfg.get("timezone", "UTC"),
                enabled=bool(cfg.get("enabled", True)),
                bbox={
                    "lat_min": float(cfg["bbox"]["lat_min"]),
                    "lon_min": float(cfg["bbox"]["lon_min"]),
                    "lat_max": float(cfg["bbox"]["lat_max"]),
                    "lon_max": float(cfg["bbox"]["lon_max"]),
                },
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("City registry: skipping %r — bad entry: %s", city_id, exc)

    logger.debug("City registry loaded %d cities from %s", len(cities), _YAML_PATH)
    return cities


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_city(city_id: str) -> CityConfig | None:
    """Return CityConfig for city_id (enabled or disabled), or None if unknown."""
    return _load().get(city_id)


def all_cities(*, include_disabled: bool = False) -> list[CityConfig]:
    """Return CityConfig list sorted by id.  Disabled cities excluded by default."""
    cities = list(_load().values())
    if not include_disabled:
        cities = [c for c in cities if c.enabled]
    return sorted(cities, key=lambda c: c.id)


def all_city_ids(*, include_disabled: bool = False) -> list[str]:
    """Return sorted list of city ids (enabled only by default)."""
    return [c.id for c in all_cities(include_disabled=include_disabled)]


def get_bbox(city_id: str) -> dict | None:
    """Return {lat_min, lon_min, lat_max, lon_max} for city_id, or None."""
    city = get_city(city_id)
    return city.bbox if city else None


def reload() -> None:
    """Force a re-read of cities.yaml (clears the lru_cache).  Useful in tests."""
    _load.cache_clear()
