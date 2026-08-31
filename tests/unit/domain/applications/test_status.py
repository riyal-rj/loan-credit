from __future__ import annotations

from finassist.domain.applications.status import (
    ApplicationStatus,
    is_legal_transition,
    is_terminal,
)


def test_full_happy_path_pipeline_is_legal() -> None:
    pipeline = [
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
        ApplicationStatus.APPROVED,
    ]
    for source, target in zip(pipeline, pipeline[1:], strict=False):
        assert is_legal_transition(source, target), f"{source} -> {target} should be legal"


def test_terminal_statuses_have_no_outgoing_transitions() -> None:
    for terminal in (
        ApplicationStatus.APPROVED,
        ApplicationStatus.DECLINED,
        ApplicationStatus.CANCELLED,
    ):
        assert is_terminal(terminal)
        for target in ApplicationStatus:
            assert not is_legal_transition(terminal, target)


def test_cannot_skip_pipeline_steps() -> None:
    assert not is_legal_transition(ApplicationStatus.DRAFT, ApplicationStatus.APPROVED)
    assert not is_legal_transition(ApplicationStatus.SUBMITTED, ApplicationStatus.RISK_SYNTHESIS)


def test_needs_more_information_re_enters_document_processing() -> None:
    assert is_legal_transition(
        ApplicationStatus.NEEDS_MORE_INFORMATION, ApplicationStatus.DOCUMENT_PROCESSING
    )


def test_cancellation_available_from_every_non_terminal_state() -> None:
    non_terminal = [s for s in ApplicationStatus if not is_terminal(s)]
    for status in non_terminal:
        assert is_legal_transition(
            status, ApplicationStatus.CANCELLED
        ), f"{status} should allow cancellation"


def test_escalated_can_resolve_to_a_terminal_decision_or_back_to_review() -> None:
    assert is_legal_transition(ApplicationStatus.ESCALATED, ApplicationStatus.APPROVED)
    assert is_legal_transition(ApplicationStatus.ESCALATED, ApplicationStatus.DECLINED)
    assert is_legal_transition(ApplicationStatus.ESCALATED, ApplicationStatus.AWAITING_HUMAN_REVIEW)
