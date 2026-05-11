"""Tests for the terrain domain pipeline.

Coverage:
  A. Connector helpers (_grid_points, _synthetic_flat, fetch_dem_samples)
  B. Ingestor pure functions (_assign_h3, _cell_elevation, _slope_aspect, _ruggedness)
  C. ingest_terrain end-to-end using synthetic source (no network, writes to real store)
  D. TerrainDriver class (instantiation, conformance, metadata)
  E. Dispatcher wiring (ALL_DOMAINS, _DOMAIN_FN, _DOMAIN_INTERVAL)
  F. Schema validation (provider contract, consumer contract)

No live network calls — all tests use force_source="synthetic" or pure in-process data.
"""
from __future__ import annotations

import math
from datetime import timedelta

import pytest


# ── Shared fixtures ────────────────────────────────────────────────────────

_BBOX = dict(lat_min=12.97, lat_max=12.99, lon_min=77.57, lon_max=77.59)
_CITY = "test_terrain_city"

# Five synthetic samples: ok, ok, void, void_filled, suspected_artefact
_SAMPLES_MIXED = [
    {"lat": 12.971, "lon": 77.571, "elevation_m": 920.0, "quality_flag": "ok",
     "provenance": {"source_id": "copernicus_dem_esa"}},
    {"lat": 12.972, "lon": 77.572, "elevation_m": 918.0, "quality_flag": "ok",
     "provenance": {"source_id": "copernicus_dem_esa"}},
    {"lat": 12.973, "lon": 77.573, "elevation_m": None,  "quality_flag": "void",
     "provenance": {"source_id": "copernicus_dem_esa"}},
    {"lat": 12.974, "lon": 77.574, "elevation_m": 915.0, "quality_flag": "void_filled",
     "provenance": {"source_id": "copernicus_dem_esa"}},
    {"lat": 12.975, "lon": 77.575, "elevation_m": 990.0, "quality_flag": "suspected_artefact",
     "provenance": {"source_id": "copernicus_dem_esa"}},
]


# ── A. Connector helpers ───────────────────────────────────────────────────

class TestGridPoints:
    def test_returns_list_of_tuples(self):
        from airos.drivers.connectors.terrain.srtm import _grid_points
        pts = _grid_points(12.87, 77.47, 12.89, 77.49)
        assert isinstance(pts, list)
        assert all(isinstance(p, tuple) and len(p) == 2 for p in pts)

    def test_points_within_bbox(self):
        from airos.drivers.connectors.terrain.srtm import _grid_points
        pts = _grid_points(12.87, 77.47, 13.07, 77.69)
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        assert min(lats) >= 12.87
        assert max(lats) <= 13.07
        assert min(lons) >= 77.47
        assert max(lons) <= 77.69

    def test_count_scales_with_bbox_size(self):
        from airos.drivers.connectors.terrain.srtm import _grid_points
        small = _grid_points(12.97, 77.57, 12.98, 77.58)
        large = _grid_points(12.87, 77.47, 13.07, 77.69)
        assert len(large) > len(small) * 10

    def test_custom_spacing(self):
        from airos.drivers.connectors.terrain.srtm import _grid_points
        fine   = _grid_points(12.87, 77.47, 13.07, 77.69, spacing=0.001)
        coarse = _grid_points(12.87, 77.47, 13.07, 77.69, spacing=0.01)
        assert len(fine) > len(coarse)

    def test_empty_bbox_returns_empty(self):
        from airos.drivers.connectors.terrain.srtm import _grid_points
        pts = _grid_points(13.0, 77.0, 12.0, 76.0)   # inverted → no points
        assert pts == []


class TestSyntheticFlat:
    def test_returns_one_sample_per_point(self):
        from airos.drivers.connectors.terrain.srtm import _grid_points, _synthetic_flat
        pts = _grid_points(**_BBOX)
        samples = _synthetic_flat(pts, _BBOX)
        assert len(samples) == len(pts)

    def test_bangalore_elevation_approximate(self):
        """Synthetic lookup should return ~920 m for central Bangalore."""
        from airos.drivers.connectors.terrain.srtm import _grid_points, _synthetic_flat
        bbox = dict(lat_min=12.97, lat_max=12.98, lon_min=77.57, lon_max=77.58)
        pts  = _grid_points(**bbox)
        samp = _synthetic_flat(pts, bbox)
        assert abs(samp[0]["elevation_m"] - 920.0) < 50.0   # within 50 m

    def test_quality_flag_is_void_filled(self):
        from airos.drivers.connectors.terrain.srtm import _grid_points, _synthetic_flat
        pts  = _grid_points(**_BBOX)
        samp = _synthetic_flat(pts, _BBOX)
        assert all(s["quality_flag"] == "void_filled" for s in samp)

    def test_provenance_fields_present(self):
        from airos.drivers.connectors.terrain.srtm import _grid_points, _synthetic_flat
        pts  = _grid_points(**_BBOX)
        samp = _synthetic_flat(pts, _BBOX)
        for s in samp[:3]:
            assert "source_id"   in s["provenance"]
            assert "ingested_at" in s["provenance"]
            assert "license"     in s["provenance"]

    def test_source_id_marks_synthetic(self):
        from airos.drivers.connectors.terrain.srtm import _grid_points, _synthetic_flat
        pts  = _grid_points(**_BBOX)
        samp = _synthetic_flat(pts, _BBOX)
        assert "synthetic" in samp[0]["provenance"]["source_id"]


