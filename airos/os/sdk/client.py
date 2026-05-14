from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from airos.network.api import local as local_api


@dataclass(frozen=True)
class AirOSClient:
    """
    AirOS runtime query client (QUERY mode).

    Reads from the live store (SQLite + output files) written by the AirOS
    pipeline.  Use this for decision packets, observations, features,
    recommendations, events, metrics, and audit data.

    Requires the pipeline to have run at least once.

    Example
    -------
    ::

        from airos.os.sdk import AirOSClient

        client = AirOSClient()
        packets = client.get_decision_packets(category="air_quality")
        obs = client.get_observations(variable="pm25")
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

    def get_events(
        self,
        event_type: str | None = None,
        severity: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        return local_api.get_events(event_type=event_type, severity=severity, start_time=start_time, end_time=end_time, base_dir=self._base)

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

    # ------------------------------------------------------------------
    # Mutations — write operations on the live store
    # ------------------------------------------------------------------

    def close_insight(
        self,
        insight_id: str,
        outcome_status: str,
        closed_by: str,
        *,
        condition_verdict: str | None = None,
        cause_verdict: str | None = None,
        routing_verdict: str | None = None,
        action_verdict: str | None = None,
    ) -> None:
        """Record an officer's closure decision on an insight.

        Parameters
        ----------
        insight_id:
            The insight to close.
        outcome_status:
            One of ``"confirmed"``, ``"refuted"``, ``"partially_confirmed"``,
            ``"unverifiable"``. This is the back-compat condition-layer field.
        closed_by:
            Non-empty reviewer identity string (email or officer ID).
            Anonymous closure is prohibited by the Review Contract.
        condition_verdict, cause_verdict, routing_verdict, action_verdict:
            Four-way verdict split (methodology §4.3). All optional;
            v1 deployments typically only collect ``condition_verdict``.

        Raises
        ------
        ValueError
            If ``closed_by`` is empty or any verdict value is invalid.
        """
        from airos.drivers.store.writer import close_insight as _close
        _close(
            insight_id=insight_id,
            outcome_status=outcome_status,
            closed_by=closed_by,
            condition_verdict=condition_verdict,
            cause_verdict=cause_verdict,
            routing_verdict=routing_verdict,
            action_verdict=action_verdict,
        )

    def submit_analysis_request(self, h3_id: str, city_id: str) -> tuple[bool, str]:
        """Queue a cell for async analysis by the H3 Expert Agent.

        Returns ``(ok, message)``.  Rejected if a request is already
        pending/running, or a completed request is within the cooldown window.
        """
        from airos.drivers.store.writer import submit_analysis_request as _submit
        return _submit(h3_id, city_id)

    def get_request_status(self, h3_id: str, city_id: str) -> dict:
        """Return the most recent analysis request for a cell.

        Returns an empty dict if no request exists.

        Keys: request_id, status, requested_at, started_at, completed_at,
        insight_id, error_msg.
        """
        from airos.drivers.store.reader import get_request_status as _status
        return _status(h3_id, city_id)


# Backward-compatibility alias — will be removed in a future release.
# Use AirOSClient for all new code.
UrbanPlatformClient = AirOSClient

