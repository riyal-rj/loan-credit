"""`ApplicationWorkflow`: the durable macro-orchestrator for one application version
(docs/adr/0002, docs/adr/0011).

Pure control flow only -- every network/database/clock call lives in `activities.py`
(`ApplicationActivities`), never here, so this class stays deterministic and replay-safe
(ADR-0002). Activities are called by their registered *name* (`workflow.execute_activity`), not by
importing `ApplicationActivities` and using `execute_activity_method`: that class transitively
imports SQLAlchemy, `uuid`-based ID generation, and the rest of the application/infrastructure
stack, and Temporal's workflow sandbox re-validates this module's *entire* import graph under
restricted builtins at worker-start time -- pulling that graph in here fails validation
(``random.getrandbits restricted``) even though none of it ever runs inside the workflow. Only
`activity_io.py` (plain dataclasses + name constants, no heavy imports) is safe to import here.

Two entry points share one workflow definition:

- ``starting_status=SUBMITTED``: the first submission. Runs intake validation, then (unless intake
  itself already escalated) falls through to document processing.
- ``starting_status=DOCUMENT_PROCESSING``: a resubmission after `NEEDS_MORE_INFORMATION`. Intake
  was already validated by the *prior* (closed) workflow execution, so this one starts directly at
  the document-presence check.

Both `validate_intake_activity` and `check_required_documents_activity` always end at
`AWAITING_HUMAN_REVIEW`: the real state machine (Phase 1B, exhaustively property-tested) only
allows `DECLINED`/`NEEDS_MORE_INFORMATION` to be reached *from* human review, never automatically,
which is master instruction invariant §5.1 holding at the transition-legality level. So there is no
"declined"/"needs more info" early-exit branch here to begin with -- every path converges on
waiting for a human decision, with the *reason* the case reached review (out-of-bounds request, no
documents, or the every-case Phase 5/6-not-implemented-yet escalation) recorded on the
`AWAITING_HUMAN_REVIEW` transition itself (docs/adr/0011).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from finassist.domain.applications.status import ApplicationStatus

from finassist.infrastructure.temporal.activity_io import (
    APPLY_REVIEW_DECISION_ACTIVITY,
    CHECK_REQUIRED_DOCUMENTS_ACTIVITY,
    VALIDATE_INTAKE_ACTIVITY,
    ActivityContext,
    ActivityStatusResult,
    ApplyReviewDecisionActivityInput,
)

_ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(seconds=30)
_ACTIVITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
    non_retryable_error_types=[
        "ApplicationNotFoundError",
        "ProductNotFoundError",
        "InvalidApplicationDataError",
        "IllegalStateTransitionError",
    ],
)


@dataclass(frozen=True, slots=True)
class ApplicationWorkflowInput:
    tenant_id: str
    application_id: str
    version: int
    starting_status: str
    human_review_sla_seconds: float


@dataclass(frozen=True, slots=True)
class ApplicationWorkflowResult:
    final_status: str
    final_version: int


@dataclass(frozen=True, slots=True)
class ReviewDecisionSignal:
    decision: str
    reason: str
    reviewer_id: str


_SLA_TIMEOUT_REASON = "human review SLA timeout: no decision recorded within the review window"


@workflow.defn(name="ApplicationWorkflow")
class ApplicationWorkflow:
    def __init__(self) -> None:
        self._decision: ReviewDecisionSignal | None = None

    @workflow.signal(name="submit_review_decision")
    async def submit_review_decision(self, signal: ReviewDecisionSignal) -> None:
        self._decision = signal

    @workflow.run
    async def run(self, workflow_input: ApplicationWorkflowInput) -> ApplicationWorkflowResult:
        ctx = ActivityContext(
            tenant_id=workflow_input.tenant_id, application_id=workflow_input.application_id
        )

        reached_human_review = False
        if workflow_input.starting_status == ApplicationStatus.SUBMITTED.value:
            intake_result = await workflow.execute_activity(
                VALIDATE_INTAKE_ACTIVITY,
                ctx,
                result_type=ActivityStatusResult,
                start_to_close_timeout=_ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            reached_human_review = (
                intake_result.status == ApplicationStatus.AWAITING_HUMAN_REVIEW.value
            )
        elif workflow_input.starting_status != ApplicationStatus.DOCUMENT_PROCESSING.value:
            raise ValueError(
                f"ApplicationWorkflow does not support starting_status="
                f"{workflow_input.starting_status!r}"
            )

        if not reached_human_review:
            # check_required_documents_activity always ends at AWAITING_HUMAN_REVIEW itself (with
            # or without an intermediate VERIFICATION hop) -- see its module docstring.
            await workflow.execute_activity(
                CHECK_REQUIRED_DOCUMENTS_ACTIVITY,
                ctx,
                result_type=ActivityStatusResult,
                start_to_close_timeout=_ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )

        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(seconds=workflow_input.human_review_sla_seconds),
            )
            if self._decision is None:  # pragma: no cover - wait_condition guarantees this
                raise RuntimeError("wait_condition returned with no decision signal recorded")
            decision = self._decision
        except TimeoutError:
            decision = ReviewDecisionSignal(
                decision=ApplicationStatus.ESCALATED.value,
                reason=_SLA_TIMEOUT_REASON,
                reviewer_id="",
            )

        final_result = await workflow.execute_activity(
            APPLY_REVIEW_DECISION_ACTIVITY,
            ApplyReviewDecisionActivityInput(
                tenant_id=workflow_input.tenant_id,
                application_id=workflow_input.application_id,
                decision=decision.decision,
                reason=decision.reason,
                reviewer_id=decision.reviewer_id or None,
            ),
            result_type=ActivityStatusResult,
            start_to_close_timeout=_ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        return ApplicationWorkflowResult(
            final_status=final_result.status, final_version=final_result.version
        )
