from __future__ import annotations

import hashlib

import pandas as pd

from .schemas import empty_observations, normalize_quality_flag


def _obs_id(*parts: str) -> str:
    raw = "|".join(parts)
    return "obs_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def stations_pm25_to_observations(stations_hourly: pd.DataFrame) -> pd.DataFrame:
    """
    Convert station-hourly PM2.5 readings into the canonical Observation schema.

    Notes:
    - `entity_id` is initially set to the source `station_id` (string). The sensors
      registry can later remap to stable ids.
    - Keeps provenance via `source` + `quality_flag` ("synthetic" if data_source hints so).
    """
    if stations_hourly is None or stations_hourly.empty:
        return empty_observations()

    df = stations_hourly.copy()
    if "timestamp" not in df.columns:
        raise ValueError("stations_hourly missing required column: timestamp")
    if "station_id" not in df.columns:
        raise ValueError("stations_hourly missing required column: station_id")
    if "pm25" not in df.columns:
        raise ValueError("stations_hourly missing required column: pm25")

    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    src = df.get("data_source", "unknown").astype(str)
    qf = src.apply(lambda s: "synthetic" if "synthetic" in s.lower() else "ok").map(normalize_quality_flag)

    out = pd.DataFrame(
        {
            "entity_id": df["station_id"].astype(str),
            "entity_type": "sensor",
            "observed_property": "pm25",
            "value": pd.to_numeric(df["pm25"], errors="coerce"),
            "unit": "µg/m3",
            "timestamp": ts,
            "source": src,
            "quality_flag": qf,
            # provenance / join helpers (allowed as extra columns)
            "point_lat": pd.to_numeric(df.get("latitude"), errors="coerce"),
            "point_lon": pd.to_numeric(df.get("longitude"), errors="coerce"),
            "station_name": df.get("station_name", "").astype(str),
        }
    )

    out["observation_id"] = out.apply(
        lambda r: _obs_id(str(r["entity_id"]), str(r["observed_property"]), str(pd.to_datetime(r["timestamp"], utc=True)), str(r["source"])),
        axis=1,
    )

    # canonical column order first (allow extra columns later if we append)
    out = out[
        [
            "observation_id",
            "entity_id",
            "entity_type",
            "observed_property",
            "value",
            "unit",
            "timestamp",
            "source",
            "quality_flag",
            "point_lat",
            "point_lon",
            "station_name",
        ]
    ]
    return out


def weather_hourly_to_observations(weather_hourly: pd.DataFrame) -> pd.DataFrame:
    """
    Convert hourly weather dataframe into canonical Observation records.

    Input (legacy-compatible):
      timestamp + weather vars, plus optional weather_source_type (real|synthetic)
    """
    if weather_hourly is None or weather_hourly.empty:
        return empty_observations()

    df = weather_hourly.copy()
    if "timestamp" not in df.columns:
        raise ValueError("weather_hourly missing required column: timestamp")

    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    source_type = df.get("weather_source_type", "unknown").astype(str)
    qf = source_type.apply(lambda s: "synthetic" if "synthetic" in s.lower() else "ok").map(normalize_quality_flag)

    # Keep only columns that are actually in the dataframe (avoid forcing schema changes).
    var_units = {
        "temperature_2m": "°C",
        "relative_humidity_2m": "%",
        "wind_speed_10m": "m/s",
        "wind_direction_10m": "deg",
        "precipitation": "mm",
        "wind_direction_sin": "1",
        "wind_direction_cos": "1",
    }
    vars_present = [v for v in var_units.keys() if v in df.columns]
    if not vars_present:
        return empty_observations()

    rows = []
    for v in vars_present:
        tmp = pd.DataFrame(
            {
                "entity_id": "weather_point",
                "entity_type": "weather",
                "observed_property": v,
                "value": pd.to_numeric(df[v], errors="coerce"),
                "unit": var_units[v],
                "timestamp": ts,
                "source": "open_meteo",
                "quality_flag": qf,
                "spatial_scope": "global",  # will be broadcast to grid cells
            }
        )
        rows.append(tmp)

    out = pd.concat(rows, ignore_index=True)
    out["observation_id"] = out.apply(
        lambda r: _obs_id(str(r["entity_id"]), str(r["observed_property"]), str(pd.to_datetime(r["timestamp"], utc=True)), str(r["source"])),
        axis=1,
    )

    out = out[
        [
            "observation_id",
            "entity_id",
            "entity_type",
            "observed_property",
            "value",
            "unit",
            "timestamp",
            "source",
            "quality_flag",
            "spatial_scope",
        ]
    ]
    return out