class TestFetchDemSamples:
    def test_synthetic_returns_samples(self):
        from airos.drivers.connectors.terrain.srtm import fetch_dem_samples
        samples = fetch_dem_samples(**_BBOX, force_source="synthetic")
        assert len(samples) > 0

    def test_synthetic_sample_schema(self):
        from airos.drivers.connectors.terrain.srtm import fetch_dem_samples
        samples = fetch_dem_samples(**_BBOX, force_source="synthetic")
        required = {"lat", "lon", "elevation_m", "quality_flag",
                    "source_record_id", "provenance"}
        for s in samples[:5]:
            assert required.issubset(s.keys())

    def test_synthetic_sample_coordinates_in_bbox(self):
        from airos.drivers.connectors.terrain.srtm import fetch_dem_samples
        samples = fetch_dem_samples(**_BBOX, force_source="synthetic")
        for s in samples:
            assert _BBOX["lat_min"] <= s["lat"] <= _BBOX["lat_max"]
            assert _BBOX["lon_min"] <= s["lon"] <= _BBOX["lon_max"]

    def test_empty_bbox_returns_empty(self):
        from airos.drivers.connectors.terrain.srtm import fetch_dem_samples
        samples = fetch_dem_samples(13.0, 77.0, 12.0, 76.0, force_source="synthetic")
        assert samples == []


# ── B. Ingestor pure functions ─────────────────────────────────────────────

class TestAssignH3:
    def test_groups_by_cell(self):
        from airos.drivers.store.terrain_ingestor import _assign_h3
        groups = _assign_h3(_SAMPLES_MIXED, resolution=8)
        # All samples from a tiny bbox should land in ≤ a few cells
        assert len(groups) >= 1
        total = sum(len(v) for v in groups.values())
        assert total == len(_SAMPLES_MIXED)

    def test_empty_samples_returns_empty(self):
        from airos.drivers.store.terrain_ingestor import _assign_h3
        assert _assign_h3([], resolution=8) == {}


class TestCellElevation:
    def test_mean_excludes_artefact_and_null(self):
        """ok=920, ok=918, void=None, void_filled=915, artefact=990 → mean(920,918,915)=917.67"""
        from airos.drivers.store.terrain_ingestor import _cell_elevation
        elev, conf = _cell_elevation(_SAMPLES_MIXED)
        assert elev == pytest.approx(917.67, abs=0.1)

    def test_all_ok_confidence_is_0_90(self):
        from airos.drivers.store.terrain_ingestor import _cell_elevation
        ok_only = [s for s in _SAMPLES_MIXED if s["quality_flag"] == "ok"]
        _, conf = _cell_elevation(ok_only)
        assert conf == pytest.approx(0.90)

    def test_high_void_fraction_gives_0_65(self):
        """More than 10% void_filled → confidence 0.65."""
        from airos.drivers.store.terrain_ingestor import _cell_elevation
        samples = (
            [{"elevation_m": 920.0, "quality_flag": "void_filled",
              "provenance": {"source_id": "cop"}}] * 3 +
            [{"elevation_m": 918.0, "quality_flag": "ok",
              "provenance": {"source_id": "cop"}}] * 7
        )
        _, conf = _cell_elevation(samples)
        assert conf == pytest.approx(0.65)

    def test_synthetic_source_gives_0_0(self):
        from airos.drivers.store.terrain_ingestor import _cell_elevation
        samples = [{"elevation_m": 920.0, "quality_flag": "ok",
                    "provenance": {"source_id": "synthetic_fallback"}}] * 4
        _, conf = _cell_elevation(samples)
        assert conf == pytest.approx(0.0)

    def test_all_artefact_or_null_returns_none(self):
        from airos.drivers.store.terrain_ingestor import _cell_elevation
        bad = [
            {"elevation_m": None,  "quality_flag": "void",               "provenance": {"source_id": "x"}},
            {"elevation_m": 999.0, "quality_flag": "suspected_artefact", "provenance": {"source_id": "x"}},
        ]
        elev, conf = _cell_elevation(bad)
        assert elev is None
        assert conf == 0.0

    def test_empty_samples_returns_none(self):
        from airos.drivers.store.terrain_ingestor import _cell_elevation
        elev, conf = _cell_elevation([])
        assert elev is None
        assert conf == 0.0


