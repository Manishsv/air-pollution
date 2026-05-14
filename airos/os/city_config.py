"""
City registry for the AIR Climate Suite.

Each entry defines the canonical city_id, display name, bounding box, and
CPCB city name aliases used by the CPCB connector.

Connector selection is driven by environment variables (not per-city config):
  CPCB_API_KEY   — if set, CPCB is used for air quality
  EARTHDATA_TOKEN — if set, NASA Earthdata (MODIS LST + GPM IMERG) is used for heat and flood
  Fallback: OpenMeteo for any domain whose env var is absent
"""
from __future__ import annotations

CITIES: dict[str, dict] = {
    "bangalore": {
        "display_name": "Bangalore",
        "cpcb_name":    "Bengaluru",      # city name as it appears in CPCB API
        "centre":       (12.9716, 77.5946),
        "zoom":         11,
        "bbox": dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69),
        "timezone":     "Asia/Kolkata",
    },
    "delhi": {
        "display_name": "Delhi",
        "cpcb_name":    "Delhi",
        "centre":       (28.6139, 77.2090),
        "zoom":         11,
        "bbox": dict(lat_min=28.50, lon_min=76.90, lat_max=28.80, lon_max=77.30),
        "timezone":     "Asia/Kolkata",
    },
    "mumbai": {
        "display_name": "Mumbai",
        "cpcb_name":    "Mumbai",
        "centre":       (19.0760, 72.8777),
        "zoom":         11,
        "bbox": dict(lat_min=18.90, lon_min=72.75, lat_max=19.20, lon_max=73.00),
        "timezone":     "Asia/Kolkata",
    },
    "hyderabad": {
        "display_name": "Hyderabad",
        "cpcb_name":    "Hyderabad",
        "centre":       (17.3850, 78.4867),
        "zoom":         11,
        "bbox": dict(lat_min=17.30, lon_min=78.35, lat_max=17.55, lon_max=78.60),
        "timezone":     "Asia/Kolkata",
    },
    "chennai": {
        "display_name": "Chennai",
        "cpcb_name":    "Chennai",
        "centre":       (13.0827, 80.2707),
        "zoom":         11,
        "bbox": dict(lat_min=12.90, lon_min=80.15, lat_max=13.15, lon_max=80.35),
        "timezone":     "Asia/Kolkata",
    },
    "pune": {
        "display_name": "Pune",
        "cpcb_name":    "Pune",
        "centre":       (18.5204, 73.8567),
        "zoom":         11,
        "bbox": dict(lat_min=18.45, lon_min=73.75, lat_max=18.65, lon_max=73.98),
        "timezone":     "Asia/Kolkata",
    },
}


def get_city(city_id: str) -> dict:
    """Return city config. Raises KeyError for unknown city_id."""
    return CITIES[city_id.lower()]


def get_bbox(city_id: str) -> dict:
    return get_city(city_id)["bbox"]


def get_centre(city_id: str) -> tuple[float, float]:
    """Return (lat, lng) map centre for the city."""
    return get_city(city_id)["centre"]


def get_zoom(city_id: str) -> int:
    return get_city(city_id).get("zoom", 11)


def get_timezone(city_id: str) -> str:
    """Return IANA timezone name for the city.

    Used for converting UTC timestamps in `h3_signals.observed_at` to local
    civil time for circadian baseline computation (methodology §3.2).
    Defaults to Asia/Kolkata (the deployment region) if missing.
    """
    try:
        return get_city(city_id).get("timezone", "Asia/Kolkata")
    except KeyError:
        return "Asia/Kolkata"


def get_cpcb_name(city_id: str) -> str:
    return get_city(city_id).get("cpcb_name", city_id)


# Panel-ready list: display_name → city_id (for Streamlit selectbox)
PANEL_CITIES: dict[str, str] = {
    v["display_name"]: k for k, v in CITIES.items()
}
