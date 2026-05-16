"""Cause classifier for elevated PM2.5 / AQI incidents.

Reads H3 signals for a cell and returns a ranked list of cause hypotheses with
confidence scores. Used by InsightPacketGenerator to enrich air-domain packets
with cause attribution and department routing.

Hypotheses (in priority order for display):
  construction_dust     — coarse dust from active construction sites
  waste_burning         — biomass / solid waste combustion
  traffic_resuspension  — road dust and tailpipe on high-density roads
  industrial_emission   — industrial SO2/NO2 point-source
  meteorological_trapping — inversion / low-wind accumulation

Signal requirements (all fetched from h3_signals for the same city/h3_id):
  PM25_PM10_RATIO  (air)        < 0.5 → coarse; > 0.8 → fine combustion
  PM10             (air)        absolute concentration
  NO2              (air)        traffic + industrial indicator
  SO2              (air)        industrial + waste-burning indicator
  CONSTRUCTION_RISK_INDEX (construction)
  SITE             (waste)      1 = active waste site in cell
  ROAD_DENSITY     (roads)
  MAJOR_ROAD_RATIO (roads)
  WIND_SPEED_KMH   (weather)    low wind → meteorological trapping
  HUMIDITY_PCT     (weather)    high humidity worsens trapping
  FRP              (fire)       fire radiative power → burning

Usage:
    from airos.os.cause_classifier import CauseClassifier
    results = CauseClassifier().classify("bangalore", "8a3969a0cdbffff")
    # → [{"cause": "construction_dust", "confidence": 0.78, "evidence": [...]}, ...]
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Versioning — methodology §4.4
# Bump CLASSIFIER_VERSION when the scoring logic changes (e.g. new cause added,
# weight composition rule changes). Bump WEIGHT_CONFIG_VERSION when the
# numerical thresholds/weights change. Both are written to every decision
# packet so historical packets can be reproduced or stratified by version.
# ---------------------------------------------------------------------------

CLASSIFIER_VERSION    = "cause-classifier-v0.7"
WEIGHT_CONFIG_VERSION = "weights-v0.7-airshed-upwind"

# Confidence margin for tie-breaker routing (§4.4). When top1 − top2 < this,
# the packet is flagged `attribution_uncertain` and the second cause's
# primary department is emitted as `secondary_review_by`.
ATTRIBUTION_MARGIN    = 0.15

# ── Externalised weights + thresholds (methodology §4.4) ─────────────────────
# Loaded from data/config/cause_classifier_weights.yaml at module import so
# tuning is a config edit, not a code change. Hardcoded fallbacks below are
# used if the YAML is missing or malformed — preserves the behaviour of the
# pre-externalisation classifier.

_FALLBACK_THRESHOLDS = {
    "pm25_elevated":     60.0,
    "pm10_high":        100.0,
    "no2_high":          40.0,
    "so2_high":          20.0,
    "ratio_coarse":       0.5,
    "ratio_fine":         0.8,
    "wind_calm":          5.0,
    "wind_low":          10.0,
    "humidity_high":     70.0,
    "construction_high":  0.6,
    "construction_mod":   0.3,
    "road_high":      25000,
    "road_mod":       15000,
    "frp_present":       10.0,
    "poi_many":           5,
    "poi_some":           1,
}

# Legacy module-level constants kept for any external callers still importing
# them by name. New code should read from `_W.thresh(...)` instead.
_PM25_ELEVATED = _FALLBACK_THRESHOLDS["pm25_elevated"]
_PM10_HIGH     = _FALLBACK_THRESHOLDS["pm10_high"]
_NO2_HIGH      = _FALLBACK_THRESHOLDS["no2_high"]
_SO2_HIGH      = _FALLBACK_THRESHOLDS["so2_high"]
_RATIO_COARSE  = _FALLBACK_THRESHOLDS["ratio_coarse"]
_RATIO_FINE    = _FALLBACK_THRESHOLDS["ratio_fine"]
_WIND_CALM     = _FALLBACK_THRESHOLDS["wind_calm"]
_WIND_LOW      = _FALLBACK_THRESHOLDS["wind_low"]
_HUMIDITY_HIGH = _FALLBACK_THRESHOLDS["humidity_high"]
_CONSTR_HIGH   = _FALLBACK_THRESHOLDS["construction_high"]
_CONSTR_MOD    = _FALLBACK_THRESHOLDS["construction_mod"]
_ROAD_HIGH     = _FALLBACK_THRESHOLDS["road_high"]
_ROAD_MOD      = _FALLBACK_THRESHOLDS["road_mod"]
_FRP_PRESENT   = _FALLBACK_THRESHOLDS["frp_present"]
_POI_MANY      = _FALLBACK_THRESHOLDS["poi_many"]
_POI_SOME      = _FALLBACK_THRESHOLDS["poi_some"]


class _WeightConfig:
    """Loaded view over `data/config/cause_classifier_weights.yaml`.

    Exposes:
        .thresh(key)           → numeric threshold
        .cause(cause, key)     → (weight: float, band: str)
        .version               → string (overrides the module WEIGHT_CONFIG_VERSION
                                  if the YAML defines its own `version` field)
    """

    def __init__(self) -> None:
        self._thresholds = dict(_FALLBACK_THRESHOLDS)
        self._causes: dict[str, dict[str, tuple[float, str]]] = {}
        self._version: str | None = None
        self._loaded = False
        self._reload()

    def _reload(self) -> None:
        try:
            import os
            import yaml
            here = os.path.dirname(__file__)
            yaml_path = os.path.normpath(os.path.join(
                here, "..", "..", "data", "config", "cause_classifier_weights.yaml",
            ))
            with open(yaml_path) as f:
                data = yaml.safe_load(f) or {}
            for k, v in (data.get("thresholds") or {}).items():
                self._thresholds[k] = v
            for cause, rules in (data.get("causes") or {}).items():
                self._causes[cause] = {
                    key: (float(rule.get("weight", 0)), str(rule.get("band", "static")))
                    for key, rule in (rules or {}).items()
                    if isinstance(rule, dict)
                }
            self._version = data.get("version")
            self._loaded  = True
            logger.debug("CauseClassifier weights loaded from %s (version %s)",
                         yaml_path, self._version)
        except Exception as exc:
            logger.warning(
                "Could not load cause_classifier_weights.yaml; using hardcoded fallbacks: %s",
                exc,
            )

    def thresh(self, key: str) -> float:
        return self._thresholds.get(key, 0)

    def cause(self, cause: str, key: str) -> tuple[float, str]:
        """Return (weight, band) for a cause/key pair, defaulting to (0, 'static')."""
        return self._causes.get(cause, {}).get(key, (0.0, "static"))

    @property
    def version(self) -> str | None:
        return self._version


_W = _WeightConfig()

# If the YAML supplied a version, use it as the canonical WEIGHT_CONFIG_VERSION
# so packets reflect the live config rather than the module-level default.
if _W.version:
    WEIGHT_CONFIG_VERSION = _W.version


class CauseClassifier:
    """Classify the likely cause of an elevated-pollution event for one H3 cell."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from airos.drivers.store.schema import DB_PATH
            db_path = str(DB_PATH)
        self._db = db_path

    # ── Public API ─────────────────────────────────────────────────────────

    def classify(
        self,
        city_id: str,
        h3_id: str,
    ) -> list[dict[str, Any]]:
        """Return ranked cause hypotheses for the given cell.

        Returns a list of dicts (highest confidence first):
        [
          {
            "cause":      str,          # e.g. "construction_dust"
            "confidence": float,        # 0.0–1.0
            "evidence":   list[str],    # human-readable signal observations
            "signals":    dict,         # raw signal values used
          }, ...
        ]
        Only causes with confidence > 0.05 are returned.
        """
        sigs = self._load_signals(city_id, h3_id)
        if not sigs:
            return []

        results = []
        for fn in (
            self._construction_dust,
            self._waste_burning,
            self._traffic_resuspension,
            self._industrial_emission,
            self._meteorological_trapping,
            self._regional_transport,
        ):
            h = fn(sigs)
            if h["confidence"] > 0.05:
                results.append(h)

        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results

    def classify_batch(
        self,
        city_id: str,
        h3_ids: list[str],
    ) -> dict[str, list[dict]]:
        """Classify a batch of cells. Returns {h3_id: hypotheses}."""
        sigs_batch = self._load_signals_batch(city_id, h3_ids)
        out: dict[str, list[dict]] = {}
        for h3_id in h3_ids:
            sigs = sigs_batch.get(h3_id, {})
            if not sigs:
                out[h3_id] = []
                continue
            results = []
            for fn in (
                self._construction_dust,
                self._waste_burning,
                self._traffic_resuspension,
                self._industrial_emission,
                self._meteorological_trapping,
            ):
                h = fn(sigs)
                if h["confidence"] > 0.05:
                    results.append(h)
            results.sort(key=lambda x: x["confidence"], reverse=True)
            out[h3_id] = results
        return out

    # ── Signal loading ──────────────────────────────────────────────────────

    def _load_signals(self, city_id: str, h3_id: str) -> dict[str, float | None]:
        from airos.drivers.store.schema import ro_connect
        conn = ro_connect(self._db)
        try:
            # Pick the most recent value for each signal independently —
            # different domains have different ingestion cadences.
            rows = conn.execute(
                """
                SELECT s.signal, s.value
                FROM h3_signals s
                INNER JOIN (
                    SELECT signal, MAX(hour_bucket) AS max_bucket
                    FROM h3_signals
                    WHERE city_id = ? AND h3_id = ?
                    GROUP BY signal
                ) latest ON s.signal = latest.signal AND s.hour_bucket = latest.max_bucket
                WHERE s.city_id = ? AND s.h3_id = ?
                """,
                (city_id, h3_id, city_id, h3_id),
            ).fetchall()
        finally:
            conn.close()
        return {r[0]: r[1] for r in rows}

    def _load_signals_batch(
        self, city_id: str, h3_ids: list[str]
    ) -> dict[str, dict[str, float | None]]:
        placeholders = ",".join("?" * len(h3_ids))
        from airos.drivers.store.schema import ro_connect
        conn = ro_connect(self._db)
        try:
            # Per-cell, per-signal latest value (domains update at different cadences).
            rows = conn.execute(
                f"""
                SELECT s.h3_id, s.signal, s.value
                FROM h3_signals s
                INNER JOIN (
                    SELECT h3_id, signal, MAX(hour_bucket) AS max_bucket
                    FROM h3_signals
                    WHERE city_id = ? AND h3_id IN ({placeholders})
                    GROUP BY h3_id, signal
                ) latest ON s.h3_id = latest.h3_id
                         AND s.signal = latest.signal
                         AND s.hour_bucket = latest.max_bucket
                WHERE s.city_id = ?
                """,
                [city_id] + h3_ids + [city_id],
            ).fetchall()
        finally:
            conn.close()
        out: dict[str, dict] = {}
        for h3_id, signal, value in rows:
            out.setdefault(h3_id, {})[signal] = value
        return out

    # ── Hypothesis scorers ──────────────────────────────────────────────────

    def _bump(self, out: dict, cause: str, key: str, text: str) -> None:
        """Add weight to score + append band-prefixed evidence line.

        Resolves (weight, band) from the externalised YAML; if the YAML didn't
        define the key, weight is 0 so the line silently contributes nothing.
        """
        w, band = _W.cause(cause, key)
        if w <= 0:
            return
        out["score"] += w
        out["evidence"].append(f"[{band}] {text}")

    def _construction_dust(self, sigs: dict) -> dict:
        out = {"score": 0.0, "evidence": []}
        cause = "construction_dust"

        ratio    = sigs.get("PM25_PM10_RATIO")
        pm10     = sigs.get("PM10")
        constr   = sigs.get("CONSTRUCTION_RISK_INDEX")
        no2      = sigs.get("NO2")
        poi_con  = sigs.get("POI_CONSTRUCTION_COUNT") or 0

        coarse  = _W.thresh("ratio_coarse")
        pm10_hi = _W.thresh("pm10_high")
        ch_hi   = _W.thresh("construction_high")
        ch_mod  = _W.thresh("construction_mod")
        poi_m   = _W.thresh("poi_many")
        poi_s   = _W.thresh("poi_some")

        if ratio is not None and ratio < coarse:
            self._bump(out, cause, "coarse_ratio",
                       f"PM2.5/PM10 ratio {ratio:.2f} < {coarse} (coarse-dominant)")
        elif ratio is not None and ratio < 0.65:
            self._bump(out, cause, "moderate_coarse_ratio",
                       f"PM2.5/PM10 ratio {ratio:.2f} (moderately coarse)")

        if pm10 is not None and pm10 > pm10_hi:
            self._bump(out, cause, "pm10_high",
                       f"PM10 {pm10:.1f} µg/m³ > {pm10_hi} threshold")
        elif pm10 is not None and pm10 > 70:
            self._bump(out, cause, "pm10_moderate",
                       f"PM10 {pm10:.1f} µg/m³ (moderate)")

        if constr is not None and constr >= ch_hi:
            self._bump(out, cause, "constr_high",
                       f"CONSTRUCTION_RISK_INDEX {constr:.2f} (satellite — high)")
        elif constr is not None and constr >= ch_mod:
            self._bump(out, cause, "constr_moderate",
                       f"CONSTRUCTION_RISK_INDEX {constr:.2f} (satellite — moderate)")

        if poi_con >= poi_m:
            self._bump(out, cause, "poi_many",
                       f"{int(poi_con)} OSM-tagged construction sites in cell")
        elif poi_con >= poi_s:
            self._bump(out, cause, "poi_some",
                       f"{int(poi_con)} OSM-tagged construction site(s) in cell")

        if no2 is not None and no2 < 20:
            self._bump(out, cause, "low_no2_bonus",
                       f"NO2 {no2:.1f} µg/m³ (low — reduces traffic/industrial weight)")

        return {
            "cause": cause,
            "confidence": round(min(out["score"], 1.0), 3),
            "evidence": out["evidence"],
            "signals": _pick(sigs, [
                "PM25_PM10_RATIO", "PM10", "CONSTRUCTION_RISK_INDEX",
                "POI_CONSTRUCTION_COUNT", "NO2",
            ]),
        }

    def _waste_burning(self, sigs: dict) -> dict:
        out = {"score": 0.0, "evidence": []}
        cause = "waste_burning"

        ratio  = sigs.get("PM25_PM10_RATIO")
        frp    = sigs.get("FRP")
        waste  = sigs.get("SITE")
        so2    = sigs.get("SO2")
        pm25   = sigs.get("PM25")
        poi_w  = sigs.get("POI_WASTE_FACILITY_COUNT") or 0
        poi_c  = sigs.get("POI_CREMATORIUM_COUNT") or 0

        fine    = _W.thresh("ratio_fine")
        frp_th  = _W.thresh("frp_present")
        so2_hi  = _W.thresh("so2_high")
        pm25_el = _W.thresh("pm25_elevated")
        poi_s   = _W.thresh("poi_some")

        if ratio is not None and ratio > fine:
            self._bump(out, cause, "fine_ratio",
                       f"PM2.5/PM10 ratio {ratio:.2f} > {fine} (fine combustion)")
        elif ratio is not None and ratio > 0.65:
            self._bump(out, cause, "moderate_fine_ratio",
                       f"PM2.5/PM10 ratio {ratio:.2f} (moderately fine)")

        if frp is not None and frp >= frp_th:
            self._bump(out, cause, "frp_present",
                       f"FRP {frp:.1f} MW — active burning detected via satellite")

        if waste is not None and waste >= 1.0:
            self._bump(out, cause, "waste_site",
                       "Known waste site in cell (driver flag)")

        if poi_w >= poi_s:
            self._bump(out, cause, "poi_waste",
                       f"{int(poi_w)} OSM waste facility/-ies in cell")

        if poi_c >= poi_s:
            self._bump(out, cause, "poi_crematorium",
                       f"{int(poi_c)} crematorium/-a in cell")

        if so2 is not None and so2 > so2_hi:
            self._bump(out, cause, "so2_elevated",
                       f"SO2 {so2:.1f} µg/m³ elevated")

        if pm25 is not None and pm25 > pm25_el:
            self._bump(out, cause, "pm25_elevated",
                       f"PM2.5 {pm25:.1f} µg/m³ elevated")

        return {
            "cause": cause,
            "confidence": round(min(out["score"], 1.0), 3),
            "evidence": out["evidence"],
            "signals": _pick(sigs, [
                "PM25_PM10_RATIO", "FRP", "SITE",
                "POI_WASTE_FACILITY_COUNT", "POI_CREMATORIUM_COUNT", "SO2", "PM25",
            ]),
        }

    def _traffic_resuspension(self, sigs: dict) -> dict:
        out = {"score": 0.0, "evidence": []}
        cause = "traffic_resuspension"

        ratio    = sigs.get("PM25_PM10_RATIO")
        road_d   = sigs.get("ROAD_DENSITY")
        major_r  = sigs.get("MAJOR_ROAD_RATIO")
        no2      = sigs.get("NO2")
        pm10     = sigs.get("PM10")
        poi_fuel = sigs.get("POI_FUEL_STATION_COUNT") or 0
        poi_tr   = sigs.get("POI_TRANSIT_TERMINAL_COUNT") or 0

        rd_hi   = _W.thresh("road_high")
        rd_mod  = _W.thresh("road_mod")
        no2_hi  = _W.thresh("no2_high")
        pm10_hi = _W.thresh("pm10_high")
        poi_s   = _W.thresh("poi_some")
        poi_m   = _W.thresh("poi_many")

        if road_d is not None and road_d >= rd_hi:
            self._bump(out, cause, "road_high",
                       f"ROAD_DENSITY {road_d:.0f} m/km² (high)")
        elif road_d is not None and road_d >= rd_mod:
            self._bump(out, cause, "road_moderate",
                       f"ROAD_DENSITY {road_d:.0f} m/km² (moderate)")

        if major_r is not None and major_r > 0.3:
            self._bump(out, cause, "major_road_ratio",
                       f"MAJOR_ROAD_RATIO {major_r:.2f}")

        if no2 is not None and no2 >= no2_hi:
            self._bump(out, cause, "no2_high",
                       f"NO2 {no2:.1f} µg/m³ — tailpipe combustion indicator")
        elif no2 is not None and no2 >= 20:
            self._bump(out, cause, "no2_moderate",
                       f"NO2 {no2:.1f} µg/m³ (moderate)")

        if poi_tr >= poi_s:
            self._bump(out, cause, "poi_transit",
                       f"{int(poi_tr)} bus/transit terminal(s) in cell — diesel idling")
        if poi_fuel >= poi_m:
            self._bump(out, cause, "poi_fuel_many",
                       f"{int(poi_fuel)} fuel stations in cell (cluster)")
        elif poi_fuel >= poi_s:
            self._bump(out, cause, "poi_fuel_some",
                       f"{int(poi_fuel)} fuel station(s) in cell")

        if ratio is not None and ratio < 0.65:
            self._bump(out, cause, "coarse_road_signature",
                       f"PM2.5/PM10 ratio {ratio:.2f} (road-dust coarse signature)")

        if pm10 is not None and pm10 > pm10_hi:
            self._bump(out, cause, "pm10_high",
                       f"PM10 {pm10:.1f} µg/m³ (elevated)")

        return {
            "cause": cause,
            "confidence": round(min(out["score"], 1.0), 3),
            "evidence": out["evidence"],
            "signals": _pick(sigs, [
                "ROAD_DENSITY", "MAJOR_ROAD_RATIO", "NO2",
                "POI_FUEL_STATION_COUNT", "POI_TRANSIT_TERMINAL_COUNT",
                "PM25_PM10_RATIO", "PM10",
            ]),
        }

    def _industrial_emission(self, sigs: dict) -> dict:
        out = {"score": 0.0, "evidence": []}
        cause = "industrial_emission"

        so2     = sigs.get("SO2")
        no2     = sigs.get("NO2")
        ratio   = sigs.get("PM25_PM10_RATIO")
        poi_ind = sigs.get("POI_INDUSTRIAL_COUNT") or 0
        poi_kil = sigs.get("POI_KILN_COUNT") or 0

        so2_hi = _W.thresh("so2_high")
        no2_hi = _W.thresh("no2_high")
        fine   = _W.thresh("ratio_fine")
        poi_m  = _W.thresh("poi_many")
        poi_s  = _W.thresh("poi_some")

        if so2 is not None and so2 > so2_hi * 2:
            self._bump(out, cause, "so2_very_high",
                       f"SO2 {so2:.1f} µg/m³ significantly elevated")
        elif so2 is not None and so2 > so2_hi:
            self._bump(out, cause, "so2_elevated",
                       f"SO2 {so2:.1f} µg/m³ elevated")

        if no2 is not None and no2 > no2_hi * 2:
            self._bump(out, cause, "no2_very_high",
                       f"NO2 {no2:.1f} µg/m³ significantly elevated")
        elif no2 is not None and no2 >= no2_hi:
            self._bump(out, cause, "no2_elevated",
                       f"NO2 {no2:.1f} µg/m³ elevated")

        if poi_ind >= poi_m:
            self._bump(out, cause, "poi_industrial_many",
                       f"{int(poi_ind)} industrial facilities in cell (cluster)")
        elif poi_ind >= poi_s:
            self._bump(out, cause, "poi_industrial_some",
                       f"{int(poi_ind)} industrial facility/-ies in cell")

        if poi_kil >= poi_s:
            self._bump(out, cause, "poi_kiln",
                       f"{int(poi_kil)} kiln(s) in cell (biomass + dust)")

        if ratio is not None and ratio > fine:
            self._bump(out, cause, "fine_signature",
                       f"PM2.5/PM10 ratio {ratio:.2f} (fine-particle combustion)")

        return {
            "cause": cause,
            "confidence": round(min(out["score"], 1.0), 3),
            "evidence": out["evidence"],
            "signals": _pick(sigs, [
                "SO2", "NO2", "POI_INDUSTRIAL_COUNT", "POI_KILN_COUNT", "PM25_PM10_RATIO",
            ]),
        }

    def _meteorological_trapping(self, sigs: dict) -> dict:
        out = {"score": 0.0, "evidence": []}
        cause = "meteorological_trapping"

        wind  = sigs.get("WIND_SPEED_KMH")
        hum   = sigs.get("HUMIDITY_PCT")
        pm25  = sigs.get("PM25")
        aqi   = sigs.get("AQI")
        vent  = sigs.get("VENTILATION_INDEX")
        avg_h = sigs.get("AVG_BUILDING_HEIGHT_M")
        intens= sigs.get("BUILT_INTENSITY")

        calm    = _W.thresh("wind_calm")
        low     = _W.thresh("wind_low")
        hum_hi  = _W.thresh("humidity_high")
        pm25_el = _W.thresh("pm25_elevated")

        if wind is not None and wind < calm:
            self._bump(out, cause, "wind_calm",
                       f"Wind speed {wind:.1f} km/h (near-calm — inversion likely)")
        elif wind is not None and wind < low:
            self._bump(out, cause, "wind_low",
                       f"Wind speed {wind:.1f} km/h (low — reduced dispersion)")

        if hum is not None and hum >= hum_hi:
            self._bump(out, cause, "humidity_high",
                       f"Humidity {hum:.0f}% (promotes particle growth)")

        if aqi is not None and aqi > 150:
            self._bump(out, cause, "aqi_high_bonus",
                       f"AQI {aqi:.0f} elevated")
        if pm25 is not None and pm25 > pm25_el:
            self._bump(out, cause, "pm25_elevated",
                       f"PM2.5 {pm25:.1f} µg/m³ elevated")

        # Topographic enclosure: basin cells with low ventilation trap
        # pollution even at moderate wind speeds (methodology §D.1).
        if vent is not None and vent < 2.0:
            self._bump(out, cause, "low_ventilation",
                       f"VENTILATION_INDEX {vent:.2f} km/h-equiv "
                       f"(topographic basin — poor flushing)")

        # Urban canyon: tall + dense built mass restricts horizontal mixing
        # at street level, independent of topography (methodology §D.18).
        # Triggers in cells with avg height > 15 m AND built fraction > 0.4 —
        # i.e. CBD / IT-park morphology, not low-rise suburbs.
        if (avg_h is not None and intens is not None
                and avg_h > 15.0 and intens > 0.4):
            self._bump(out, cause, "urban_canyon",
                       f"Built height {avg_h:.1f} m, intensity {intens:.2f} "
                       f"(urban canyon — restricts street-level mixing)")

        return {
            "cause": cause,
            "confidence": round(min(out["score"], 1.0), 3),
            "evidence": out["evidence"],
            "signals": _pick(sigs, ["WIND_SPEED_KMH", "HUMIDITY_PCT", "AQI",
                                    "PM25", "VENTILATION_INDEX",
                                    "AVG_BUILDING_HEIGHT_M", "BUILT_INTENSITY"]),
        }

    def _regional_transport(self, sigs: dict) -> dict:
        """Cell PM2.5 is dominated by pollution arriving from upwind cells.

        Triggers when UPWIND_PM25_LOAD (k≤2, neighbourhood) or
        UPWIND_PM25_LOAD_K10 (k≤10, regional ~7.5 km) is large relative
        to own PM2.5 AND wind speed is enough to transport pollution.
        The K10 signal carries more weight because cross-district
        transport is a stronger "this isn't local" signal than
        neighbourhood-scale advection. Methodology §D.1.
        """
        out = {"score": 0.0, "evidence": []}
        cause = "regional_transport"

        pm25       = sigs.get("PM25")
        upwind     = sigs.get("UPWIND_PM25_LOAD")
        upwind_r   = sigs.get("UPWIND_PM25_LOAD_K10")
        upwind_ar  = sigs.get("UPWIND_PM25_LOAD_REGIONAL")
        wind       = sigs.get("WIND_SPEED_KMH")
        poi_ind    = sigs.get("POI_INDUSTRIAL_COUNT") or 0
        poi_con    = sigs.get("POI_CONSTRUCTION_COUNT") or 0
        poi_kil    = sigs.get("POI_KILN_COUNT") or 0
        poi_w      = sigs.get("POI_WASTE_FACILITY_COUNT") or 0

        # Need at least one upwind reading to evaluate this cause.
        if upwind is None and upwind_r is None and upwind_ar is None:
            return {
                "cause": cause, "confidence": 0.0, "evidence": [],
                "signals": _pick(sigs, ["UPWIND_PM25_LOAD",
                                        "UPWIND_PM25_LOAD_K10",
                                        "UPWIND_PM25_LOAD_REGIONAL", "PM25",
                                        "WIND_SPEED_KMH",
                                        "POI_INDUSTRIAL_COUNT"]),
            }

        # Neighbourhood-scale (k=2) upwind dominates own PM
        if upwind is not None:
            if pm25 is not None and pm25 > 0 and upwind > 1.5 * pm25:
                self._bump(out, cause, "upwind_dominates",
                           f"UPWIND_PM25_LOAD {upwind:.1f} > 1.5× own PM2.5 ({pm25:.1f})")
            elif pm25 is not None and pm25 > 0 and upwind > pm25:
                self._bump(out, cause, "upwind_dominates",
                           f"UPWIND_PM25_LOAD {upwind:.1f} > own PM2.5 ({pm25:.1f})")
            if upwind >= 30.0:
                self._bump(out, cause, "upwind_high",
                           f"UPWIND_PM25_LOAD {upwind:.1f} µg/m³-equiv (high incoming, ~1.5 km)")

        # Metro-scale (k=10) upwind — stronger evidence of cross-district
        # transport (the cell is genuinely a receptor, not just inheriting
        # from its block).
        if upwind_r is not None:
            if pm25 is not None and pm25 > 0 and upwind_r > 1.5 * pm25:
                self._bump(out, cause, "upwind_regional_dominates",
                           f"UPWIND_PM25_LOAD_K10 {upwind_r:.1f} > 1.5× own PM2.5 "
                           f"({pm25:.1f}) — regional ~7.5 km source upwind")
            if upwind_r >= 100.0:
                self._bump(out, cause, "upwind_regional_high",
                           f"UPWIND_PM25_LOAD_K10 {upwind_r:.1f} µg/m³-equiv "
                           f"(high regional incoming, ~7.5 km cone)")

        # Airshed-scale (~100-300 km) upwind — strongest single signal that
        # the source is trans-boundary (e.g., Punjab → Delhi during stubble
        # burning). Produced by the airshed compositor, present only for
        # cells inside an enabled airshed/watershed/corridor AOI.
        if upwind_ar is not None:
            if pm25 is not None and pm25 > 0 and upwind_ar > 2.0 * pm25:
                self._bump(out, cause, "upwind_airshed_dominates",
                           f"UPWIND_PM25_LOAD_REGIONAL {upwind_ar:.1f} > 2× own "
                           f"PM2.5 ({pm25:.1f}) — trans-boundary advection")
            if upwind_ar >= 250.0:
                self._bump(out, cause, "upwind_airshed_high",
                           f"UPWIND_PM25_LOAD_REGIONAL {upwind_ar:.1f} µg/m³-equiv "
                           f"(airshed-scale source upwind, ~100-300 km)")

        # Wind moderate enough to actually transport
        if wind is not None and 5.0 <= wind <= 30.0:
            self._bump(out, cause, "upwind_wind_moderate",
                       f"Wind {wind:.1f} km/h (sufficient for transport)")

        # Few local sources → argues against local cause
        total_local_sources = poi_ind + poi_con + poi_kil + poi_w
        if total_local_sources <= 2:
            self._bump(out, cause, "low_local_sources",
                       f"Only {int(total_local_sources)} local emission-source POI(s) — "
                       f"local cause is unlikely")

        return {
            "cause": cause,
            "confidence": round(min(out["score"], 1.0), 3),
            "evidence": out["evidence"],
            "signals": _pick(sigs, [
                "UPWIND_PM25_LOAD", "UPWIND_PM25_LOAD_K10",
                "UPWIND_PM25_LOAD_REGIONAL",
                "PM25", "WIND_SPEED_KMH",
                "POI_INDUSTRIAL_COUNT", "POI_CONSTRUCTION_COUNT",
                "POI_KILN_COUNT", "POI_WASTE_FACILITY_COUNT",
            ]),
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pick(sigs: dict, keys: list[str]) -> dict:
    return {k: sigs.get(k) for k in keys}
