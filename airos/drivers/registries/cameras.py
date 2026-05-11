"""Camera registry — maps CCTV camera entity_id to physical location and city.

Operators register cameras by editing  data/config/camera_registry.json.
The schema per camera entry:

    {
      "entity_id":     "cam_blr_mg_road_01",   # matches device_id used in publisher
      "city_id":       "bangalore",
      "latitude":      12.9758,
      "longitude":     77.6005,
      "location_name": "MG Road junction — northbound lane",
      "active":        true                     # set false to exclude without deleting
    }

The registry is loaded once per process and cached.  Call `reload()` to force
a refresh (e.g. after an operator adds a new camera without restarting).

If the registry file does not exist or is empty, the crowd ingestor falls back
to observation-store lat/lon columns (point_lat / point_lon) if present.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Default path — relative to project root.  Override via CAMERA_REGISTRY env var.
_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "config" / "camera_registry.json"

# Module-level cache
_registry_df: pd.DataFrame | None = None
_registry_path: Path | None = None


def _load(path: Path) -> pd.DataFrame:
    """Load and validate the camera registry JSON file."""
    if not path.exists():
        logger.debug("Camera registry not found at %s — returning empty registry.", path)
        return _empty()

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        logger.warning("Camera registry parse error (%s): %s", path, exc)
        return _empty()

    if not isinstance(raw, list):
        logger.warning("Camera registry must be a JSON array — got %s", type(raw).__name__)
        return _empty()

    df = pd.DataFrame(raw)
    required = {"entity_id", "city_id", "latitude", "longitude"}
    missing = required - set(df.columns)
    if missing:
        logger.warning("Camera registry missing required columns: %s", missing)
        return _empty()

    # Coerce types
    df["latitude"]  = pd.to_numeric(df["latitude"],  errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["active"]    = df.get("active", True).astype(bool) if "active" in df.columns else True
    df = df[df["active"].fillna(True)]
    df = df.dropna(subset=["latitude", "longitude", "entity_id", "city_id"])

    logger.info("Camera registry loaded: %d active cameras from %s", len(df), path)
    return df.reset_index(drop=True)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["entity_id", "city_id", "latitude", "longitude", "location_name", "active"]
    )


def load(path: Path | str | None = None) -> pd.DataFrame:
    """Return the camera registry as a DataFrame (cached).

    Parameters
    ----------
    path : override the default registry file location.
    """
    global _registry_df, _registry_path

    import os
    env_path = os.environ.get("CAMERA_REGISTRY")
    resolved = Path(path or env_path or _DEFAULT_REGISTRY_PATH)

    if _registry_df is not None and resolved == _registry_path:
        return _registry_df

    _registry_df   = _load(resolved)
    _registry_path = resolved
    return _registry_df


def reload(path: Path | str | None = None) -> pd.DataFrame:
    """Force reload the registry (call after adding cameras without restart)."""
    global _registry_df
    _registry_df = None
    return load(path)


def cameras_for_city(city_id: str) -> pd.DataFrame:
    """Return the subset of cameras registered for a given city."""
    reg = load()
    if reg.empty:
        return reg
    return reg[reg["city_id"].astype(str) == city_id].reset_index(drop=True)


def locate_entity(entity_id: str) -> dict[str, Any] | None:
    """Return the registry row for a camera entity_id, or None if not registered."""
    reg = load()
    if reg.empty:
        return None
    row = reg[reg["entity_id"].astype(str) == str(entity_id)]
    if row.empty:
        return None
    return row.iloc[0].to_dict()
