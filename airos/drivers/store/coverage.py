"""Data coverage and observation uncertainty utilities.

Every H3 cell gets two extra signals written alongside domain signals:

    NEAREST_OBS_KM   — distance (km) to the nearest real observation point used
                        in interpolation.  0 = cell has a sensor; 30+ = pure extrapolation.

    DATA_CONFIDENCE  — 0.0–1.0 score derived from NEAREST_OBS_KM via an
                        inverse-square decay with a 10 km half-life:
                            confidence = 1 / (1 + (d / 10)²)
                        Meaning:
                          0 km  → 1.00  (sensor is in this cell)
                          5 km  → 0.80
                         10 km  → 0.50
                         20 km  → 0.20
                         30 km  → 0.10

These signals are written into h3_signals (domain = same as the parent domain,
source = 'coverage_model') and are therefore:
  • Visible to the H3 Expert Agent in its initial context
  • Queryable for the sensor siting score (siting_score = avg_risk × coverage_gap)

Sensor siting score
-------------------
    siting_score = avg_risk_importance × (1 - data_confidence)

Where avg_risk_importance converts risk_level to a numeric:
    severe   → 1.00
    high     → 0.75
    moderate → 0.40
    good     → 0.10

A cell that is consistently high-risk AND far from any sensor scores highest —
that is the single best location for the next sensor deployment.

Domain confidence defaults (when exact distances are unavailable)
----------------------------------------------------------------
    air         computed from IDW distances      (point observations)
    fire        1.0 where hotspot observed;      (direct observation, no interp)
                not written where no hotspot
    heat        0.50 — one city-centroid point   (coarse broadcast)
    flood       0.45 — centroid rainfall + model
    weather     0.30 — one city-centroid point   (coarsest broadcast)
    water       0.60 — satellite, moderate res
    construction 0.60 — SAR/optical, moderate res
    green       0.65 — NDVI, good spatial res
    noise       0.45 — proximity model only
    waste       1.0 where hotspot; not written elsewhere
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Confidence decay
# ---------------------------------------------------------------------------

_DECAY_KM = 10.0   # distance (km) at which confidence falls to 0.50

# Default confidence for domains where we can't compute exact distances
DOMAIN_DEFAULT_CONFIDENCE: dict[str, float] = {
    "air":          0.50,   # overridden per-cell when obs are available
    "fire":         1.00,   # only written for real hotspot cells
    "heat":         0.50,
    "flood":        0.45,
    "weather":      0.30,
    "water":        0.60,
    "construction": 0.60,
    "green":        0.65,
    "noise":        0.45,
    "waste":        1.00,   # only written for real hotspot cells
}

# Risk level → numeric importance for siting score
RISK_IMPORTANCE: dict[str, float] = {
    "severe":   1.00,
    "high":     0.75,
    "moderate": 0.40,
    "good":     0.10,
    "unknown":  0.25,
}


def distance_to_confidence(dist_km: float, decay_km: float = _DECAY_KM) -> float:
    """Convert distance-to-nearest-observation into a data confidence score [0, 1].

    Uses an inverse-square decay so confidence drops quickly with distance:
        f(d) = 1 / (1 + (d / decay_km)²)
    """
    if dist_km <= 0.0:
        return 1.0
    return 1.0 / (1.0 + (dist_km / decay_km) ** 2)


def coverage_signals(
    h3_id: str,
    nearest_obs_km: float | None,
    domain: str,
) -> list[dict]:
    """Build the NEAREST_OBS_KM and DATA_CONFIDENCE signal rows for one cell.

    Parameters
    ----------
    h3_id          : H3 cell identifier
    nearest_obs_km : distance to nearest real observation, or None to use domain default
    domain         : domain name (used to look up default confidence when dist is None)

    Returns a list of signal-row dicts ready for write_signals().
    """
    if nearest_obs_km is not None:
        confidence = distance_to_confidence(nearest_obs_km)
        rows = [
            {"h3_id": h3_id, "signal": "NEAREST_OBS_KM",
             "value": round(nearest_obs_km, 3), "unit": "km"},
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",
             "value": round(confidence, 4), "unit": "score"},
        ]
    else:
        confidence = DOMAIN_DEFAULT_CONFIDENCE.get(domain, 0.5)
        rows = [
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",
             "value": round(confidence, 4), "unit": "score"},
        ]
    return rows
