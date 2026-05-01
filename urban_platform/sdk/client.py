from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from urban_platform.api import local as local_api


@dataclass(frozen=True)
class UrbanPlatformClient:
    """
    Minimal platform SDK client.

    The dashboard must use this client (not direct file reads).
    """

    base_path: str = "."

    @property
    def _base(self) -> Path:
        return Path(self.base_path).resolve()

    def get_decision_packets(
        self,
        h3_id: str | None = None,
        min_confidence: float | None = None,
        recommendation_allowed: bool | None = None,
        category: str | None = None,
        actionability_level: str | None = None,
        confidence_level: str | None = None,
    ) -> list[dict]:
        packets = local_api.get_decision_packets(
            h3_id=h3_id,
            min_confidence=min_confidence,
            recommendation_allowed=recommendation_allowed,
            category=category,
            base_dir=self._base,
        )

        def _get(d: dict, *path, default=None):
            cur: Any = d
            for p in path:
                if not isinstance(cur, dict):
                    return default
                cur = cur.get(p)
            return cur if cur is not None else default

        if actionability_level is not None:
            packets = [p for p in packets if str(p.get("actionability_level", "")).lower() == str(actionability_level).lower()]
        if confidence_level is not None:
            packets = [p for p in packets if str(p.get("confidence_level", "")).lower() == str(confidence_level).lower()]
        # ensure packet has minimal fields
        packets = [p for p in packets if isinstance(_get(p, "confidence", "confidence_score"), (int, float)) or _get(p, "confidence", "confidence_score") is not None]
        return packets

    def get_decision_packet(self, packet_id: str) -> dict | None:
        return local_api.get_decision_packet(packet_id, base_dir=self._base)

    def get_features(
        self,
        grid_id: str | None = None,
        feature_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        return local_api.get_features(feature_name=feature_name, grid_id=grid_id, start_time=start_time, end_time=end_time, base_dir=self._base)

    def get_observations(
        self,
        variable: str | None = None,
        grid_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        return local_api.get_observations(variable=variable, grid_id=grid_id, start_time=start_time, end_time=end_time, base_dir=self._base)

    def get_recommendations(self, grid_id: str | None = None, min_confidence: float | None = None):
        return local_api.get_recommendations(grid_id=grid_id, min_confidence=min_confidence, base_dir=self._base)

    def get_source_reliability(self, entity_id: str | None = None, variable: str | None = None, status: str | None = None) -> pd.DataFrame:
        return local_api.get_source_reliability(entity_id=entity_id, variable=variable, status=status, base_dir=self._base)

    def get_metrics(self) -> dict:
        p = (self._base / "data" / "outputs" / "metrics.json")
        return local_api._read_json(p)  # type: ignore[attr-defined]

    def get_data_audit(self) -> dict:
        p = (self._base / "data" / "outputs" / "data_audit.json")
        return local_api._read_json(p)  # type: ignore[attr-defined]

    def get_spec_manifest(self) -> dict:
        return local_api.get_spec_manifest(base_dir=self._base)

    def get_conformance_report(self) -> dict:
        return local_api.get_conformance_report(base_dir=self._base)

    def validate_artifact(self, schema_name: str, data: Any) -> dict:
        return local_api.validate_artifact(schema_name, data, base_dir=self._base)

    def get_map_layers(self) -> dict:
        """
        Return lightweight layers for mapping (packets + stations).
        """
        packets = self.get_decision_packets()
        return {"decision_packets": packets}

