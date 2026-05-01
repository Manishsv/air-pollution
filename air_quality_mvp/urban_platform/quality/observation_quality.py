from __future__ import annotations

import pandas as pd


def apply_source_reliability_to_observations(observation_store_df: pd.DataFrame, reliability_df: pd.DataFrame) -> pd.DataFrame:
    """
    Join reliability metrics onto observations and adjust confidence/quality flags.

    Adds:
      - source_reliability_score
      - source_reliability_status
      - source_reliability_issues
      - original_quality_flag
      - adjusted_confidence (stored back into `confidence`)
    """
    if observation_store_df is None or observation_store_df.empty:
        return observation_store_df
    if reliability_df is None or reliability_df.empty:
        out = observation_store_df.copy()
        out["source_reliability_score"] = pd.NA
        out["source_reliability_status"] = pd.NA
        out["source_reliability_issues"] = pd.NA
        out["original_quality_flag"] = out.get("quality_flag", pd.NA)
        return out

    obs = observation_store_df.copy()
    rel = reliability_df.copy()
    rel = rel.rename(columns={"variable": "variable"}).copy()

    # Ensure join keys exist
    obs["entity_id"] = obs["entity_id"].astype(str)
    obs["variable"] = obs["variable"].astype(str)
    rel["entity_id"] = rel["entity_id"].astype(str)
    rel["variable"] = rel["variable"].astype(str)

    rel_keep = rel[
        [
            "entity_id",
            "variable",
            "reliability_score",
            "status",
            "reliability_issues",
        ]
    ].copy()
    rel_keep = rel_keep.rename(
        columns={
            "reliability_score": "source_reliability_score",
            "status": "source_reliability_status",
            "reliability_issues": "source_reliability_issues",
        }
    )

    out = obs.merge(rel_keep, on=["entity_id", "variable"], how="left")
    out["original_quality_flag"] = out.get("quality_flag", pd.NA)

    # Adjust confidence
    out["confidence"] = pd.to_numeric(out.get("confidence"), errors="coerce")
    out["source_reliability_score"] = pd.to_numeric(out.get("source_reliability_score"), errors="coerce")
    out["source_reliability_score"] = out["source_reliability_score"].fillna(1.0).clip(0.0, 1.0)
    out["confidence"] = (out["confidence"].fillna(0.0) * out["source_reliability_score"]).clip(0.0, 1.0)

    # Flag suspect/offline sources
    st = out.get("source_reliability_status", "").astype(str).str.lower()
    out.loc[st.isin(["suspect", "offline"]), "quality_flag"] = "suspect"
    return out