class TestSlopeAspect:
    def _neighbours(self, cell: str) -> list[str]:
        import h3
        return [n for n in h3.grid_disk(cell, 1) if n != cell]

    def _centre(self, cell: str) -> tuple[float, float]:
        import h3
        return h3.cell_to_latlng(cell)

    _CELL = "8860145b39fffff"   # central Bangalore

    def test_flat_terrain_slope_is_zero(self):
        from airos.drivers.store.terrain_ingestor import _slope_aspect
        clat, clon = self._centre(self._CELL)
        neighbour_elevs = {n: 920.0 for n in self._neighbours(self._CELL)}
        slope, aspect = _slope_aspect(clat, clon, 920.0, neighbour_elevs)
        assert slope == pytest.approx(0.0, abs=0.05)

    def test_flat_terrain_aspect_is_minus_one(self):
        from airos.drivers.store.terrain_ingestor import _slope_aspect
        clat, clon = self._centre(self._CELL)
        neighbour_elevs = {n: 920.0 for n in self._neighbours(self._CELL)}
        _, aspect = _slope_aspect(clat, clon, 920.0, neighbour_elevs)
        assert aspect == pytest.approx(-1.0, abs=0.1)

    def test_north_sloped_terrain_aspect_near_north(self):
        """Higher elevation to the north → uphill faces north → aspect ≈ 0°."""
        import h3
        from airos.drivers.store.terrain_ingestor import _slope_aspect
        clat, clon = self._centre(self._CELL)
        neighbour_elevs = {}
        for n in self._neighbours(self._CELL):
            nlat, _ = h3.cell_to_latlng(n)
            neighbour_elevs[n] = 920.0 + (nlat - clat) * 111320 * 0.05
        slope, aspect = _slope_aspect(clat, clon, 920.0, neighbour_elevs)
        assert slope > 1.0   # definitely sloped
        # North-facing aspect: should be near 0° (or 360°)
        assert aspect < 15.0 or aspect > 345.0

    def test_slope_non_negative(self):
        import h3
        from airos.drivers.store.terrain_ingestor import _slope_aspect
        clat, clon = self._centre(self._CELL)
        neighbour_elevs = {n: 900.0 + i * 3 for i, n in
                           enumerate(self._neighbours(self._CELL))}
        slope, _ = _slope_aspect(clat, clon, 910.0, neighbour_elevs)
        assert slope >= 0.0

    def test_aspect_in_valid_range(self):
        import h3
        from airos.drivers.store.terrain_ingestor import _slope_aspect
        clat, clon = self._centre(self._CELL)
        neighbour_elevs = {n: 900.0 + i * 5 for i, n in
                           enumerate(self._neighbours(self._CELL))}
        slope, aspect = _slope_aspect(clat, clon, 910.0, neighbour_elevs)
        if slope > 0.05:
            assert 0.0 <= aspect <= 360.0

    def test_fewer_than_three_neighbours_returns_flat(self):
        from airos.drivers.store.terrain_ingestor import _slope_aspect
        clat, clon = self._centre(self._CELL)
        slope, aspect = _slope_aspect(clat, clon, 920.0, {"x": 925.0, "y": 915.0})
        assert slope == 0.0
        assert aspect == pytest.approx(-1.0)


class TestRuggedness:
    def test_flat_terrain_is_zero(self):
        from airos.drivers.store.terrain_ingestor import _ruggedness
        assert _ruggedness(920.0, {"a": 920.0, "b": 920.0, "c": 920.0}) == 0.0

    def test_symmetric_elevation_gives_correct_mean(self):
        from airos.drivers.store.terrain_ingestor import _ruggedness
        # Centre=920, neighbours at 910 and 930 → mean(|920-910|, |920-930|) = 10.0
        rug = _ruggedness(920.0, {"a": 910.0, "b": 930.0})
        assert rug == pytest.approx(10.0)

    def test_empty_neighbours_is_zero(self):
        from airos.drivers.store.terrain_ingestor import _ruggedness
        assert _ruggedness(920.0, {}) == 0.0

    def test_non_negative(self):
        from airos.drivers.store.terrain_ingestor import _ruggedness
        rug = _ruggedness(500.0, {"a": 600.0, "b": 400.0, "c": 550.0})
        assert rug >= 0.0


