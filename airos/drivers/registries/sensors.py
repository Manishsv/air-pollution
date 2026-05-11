from __future__ import annotations

import hashlib
from typing import Optional

import pandas as pd


def _stable_entity_id(*parts: str) -> str:
    raw = "|".join([p.strip() for p in parts if p is not None])
    return "sensor_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def register_sensors(stations_hourly: pd.DataFrame, *, source_hint: Optional[str] = None) -> pd.DataFrame:
    """
    Deduplicate stations and map source station IDs to stable `entity_id`.

    Input expectation (legacy-compatible):
      station_id, station_name, latitude, longitude, (optional) data_source

    Output:
      entity_id, station_id, station_name, latitude, longitude, source
    """
    if stations_hourly is None or stations_hourly.empty:
        return pd.DataFrame(columns=["entity_id", "station_id", "station_name", "latitude", "longitude", "source"])

    df = stations_hourly.copy()
    src = source_hint or (df.get("data_source") if isinstance(df, pd.DataFrame) else None)
    if "data_source" in df.columns:
        df["source"] = df["data_source"].astype(str)
    else:
        df["source"] = str(source_hint or "unknown")

    meta = (
        df[["station_id", "station_name", "latitude", "longitude", "source"]]
        .dropna(subset=["station_id", "latitude", "longitude"])
        .drop_duplicates()
        .reset_index(drop=True)
    )
    meta["entity_id"] = meta.apply(
        lambda r: _stable_entity_id(str(r["source"]), str(r["station_id"]), f'{float(r["latitude"]):.6f}', f'{float(r["longitude"]):.6f}'),
        axis=1,
    )
    # Prefer stable column order
    return meta[["entity_id", "station_id", "station_name", "latitude", "longitude", "source"]]

