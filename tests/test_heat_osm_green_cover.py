"""Tests for the OSM green cover connector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from urban_platform.connectors.heat.osm_green_cover import (
    _green_cover_fraction,
    _h3_cell_polygon,
    _water_proximity_score,
    compute_green_cover,
)

# ── Helper ─────────────────────────────────────────────────────────────────

def _small_bangalore_box() -> Polygon:
    """A tiny bbox near Bangalore — small enough to have a few H3 cells at res 9."""
    return box(77.58, 12.96, 77.62, 13.00)


def _mock_ox_empty() -> MagicMock:
    """osmnx that always raises (simulates no features)."""
    ox = MagicMock()
    ox.features_from_polygon.side_effect = Exception("no features")
    return ox


def _mock_ox_with_green(boundary: Polygon) -> MagicMock:
    """osmnx returning a GDF that fully covers the boundary as green."""
    import geopandas as gpd
    from shapely.geometry import mapping
    ox = MagicMock()
    gdf = gpd.GeoDataFrame({"geometry": [boundary]}, crs="EPSG:4326")
    ox.features_from_polygon.return_value = gdf
    return ox


def _mock_ox_no_water() -> MagicMock:
    """osmnx returning green but no water."""
    import geopandas as gpd
    ox = MagicMock()
    full_poly = box(-180, -90, 180, 90)
    gdf = gpd.GeoDataFrame({"geometry": [full_poly]}, crs="EPSG:4326")
    # First calls are green (return gdf), last calls are water (raise)
    call_count = [0]
    def side_effect(boundary, tags=None):
        call_count[0] += 1
        if "water" in str(tags) or "wetland" in str(tags) or "waterway" in str(tags) or "reservoir" in str(tags):
            raise Exception("no water features")
        return gdf
    ox.features_from_polygon.side_effect = side_effect
    return ox


# ── Unit: _h3_cell_polygon ─────────────────────────────────────────────────

def test_h3_cell_polygon_is_polygon():
    import h3
    cell = list(h3.geo_to_cells(
        {"type": "Polygon", "coordinates": [[(77.59, 12.97), (77.60, 12.97), (77.60, 12.98), (77.59, 12.98), (77.59, 12.97)]]},
        9,
    ))[0]
    poly = _h3_cell_polygon(cell)
    assert poly.geom_type == "Polygon"
    assert poly.area > 0


# ── Unit: _green_cover_fraction ────────────────────────────────────────────

def test_green_cover_full():
    cell = box(0, 0, 1, 1)
    green = box(0, 0, 1, 1)
    assert _green_cover_fraction(cell, green) == pytest.approx(1.0, abs=0.01)


def test_green_cover_zero():
    cell = box(0, 0, 1, 1)
    green = box(5, 5, 6, 6)  # no overlap
    assert _green_cover_fraction(cell, green) == pytest.approx(0.0, abs=0.01)


def test_green_cover_half():
    cell = box(0, 0, 2, 1)
    green = box(0, 0, 1, 1)  # left half
    frac = _green_cover_fraction(cell, green)
    assert frac == pytest.approx(0.5, abs=0.05)


def test_green_cover_none_green():
    cell = box(0, 0, 1, 1)
    assert _green_cover_fraction(cell, None) == 0.0


# ── Unit: _water_proximity_score ──────────────────────────────────────────

def test_water_proximity_none():
    cell = box(0, 0, 1, 1)
    assert _water_proximity_score(cell, None) == 0.0


def test_water_proximity_intersecting():
    cell = box(0, 0, 1, 1)
    water = box(0.5, 0.5, 1.5, 1.5)  # overlaps
    assert _water_proximity_score(cell, water) == 1.0


def test_water_proximity_far():
    cell = box(0, 0, 0.001, 0.001)  # tiny cell near origin
    water = box(10, 10, 11, 11)     # far away (>500m equivalent)
    score = _water_proximity_score(cell, water)
    assert score == 0.0


def test_water_proximity_between():
    # Cell at origin, water 250m away (approx 0.00225 degrees)
    cell = box(0, 0, 0.001, 0.001)
    radius_m = 500.0
    deg_per_m = 1.0 / 111_000.0
    half_radius = (radius_m / 2) * deg_per_m  # 250m in degrees
    water = box(half_radius + 0.001, 0, half_radius + 0.002, 0.001)
    score = _water_proximity_score(cell, water, radius_m=radius_m)
    assert 0.0 < score < 1.0


# ── Integration: compute_green_cover ──────────────────────────────────────

def test_compute_green_cover_returns_dataframe():
    boundary = _small_bangalore_box()
    ox = _mock_ox_empty()
    df = compute_green_cover(boundary, h3_resolution=9, osmnx_module=ox)
    assert isinstance(df, pd.DataFrame)


def test_compute_green_cover_columns():
    boundary = _small_bangalore_box()
    ox = _mock_ox_empty()
    df = compute_green_cover(boundary, h3_resolution=9, osmnx_module=ox)
    assert set(df.columns) == {"h3_id", "green_cover_fraction", "water_proximity_score", "osm_feature_count"}


def test_compute_green_cover_has_rows():
    boundary = _small_bangalore_box()
    ox = _mock_ox_empty()
    df = compute_green_cover(boundary, h3_resolution=9, osmnx_module=ox)
    assert len(df) > 0


def test_compute_green_cover_zero_when_no_features():
    boundary = _small_bangalore_box()
    ox = _mock_ox_empty()
    df = compute_green_cover(boundary, h3_resolution=9, osmnx_module=ox)
    assert (df["green_cover_fraction"] == 0.0).all()
    assert (df["water_proximity_score"] == 0.0).all()


def test_compute_green_cover_fraction_range():
    boundary = _small_bangalore_box()
    ox = _mock_ox_empty()
    df = compute_green_cover(boundary, h3_resolution=9, osmnx_module=ox)
    assert (df["green_cover_fraction"] >= 0.0).all()
    assert (df["green_cover_fraction"] <= 1.0).all()


def test_compute_green_cover_water_range():
    boundary = _small_bangalore_box()
    ox = _mock_ox_empty()
    df = compute_green_cover(boundary, h3_resolution=9, osmnx_module=ox)
    assert (df["water_proximity_score"] >= 0.0).all()
    assert (df["water_proximity_score"] <= 1.0).all()


def test_compute_green_cover_h3_id_strings():
    boundary = _small_bangalore_box()
    ox = _mock_ox_empty()
    df = compute_green_cover(boundary, h3_resolution=9, osmnx_module=ox)
    assert df["h3_id"].dtype == object
    assert df["h3_id"].str.len().gt(0).all()


def test_compute_green_cover_full_green_gives_high_fraction():
    import geopandas as gpd
    boundary = _small_bangalore_box()
    # Cover the entire extent with green
    huge_green = box(77.0, 12.0, 78.0, 14.0)
    gdf = gpd.GeoDataFrame({"geometry": [huge_green]}, crs="EPSG:4326")
    ox = MagicMock()
    def side_effect(b, tags=None):
        tag_str = str(tags)
        if "water" in tag_str or "wetland" in tag_str or "waterway" in tag_str or "reservoir" in tag_str:
            raise Exception("no water")
        return gdf
    ox.features_from_polygon.side_effect = side_effect
    df = compute_green_cover(boundary, h3_resolution=9, osmnx_module=ox)
    assert (df["green_cover_fraction"] > 0.9).all(), f"Expected high green cover, got {df['green_cover_fraction'].tolist()}"


def test_compute_green_cover_osm_failure_returns_empty():
    """If osmnx import fails and no module provided, return empty DataFrame."""
    boundary = _small_bangalore_box()
    with patch.dict("sys.modules", {"osmnx": None}):
        # Pass a broken module that raises on any attribute access
        broken = MagicMock()
        broken.features_from_polygon.side_effect = Exception("import failed")
        # Force h3.geo_to_cells to also fail to simulate total failure
        with patch("urban_platform.connectors.heat.osm_green_cover.h3") as mock_h3:
            mock_h3.geo_to_cells.side_effect = Exception("h3 failed")
            df = compute_green_cover(boundary, h3_resolution=9, osmnx_module=broken)
    assert isinstance(df, pd.DataFrame)
    assert df.empty