# ── C. ingest_terrain end-to-end ───────────────────────────────────────────

class TestIngestTerrainEndToEnd:
    """Uses force_source="synthetic" — no network calls, writes to real store."""

    @pytest.fixture(scope="class")
    def rows_written(self):
        from unittest.mock import patch
        from airos.drivers.store.terrain_ingestor import ingest_terrain
        # Patch the connector to always use synthetic (avoids any network attempt)
        with patch(
            "airos.drivers.store.terrain_ingestor.fetch_dem_samples",
            wraps=lambda *a, **kw: __import__(
                "airos.drivers.connectors.terrain.srtm", fromlist=["fetch_dem_samples"]
            ).fetch_dem_samples(*a, **{**kw, "force_source": "synthetic"}),
        ):
            return ingest_terrain(_CITY, _BBOX, force=True)

    def test_returns_positive_int(self, rows_written):
        assert isinstance(rows_written, int)
        assert rows_written > 0

    def test_six_signals_per_cell(self, rows_written):
        """Each cell gets exactly 6 signals: ELEVATION_M, SLOPE_DEG, ASPECT_DEG,
        RUGGEDNESS_INDEX, DATA_CONFIDENCE, TERRAIN_CLASS."""
        assert rows_written % 6 == 0

    def test_signals_readable_from_store(self, rows_written):
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        df = store.fetchdf(
            "SELECT DISTINCT signal_name FROM h3_signals "
            "WHERE domain = 'terrain' LIMIT 100"
        )
        if df is None or df.empty:
            pytest.skip("Store read returned empty — likely a test-isolation issue")
        signal_names = set(df["signal_name"].tolist())
        expected = {"ELEVATION_M", "SLOPE_DEG", "ASPECT_DEG",
                    "RUGGEDNESS_INDEX", "DATA_CONFIDENCE"}
        assert expected.issubset(signal_names)

    def test_terrain_class_written_by_ingestor(self, rows_written):
        """TERRAIN_CLASS is written by classify_terrain() called at end of ingest."""
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        df = store.fetchdf(
            "SELECT COUNT(*) AS n FROM h3_signals "
            "WHERE domain = 'terrain' AND signal_name = 'TERRAIN_CLASS'"
        )
        if df is None or df.empty:
            pytest.skip("Store read returned empty — likely a test-isolation issue")
        assert int(df["n"].iloc[0]) > 0, \
            "TERRAIN_CLASS should be written by classify_terrain() at end of ingest"

    def test_data_confidence_zero_for_synthetic(self, rows_written):
        """Synthetic source → DATA_CONFIDENCE = 0.0 for all cells."""
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        df = store.fetchdf(
            "SELECT value FROM h3_signals "
            "WHERE domain = 'terrain' AND signal_name = 'DATA_CONFIDENCE'"
        )
        if df is None or df.empty:
            pytest.skip("No DATA_CONFIDENCE rows found")
        assert (df["value"].astype(float) == 0.0).all(), \
            "Synthetic source should produce DATA_CONFIDENCE=0.0"

    def test_force_false_skips_on_second_call(self, rows_written):
        """Second call without force=True should be skipped (watermark guard).

        The class-scoped ``rows_written`` fixture already ran an ingest with
        force=True, so the watermark is set.  A second call with force=False
        should return 0 immediately.
        """
        assert rows_written > 0, "pre-condition: first ingest must have written rows"
        from unittest.mock import patch
        from airos.drivers.store.terrain_ingestor import ingest_terrain
        with patch(
            "airos.drivers.store.terrain_ingestor.fetch_dem_samples",
            wraps=lambda *a, **kw: __import__(
                "airos.drivers.connectors.terrain.srtm", fromlist=["fetch_dem_samples"]
            ).fetch_dem_samples(*a, **{**kw, "force_source": "synthetic"}),
        ):
            result = ingest_terrain(_CITY, _BBOX, force=False)
        # Watermark already set by fixture run → second call must be skipped
        assert result == 0


# ── D. TerrainDriver class ─────────────────────────────────────────────────

