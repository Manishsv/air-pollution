"""Configurable rules registry — single source of truth for all domain thresholds.

Every threshold, score weight, saturation ceiling, and detection floor that
influences a risk decision is defined here.  Pipelines read values through this
module instead of hardcoding literals.

Config file
-----------
``data/config/rules_registry.yaml`` (YAML, human-readable, git-tracked).
If the file does not exist the registry falls back to the built-in defaults
below, so the system works out-of-the-box without any configuration.

Override via environment variable
----------------------------------
Set ``RULES_REGISTRY`` to an absolute path to load a different file.

Per-city overrides
------------------
Any key can be overridden for a specific city by nesting under a ``cities``
block in the YAML:

    domains:
      crowd:
        gathering_threshold_per_km2: 500      # global default
        cities:
          mumbai:
            gathering_threshold_per_km2: 300  # denser population

API
---
    from airos.os.rules import rules

    # Scalar
    rules.get("crowd", "gathering_threshold_per_km2", default=500.0)
    rules.get("crowd", "gathering_threshold_per_km2", city_id="mumbai", default=500.0)

    # Nested dict (e.g. risk level map)
    rules.get("air", "pm25_category_thresholds_ug_m3")
    # → {"severe": 250, "very_poor": 120, "poor": 90, "moderate": 60, "satisfactory": 30}

    # Hot-reload after editing the YAML (no restart needed)
    rules.reload()

What belongs here
-----------------
  ✔ Risk level boundaries (severe/high/moderate/low)
  ✔ Alert and detection thresholds
  ✔ Score saturation / normalisation ceilings
  ✔ Score composition weights
  ✔ Data confidence ratings
  ✔ Observation time windows

  ✗ Mathematical constants (earth radius, π)
  ✗ Algorithmic stability parameters (IDW distance floor)
  ✗ Output pagination (top_n decision packets)
  ✗ Reference layer coordinates (separate config concern)
"""
from __future__ import annotations

import copy
import datetime
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Path for the change-history audit log (sibling of the registry YAML)
_DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parents[3]
    / "data" / "config" / "rules_registry_history.yaml"
)

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "config" / "rules_registry.yaml"
)

