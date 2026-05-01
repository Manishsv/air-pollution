from __future__ import annotations

import pandas as pd


def build_observation_table(observations: pd.DataFrame, grid) -> pd.DataFrame:
    """
    Build a unified observation table aligned to a spatial grid.

    Output columns (canonical fabric table):
      grid_id, timestamp, variable, value, unit, source, confidence, quality_flag,
      plus provenance fields (observation_id, entity_id, entity_type, spatial_scope, point_lat, point_lon).

    Notes:
    - Point observations with `point_lat/point_lon` are mapped to H3 `grid_id`.
    - Observations with `spatial_scope=="global"` are broadcast to all grid cells.
    """
    if observations is None or observations.empty:
        return pd.DataFrame(
            columns=[
                "grid_id",
                "timestamp",
                "variable",
                "value",
                "unit",
                "source",
                "confidence",
                "quality_flag",
                "observation_id",
                "entity_id",
                "entity_type",
                "spatial_scope",
                "point_lat",
                "point_lon",
            ]
        )

    obs = observations.copy()
    obs["timestamp"] = pd.to_datetime(obs["timestamp"], utc=True, errors="coerce")
    obs["variable"] = obs["observed_property"].astype(str)

    # Confidence heuristic from quality_flag
    obs["confidence"] = 0.7
    q = obs.get("quality_flag", "unknown").astype(str).str.lower()
    obs.loc[q.eq("synthetic"), "confidence"] = 0.1
    obs.loc[q.eq("bad"), "confidence"] = 0.3
    obs.loc[q.eq("ok"), "confidence"] = 0.8

    # Ensure provenance columns exist (best-effort)
    for c, default in [
        ("observation_id", pd.NA),
        ("entity_id", pd.NA),
        ("entity_type", pd.NA),
        ("spatial_scope", pd.NA),
        ("point_lat", pd.NA),
        ("point_lon", pd.NA),
    ]:
        if c not in obs.columns:
            obs[c] = default

    # Grid mapping
    obs["grid_id"] = obs.get("grid_id", pd.NA)
    if grid is not None and len(grid) > 0:
        try:
            import h3

            # Map point observations to H3 if they don't already have grid_id.
            mask_point = obs["grid_id"].isna() & obs["point_lat"].notna() & obs["point_lon"].notna()
            if mask_point.any():
                res = int(getattr(grid, "attrs", {}).get("h3_resolution", 0) or 0)
                if res <= 0 and "h3_id" in getattr(grid, "columns", []):
                    # Best-effort: infer resolution from first cell id.
                    try:
                        res = int(h3.get_resolution(str(grid["h3_id"].iloc[0])))
                    except Exception:
                        res = 0
                if res > 0:
                    obs.loc[mask_point, "grid_id"] = obs.loc[mask_point].apply(
                        lambda r: h3.latlng_to_cell(float(r["point_lat"]), float(r["point_lon"]), res),
                        axis=1,
                    )
        except Exception:
            # Never break pipeline on optional grid mapping.
            pass

        # Broadcast global observations to all grid cells.
        grid_ids = None
        if "h3_id" in getattr(grid, "columns", []):
            grid_ids = grid["h3_id"].astype(str).unique().tolist()
        if grid_ids:
            mask_global = obs["grid_id"].isna() & obs["spatial_scope"].astype(str).str.lower().eq("global")
            if mask_global.any():
                base = obs.loc[mask_global].copy()
                reps = []
                for gid in grid_ids:
                    tmp = base.copy()
                    tmp["grid_id"] = gid
                    reps.append(tmp)
                obs = pd.concat([obs.loc[~mask_global], *reps], ignore_index=True)

    return obs[
        [
            "grid_id",
            "timestamp",
            "variable",
            "value",
            "unit",
            "source",
            "confidence",
            "quality_flag",
            "observation_id",
            "entity_id",
            "entity_type",
            "spatial_scope",
            "point_lat",
            "point_lon",
        ]
    ]

