from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from urban_platform.storage.models import AuditEvent, StoredOutput, StoredRecord, StoredRun


def now_utc_iso() -> str:
    # Avoid datetime dependency spread; callers may also supply timestamps explicitly.
    from datetime import datetime, timezone  # noqa: WPS433

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """
    Deterministic hash for payload dicts.
    - stable key ordering
    - compact separators
    """
    s = _stable_json_dumps(payload)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


class FileAirOsStore:
    """
    Simple append-only JSONL store for dev/pilot runtime.

    Files under root_dir:
    - records.jsonl
    - outputs.jsonl
    - audit_events.jsonl
    - runs.jsonl
    """

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def records_path(self) -> Path:
        return self.root_dir / "records.jsonl"

    @property
    def outputs_path(self) -> Path:
        return self.root_dir / "outputs.jsonl"

    @property
    def audit_events_path(self) -> Path:
        return self.root_dir / "audit_events.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.root_dir / "runs.jsonl"

    def _append_jsonl(self, path: Path, obj: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8") if not path.exists() else None
        with path.open("a", encoding="utf-8") as f:
            f.write(_stable_json_dumps(obj) + "\n")

    # Records
    def put_record(self, record: StoredRecord) -> StoredRecord:
        payload_hash = record.payload_hash or compute_payload_hash(record.payload)
        stored = StoredRecord(
            **{**asdict(record), "payload_hash": payload_hash},
        )
        self._append_jsonl(self.records_path, asdict(stored))
        return stored

    def get_record(self, record_id: str) -> StoredRecord | None:
        rid = str(record_id)
        for obj in _iter_jsonl(self.records_path):
            if str(obj.get("record_id") or "") == rid:
                return StoredRecord(**obj)  # type: ignore[arg-type]
        return None

    def list_records(
        self, *, deployment_id: str | None = None, contract_key: str | None = None
    ) -> list[StoredRecord]:
        out: list[StoredRecord] = []
        for obj in _iter_jsonl(self.records_path):
            if deployment_id and str(obj.get("deployment_id") or "") != deployment_id:
                continue
            if contract_key and str(obj.get("contract_key") or "") != contract_key:
                continue
            try:
                out.append(StoredRecord(**obj))  # type: ignore[arg-type]
            except TypeError:
                continue
        return out

    # Outputs
    def put_output(self, output: StoredOutput) -> StoredOutput:
        payload_hash = output.payload_hash or compute_payload_hash(output.payload)
        stored = StoredOutput(
            **{**asdict(output), "payload_hash": payload_hash},
        )
        self._append_jsonl(self.outputs_path, asdict(stored))
        return stored

    def get_output(self, output_id: str) -> StoredOutput | None:
        oid = str(output_id)
        for obj in _iter_jsonl(self.outputs_path):
            if str(obj.get("output_id") or "") == oid:
                return StoredOutput(**obj)  # type: ignore[arg-type]
        return None

    def list_outputs(
        self, *, deployment_id: str | None = None, contract_key: str | None = None
    ) -> list[StoredOutput]:
        out: list[StoredOutput] = []
        for obj in _iter_jsonl(self.outputs_path):
            if deployment_id and str(obj.get("deployment_id") or "") != deployment_id:
                continue
            if contract_key and str(obj.get("contract_key") or "") != contract_key:
                continue
            try:
                out.append(StoredOutput(**obj))  # type: ignore[arg-type]
            except TypeError:
                continue
        return out

    # Audit
    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        self._append_jsonl(self.audit_events_path, asdict(event))
        return event

    def list_audit_events(self, *, deployment_id: str | None = None) -> list[AuditEvent]:
        out: list[AuditEvent] = []
        for obj in _iter_jsonl(self.audit_events_path):
            if deployment_id and str(obj.get("deployment_id") or "") != deployment_id:
                continue
            try:
                out.append(AuditEvent(**obj))  # type: ignore[arg-type]
            except TypeError:
                continue
        return out

    # Runs
    def put_run(self, run: StoredRun) -> StoredRun:
        self._append_jsonl(self.runs_path, asdict(run))
        return run

    def get_run(self, run_id: str) -> StoredRun | None:
        rid = str(run_id)
        latest: StoredRun | None = None
        for obj in _iter_jsonl(self.runs_path):
            if str(obj.get("run_id") or "") != rid:
                continue
            try:
                latest = StoredRun(**obj)  # type: ignore[arg-type]
            except TypeError:
                continue
        return latest

    def list_runs(
        self,
        *,
        deployment_id: str | None = None,
        application_id: str | None = None,
        status: str | None = None,
    ) -> list[StoredRun]:
        by_id: dict[str, StoredRun] = {}
        for obj in _iter_jsonl(self.runs_path):
            try:
                r = StoredRun(**obj)  # type: ignore[arg-type]
            except TypeError:
                continue
            by_id[str(r.run_id)] = r  # append-only; last write wins

        out: list[StoredRun] = []
        for r in by_id.values():
            if deployment_id and r.deployment_id != deployment_id:
                continue
            if application_id and r.application_id != application_id:
                continue
            if status and r.status != status:
                continue
            out.append(r)

        out.sort(key=lambda x: (x.started_at or ""), reverse=True)
        return out

