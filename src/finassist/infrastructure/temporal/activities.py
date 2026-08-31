"""`ApplicationActivities`: the only place `ApplicationWorkflow` performs I/O (ADR-0002: "network,
database, random, clock ... operations belong in activities").

Each method wraps exactly one `application/commands/advance_*`/`apply_review_decision` handler.
Idempotency uses Temporal's own stable identifiers -- ``f"{workflow_id}:{activity_id}"`` -- as the
key reserved via the existing `integration.idempotency_keys` mechanism (ADR-0011: reusing it
instead of adding a parallel `governance.tool_calls` table). `activity_id` alone is *not* unique
across different workflow executions (Temporal assigns small incrementing IDs per run), so it must
always be combined with `workflow_id`, which already encodes tenant/application/version.

On a retried activity invocation (Temporal re-running an activity whose previous attempt actually
committed but was, e.g., reported lost due to a worker crash before acknowledging), the command
handler raises `DuplicateRequestError` for the reused key. That is the *expected*, successful
outcome of a retry here -- caught and translated into "re-read the current state and return it,"
never surfaced to Temporal as an activity failure.
"""

from __future__ import annotations

from temporalio import activity

from finassist.application.commands.advance_document_processing import (
    AdvanceDocumentProcessingCommand,
    AdvanceDocumentProcessingHandler,
)
from finassist.application.commands.advance_intake_validation import (
    AdvanceIntakeValidationCommand,
    AdvanceIntakeValidationHandler,
)
from finassist.application.commands.apply_review_decision import (
    ApplyReviewDecisionCommand,
    ApplyReviewDecisionHandler,
)
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.application.queries.get_application_status import (
    GetApplicationStatusHandler,
    GetApplicationStatusQuery,
)
from finassist.bootstrap.logging import get_logger
from finassist.domain.applications.exceptions import DuplicateRequestError
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.infrastructure.temporal.activity_io import (
    APPLY_REVIEW_DECISION_ACTIVITY,
    CHECK_REQUIRED_DOCUMENTS_ACTIVITY,
    VALIDATE_INTAKE_ACTIVITY,
    ActivityContext,
    ActivityStatusResult,
    ApplyReviewDecisionActivityInput,
)

logger = get_logger(__name__)


def _idempotency_key() -> str:
    info = activity.info()
    return f"{info.workflow_id}:{info.activity_id}"


class ApplicationActivities:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def _current_status(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> ActivityStatusResult:
        result = await GetApplicationStatusHandler(uow_factory=self._uow_factory).handle(
            GetApplicationStatusQuery(tenant_id=tenant_id, application_id=application_id)
        )
        return ActivityStatusResult(status=result.status.value, version=result.version)

    @activity.defn(name=VALIDATE_INTAKE_ACTIVITY)
    async def validate_intake_activity(self, ctx: ActivityContext) -> ActivityStatusResult:
        tenant_id = TenantId(ctx.tenant_id)
        application_id = ApplicationId(ctx.application_id)
        handler = AdvanceIntakeValidationHandler(uow_factory=self._uow_factory, clock=self._clock)
        try:
            result = await handler.handle(
                AdvanceIntakeValidationCommand(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    idempotency_key=_idempotency_key(),
                )
            )
            return ActivityStatusResult(status=result.status.value, version=result.version)
        except DuplicateRequestError:
            logger.info(
                "activity.validate_intake.duplicate_retry", application_id=ctx.application_id
            )
            return await self._current_status(tenant_id=tenant_id, application_id=application_id)

    @activity.defn(name=CHECK_REQUIRED_DOCUMENTS_ACTIVITY)
    async def check_required_documents_activity(
        self, ctx: ActivityContext
    ) -> ActivityStatusResult:
        tenant_id = TenantId(ctx.tenant_id)
        application_id = ApplicationId(ctx.application_id)
        handler = AdvanceDocumentProcessingHandler(
            uow_factory=self._uow_factory, clock=self._clock
        )
        try:
            result = await handler.handle(
                AdvanceDocumentProcessingCommand(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    idempotency_key=_idempotency_key(),
                )
            )
            return ActivityStatusResult(status=result.status.value, version=result.version)
        except DuplicateRequestError:
            logger.info(
                "activity.check_required_documents.duplicate_retry",
                application_id=ctx.application_id,
            )
            return await self._current_status(tenant_id=tenant_id, application_id=application_id)

    @activity.defn(name=APPLY_REVIEW_DECISION_ACTIVITY)
    async def apply_review_decision_activity(
        self, activity_input: ApplyReviewDecisionActivityInput
    ) -> ActivityStatusResult:
        tenant_id = TenantId(activity_input.tenant_id)
        application_id = ApplicationId(activity_input.application_id)
        handler = ApplyReviewDecisionHandler(uow_factory=self._uow_factory, clock=self._clock)
        try:
            result = await handler.handle(
                ApplyReviewDecisionCommand(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    idempotency_key=_idempotency_key(),
                    decision=ApplicationStatus(activity_input.decision),
                    reason=activity_input.reason,
                    reviewer_id=activity_input.reviewer_id,
                )
            )
            return ActivityStatusResult(status=result.status.value, version=result.version)
        except DuplicateRequestError:
            logger.info(
                "activity.apply_review_decision.duplicate_retry",
                application_id=activity_input.application_id,
            )
            return await self._current_status(tenant_id=tenant_id, application_id=application_id)
