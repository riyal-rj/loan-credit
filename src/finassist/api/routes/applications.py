"""`/applications` routes -- the first HTTP surface for the `applications` bounded context
(create/submit existed as command handlers since Phase 1B with no route; Phase 3 wires them up
alongside the new resubmit/document-upload/status/review-decision endpoints, per master
instruction §11's minimum API list and §25's Phase 3 scope).

Each handler is a thin translation: parse the Pydantic request, build the command, call the
already-tested application-layer handler, translate the result. No business logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status

from finassist.api.dependencies.tenant import get_tenant_id
from finassist.api.schemas.applications import (
    ApplicationStatusResponse,
    CreateApplicationRequest,
    CreateApplicationResponse,
    ResubmitApplicationResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    SubmitApplicationResponse,
    UploadDocumentResponse,
)
from finassist.application.commands.create_application import (
    CreateApplicationCommand,
    CreateApplicationHandler,
)
from finassist.application.commands.resubmit_application import (
    ResubmitApplicationCommand,
    ResubmitApplicationHandler,
)
from finassist.application.commands.submit_application import (
    SubmitApplicationCommand,
    SubmitApplicationHandler,
)
from finassist.application.commands.upload_document import (
    UploadDocumentCommand,
    UploadDocumentHandler,
)
from finassist.application.queries.get_application_status import (
    GetApplicationStatusHandler,
    GetApplicationStatusQuery,
)
from finassist.bootstrap.container import Container
from finassist.domain.applications.exceptions import (
    InvalidApplicationDataError,
    NoActiveWorkflowError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.identifiers import ApplicationId, ProductId, TenantId
from finassist.domain.shared.money import Money

_REVIEW_DECISIONS = frozenset(
    {
        ApplicationStatus.APPROVED.value,
        ApplicationStatus.DECLINED.value,
        ApplicationStatus.NEEDS_MORE_INFORMATION.value,
        ApplicationStatus.ESCALATED.value,
    }
)


def build_applications_router(container: Container) -> APIRouter:
    router = APIRouter(tags=["applications"])

    @router.post(
        "/applications",
        response_model=CreateApplicationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_application(
        body: CreateApplicationRequest,
        tenant_id: TenantId = Depends(get_tenant_id),
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
    ) -> CreateApplicationResponse:
        handler = CreateApplicationHandler(
            uow_factory=container.uow_factory,
            id_generator=container.id_generator,
            clock=container.clock,
        )
        result = await handler.handle(
            CreateApplicationCommand(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                applicant_given_name=body.applicant_given_name,
                applicant_family_name=body.applicant_family_name,
                applicant_date_of_birth=body.applicant_date_of_birth,
                applicant_email=body.applicant_email,
                product_id=ProductId(body.product_id),
                requested_amount=Money.of(body.requested_amount, body.currency),
                requested_term_months=body.requested_term_months,
            )
        )
        return CreateApplicationResponse(
            application_id=str(result.application_id),
            applicant_id=str(result.applicant_id),
            status=result.status.value,
            version=result.version,
        )

    @router.post("/applications/{application_id}/submit", response_model=SubmitApplicationResponse)
    async def submit_application(
        application_id: str,
        tenant_id: TenantId = Depends(get_tenant_id),
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
    ) -> SubmitApplicationResponse:
        handler = SubmitApplicationHandler(
            uow_factory=container.uow_factory,
            clock=container.clock,
            workflow_runner=container.workflow_runner,
        )
        result = await handler.handle(
            SubmitApplicationCommand(
                tenant_id=tenant_id,
                application_id=ApplicationId(application_id),
                idempotency_key=idempotency_key,
            )
        )
        return SubmitApplicationResponse(
            application_id=str(result.application_id),
            status=result.status.value,
            version=result.version,
            workflow_id=result.workflow_id,
        )

    @router.post(
        "/applications/{application_id}/resubmit", response_model=ResubmitApplicationResponse
    )
    async def resubmit_application(
        application_id: str,
        tenant_id: TenantId = Depends(get_tenant_id),
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
    ) -> ResubmitApplicationResponse:
        handler = ResubmitApplicationHandler(
            uow_factory=container.uow_factory,
            clock=container.clock,
            workflow_runner=container.workflow_runner,
        )
        result = await handler.handle(
            ResubmitApplicationCommand(
                tenant_id=tenant_id,
                application_id=ApplicationId(application_id),
                idempotency_key=idempotency_key,
            )
        )
        return ResubmitApplicationResponse(
            application_id=str(result.application_id),
            status=result.status.value,
            version=result.version,
            workflow_id=result.workflow_id,
        )

    @router.post(
        "/applications/{application_id}/documents",
        response_model=UploadDocumentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_document(
        application_id: str,
        document_type: str = Form(...),
        file: UploadFile = File(...),
        tenant_id: TenantId = Depends(get_tenant_id),
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
    ) -> UploadDocumentResponse:
        data = await file.read()
        handler = UploadDocumentHandler(
            uow_factory=container.uow_factory,
            object_store=container.object_store,
            id_generator=container.id_generator,
            clock=container.clock,
        )
        result = await handler.handle(
            UploadDocumentCommand(
                tenant_id=tenant_id,
                application_id=ApplicationId(application_id),
                idempotency_key=idempotency_key,
                document_type=document_type,
                filename=file.filename or "document",
                content_type=file.content_type or "application/octet-stream",
                data=data,
            )
        )
        return UploadDocumentResponse(
            document_id=result.document_id,
            application_id=str(result.application_id),
            object_key=result.object_key,
            checksum_sha256=result.checksum_sha256,
        )

    @router.get("/applications/{application_id}", response_model=ApplicationStatusResponse)
    async def get_application_status(
        application_id: str, tenant_id: TenantId = Depends(get_tenant_id)
    ) -> ApplicationStatusResponse:
        handler = GetApplicationStatusHandler(uow_factory=container.uow_factory)
        result = await handler.handle(
            GetApplicationStatusQuery(
                tenant_id=tenant_id, application_id=ApplicationId(application_id)
            )
        )
        return ApplicationStatusResponse(
            application_id=str(result.application_id),
            status=result.status.value,
            version=result.version,
            active_workflow_id=result.active_workflow_id,
        )

    @router.post(
        "/internal/applications/{application_id}/review-decisions",
        response_model=ReviewDecisionResponse,
    )
    async def submit_review_decision(
        application_id: str,
        body: ReviewDecisionRequest,
        tenant_id: TenantId = Depends(get_tenant_id),
    ) -> ReviewDecisionResponse:
        """Phase-3 reviewer-queue stopgap (docs/adr/0011) -- signals the running workflow; the
        workflow's own activity is what actually applies the decision (ADR-0002). Phase 7 replaces
        this endpoint with the real reviewer UI/API (assignment, claim, SLA, segregation of
        duties); it does not replace the underlying signal mechanism."""
        if body.decision not in _REVIEW_DECISIONS:
            raise InvalidApplicationDataError(
                f"decision {body.decision!r} must be one of {sorted(_REVIEW_DECISIONS)}"
            )
        status_handler = GetApplicationStatusHandler(uow_factory=container.uow_factory)
        current = await status_handler.handle(
            GetApplicationStatusQuery(
                tenant_id=tenant_id, application_id=ApplicationId(application_id)
            )
        )
        if current.active_workflow_id is None:
            raise NoActiveWorkflowError(application_id)

        await container.workflow_runner.signal_review_decision(
            workflow_id=current.active_workflow_id,
            decision=body.decision,
            reason=body.reason,
            reviewer_id=body.reviewer_id,
        )
        return ReviewDecisionResponse(
            application_id=application_id,
            workflow_id=current.active_workflow_id,
            decision=body.decision,
        )

    return router
