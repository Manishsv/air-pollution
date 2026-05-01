from __future__ import annotations

import pandas as pd

from src.aq_data import build_aq_panel as _legacy_build_aq_panel


def interpolate_pm25(*, observations: pd.DataFrame, grid: pd.DataFrame, lookback_days: int, h3_resolution: int, idw_power: float, min_stations: int) -> pd.DataFrame:
    """
    Interpolate PM2.5 over a grid from station observations.

    Migration note: uses legacy IDW logic which expects station-hourly input, not
    canonical Observation yet. Will be adapted once registries/fabric are wired.
    """
    return _legacy_build_aq_panel(
        h3_grid=grid,
        stations_hourly=observations,
        lookback_days=lookback_days,
        h3_resolution=h3_resolution,
        idw_power=idw_power,
        min_stations=min_stations,
    )


def build_aq_panel_from_observation_table(
    observation_table: pd.DataFrame,
    *,
    h3_grid_centroids: pd.DataFrame,
    lookback_days: int,
    h3_resolution: int,
    idw_power: float,
    min_stations: int,
) -> pd.DataFrame:
    """
    Derive legacy-compatible `aq_panel` from the canonical observation table.

    The legacy interpolation expects station-hourly input (point observations):
      station_id, station_name, latitude, longitude, timestamp, pm25, data_source
    """
    if observation_table is None or observation_table.empty:
        return pd.DataFrame()

    df = observation_table.copy()
    pm = df[df["variable"].astype(str).str.lower().eq("pm25")].copy()

    # Prefer sensor observations (station points) rather than the interpolated cell series.
    if "entity_type" in pm.columns:
        pm = pm[pm["entity_type"].astype(str).str.lower().eq("sensor")].copy()
    if pm.empty:
        return pd.DataFrame()

    stations_hourly = pd.DataFrame(
        {
            "station_id": pm["entity_id"].astype(str),
            "station_name": (pm["station_name"] if "station_name" in pm.columns else pd.Series([""] * len(pm))).astype(str),
            "latitude": pd.to_numeric(pm.get("point_lat"), errors="coerce"),
            "longitude": pd.to_numeric(pm.get("point_lon"), errors="coerce"),
            "timestamp": pd.to_datetime(pm["timestamp"], utc=True, errors="coerce"),
            "pm25": pd.to_numeric(pm["value"], errors="coerce"),
            "data_source": pm.get("source", "unknown").astype(str),
        }
    ).dropna(subset=["station_id", "latitude", "longitude", "timestamp", "pm25"])

    return _legacy_build_aq_panel(
        h3_grid=h3_grid_centroids,
        stations_hourly=stations_hourly,
        lookback_days=lookback_days,
        h3_resolution=h3_resolution,
        idw_power=idw_power,
        min_stations=min_stations,
    )


def build_weather_hourly_from_observation_table(observation_table: pd.DataFrame) -> pd.DataFrame:
    """
    Derive legacy-compatible `weather_hourly` from canonical observation table.

    The observation table is grid-aligned (weather was broadcast); we collapse
    back to a single time series by taking the first record per timestamp+variable.
    """
    if observation_table is None or observation_table.empty:
        return pd.DataFrame()

    df = observation_table.copy()
    if "entity_type" in df.columns:
        df = df[df["entity_type"].astype(str).str.lower().eq("weather")].copy()
    if df.empty:
        return pd.DataFrame()

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).copy()

    # Deduplicate broadcasted copies.
    df = df.sort_values(["timestamp", "variable"]).drop_duplicates(subset=["timestamp", "variable"], keep="first")

    wide = df.pivot_table(index="timestamp", columns="variable", values="value", aggfunc="first").reset_index()

    # Restore provenance column expected by legacy feature engineering.
    q = df.drop_duplicates(subset=["timestamp"])[["timestamp", "quality_flag"]].copy()
    q["weather_source_type"] = q["quality_flag"].astype(str).str.lower().apply(lambda s: "synthetic" if "synthetic" in s else "real")
    wide = wide.merge(q[["timestamp", "weather_source_type"]], on="timestamp", how="left")
    return wide

