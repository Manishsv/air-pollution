from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class BuilderRegistration:
    """
    Allowlisted application builder registration.

    Notes:
    - This registry is explicit Python, not YAML-driven.
    - It must never resolve arbitrary module paths from deployment registries.
    - Callables are imported lazily in `get_builder()` to keep imports small and avoid cycles.
    """

    application_id: str
    domain_id: str
    description: str
    output_contract_keys: tuple[str, ...]
    callable_name: str
    safety_notes: tuple[str, ...]

    def resolve_callable(self) -> Callable[..., Any]:
        # Explicit resolution only (no dynamic import from YAML).
        if self.application_id == "flood_risk_dashboard_payload":
            from airos.apps.flood.dashboard_payload import (  # noqa: WPS433
                build_flood_risk_dashboard_payload,
            )

            return build_flood_risk_dashboard_payload

        if self.application_id == "flood_decision_packets":
            from airos.apps.flood.decision_packets import (  # noqa: WPS433
                build_flood_decision_packets,
            )

            return build_flood_decision_packets

        if self.application_id == "flood_field_verification_tasks":
            from airos.apps.flood.field_tasks import (  # noqa: WPS433
                build_flood_field_verification_tasks,
            )

            return build_flood_field_verification_tasks

        if self.application_id == "program_reporting_review_packet":
            from airos.apps.program_reporting.review_packets import (  # noqa: WPS433
                build_fund_release_review_packet,
            )

            return build_fund_release_review_packet

        # Should never happen if registry and lookup are consistent.
        raise KeyError(f"Builder callable not mapped for application_id: {self.application_id}")


_BUILDERS: tuple[BuilderRegistration, ...] = (
    BuilderRegistration(
        application_id="flood_risk_dashboard_payload",
        domain_id="flood_risk",
        description="Builds the flood risk dashboard payload (fixture demo).",
        output_contract_keys=("consumer_flood_risk_dashboard",),
        callable_name="airos.apps.flood.dashboard_payload.build_flood_risk_dashboard_payload",
        safety_notes=(
            "Decision support only; no emergency orders.",
            "Fixture/demo data paths are allowlisted in the deployment runner.",
            "UI must remain presentation-only; do not add domain logic in Streamlit.",
        ),
    ),
    BuilderRegistration(
        application_id="flood_decision_packets",
        domain_id="flood_risk",
        description="Builds flood decision packets (fixture demo).",
        output_contract_keys=("consumer_flood_decision_packet",),
        callable_name="airos.apps.flood.decision_packets.build_flood_decision_packets",
        safety_notes=(
            "Decision support only; requires human review.",
            "No operational enforcement, dispatch, or emergency orders from packets.",
        ),
    ),
    BuilderRegistration(
        application_id="flood_field_verification_tasks",
        domain_id="flood_risk",
        description="Builds flood field verification tasks from decision packets (fixture demo).",
        output_contract_keys=("consumer_field_verification_task",),
        callable_name="airos.apps.flood.field_tasks.build_flood_field_verification_tasks",
        safety_notes=(
            "Verification planning only; not an enforcement task.",
            "Tasks do not authorize action; they support human verification workflows.",
        ),
    ),
    BuilderRegistration(
        application_id="program_reporting_review_packet",
        domain_id="program_reporting",
        description="Builds Phase 1 fund-release review packets from city submissions (fixture demo).",
        output_contract_keys=("consumer_fund_release_review_packet",),
        callable_name="airos.apps.program_reporting.review_packets.build_fund_release_review_packet",
        safety_notes=(
            "Review support only; does not authorize fund release.",
            "No finance system integration; self-reported aggregates only in Phase 1.",
            "Blocked uses must remain explicit (no penalties/enforcement/blacklisting automation).",
        ),
    ),
)


def list_builders() -> list[BuilderRegistration]:
    return list(_BUILDERS)


def has_builder(application_id: str) -> bool:
    aid = str(application_id or "").strip()
    return any(b.application_id == aid for b in _BUILDERS)


def get_builder(application_id: str) -> BuilderRegistration:
    aid = str(application_id or "").strip()
    for b in _BUILDERS:
        if b.application_id == aid:
            return b
    known = ", ".join(sorted(b.application_id for b in _BUILDERS))
    raise KeyError(f"Unknown application_id {aid!r}. Known allowlisted builders: {known}")

