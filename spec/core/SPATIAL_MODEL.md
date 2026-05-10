# AirOS Core — Spatial Model Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Core

---

## Purpose [INFORMATIVE]

The spatial model defines the common address space shared by all AirOS components. Every signal, assessment, insight, and decision packet is anchored to a cell in this address space. Components that disagree on the spatial model cannot interoperate.

---

## Grid System [NORMATIVE]

AirOS uses the **H3 Discrete Global Grid System** (Uber H3, https://h3geo.org) as its spatial address space.

- **All signals MUST be stored at H3 resolution 8.** This corresponds to cells of approximately 0.74 km² area and ~1 km edge-to-edge distance.
- A cell is identified by its H3 index string (e.g. `8860145b4bfffff`).
- The grid is hierarchical — resolution 7 cells (~5.16 km²) are used for city-wide rollups; resolution 8 is the authoritative signal resolution.

| Resolution | Approx. area | Edge-to-edge | AirOS use |
|------------|-------------|--------------|-----------|
| 7 | 5.16 km² | ~2.6 km | City-wide rollups (read-only) |
| **8** | **0.74 km²** | **~1.0 km** | **All signals and assessments (normative)** |
| 9 | 0.11 km² | ~0.4 km | Not used in this version |

**Non-conformance:** A Driver that writes `h3_signals` rows with cells at a resolution other than 8 MUST be rejected by the conformance gate. See [Drivers / Conformance](../drivers/CONFORMANCE.md).

---

## City Bounding Box [NORMATIVE]

Each city in a deployment MUST be defined by a bounding box:

```
{ lat_min, lon_min, lat_max, lon_max }
```

Only H3 cells whose centroids fall within the bounding box are valid targets for signals in that city's partition. Drivers MUST NOT write signals for cells outside the bounding box of their target city.

---

## Raw Data to H3 Cell: Four Assignment Methods [NORMATIVE]

All raw upstream data MUST be translated to H3 resolution-8 cells before being written to the Knowledge Store. There are four canonical methods. A Driver MUST document which method(s) it uses in its `signals.yaml` declaration.

### Method A — Point Observations → IDW Interpolation

**Used for:** AQI sensors, rain gauges, weather stations

Sensors report at discrete GPS coordinates. Inverse Distance Weighting (IDW) interpolates values to all H3 cell centroids within the bounding box.

**Formula:**

```
v̂(x) = Σᵢ wᵢ · vᵢ / Σᵢ wᵢ

wᵢ = 1 / max(dᵢ, d_floor)²

where:
  vᵢ   = observed value at sensor i
  dᵢ   = distance from sensor i to cell centroid x (km)
  d_floor = 0.05 km  (prevents division by zero for co-located sensors)
```

**DATA_CONFIDENCE decay:** `DATA_CONFIDENCE` MUST decay with distance from the nearest observation. The exact decay function and distance thresholds are implementation-defined; the minimum floor MUST be non-negative. [INFORMATIVE: The reference implementation sets `DATA_CONFIDENCE ≤ 0.3` for cells with no sensor within 50 km, and uses a linear decay between the nearest-sensor distance and that threshold.]

**NEAREST_OBS_KM signal:** Drivers using IDW SHOULD also write a `NEAREST_OBS_KM` signal recording the distance to the closest active sensor, so Apps can reason about interpolation quality.

**Assumptions [INFORMATIVE]:** IDW assumes spatial stationarity and isotropy. In urban environments with strong point sources (factory chimneys, busy intersections), these assumptions may not hold. Outputs near point sources SHOULD carry a lower `DATA_CONFIDENCE`.

### Method B — Polygon Features → Centroid Assignment

**Used for:** Building footprints, land parcels, administrative zones, crowd / footfall zones

A polygon feature is assigned to the H3 cell that contains its centroid:

```
cell = h3_latlng_to_cell(centroid_lat, centroid_lon, resolution=8)
```

Multiple features assigned to the same cell are aggregated (summed, averaged, or counted) before writing. The aggregation function MUST be declared in the Driver's `signals.yaml`.

### Method C — Line Features → Clip and Sum

**Used for:** Roads, waterways, drains, pipelines

A line feature may cross multiple H3 cell boundaries. For each candidate cell:

1. Compute the spatial intersection of the line with the cell polygon
2. Project both to a local UTM coordinate system for metric accuracy
3. Sum the intersection length in metres

The result is the total metric length of that feature type within each cell. Cells with no intersection receive no row (not zero — absence means no data).

**DATA_CONFIDENCE for line features:** SHOULD be set to reflect OSM mapping completeness for the region. Informal settlements with incomplete road mapping SHOULD have lower `DATA_CONFIDENCE` for road and drain signals.

### Method D — Satellite Grid → Direct Assignment

**Used for:** Sentinel-2 derived indices (LST, NDVI, MNDWI, water quality), MODIS fire

Each satellite pixel or derived grid cell has a centroid coordinate. Assign to H3:

```
cell = h3_latlng_to_cell(pixel_centroid_lat, pixel_centroid_lon, resolution=8)
```

Multiple pixels assigned to the same cell are averaged. Cloud-covered pixels MUST be excluded, not averaged as zero. The `DATA_CONFIDENCE` for satellite-derived signals MUST reflect cloud cover fraction:

```
DATA_CONFIDENCE ≈ 1 - cloud_fraction
```

**Minimum coverage [NORMATIVE]:** If cloud cover exceeds 80% of a cell, the Driver SHOULD NOT write signals for that cell in that fetch cycle (no data is preferable to heavily interpolated data).

---

## Neighbour Relationships [NORMATIVE]

The H3 k-ring neighbourhood is the standard way to express spatial proximity in AirOS. A cell's k=1 ring has 6 neighbours; k=2 has 18; k=3 has 36.

Apps that read neighbour context MUST use the H3 k-ring function to compute neighbours — they MUST NOT use Euclidean distance to approximate neighbourhoods.

---

## City-Wide Rollups [INFORMATIVE]

Some App queries aggregate signals across all cells in a city. These aggregations use resolution-7 parent cells as intermediate grouping keys. A resolution-7 cell contains approximately 7 resolution-8 children.

Rollups are computed at query time by Apps; they are not persisted in the Knowledge Store.

---

## Coordinate Reference System [NORMATIVE]

All coordinates MUST be in WGS84 (EPSG:4326) geographic coordinates (decimal degrees latitude/longitude).

Metric distance calculations (Method C, IDW distance, sensor-to-cell distances) MUST use a projected coordinate system appropriate for the city's latitude band. Implementations MUST select the appropriate local UTM zone for their region of deployment.

[INFORMATIVE: The reference implementation uses UTM Zone 43N (EPSG:32643) for cities between 72°E–78°E longitude and UTM Zone 44N (EPSG:32644) for cities between 78°E–84°E. Deployments outside this range must configure a different zone.]
