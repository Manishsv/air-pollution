from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class PeopleCountProvenance:
    model_name: str
    model_version: str | None = None
    inference_device: str | None = None
    confidence: float | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_people_count_feed(
    *,
    device_id: str,
    window_seconds: int = 5,
    provider_id: str = "local_device",
    source_name: str = "laptop_webcam",
    license: str = "internal",
    provenance: PeopleCountProvenance = PeopleCountProvenance(model_name="placeholder_people_counter"),
    quality_flag: str = "ok",
    count_people: Optional[Callable[[], int]] = None,
    record_metadata: Optional[dict[str, Any]] = None,
    source_metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Build a provider-contract shaped payload for laptop camera people counting.

    Privacy note:
    - This function does NOT store frames or video.
    - If you later integrate real camera capture, keep it in-memory and only emit counts.

    Parameters:
    - device_id: becomes record.entity_id (later maps to Observation.entity_id)
    - window_seconds: must be 5 for v1 schema
    - count_people: optional callback that returns the people count for *this* window
      (default returns 0, which is still schema-valid).
    """
    if not str(device_id or "").strip():
        raise ValueError("device_id is required")
    if int(window_seconds) != 5:
        raise ValueError("window_seconds must be 5 to match the v1 provider contract")
    if not str(provenance.model_name or "").strip():
        raise ValueError("provenance.model_name is required")

    people_count = int(count_people() if count_people is not None else 0)
    if people_count < 0:
        raise ValueError("people_count must be >= 0")

    prov: dict[str, Any] = {
        "model_name": provenance.model_name,
    }
    if provenance.model_version is not None:
        prov["model_version"] = provenance.model_version
    if provenance.inference_device is not None:
        prov["inference_device"] = provenance.inference_device
    if provenance.confidence is not None:
        prov["confidence"] = provenance.confidence

    rec: dict[str, Any] = {
        "entity_id": str(device_id),
        "timestamp": _now_iso(),
        "window_seconds": 5,
        "observed_property": "people_count",
        "value": people_count,
        "unit": "count",
        "quality_flag": str(quality_flag),
        "provenance": prov,
    }
    if record_metadata:
        rec["record_metadata"] = dict(record_metadata)

    meta = dict(source_metadata or {})
    meta.setdefault("privacy_mode", "no_media_persisted")

    return {
        "provider_id": str(provider_id),
        "source_name": str(source_name),
        "source_type": "video_camera",
        "license": str(license),
        "source_metadata": meta,
        "records": [rec],
    }

