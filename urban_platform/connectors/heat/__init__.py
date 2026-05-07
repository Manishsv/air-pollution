"""Heat domain connectors: temperature observations and green cover."""
from .openmeteo import fetch_temperature_observations as _fetch_temp_raw
from .osm_green_cover import compute_green_cover


def fetch_temperature_observations(
    city_name, lat_min, lon_min, lat_max, lon_max,
    lookback_days=1, session=None, *, city_id=None,
):
    df = _fetch_temp_raw(city_name, lat_min, lon_min, lat_max, lon_max,
                         lookback_days=lookback_days, session=session)
    if city_id and not df.empty:
        try:
            from urban_platform.observation_store import ObservationStoreWriter
            ObservationStoreWriter().write(df, domain="heat", city_id=city_id)
        except Exception:
            pass
    return df


__all__ = ["fetch_temperature_observations", "compute_green_cover"]
