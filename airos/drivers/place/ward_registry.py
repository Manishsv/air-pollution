"""Ward boundary registry.

Loads ward boundaries from a GeoJSON file if one exists at
  data/registries/wards/{city_id}.geojson

Falls back to a synthetic rectangular grid derived from the city's bbox in
the city registry (data/config/cities.yaml).  The grid is deterministic —
same city always produces the same ward layout — so it can be used as a
stable demo fixture.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

from .schema import Ward
from .city_registry import get_bbox as _get_city_bbox

logger = logging.getLogger(__name__)

_REGISTRIES_DIR = Path(__file__).resolve().parents[3] / "data" / "registries" / "wards"

# Grid dimensions for synthetic wards (rows × cols)
_GRID = (4, 5)  # 20 wards per city

_ROW_NAMES = ["South", "South-Central", "North-Central", "North"]
_COL_NAMES = ["West", "West-Central", "Central", "East-Central", "East"]


def load_wards(city_id: str) -> List[Ward]:
    """Return ward boundaries for city_id.

    Tries to load from data/registries/wards/{city_id}.geojson first.
    Falls back to a synthetic rectangular grid using the bbox from the
    city registry (data/config/cities.yaml).
    """
    geojson_path = _REGISTRIES_DIR / f"{city_id}.geojson"
    if geojson_path.exists():
        return _load_from_geojson(city_id, geojson_path)

    bbox = _get_city_bbox(city_id)
    if bbox:
        return _synthetic_grid(
            city_id,
            bbox["lat_min"], bbox["lon_min"],
            bbox["lat_max"], bbox["lon_max"],
        )

    logger.warning(
        "No ward data for city_id=%r and no bbox in city registry — "
        "add the city to data/config/cities.yaml",
        city_id,
    )
    return []


def _load_from_geojson(city_id: str, path: Path) -> List[Ward]:
    try:
        with open(path, encoding="utf-8") as f:
            fc = json.load(f)
        wards = []
        for feat in fc.get("features", []):
            props = feat.get("properties", {})
            geom  = feat.get("geometry", {})
            if geom.get("type") != "Polygon":
                continue
            coords = geom["coordinates"][0]
            wards.append(Ward(
                ward_id=str(props.get("ward_id", props.get("id", len(wards)))),
                city_id=city_id,
                name=str(props.get("name", props.get("ward_name", f"Ward {len(wards)+1}"))),
                coordinates=coords,
                metadata={k: v for k, v in props.items()
                          if k not in ("ward_id", "id", "name", "ward_name")},
            ))
        logger.info("Loaded %d wards for %s from %s", len(wards), city_id, path)
        return wards
    except Exception as exc:
        logger.warning("Failed to load wards from %s: %s — using synthetic", path, exc)
        bbox = _get_city_bbox(city_id)
        if bbox:
            return _synthetic_grid(
                city_id,
                bbox["lat_min"], bbox["lon_min"],
                bbox["lat_max"], bbox["lon_max"],
            )
        return []


def _synthetic_grid(
    city_id: str,
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
) -> List[Ward]:
    """Divide the city bounding box into a uniform rows×cols grid of wards."""
    rows, cols = _GRID
    lat_step = (lat_max - lat_min) / rows
    lon_step = (lon_max - lon_min) / cols
    wards = []
    for r in range(rows):
        for c in range(cols):
            s = lat_min + r * lat_step
            n = s + lat_step
            w = lon_min + c * lon_step
            e = w + lon_step
            ward_num  = r * cols + c + 1
            row_name  = _ROW_NAMES[r] if r < len(_ROW_NAMES) else str(r)
            col_name  = _COL_NAMES[c] if c < len(_COL_NAMES) else str(c)
            wards.append(Ward(
                ward_id=f"{city_id}_w{ward_num:02d}",
                city_id=city_id,
                name=f"Ward {ward_num} ({row_name} {col_name})",
                coordinates=[[w, s], [e, s], [e, n], [w, n], [w, s]],
                metadata={"synthetic": True, "row": r, "col": c},
            ))
    return wards
