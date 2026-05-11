from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

RAW_DATA_ROOT: Path = Path(__file__).resolve().parents[3] / "data" / "raw"

# Canonical narrow column order
OBSERVATION_COLUMNS = [
    "observation_id",   # sha256[:32] of station_id|timestamp|variable
    "domain",           # "flood" | "air" | "heat"
    "city_id",
    "station_id",
    "latitude",
    "longitude",
    "timestamp",        # datetime[ns, UTC]
    "variable",         # measured quantity name
    "value",            # float
    "unit",
    "source",           # data_source from connector (e.g. "openmeteo")
    "quality_flag",     # "real" | "synthetic"
    "fetched_at",       # wall-clock UTC of the API call
]

# (connector_column_name) -> (variable_label, unit)
FLOOD_VARIABLE_MAP: Dict[str, Tuple[str, str]] = {
    "rainfall_intensity_mm_per_hr": ("rainfall_intensity_mm_per_hr", "mm/hr"),
    "rainfall_accumulation_3h_mm":  ("rainfall_accumulation_3h_mm",  "mm"),
}

AIR_VARIABLE_MAP: Dict[str, Tuple[str, str]] = {
    "pm25_ugm3":    ("pm25_ugm3",    "µg/m³"),
    "pm10_ugm3":    ("pm10_ugm3",    "µg/m³"),
    "european_aqi": ("european_aqi", "index"),
}

HEAT_VARIABLE_MAP: Dict[str, Tuple[str, str]] = {
    "temperature_c":          ("temperature_c",          "°C"),
    "apparent_temperature_c": ("apparent_temperature_c", "°C"),
    "relative_humidity_pct":  ("relative_humidity_pct",  "%"),
}

DOMAIN_VARIABLE_MAPS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "flood": FLOOD_VARIABLE_MAP,
    "air":   AIR_VARIABLE_MAP,
    "heat":  HEAT_VARIABLE_MAP,
}

DEFAULT_RETENTION_DAYS: Dict[str, int] = {
    "flood": 90,
    "air":   90,
    "heat":  90,
}
