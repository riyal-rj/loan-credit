"""The application case state machine (master instruction §8, "Required application state
machine").

`ALLOWED_TRANSITIONS` is the single source of truth for legal state changes; `Application.
transition_to` (see `application.py`) is the only code path permitted to change an aggregate's
status, and it consults this table before doing so. No other module may special-case a status
transition.
"""

from __future__ import annotations

from enum import StrEnum


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INTAKE_VALIDATION = "INTAKE_VALIDATION"
    DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
    VERIFICATION = "VERIFICATION"
    POLICY_EVALUATION = "POLICY_EVALUATION"
    AFFORDABILITY_EVALUATION = "AFFORDABILITY_EVALUATION"
    FRAUD_ANALYSIS = "FRAUD_ANALYSIS"
    RISK_SYNTHESIS = "RISK_SYNTHESIS"
    AWAITING_HUMAN_REVIEW = "AWAITING_HUMAN_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {ApplicationStatus.APPROVED, ApplicationStatus.DECLINED, ApplicationStatus.CANCELLED}
)

_CANCELLABLE_FROM: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.DRAFT,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.INTAKE_VALIDATION,
        ApplicationStatus.DOCUMENT_PROCESSING,
        ApplicationStatus.VERIFICATION,
        ApplicationStatus.POLICY_EVALUATION,
        ApplicationStatus.AFFORDABILITY_EVALUATION,
        ApplicationStatus.FRAUD_ANALYSIS,
        ApplicationStatus.RISK_SYNTHESIS,
        ApplicationStatus.AWAITING_HUMAN_REVIEW,
        ApplicationStatus.NEEDS_MORE_INFORMATION,
        ApplicationStatus.ESCALATED,
    }
)

# The forward pipeline (§3/§8). Each state's automated processing, on success, advances exactly
# one step; any of these automated states may also fail forward into AWAITING_HUMAN_REVIEW
# (low confidence / exception / adverse signal, per invariant §5.10) rather than only proceeding
# linearly.
_FORWARD_PIPELINE: dict[ApplicationStatus, ApplicationStatus] = {
    ApplicationStatus.DRAFT: ApplicationStatus.SUBMITTED,
    ApplicationStatus.SUBMITTED: ApplicationStatus.INTAKE_VALIDATION,
    ApplicationStatus.INTAKE_VALIDATION: ApplicationStatus.DOCUMENT_PROCESSING,
    ApplicationStatus.DOCUMENT_PROCESSING: ApplicationStatus.VERIFICATION,
    ApplicationStatus.VERIFICATION: ApplicationStatus.POLICY_EVALUATION,
    ApplicationStatus.POLICY_EVALUATION: ApplicationStatus.AFFORDABILITY_EVALUATION,
    ApplicationStatus.AFFORDABILITY_EVALUATION: ApplicationStatus.FRAUD_ANALYSIS,
    ApplicationStatus.FRAUD_ANALYSIS: ApplicationStatus.RISK_SYNTHESIS,
    ApplicationStatus.RISK_SYNTHESIS: ApplicationStatus.AWAITING_HUMAN_REVIEW,
}

_CAN_ESCALATE_TO_HUMAN_REVIEW: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.INTAKE_VALIDATION,
        ApplicationStatus.DOCUMENT_PROCESSING,
        ApplicationStatus.VERIFICATION,
        ApplicationStatus.POLICY_EVALUATION,
        ApplicationStatus.AFFORDABILITY_EVALUATION,
        ApplicationStatus.FRAUD_ANALYSIS,
        ApplicationStatus.RISK_SYNTHESIS,
    }
)


def _build_allowed_transitions() -> dict[ApplicationStatus, frozenset[ApplicationStatus]]:
    transitions: dict[ApplicationStatus, set[ApplicationStatus]] = {
        status: set() for status in ApplicationStatus
    }

    for source, target in _FORWARD_PIPELINE.items():
        transitions[source].add(target)

    for source in _CAN_ESCALATE_TO_HUMAN_REVIEW:
        transitions[source].add(ApplicationStatus.AWAITING_HUMAN_REVIEW)

    transitions[ApplicationStatus.AWAITING_HUMAN_REVIEW].update(
        {
            ApplicationStatus.APPROVED,
            ApplicationStatus.DECLINED,
            ApplicationStatus.NEEDS_MORE_INFORMATION,
            ApplicationStatus.ESCALATED,
        }
    )
    transitions[ApplicationStatus.ESCALATED].update(
        {
            ApplicationStatus.APPROVED,
            ApplicationStatus.DECLINED,
            ApplicationStatus.AWAITING_HUMAN_REVIEW,
        }
    )
    transitions[ApplicationStatus.NEEDS_MORE_INFORMATION].add(ApplicationStatus.DOCUMENT_PROCESSING)

    for source in _CANCELLABLE_FROM:
        transitions[source].add(ApplicationStatus.CANCELLED)

    return {status: frozenset(targets) for status, targets in transitions.items()}


ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = (
    _build_allowed_transitions()
)


def is_legal_transition(source: ApplicationStatus, target: ApplicationStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[source]


def is_terminal(status: ApplicationStatus) -> bool:
    return status in TERMINAL_STATUSES