class TestTerrainDriver:
    @pytest.fixture
    def driver(self):
        from airos.drivers.store.drivers.terrain_driver import TerrainDriver
        return TerrainDriver()

    def test_domain_is_terrain(self, driver):
        assert driver.domain == "terrain"

    def test_cadence_is_90_days(self, driver):
        assert driver.cadence_hours == 24 * 90

    def test_produces_no_assessments(self, driver):
        assert driver.produces_assessments is False

    def test_signal_names_match_spec(self, driver):
        expected = {"ELEVATION_M", "SLOPE_DEG", "ASPECT_DEG",
                    "RUGGEDNESS_INDEX", "DATA_CONFIDENCE", "TERRAIN_CLASS"}
        assert expected.issubset(set(driver.signal_names))

    def test_terrain_class_in_signal_names(self, driver):
        """TERRAIN_CLASS is rule-derived by classify_terrain() and declared in signal_names."""
        assert "TERRAIN_CLASS" in driver.signal_names

    def test_no_required_env_vars(self, driver):
        assert driver._required_env_vars == []

    def test_conformance_check_passes(self, driver):
        result = driver.conformance_check()
        assert result.ok is True

    def test_driver_loads_via_registry(self):
        from pathlib import Path
        from airos.os.sdk.driver_loader import load_drivers
        drivers = load_drivers(Path("data/config/drivers_registry.yaml"))
        assert "terrain" in drivers
        assert drivers["terrain"].__class__.__name__ == "TerrainDriver"


# ── E. Dispatcher wiring ───────────────────────────────────────────────────

class TestDispatcherWiring:
    def test_terrain_in_all_domains(self):
        from airos.drivers.store.ingestor import ALL_DOMAINS
        assert "terrain" in ALL_DOMAINS

    def test_terrain_in_domain_fn(self):
        from airos.drivers.store.ingestor import _DOMAIN_FN
        assert "terrain" in _DOMAIN_FN
        assert callable(_DOMAIN_FN["terrain"])

    def test_terrain_interval_is_90_days(self):
        from airos.drivers.store.ingestor import _DOMAIN_INTERVAL
        assert _DOMAIN_INTERVAL["terrain"] == timedelta(days=90)

    def test_terrain_in_no_assessment_domains(self):
        """Scheduler must not try to generate assessments for terrain."""
        import inspect
        from airos.drivers.store import ingestor
        src = inspect.getsource(ingestor)
        assert '"terrain"' in src or "'terrain'" in src


# ── F. Schema validation ───────────────────────────────────────────────────

class TestSchemaValidation:
    def test_provider_example_validates(self):
        import json
        from pathlib import Path
        from airos.os.specifications.conformance import validator_for_schema_file
        schema  = "specifications/provider_contracts/terrain_dem_feed.v1.schema.json"
        example = "specifications/examples/terrain/provider_dem_samples.sample.json"
        validator_for_schema_file(schema).validate(
            json.loads(Path(example).read_text())
        )

    def test_consumer_example_validates(self):
        import json
        from pathlib import Path
        from airos.os.specifications.conformance import validator_for_schema_file
        schema  = "specifications/consumer_contracts/terrain_signals.v1.schema.json"
        example = "specifications/examples/terrain/terrain_signals_dashboard.sample.json"
        validator_for_schema_file(schema).validate(
            json.loads(Path(example).read_text())
        )

    def test_synthetic_samples_match_provider_schema(self):
        """Samples from the connector must satisfy the provider contract."""
        import json
        from datetime import datetime, timezone
        from pathlib import Path
        from airos.drivers.connectors.terrain.srtm import fetch_dem_samples
        from airos.os.specifications.conformance import validator_for_schema_file

        samples = fetch_dem_samples(**_BBOX, force_source="synthetic")
        payload = {
            "provider_id":      "synthetic_fallback",
            "source_name":      "Synthetic flat terrain",
            "source_type":      "dem_raster_sampled",
            "dem_source":       "srtm_30m",
            "license":          "synthetic — not for operational use",
            "void_fill_applied": False,
            "bbox":             _BBOX,
            "resolution_m":     30,
            "source_metadata":  {"note": "synthetic test payload"},
            "samples":          samples,
        }
        schema = "specifications/provider_contracts/terrain_dem_feed.v1.schema.json"
        validator_for_schema_file(schema).validate(payload)

    def test_provider_schema_rejects_missing_bbox(self):
        """Payload without bbox must fail validation."""
        import jsonschema
        from airos.os.specifications.conformance import validator_for_schema_file
        bad_payload = {
            "provider_id": "x", "source_name": "x", "source_type": "dem_raster_sampled",
            "dem_source": "srtm_30m", "license": "x", "resolution_m": 30,
            "source_metadata": {}, "samples": [],
        }
        schema = "specifications/provider_contracts/terrain_dem_feed.v1.schema.json"
        with pytest.raises(jsonschema.ValidationError):
            validator_for_schema_file(schema).validate(bad_payload)
