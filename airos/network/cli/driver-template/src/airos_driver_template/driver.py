"""
AirOS Driver Template
======================
Copy this file as the starting point for a new AirOS data source driver.

Replace every occurrence of:
  - TemplateDriver   → your driver class name (e.g. OpenAQDriver)
  - template_domain  → your domain name (e.g. openaq_v2)
  - MY_PRIMARY_SIGNAL → your signal name(s)
  - MY_API_KEY       → your env var name(s)

Then update signals.yaml to match what fetch() actually writes.

Checklist before publishing:
  [ ] domain is unique — no existing AirOS domain or installed driver uses it
  [ ] fetch() is idempotent — two calls for the same city/hour produce same rows
  [ ] fetch() calls record_ingest() at the end (success or partial)
  [ ] conformance_check() completes in < 1 second without live API calls
  [ ] signals.yaml lists every signal written, including DATA_CONFIDENCE
  [ ] driver passes: python -m pytest src/airos_driver_template/tests/
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from airos.os.sdk.base_driver import BaseDriver
from airos.os.sdk.driver_types import ConformanceResult, DriverFetchError

logger = logging.getLogger(__name__)

# Load signal names from signals.yaml so they stay in sync automatically.
# If you prefer, replace with a plain list:
#   _SIGNAL_NAMES = ["MY_PRIMARY_SIGNAL", "DATA_CONFIDENCE"]
def _load_signal_names() -> list[str]:
    try:
        import yaml
        signals_yaml = Path(__file__).parent / "signals.yaml"
        data = yaml.safe_load(signals_yaml.read_text())
        return [s["name"] for s in data.get("signals", [])]
    except Exception:
        return ["MY_PRIMARY_SIGNAL", "DATA_CONFIDENCE"]


class TemplateDriver(BaseDriver):
    """Minimal AirOS driver template — replace with your implementation."""

    # ------------------------------------------------------------------ #
    # Identity — REQUIRED, change these                                   #
    # ------------------------------------------------------------------ #

    domain = "template_domain"
    """Unique domain name. Use underscores, lowercase ASCII.
    If providing an alternate source for an existing domain (e.g. air),
    use a suffix: 'air_myapi' so the built-in 'air' driver is not shadowed.
    """

    cadence_hours = 1.0
    """How often to fetch. 0.25 = 15 min, 1.0 = hourly, 6.0 = every 6h."""

    produces_assessments = True
    """True if fetch() writes h3_assessments rows (risk levels).
    Set False for structural context drivers (like buildings, weather).
    """

    # ------------------------------------------------------------------ #
    # Metadata — recommended                                              #
    # ------------------------------------------------------------------ #

    signal_names = _load_signal_names()
    data_sources = ["My Upstream API (https://api.example.com)"]
    _required_env_vars = ["MY_API_KEY"]

    # ------------------------------------------------------------------ #
    # Conformance — override to add driver-specific checks                #
    # ------------------------------------------------------------------ #

    def conformance_check(self) -> ConformanceResult:
        """Validate config without making live API calls."""
        # BaseDriver checks _required_env_vars for you.
        result = super().conformance_check()

        # Add driver-specific checks here:
        # config_file = Path("data/config/my_driver.yaml")
        # if not config_file.exists():
        #     result.failures.append(f"Config file not found: {config_file}")
        #     result.ok = False

        return result

    # ------------------------------------------------------------------ #
    # Fetch — REQUIRED, implement your data pull here                     #
    # ------------------------------------------------------------------ #

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        """Pull data, compute H3 signals, write to Knowledge Store.

        Returns the number of signal rows written.
        """
        # Step 1: check watermark (skip if too recent, unless force=True)
        self._check_interval(city_id, force)

        # Step 2: pull raw data from upstream
        raw_data = self._fetch_raw(city_id, bbox)
        if not raw_data:
            from airos.drivers.store.writer import record_ingest
            record_ingest(city_id=city_id, domain=self.domain,
                          rows_written=0, status="partial",
                          error_msg="upstream returned no data")
            return 0

        # Step 3: map raw observations to H3 cells
        # Use IDW for point observations, centroid-assign for polygons,
        # or direct assignment for satellite pixels.
        rows = self._map_to_h3(raw_data, bbox)

        # Step 4: write to Knowledge Store
        # The conformance gate runs automatically inside write_signals().
        from airos.drivers.store.writer import write_signals, record_ingest
        written = write_signals(rows, city_id=city_id, domain=self.domain,
                                source=self.data_sources[0])

        # Step 5: optionally write assessments (risk levels)
        if self.produces_assessments and written > 0:
            self._write_assessments(rows, city_id)

        # Step 6: record watermark
        record_ingest(city_id=city_id, domain=self.domain, rows_written=written)
        return written

    # ------------------------------------------------------------------ #
    # Private helpers — implement these                                   #
    # ------------------------------------------------------------------ #

    def _fetch_raw(self, city_id: str, bbox: dict) -> list:
        """Call your upstream API and return raw observations.

        Raise DriverFetchError on unrecoverable errors (after retries).
        Return [] if no data is available (not an error).
        """
        api_key = os.getenv("MY_API_KEY", "")
        # Example:
        # import requests
        # resp = requests.get(
        #     "https://api.example.com/data",
        #     params={"lat": bbox["lat_min"], "lon": bbox["lon_min"],
        #             "api_key": api_key},
        #     timeout=30,
        # )
        # resp.raise_for_status()
        # return resp.json()["observations"]
        raise NotImplementedError("Implement _fetch_raw()")

    def _map_to_h3(self, raw_data: list, bbox: dict) -> list[dict]:
        """Convert raw observations to h3_signals row dicts.

        Each row must have: h3_id, signal, value
        Optional: unit, observed_at, source, data_quality

        Example using IDW for point observations:
            from airos.drivers.store.geo_agg import aggregate_points_to_h3
            points_df = pd.DataFrame(raw_data)  # needs lat, lon, value columns
            h3_df = aggregate_points_to_h3(points_df, "value", res=8)
            rows = []
            for _, row in h3_df.iterrows():
                rows.append({"h3_id": row["h3_id"], "signal": "MY_PRIMARY_SIGNAL",
                              "value": row["value"], "unit": "index"})
                rows.append({"h3_id": row["h3_id"], "signal": "DATA_CONFIDENCE",
                              "value": float(row.get("data_confidence", 0.8))})
            return rows
        """
        raise NotImplementedError("Implement _map_to_h3()")

    def _write_assessments(self, rows: list[dict], city_id: str) -> None:
        """Write risk-level assessments to h3_assessments.

        Only needed if produces_assessments = True.
        Example:
            from airos.drivers.store.writer import write_assessment
            for h3_id, cell_rows in groupby(rows, "h3_id"):
                index_val = next((r["value"] for r in cell_rows
                                  if r["signal"] == "MY_PRIMARY_SIGNAL"), None)
                if index_val is None:
                    continue
                risk = "high" if index_val > 0.7 else "moderate" if index_val > 0.4 else "low"
                write_assessment(h3_id=h3_id, city_id=city_id,
                                 domain=self.domain, risk_level=risk,
                                 primary_index="MY_PRIMARY_SIGNAL",
                                 primary_value=index_val)
        """
        pass
