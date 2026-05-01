from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd


def cache_exists(path: str | Path) -> bool:
    return Path(path).exists()


def is_cache_valid(path: str | Path, ttl_days: int) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    if ttl_days <= 0:
        return True
    age_seconds = time.time() - p.stat().st_mtime
    return age_seconds <= ttl_days * 86400


def load_cached_geodata(path: str | Path) -> gpd.GeoDataFrame:
    p = Path(path)
    if p.suffix.lower() in {".parquet"}:
        return gpd.read_parquet(p)
    return gpd.read_file(p)


def save_cached_geodata(gdf: gpd.GeoDataFrame, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() in {".parquet"}:
        gdf.to_parquet(p, index=False)
    else:
        gdf.to_file(p, driver="GeoJSON")


def load_cached_dataframe(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() in {".parquet"}:
        return pd.read_parquet(p)
    if p.suffix.lower() in {".json"}:
        return pd.read_json(p)
    return pd.read_csv(p)


def save_cached_dataframe(df: pd.DataFrame, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() in {".parquet"}:
        df.to_parquet(p, index=False)
    elif p.suffix.lower() in {".json"}:
        df.to_json(p, orient="records", indent=2, date_format="iso")
    else:
        df.to_csv(p, index=False)


def stable_slug(text: str) -> str:
    return (
        "".join(ch.lower() if ch.isalnum() else "_" for ch in text.strip())
        .strip("_")
        .replace("__", "_")
    )


def polygon_hash_wgs84(geom_wkb_hex: str) -> str:
    # Accept a WKB hex string (stable across runs if geometry is stable)
    return hashlib.sha1(geom_wkb_hex.encode("utf-8")).hexdigest()[:10]


def cache_path(
    processed_cache_dir: Path,
    city_name: str,
    spatial_mode: str,
    h3_resolution: int,
    data_type: str,
    *,
    bbox: Optional[tuple[float, float, float, float]] = None,  # south,north,west,east
    poly_hash: Optional[str] = None,
    ext: str = "geojson",
) -> Path:
    city = stable_slug(city_name)
    mode = stable_slug(spatial_mode)
    parts = [city, mode]

    if bbox is not None:
        south, north, west, east = bbox
        parts.extend(
            [
                f"{south:.5f}",
                f"{north:.5f}",
                f"{west:.5f}",
                f"{east:.5f}",
            ]
        )
    elif poly_hash is not None:
        parts.append(poly_hash)

    parts.append(f"h3r{int(h3_resolution)}")
    parts.append(stable_slug(data_type))

    filename = "_".join(parts) + f".{ext}"
    return processed_cache_dir / "cache" / filename


def save_json(obj: dict, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