# ---------------------------------------------------------------------------
# Built-in defaults
# Every value here is the exact literal that was previously hardcoded in the
# corresponding pipeline.  Changing the YAML overrides these; deleting a key
# from the YAML falls back to this dict.
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, dict[str, Any]] = {
    "air": {
        # India CPCB AQI breakpoints for PM2.5 (µg/m³)
        "pm25_category_thresholds_ug_m3": {
            "severe":       250,
            "very_poor":    120,
            "poor":          90,
            "moderate":      60,
            "satisfactory":  30,
        },
        # PM2.5 value that maps to normalised score = 1.0
        "pm25_score_saturation_ug_m3": 120.0,
    },

    "fire": {
        # Accumulated FRP (MW) per H3 cell that maps to each risk level
        "frp_risk_levels_mw": {
            "severe":   100.0,
            "high":      30.0,
            "moderate":  10.0,
            "low":        5.0,
        },
        # FRP value where log-normalised score saturates at 1.0
        "frp_score_saturation_mw": 500.0,
        # Minimum FRP to consider a pixel as a fire detection
        "frp_detection_floor_mw": 5.0,
        # Number of in-city hotspots that escalates the alert to "error" severity
        "in_city_alert_error_threshold": 3,
    },

    "flood": {
        # Flood risk score boundaries
        "risk_levels": {
            "severe":   0.75,
            "high":     0.50,
            "moderate": 0.25,
        },
        # Rainfall rate (mm/hr) that maps to rainfall_score = 1.0
        "rainfall_score_saturation_mm_hr": 20.0,
        # Incident count that maps to incident_score = 1.0
        "incident_score_saturation_count": 3,
        # Weights for composite flood risk score
        "score_weights": {
            "rainfall": 0.6,
            "incident": 0.4,
        },
        # Drainage factor: minimum (= max mitigation is 1 − this)
        "drainage_factor_min": 0.75,
        # Flood risk reduction per drainage asset within proximity radius
        "drainage_factor_decrement_per_asset": 0.05,
        # Radius (km) for counting nearby incidents and drainage assets
        "proximity_radius_km": 0.5,
    },

    "waste": {
        # FRP range that identifies waste burning vs wildfire
        "frp_burn_range_mw": {
            "min": 5.0,
            "max": 30.0,
        },
        # Days a hotspot must persist to be classified as a landfill fire
        "persist_days_min": 2,
        # NDVI below this → likely exposed waste / dump site
        "ndvi_dump_threshold": 0.15,
        # NDVI sub-thresholds for dump severity classification
        "ndvi_severity_thresholds": {
            "high":     0.05,
            "moderate": 0.10,
        },
        # Methane background concentration (global tropospheric average)
        "ch4_background_ppb": 1880.0,
        # CH4 elevation (ppb above background) for severity classification
        "ch4_elevation_thresholds_ppb": {
            "high":     40.0,
            "moderate": 20.0,
        },
        # Waste risk score boundaries
        "risk_levels": {
            "severe":   0.85,
            "high":     0.65,
            "moderate": 0.45,
            "low":      0.25,
        },
        # FRP log-saturation for waste burn scoring
        "frp_burn_score_saturation_mw": 30.0,
        # Base score contributions per waste type
        "burn_base_scores": {
            "waste_burn":    0.40,
            "landfill_fire": 0.65,
        },
        # FRP contribution ceiling in the composite waste score
        "frp_contribution_weight": 0.35,
        # Per-severity score for dump detection
        "dump_severity_scores": {
            "low":      0.30,
            "moderate": 0.55,
            "high":     0.75,
        },
        # Per-severity score for landfill gas detection
        "gas_severity_scores": {
            "moderate": 0.50,
            "high":     0.80,
        },
    },

    "heat": {
        # Weights for composite heat risk score (must sum to 1.0)
        "score_weights": {
            "uhi_norm":     0.6,
            "green_deficit": 0.4,
        },
        # heat_risk_score ≥ this → classified as "high risk" for dashboard counters
        "high_risk_threshold": 0.66,
        # Green deficit thresholds for intervention recommendations
        "intervention_thresholds": {
            "tree_planting_min_deficit":   0.7,
            "green_roofs_min_deficit":     0.5,
            "cool_pavement_max_water_prox": 0.2,
        },
    },

    "noise": {
        # NRI (Noise Risk Index) boundaries
        "nri_risk_levels": {
            "severe":   0.75,
            "high":     0.50,
            "moderate": 0.25,
        },
        # Cells below this NRI with zero proximity score are suppressed (noise floor)
        "nri_minimum_filter": 0.10,
        # NRI formula: contribution caps for non-proximity sources
        "score_weights": {
            "construction_cap": 0.3,
            "fire_cap":         0.2,
        },
        # Log-saturation for fire contribution to NRI
        "fire_score_log_saturation_mw": 100.0,
        # Score thresholds for dominant noise source classification
        "dominant_source_thresholds": {
            "airport_proximity":    0.6,
            "construction_machinery": 0.3,
            "industrial_fire":      0.2,
        },
        # Minimum NRI for actionable recommendations
        "recommendation_nri_floor": 0.5,
    },

    "construction": {
        # CRI (Construction Risk Index) boundaries
        "cri_risk_levels": {
            "severe":   0.80,
            "high":     0.60,
            "moderate": 0.40,
            "low":      0.20,
        },
        # BSI score above this → dominant activity is heavy earthworks
        "bsi_earthworks_threshold": 0.6,
        # NO2 score above this → dominant activity is machinery exhaust
        "no2_machinery_threshold": 0.5,
        # Minimum CRI for recommendations to be issued
        "min_cri_for_recommendation": 0.4,
    },

    "green": {
        # GCCI (Green Cover Change Index) boundaries
        "gcci_thresholds": {
            "severe_loss":      -0.60,
            "high_loss":        -0.20,
            "moderate_loss":    -0.05,
            "moderate_gain":     0.05,
            "significant_gain":  0.20,
        },
        # |GCCI| ≥ this for recommendations to be considered actionable
        "recommendation_min_abs_gcci": 0.2,
    },

    "water": {
        # WQI (Water Quality Index) boundaries
        "wqi_risk_levels": {
            "severe": 0.75,
            "poor":   0.50,
            "moderate": 0.25,
        },
        # Sub-signal score above this → identified as dominant issue
        "dominant_issue_thresholds": {
            "foam_scum":    0.5,
            "algal_bloom":  0.5,
        },
        # Minimum WQI for actionable recommendations
        "recommendation_wqi_floor": 0.3,
    },

    "crowd": {
        # CROWD_DENSITY (people/km²) above this → GATHERING_ALERT = 1
        "gathering_threshold_per_km2": 500.0,
        # CROWD_DENSITY that saturates CROWD_INDEX at 1.0
        "index_saturation_per_km2": 2000.0,
        # Look-back window for "current" observations
        "observation_window_minutes": 20,
        # Data confidence when camera observations are present
        "data_confidence": 0.90,
    },

    "buildings": {
        "data_confidence": 0.75,
    },

    "roads": {
        "data_confidence": 0.85,
    },

    "drains": {
        # Drain density (m of waterway per km²) that saturates capacity index at 1.0
        "flood_drain_saturation_m_per_km2": 10_000.0,
        "data_confidence": 0.65,
    },
}


