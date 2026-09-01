"""`ApplicationActivities`: the only place `ApplicationWorkflow` performs I/O (ADR-0002: "network,
database, random, clock ... operations belong in activities").

Each method wraps exactly one `application/commands/advance_*`/`process_document`/
`verify_application_facts`/`enter_human_review`/`apply_review_decision` handler. Idempotency uses
Temporal's own stable identifiers -- ``f"{workflow_id}:{activity_id}"`` -- as the key reserved via
the existing `integration.idempotency_keys` mechanism (ADR-0011: reusing it instead of adding a
parallel `governance.tool_calls` table). `activity_id` alone is *not* unique across different
workflow executions (Temporal assigns small incrementing IDs per run), so it must always be
combined with `workflow_id`, which already encodes tenant/application/version.
`extract_document_facts_activity` processes potentially several documents in one activity
invocation, so each document's idempotency key is further suffixed with its `document_id`.

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
from finassist.application.commands.enter_human_review import (
    EnterHumanReviewCommand,
    EnterHumanReviewHandler,
)
from finassist.application.commands.process_document import (
    ProcessDocumentCommand,
    ProcessDocumentHandler,
)
from finassist.application.commands.verify_application_facts import (
    VerifyApplicationFactsCommand,
    VerifyApplicationFactsHandler,
    build_verification_summary,
)
from finassist.application.ports.document_extractor import DocumentExtractor
from finassist.application.ports.document_parser import DocumentParser
from finassist.application.ports.external_verification import (
    BureauClient,
    CoreBankingClient,
    EmployerVerifier,
    KycVerifier,
)
from finassist.application.ports.id_generator import IdGenerator
from finassist.application.ports.object_store import ObjectStore
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
    ENTER_HUMAN_REVIEW_ACTIVITY,
    EXTRACT_DOCUMENT_FACTS_ACTIVITY,
    VALIDATE_INTAKE_ACTIVITY,
    VERIFY_FACTS_ACTIVITY,
    ActivityContext,
    ActivityStatusResult,
    ApplyReviewDecisionActivityInput,
    EnterHumanReviewActivityInput,
    ExtractDocumentFactsActivityResult,
    VerifyFactsActivityResult,
)

logger = get_logger(__name__)


def _idempotency_key(*, suffix: str | None = None) -> str:
    info = activity.info()
    key = f"{info.workflow_id}:{info.activity_id}"
    return f"{key}:{suffix}" if suffix is not None else key


class ApplicationActivities:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        id_generator: IdGenerator,
        object_store: ObjectStore,
        document_parser: DocumentParser,
        document_extractor: DocumentExtractor,
        kyc_verifier: KycVerifier,
        employer_verifier: EmployerVerifier,
        bureau_client: BureauClient,
        core_banking_client: CoreBankingClient,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._id_generator = id_generator
        self._object_store = object_store
        self._document_parser = document_parser
        self._document_extractor = document_extractor
        self._kyc_verifier = kyc_verifier
        self._employer_verifier = employer_verifier
        self._bureau_client = bureau_client
        self._core_banking_client = core_banking_client

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

    @activity.defn(name=EXTRACT_DOCUMENT_FACTS_ACTIVITY)
    async def extract_document_facts_activity(
        self, ctx: ActivityContext
    ) -> ExtractDocumentFactsActivityResult:
        tenant_id = TenantId(ctx.tenant_id)
        application_id = ApplicationId(ctx.application_id)
        handler = ProcessDocumentHandler(
            uow_factory=self._uow_factory,
            object_store=self._object_store,
            document_parser=self._document_parser,
            document_extractor=self._document_extractor,
            id_generator=self._id_generator,
            clock=self._clock,
        )
        async with self._uow_factory.begin(tenant_id=tenant_id) as uow:
            documents = await uow.documents.list_for_application(
                tenant_id=tenant_id, application_id=application_id
            )

        fact_count = 0
        for document in documents:
            try:
                result = await handler.handle(
                    ProcessDocumentCommand(
                        tenant_id=tenant_id,
                        application_id=application_id,
                        document_id=document.document_id,
                        idempotency_key=_idempotency_key(suffix=document.document_id),
                    )
                )
                fact_count += result.fact_count
                if result.extraction_error is not None:
                    logger.warning(
                        "activity.extract_document_facts.extraction_error",
                        document_id=document.document_id,
                        error=result.extraction_error,
                    )
            except DuplicateRequestError:
                logger.info(
                    "activity.extract_document_facts.duplicate_retry",
                    document_id=document.document_id,
                )

        return ExtractDocumentFactsActivityResult(
            document_count=len(documents), fact_count=fact_count
        )

    @activity.defn(name=VERIFY_FACTS_ACTIVITY)
    async def verify_facts_activity(self, ctx: ActivityContext) -> VerifyFactsActivityResult:
        tenant_id = TenantId(ctx.tenant_id)
        application_id = ApplicationId(ctx.application_id)
        handler = VerifyApplicationFactsHandler(
            uow_factory=self._uow_factory,
            kyc_verifier=self._kyc_verifier,
            employer_verifier=self._employer_verifier,
            bureau_client=self._bureau_client,
            core_banking_client=self._core_banking_client,
            id_generator=self._id_generator,
            clock=self._clock,
        )
        try:
            result = await handler.handle(
                VerifyApplicationFactsCommand(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    idempotency_key=_idempotency_key(),
                )
            )
            return VerifyFactsActivityResult(
                contradiction_count=result.contradiction_count, summary=result.summary
            )
        except DuplicateRequestError:
            logger.info(
                "activity.verify_facts.duplicate_retry", application_id=ctx.application_id
            )
            async with self._uow_factory.begin(tenant_id=tenant_id) as uow:
                checks = await uow.verification.get_checks_for_application(
                    tenant_id=tenant_id, application_id=application_id
                )
            contradiction_count = sum(
                1 for check in checks if check.verdict.value == "CONTRADICTED"
            )
            return VerifyFactsActivityResult(
                contradiction_count=contradiction_count,
                summary=build_verification_summary(checks),
            )

    @activity.defn(name=ENTER_HUMAN_REVIEW_ACTIVITY)
    async def enter_human_review_activity(
        self, activity_input: EnterHumanReviewActivityInput
    ) -> ActivityStatusResult:
        tenant_id = TenantId(activity_input.tenant_id)
        application_id = ApplicationId(activity_input.application_id)
        handler = EnterHumanReviewHandler(uow_factory=self._uow_factory, clock=self._clock)
        try:
            result = await handler.handle(
                EnterHumanReviewCommand(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    idempotency_key=_idempotency_key(),
                    reason=activity_input.reason,
                )
            )
            return ActivityStatusResult(status=result.status.value, version=result.version)
        except DuplicateRequestError:
            logger.info(
                "activity.enter_human_review.duplicate_retry",
                application_id=activity_input.application_id,
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
