"""Air-quality connectors."""
from .openmeteo_aq import fetch_air_quality_observations as _fetch_aq_raw


def fetch_air_quality_observations(
    city_name, lat_min, lon_min, lat_max, lon_max,
    lookback_hours=24, session=None, *, city_id=None,
):
    df = _fetch_aq_raw(city_name, lat_min, lon_min, lat_max, lon_max,
                       lookback_hours=lookback_hours, session=session)
    if city_id and not df.empty:
        try:
            from urban_platform.observation_store import ObservationStoreWriter
            ObservationStoreWriter().write(df, domain="air", city_id=city_id)
        except Exception:
            pass
    return df


__all__ = ["fetch_air_quality_observations"]