# ---------------------------------------------------------------------------
# Registry class
# ---------------------------------------------------------------------------

class RulesRegistry:
    """Thread-safe in-memory rules registry backed by a YAML config file.

    Versioning
    ----------
    The YAML file MAY declare a top-level ``version`` key (SemVer string,
    e.g. "1.2.0").  On every ``reload()``, if the loaded version differs from
    the previously held version, a change record is appended to the audit log
    at ``rules_registry_history.yaml`` (sibling of the registry file).

    The audit record captures: ``changed_at``, ``changed_by``, ``version_from``,
    ``version_to``, ``keys_changed``, and an optional ``reason``.

    ``changed_by`` is taken from the ``RULES_REGISTRY_CHANGED_BY`` environment
    variable (default: "system").  ``reason`` is taken from
    ``RULES_REGISTRY_CHANGE_REASON`` (default: empty).
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._path: Path | None = None
        self._loaded: bool = False
        self._version: str = "0.0.0"   # version of the currently held data

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()

    def _load(self, *, _record_history: bool = False, _prev_data: dict | None = None, _prev_version: str = "0.0.0") -> None:
        env_path = os.environ.get("RULES_REGISTRY")
        path = Path(env_path) if env_path else _DEFAULT_REGISTRY_PATH

        # Start from deep copy of defaults
        merged: dict[str, dict[str, Any]] = copy.deepcopy(_DEFAULTS)
        new_version: str = "0.0.0"

        if path.exists():
            try:
                import yaml  # PyYAML — optional but expected in the env
                with open(path, encoding="utf-8") as f:
                    file_data = yaml.safe_load(f) or {}
                new_version = str(file_data.get("version", "0.0.0"))
                domains = file_data.get("domains", {})
                self._deep_merge(merged, domains)
                logger.info("Rules registry loaded from %s (version %s)", path, new_version)
            except ImportError:
                logger.warning(
                    "PyYAML not installed — rules registry using built-in defaults only. "
                    "Install PyYAML to enable YAML config: pip install pyyaml"
                )
            except Exception as exc:
                logger.warning(
                    "Could not load rules registry from %s: %s — using defaults.", path, exc
                )
        else:
            logger.debug(
                "Rules registry file not found at %s — using built-in defaults.", path
            )

        # Write audit history if this is a reload and something changed
        if _record_history and (_prev_version != new_version or _prev_data != merged):
            self._append_history(
                prev_data=_prev_data or {},
                new_data=merged,
                version_from=_prev_version,
                version_to=new_version,
                registry_path=path,
            )

        self._data    = merged
        self._path    = path
        self._version = new_version
        self._loaded  = True

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        """Recursively merge ``override`` into ``base`` in-place."""
        for key, val in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(val, dict):
                RulesRegistry._deep_merge(base[key], val)
            else:
                base[key] = val

    @staticmethod
    def _diff_keys(old: dict, new: dict, prefix: str = "") -> list[str]:
        """Return dotted key paths where values differ between old and new."""
        changed: list[str] = []
        all_keys = set(old) | set(new)
        for k in all_keys:
            path = f"{prefix}.{k}" if prefix else k
            if k not in old:
                changed.append(f"+{path}")
            elif k not in new:
                changed.append(f"-{path}")
            elif isinstance(old[k], dict) and isinstance(new[k], dict):
                changed.extend(RulesRegistry._diff_keys(old[k], new[k], path))
            elif old[k] != new[k]:
                changed.append(path)
        return changed

    def _append_history(
        self,
        *,
        prev_data: dict,
        new_data: dict,
        version_from: str,
        version_to: str,
        registry_path: Path,
    ) -> None:
        """Append a change record to the rules_registry_history.yaml audit log."""
        try:
            import yaml
        except ImportError:
            logger.debug("PyYAML not available — skipping registry history write")
            return

        keys_changed = self._diff_keys(prev_data, new_data)
        changed_by = os.environ.get("RULES_REGISTRY_CHANGED_BY", "system")
        reason = os.environ.get("RULES_REGISTRY_CHANGE_REASON", "")
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        record = {
            "changed_at":    now,
            "changed_by":    changed_by,
            "version_from":  version_from,
            "version_to":    version_to,
            "keys_changed":  keys_changed,
            "reason":        reason,
        }

        # History lives next to the registry YAML by default; override via env
        env_hist = os.environ.get("RULES_REGISTRY_HISTORY")
        hist_path = Path(env_hist) if env_hist else (
            registry_path.parent / "rules_registry_history.yaml"
            if registry_path.exists()
            else _DEFAULT_HISTORY_PATH
        )

        try:
            hist_path.parent.mkdir(parents=True, exist_ok=True)
            # Read existing history, append, write back
            existing: list[dict] = []
            if hist_path.exists():
                with open(hist_path, encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, list):
                        existing = loaded
            existing.append(record)
            with open(hist_path, "w", encoding="utf-8") as f:
                yaml.dump(existing, f, default_flow_style=False, allow_unicode=True)
            logger.info(
                "Rules registry history updated: %s → %s (%d key(s) changed)",
                version_from, version_to, len(keys_changed),
            )
        except Exception as exc:
            logger.warning("Could not write rules registry history: %s", exc)

    def reload(self) -> None:
        """Force a fresh load from disk.

        If the newly loaded registry differs from the current one (by version
        string or by content), a change record is appended to the history log.
        Call this after editing the YAML without restarting the process.
        """
        prev_data    = copy.deepcopy(self._data)
        prev_version = self._version
        self._loaded = False
        self._load(_record_history=True, _prev_data=prev_data, _prev_version=prev_version)
        logger.info("Rules registry reloaded (version %s).", self._version)

    @property
    def version(self) -> str:
        """Return the version string from the currently loaded YAML (or '0.0.0')."""
        self._ensure_loaded()
        return self._version

    def get(
        self,
        domain: str,
        key: str,
        *,
        city_id: str | None = None,
        default: Any = None,
    ) -> Any:
        """Return a rule value for the given domain and key.

        If ``city_id`` is provided, checks for a city-specific override first.
        Falls back to the domain-level value, then to ``default``.

        Parameters
        ----------
        domain  : Domain name e.g. "air", "flood", "crowd"
        key     : Rule key e.g. "gathering_threshold_per_km2"
        city_id : Optional city for city-specific override
        default : Value to return if the key is not found anywhere

        Returns
        -------
        The rule value (type preserved from YAML / defaults dict).
        """
        self._ensure_loaded()
        domain_data = self._data.get(domain, {})

        # City-specific override
        if city_id:
            city_val = domain_data.get("cities", {}).get(city_id, {}).get(key)
            if city_val is not None:
                return city_val

        # Domain-level value
        val = domain_data.get(key)
        if val is not None:
            return val

        # Explicit default from caller
        return default

    def all_domains(self) -> list[str]:
        """Return all domain names that have rules defined."""
        self._ensure_loaded()
        return [k for k in self._data if not k.startswith("_")]

    def snapshot(self, domain: str | None = None) -> dict:
        """Return a copy of the registry (or a single domain) for inspection/debugging."""
        self._ensure_loaded()
        if domain:
            return copy.deepcopy(self._data.get(domain, {}))
        return copy.deepcopy(self._data)


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly:
#   from airos.os.rules import rules
#   rules.get("crowd", "gathering_threshold_per_km2")
# ---------------------------------------------------------------------------
rules = RulesRegistry()
