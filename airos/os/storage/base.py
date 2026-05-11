from __future__ import annotations

from typing import Protocol

from airos.os.storage.models import AuditEvent, StoredOutput, StoredRecord, StoredRun, StoredValidationReceipt


class AirOsStore(Protocol):
    # Records (ingested inputs)
    def put_record(self, record: StoredRecord) -> StoredRecord: ...

    def get_record(self, record_id: str) -> StoredRecord | None: ...

    def list_records(
        self, *, deployment_id: str | None = None, contract_key: str | None = None
    ) -> list[StoredRecord]: ...

    # Outputs (generated payloads)
    def put_output(self, output: StoredOutput) -> StoredOutput: ...

    def get_output(self, output_id: str) -> StoredOutput | None: ...

    def list_outputs(
        self, *, deployment_id: str | None = None, contract_key: str | None = None
    ) -> list[StoredOutput]: ...

    # Audit
    def append_audit_event(self, event: AuditEvent) -> AuditEvent: ...

    def list_audit_events(self, *, deployment_id: str | None = None) -> list[AuditEvent]: ...

    # Runs (application execution metadata)
    def put_run(self, run: StoredRun) -> StoredRun: ...

    def get_run(self, run_id: str) -> StoredRun | None: ...

    def list_runs(
        self,
        *,
        deployment_id: str | None = None,
        application_id: str | None = None,
        status: str | None = None,
    ) -> list[StoredRun]: ...

    # Validation receipts
    def put_validation_receipt(
        self, receipt: StoredValidationReceipt
    ) -> StoredValidationReceipt: ...

    def get_validation_receipt(self, receipt_id: str) -> StoredValidationReceipt | None: ...

    def list_validation_receipts(
        self,
        *,
        deployment_id: str | None = None,
        contract_key: str | None = None,
        status: str | None = None,
        validation_target_type: str | None = None,
    ) -> list[StoredValidationReceipt]: ...

