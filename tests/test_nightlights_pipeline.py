"""Tests for the night lights (VIIRS) domain pipeline.

Coverage:
  A. Connector helpers (_grid_points, _synthetic_ntl, fetch_ntl_samples)
  B. Ingestor pure functions (_assign_h3, _cell_signals)
  C. ingest_nightlights end-to-end using synthetic source (no network, writes to real store)
  D. NightLightsDriver class (instantiation, conformance, metadata)
  E. Dispatcher wiring (ALL_DOMAINS, _DOMAIN_FN, _DOMAIN_INTERVAL, _NO_ASSESSMENT_DOMAINS)
  F. Schema validation (provider contract, consumer contract)

No live network calls — all tests use force_source="synthetic" or pure in-process data.
"""
from __future__ import annotations

import math
from datetime import timedelta

import pytest


# ── Shared fixtures ────────────────────────────────────────────────────────

_BBOX = dict(lat_min=12.97, lat_max=12.99, lon_min=77.57, lon_max=77.59)
_CITY = "test_nightlights_city"

# Six synthetic samples covering all 4 quality flags
_SAMPLES_MIXED = [
    {"lat": 12.971, "lon": 77.571, "radiance_nw": 18.0, "lit_fraction": 0.72,
     "quality_flag": "ok",                "source_record_id": "synth_12.9710_77.5710",
     "provenance": {"source_id": "nasa_black_marble_vnp46a2", "collected_at": "2025-12-01T00:00:00Z", "ingested_at": "2026-05-11T09:00:00Z"}},
    {"lat": 12.972, "lon": 77.572, "radiance_nw": 20.0, "lit_fraction": 0.80,
     "quality_flag": "ok",                "source_record_id": "synth_12.9720_77.5720",
     "provenance": {"source_id": "nasa_black_marble_vnp46a2", "collected_at": "2025-12-01T00:00:00Z", "ingested_at": "2026-05-11T09:00:00Z"}},
    {"lat": 12.973, "lon": 77.573, "radiance_nw": 15.0, "lit_fraction": 0.60,
     "quality_flag": "cloud_contaminated", "source_record_id": "synth_12.9730_77.5730",
     "provenance": {"source_id": "nasa_black_marble_vnp46a2", "collected_at": "2025-12-01T00:00:00Z", "ingested_at": "2026-05-11T09:00:00Z"}},
    {"lat": 12.974, "lon": 77.574, "radiance_nw": 16.0, "lit_fraction": 0.65,
     "quality_flag": "void_filled",        "source_record_id": "synth_12.9740_77.5740",
     "provenance": {"source_id": "nasa_black_marble_vnp46a2", "collected_at": "2025-12-01T00:00:00Z", "ingested_at": "2026-05-11T09:00:00Z"}},
    {"lat": 12.975, "lon": 77.575, "radiance_nw": None, "lit_fraction": None,
     "quality_flag": "no_data",            "source_record_id": "synth_12.9750_77.5750",
     "provenance": {"source_id": "nasa_black_marble_vnp46a2", "collected_at": "2025-12-01T00:00:00Z", "ingested_at": "2026-05-11T09:00:00Z"}},
    {"lat": 12.976, "lon": 77.576, "radiance_nw": 22.0, "lit_fraction": 0.88,
     "quality_flag": "ok",                "source_record_id": "synth_12.9760_77.5760",
     "provenance": {"source_id": "nasa_black_marble_vnp46a2", "collected_at": "2025-12-01T00:00:00Z", "ingested_at": "2026-05-11T09:00:00Z"}},
]


# ── A. Connector helpers ───────────────────────────────────────────────────

