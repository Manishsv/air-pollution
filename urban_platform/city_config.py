"""
City registry for the AIR Climate Suite.

Each entry defines the canonical city_id, display name, bounding box, and
CPCB city name aliases used by the CPCB connector.

Connector selection is driven by environment variables (not per-city config):
  CPCB_API_KEY   — if set, CPCB is used for air quality
  GEE_PROJECT    — if set, GEE (MODIS LST + GPM) is used for heat and flood
  Fallback: OpenMeteo for any domain whose env var is absent
"""
from __future__ import annotations

CITIES: dict[str, dict] = {
    "bangalore": {
        "display_name": "Bangalore",
        "cpcb_name":    "Bengaluru",      # city name as it appears in CPCB API
        "bbox": dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69),
    },
    "delhi": {
        "display_name": "Delhi",
        "cpcb_name":    "Delhi",
        "bbox": dict(lat_min=28.50, lon_min=76.90, lat_max=28.80, lon_max=77.30),
    },
    "mumbai": {
        "display_name": "Mumbai",
        "cpcb_name":    "Mumbai",
        "bbox": dict(lat_min=18.90, lon_min=72.75, lat_max=19.20, lon_max=73.00),
    },
    "hyderabad": {
        "display_name": "Hyderabad",
        "cpcb_name":    "Hyderabad",
        "bbox": dict(lat_min=17.30, lon_min=78.35, lat_max=17.55, lon_max=78.60),
    },
    "chennai": {
        "display_name": "Chennai",
        "cpcb_name":    "Chennai",
        "bbox": dict(lat_min=12.90, lon_min=80.15, lat_max=13.15, lon_max=80.35),
    },
    "pune": {
        "display_name": "Pune",
        "cpcb_name":    "Pune",
        "bbox": dict(lat_min=18.45, lon_min=73.75, lat_max=18.65, lon_max=73.98),
    },
}


def get_city(city_id: str) -> dict:
    """Return city config. Raises KeyError for unknown city_id."""
    return CITIES[city_id.lower()]


def get_bbox(city_id: str) -> dict:
    return get_city(city_id)["bbox"]


def get_cpcb_name(city_id: str) -> str:
    return get_city(city_id).get("cpcb_name", city_id)


# Panel-ready list: display_name → city_id (for Streamlit selectbox)
PANEL_CITIES: dict[str, str] = {
    v["display_name"]: k for k, v in CITIES.items()
}