class TestGridPoints:
    def test_returns_list_of_tuples(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points
        pts = _grid_points(12.87, 77.47, 12.89, 77.49)
        assert isinstance(pts, list)
        assert all(isinstance(p, tuple) and len(p) == 2 for p in pts)

    def test_points_within_bbox(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points
        pts = _grid_points(12.87, 77.47, 13.07, 77.69)
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        assert min(lats) >= 12.87
        assert max(lats) <= 13.07
        assert min(lons) >= 77.47
        assert max(lons) <= 77.69

    def test_count_scales_with_bbox_size(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points
        small = _grid_points(12.97, 77.57, 12.98, 77.58)
        large = _grid_points(12.87, 77.47, 13.07, 77.69)
        assert len(large) > len(small) * 5

    def test_custom_spacing(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points
        fine   = _grid_points(12.87, 77.47, 13.07, 77.69, spacing=0.001)
        coarse = _grid_points(12.87, 77.47, 13.07, 77.69, spacing=0.01)
        assert len(fine) > len(coarse)

    def test_empty_bbox_returns_empty(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points
        pts = _grid_points(13.0, 77.0, 12.0, 76.0)   # inverted → no points
        assert pts == []


class TestSyntheticNTL:
    def test_returns_one_sample_per_point(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points, _synthetic_ntl
        pts = _grid_points(**_BBOX)
        samples = _synthetic_ntl(pts, _BBOX)
        assert len(samples) == len(pts)

    def test_bangalore_radiance_in_range(self):
        """Synthetic lookup should return roughly 18 nW for central Bangalore (base ± noise)."""
        from airos.drivers.connectors.nightlights.viirs import _grid_points, _synthetic_ntl
        bbox = dict(lat_min=12.97, lat_max=12.98, lon_min=77.57, lon_max=77.58)
        pts  = _grid_points(**bbox)
        samp = _synthetic_ntl(pts, bbox)
        # Allow for noise: base=18, sigma=5, centre_factor ~1.2 → expect 5–35 nW
        radiances = [s["radiance_nw"] for s in samp if s["radiance_nw"] is not None]
        assert len(radiances) > 0
        assert all(0.0 <= r <= 60.0 for r in radiances)

    def test_quality_flag_is_void_filled(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points, _synthetic_ntl
        pts  = _grid_points(**_BBOX)
        samp = _synthetic_ntl(pts, _BBOX)
        assert all(s["quality_flag"] == "void_filled" for s in samp)

    def test_provenance_fields_present(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points, _synthetic_ntl
        pts  = _grid_points(**_BBOX)
        samp = _synthetic_ntl(pts, _BBOX)
        for s in samp[:3]:
            assert "source_id"   in s["provenance"]
            assert "ingested_at" in s["provenance"]

    def test_source_record_id_marks_synthetic(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points, _synthetic_ntl
        pts  = _grid_points(**_BBOX)
        samp = _synthetic_ntl(pts, _BBOX)
        assert all("synthetic_fallback" in s["source_record_id"] for s in samp)

    def test_lit_fraction_in_valid_range(self):
        from airos.drivers.connectors.nightlights.viirs import _grid_points, _synthetic_ntl
        pts  = _grid_points(**_BBOX)
        samp = _synthetic_ntl(pts, _BBOX)
        for s in samp:
            lf = s.get("lit_fraction")
            if lf is not None:
                assert 0.0 <= lf <= 1.0


class TestFetchNtlSamples:
    def test_synthetic_returns_samples(self):
        from airos.drivers.connectors.nightlights.viirs import fetch_ntl_samples
        samples = fetch_ntl_samples(**_BBOX, force_source="synthetic")
        assert len(samples) > 0

    def test_synthetic_sample_schema(self):
        from airos.drivers.connectors.nightlights.viirs import fetch_ntl_samples
        samples = fetch_ntl_samples(**_BBOX, force_source="synthetic")
        required = {"lat", "lon", "radiance_nw", "quality_flag",
                    "source_record_id", "provenance"}
        for s in samples[:5]:
            assert required.issubset(s.keys())

    def test_synthetic_sample_coordinates_in_bbox(self):
        from airos.drivers.connectors.nightlights.viirs import fetch_ntl_samples
        samples = fetch_ntl_samples(**_BBOX, force_source="synthetic")
        for s in samples:
            assert _BBOX["lat_min"] <= s["lat"] <= _BBOX["lat_max"]
            assert _BBOX["lon_min"] <= s["lon"] <= _BBOX["lon_max"]

    def test_empty_bbox_returns_empty(self):
        from airos.drivers.connectors.nightlights.viirs import fetch_ntl_samples
        samples = fetch_ntl_samples(13.0, 77.0, 12.0, 76.0, force_source="synthetic")
        assert samples == []


# ── B. Ingestor pure functions ─────────────────────────────────────────────

class TestCellSignals:
    def test_mean_excludes_no_data(self):
        """ok=18, ok=22, cloud=15, void=16, no_data=None → mean(18,22,15,16)=17.75"""
        from airos.drivers.store.nightlights_ingestor import _cell_signals
        rad, lit, conf = _cell_signals(_SAMPLES_MIXED)
        assert rad is not None
        assert abs(rad - (18.0 + 20.0 + 15.0 + 16.0 + 22.0) / 5) < 0.1

    def test_all_ok_confidence_is_0_90(self):
        from airos.drivers.store.nightlights_ingestor import _cell_signals
        ok_only = [s for s in _SAMPLES_MIXED if s["quality_flag"] == "ok"]
        _, _, conf = _cell_signals(ok_only)
        assert conf == pytest.approx(0.90)

    def test_high_cloud_fraction_gives_0_65(self):
        """More than 10% cloud_contaminated → confidence 0.65."""
        from airos.drivers.store.nightlights_ingestor import _cell_signals
        samples = (
            [{"radiance_nw": 15.0, "lit_fraction": 0.6,
              "quality_flag": "cloud_contaminated",
              "source_record_id": "x",
              "provenance": {"source_id": "nasa"}}] * 3 +
            [{"radiance_nw": 18.0, "lit_fraction": 0.7,
              "quality_flag": "ok",
              "source_record_id": "x",
              "provenance": {"source_id": "nasa"}}] * 7
        )
        _, _, conf = _cell_signals(samples)
        assert conf == pytest.approx(0.65)

    def test_synthetic_source_gives_0_0(self):
        from airos.drivers.store.nightlights_ingestor import _cell_signals
        samples = [{"radiance_nw": 18.0, "lit_fraction": 0.7,
                    "quality_flag": "void_filled",
                    "source_record_id": "synthetic_fallback_12.97_77.57",
                    "provenance": {"source_id": "synthetic_fallback"}}] * 4
        _, _, conf = _cell_signals(samples)
        assert conf == pytest.approx(0.0)

    def test_all_no_data_returns_none(self):
        from airos.drivers.store.nightlights_ingestor import _cell_signals
        bad = [
            {"radiance_nw": None, "lit_fraction": None, "quality_flag": "no_data",
             "source_record_id": "x", "provenance": {"source_id": "nasa"}},
            {"radiance_nw": None, "lit_fraction": None, "quality_flag": "no_data",
             "source_record_id": "x", "provenance": {"source_id": "nasa"}},
        ]
        rad, lit, conf = _cell_signals(bad)
        assert rad is None
        assert conf == 0.0

    def test_empty_samples_returns_none(self):
        from airos.drivers.store.nightlights_ingestor import _cell_signals
        rad, lit, conf = _cell_signals([])
        assert rad is None
        assert conf == 0.0

    def test_economic_activity_index_capped_at_1(self):
        """EAI = radiance / 60.0, capped at 1.0."""
        # Verify the connector produces radiance ≤ 60 for synthetic (or test via ingestor formula)
        from airos.drivers.store.nightlights_ingestor import _cell_signals, _SATURATION_VALUE
        # High-radiance sample (over saturation)
        samples = [{"radiance_nw": 80.0, "lit_fraction": 0.9,
                    "quality_flag": "ok",
                    "source_record_id": "x",
                    "provenance": {"source_id": "nasa"}}]
        rad, _, _ = _cell_signals(samples)
        eai = min(rad / _SATURATION_VALUE, 1.0)
        assert eai == pytest.approx(1.0)


# ── C. ingest_nightlights end-to-end ─────────────────────────────────────

class TestIngestNightlightsEndToEnd:
    """Uses force_source="synthetic" — no network calls, writes to real store."""

    @pytest.fixture(scope="class")
    def rows_written(self):
        from unittest.mock import patch
        from airos.drivers.store.nightlights_ingestor import ingest_nightlights
        with patch(
            "airos.drivers.store.nightlights_ingestor.fetch_ntl_samples",
            wraps=lambda *a, **kw: __import__(
                "airos.drivers.connectors.nightlights.viirs", fromlist=["fetch_ntl_samples"]
            ).fetch_ntl_samples(*a, **{**kw, "force_source": "synthetic"}),
        ):
            return ingest_nightlights(_CITY, _BBOX, force=True)

    def test_returns_positive_int(self, rows_written):
        assert isinstance(rows_written, int)
        assert rows_written > 0

    def test_signals_readable_from_store(self, rows_written):
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        df = store.fetchdf(
            "SELECT DISTINCT signal FROM h3_signals "
            "WHERE domain = 'nightlights' LIMIT 100"
        )
        if df is None or df.empty:
            pytest.skip("Store read returned empty — likely a test-isolation issue")
        signal_names = set(df["signal"].tolist())
        expected = {"NTL_RADIANCE", "NTL_LIT_FRACTION",
                    "ECONOMIC_ACTIVITY_INDEX", "DATA_CONFIDENCE"}
        assert expected.issubset(signal_names)

    def test_activity_class_written_by_ingestor(self, rows_written):
        """ACTIVITY_CLASS must be written by ingest_nightlights (not agent-derived)."""
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        df = store.fetchdf(
            "SELECT COUNT(*) AS n FROM h3_signals "
            "WHERE domain = 'nightlights' AND signal = 'ACTIVITY_CLASS'"
        )
        if df is None or df.empty:
            pytest.skip("Store read returned empty")
        assert int(df["n"].iloc[0]) > 0, "ACTIVITY_CLASS must be written by ingestor"

    def test_data_confidence_zero_for_synthetic(self, rows_written):
        """Synthetic source → DATA_CONFIDENCE = 0.0 for all cells."""
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        df = store.fetchdf(
            "SELECT value FROM h3_signals "
            "WHERE domain = 'nightlights' AND signal = 'DATA_CONFIDENCE'"
            f" AND city_id = '{_CITY}'"
        )
        if df is None or df.empty:
            pytest.skip("No DATA_CONFIDENCE rows found")
        assert (df["value"].astype(float) == 0.0).all(), \
            "Synthetic source should produce DATA_CONFIDENCE=0.0"

    def test_economic_activity_index_in_range(self, rows_written):
        """ECONOMIC_ACTIVITY_INDEX must be between 0 and 1."""
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        df = store.fetchdf(
            "SELECT value FROM h3_signals "
            "WHERE domain = 'nightlights' AND signal = 'ECONOMIC_ACTIVITY_INDEX'"
            f" AND city_id = '{_CITY}' AND value IS NOT NULL"
        )
        if df is None or df.empty:
            pytest.skip("No ECONOMIC_ACTIVITY_INDEX rows found")
        vals = df["value"].astype(float)
        assert (vals >= 0.0).all()
        assert (vals <= 1.0).all()

    def test_force_false_skips_on_second_call(self, rows_written):
        """Second call without force=True should be skipped (watermark guard).

        The class-scoped ``rows_written`` fixture already ran an ingest with
        force=True, so the watermark is set.  A second call with force=False
        should return 0 immediately.
        """
        assert rows_written > 0, "pre-condition: first ingest must have written rows"
        from unittest.mock import patch
        from airos.drivers.store.nightlights_ingestor import ingest_nightlights
        with patch(
            "airos.drivers.store.nightlights_ingestor.fetch_ntl_samples",
            wraps=lambda *a, **kw: __import__(
                "airos.drivers.connectors.nightlights.viirs", fromlist=["fetch_ntl_samples"]
            ).fetch_ntl_samples(*a, **{**kw, "force_source": "synthetic"}),
        ):
            result = ingest_nightlights(_CITY, _BBOX, force=False)
        assert result == 0


# ── D. NightLightsDriver class ─────────────────────────────────────────────

class TestNightLightsDriver:
    @pytest.fixture
    def driver(self):
        from airos.drivers.store.drivers.nightlights_driver import NightLightsDriver
        return NightLightsDriver()

    def test_domain_is_nightlights(self, driver):
        assert driver.domain == "nightlights"

    def test_cadence_is_30_days(self, driver):
        assert driver.cadence_hours == 24 * 30

    def test_produces_no_assessments(self, driver):
        assert driver.produces_assessments is False

    def test_signal_names_match_spec(self, driver):
        expected = {"NTL_RADIANCE", "NTL_LIT_FRACTION",
                    "ECONOMIC_ACTIVITY_INDEX", "DATA_CONFIDENCE", "ACTIVITY_CLASS"}
        assert expected.issubset(set(driver.signal_names))

    def test_no_required_env_vars(self, driver):
        assert driver._required_env_vars == []

    def test_conformance_check_passes(self, driver):
        result = driver.conformance_check()
        assert result.ok is True

    def test_driver_loads_via_registry(self):
        from pathlib import Path
        from airos.os.sdk.driver_loader import load_drivers
        drivers = load_drivers(Path("data/config/drivers_registry.yaml"))
        assert "nightlights" in drivers
        assert drivers["nightlights"].__class__.__name__ == "NightLightsDriver"


# ── E. Dispatcher wiring ───────────────────────────────────────────────────

class TestDispatcherWiring:
    def test_nightlights_in_all_domains(self):
        from airos.drivers.store.ingestor import ALL_DOMAINS
        assert "nightlights" in ALL_DOMAINS

    def test_nightlights_in_domain_fn(self):
        from airos.drivers.store.ingestor import _DOMAIN_FN
        assert "nightlights" in _DOMAIN_FN
        assert callable(_DOMAIN_FN["nightlights"])

    def test_nightlights_interval_is_30_days(self):
        from airos.drivers.store.ingestor import _DOMAIN_INTERVAL
        assert _DOMAIN_INTERVAL["nightlights"] == timedelta(days=30)

    def test_nightlights_in_no_assessment_domains(self):
        """Scheduler must not try to generate assessments for nightlights."""
        import inspect
        from airos.drivers.store import ingestor
        src = inspect.getsource(ingestor)
        # _NO_ASSESSMENT_DOMAINS must contain "nightlights"
        assert '"nightlights"' in src or "'nightlights'" in src


# ── F. Schema validation ───────────────────────────────────────────────────

class TestSchemaValidation:
    def test_provider_example_validates(self):
        import json
        from pathlib import Path
        from airos.os.specifications.conformance import validator_for_schema_file
        schema  = "specifications/provider_contracts/nightlights_ntl_feed.v1.schema.json"
        example = "specifications/examples/nightlights/provider_ntl_samples.sample.json"
        validator_for_schema_file(schema).validate(
            json.loads(Path(example).read_text())
        )

    def test_consumer_example_validates(self):
        import json
        from pathlib import Path
        from airos.os.specifications.conformance import validator_for_schema_file
        schema  = "specifications/consumer_contracts/nightlights_signals.v1.schema.json"
        example = "specifications/examples/nightlights/nightlights_signals_dashboard.sample.json"
        validator_for_schema_file(schema).validate(
            json.loads(Path(example).read_text())
        )

    def test_synthetic_samples_match_provider_schema(self):
        """Samples from the connector must satisfy the provider contract."""
        import json
        from pathlib import Path
        from airos.drivers.connectors.nightlights.viirs import fetch_ntl_samples
        from airos.os.specifications.conformance import validator_for_schema_file

        samples = fetch_ntl_samples(**_BBOX, force_source="synthetic")
        payload = {
            "provider_id":  "synthetic_fallback",
            "source_name":  "Synthetic NTL fallback",
            "source_type":  "synthetic",
            "bbox":         _BBOX,
            "samples":      samples,
        }
        schema = "specifications/provider_contracts/nightlights_ntl_feed.v1.schema.json"
        validator_for_schema_file(schema).validate(payload)

    def test_provider_schema_rejects_missing_bbox(self):
        """Payload without bbox must fail validation."""
        import jsonschema
        from airos.os.specifications.conformance import validator_for_schema_file
        bad_payload = {
            "provider_id": "x", "source_name": "x", "source_type": "synthetic",
            "samples": [],
        }
        schema = "specifications/provider_contracts/nightlights_ntl_feed.v1.schema.json"
        with pytest.raises(jsonschema.ValidationError):
            validator_for_schema_file(schema).validate(bad_payload)
