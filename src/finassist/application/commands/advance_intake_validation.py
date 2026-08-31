"""`AdvanceIntakeValidationCommand`: invoked by `validate_intake_activity`
(`finassist.infrastructure.temporal.activities`), never directly by the API.

`SUBMITTED -> INTAKE_VALIDATION` (entering the stage, its own save -- `save()`'s optimistic
concurrency check expects exactly one version bump per call), then either `-> DOCUMENT_PROCESSING`
(product accepts the requested amount/term) or escalates to human review (it doesn't): the real
state machine only allows `DECLINED` to be reached from `AWAITING_HUMAN_REVIEW`/`ESCALATED`, never
automatically -- see `_enter_human_review.py`'s docstring. This is a coarse catalog-bounds check
(`Product.accepts`), not the real policy engine (Phase 5).
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.commands._enter_human_review import enter_human_review
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    DuplicateRequestError,
    ProductNotFoundError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicationId, TenantId

_OPERATION_NAME = "advance_intake_validation"


@dataclass(frozen=True, slots=True)
class AdvanceIntakeValidationCommand:
    tenant_id: TenantId
    application_id: ApplicationId
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class AdvanceIntakeValidationResult:
    application_id: ApplicationId
    status: ApplicationStatus
    version: int
    accepted: bool


class AdvanceIntakeValidationHandler:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def handle(
        self, command: AdvanceIntakeValidationCommand
    ) -> AdvanceIntakeValidationResult:
        async with self._uow_factory.begin(tenant_id=command.tenant_id) as uow:
            reserved = await uow.reserve_idempotency_key(
                key=command.idempotency_key, operation_name=_OPERATION_NAME
            )
            if not reserved:
                raise DuplicateRequestError(_OPERATION_NAME, command.idempotency_key)

            application = await uow.applications.get(
                tenant_id=command.tenant_id, application_id=command.application_id
            )
            if application is None:
                raise ApplicationNotFoundError(str(command.application_id))

            product = await uow.products.get(product_id=application.product_id)
            if product is None:
                raise ProductNotFoundError(str(application.product_id))

            application.transition_to(
                ApplicationStatus.INTAKE_VALIDATION,
                reason="entering automated intake validation",
                clock=self._clock,
            )
            await uow.applications.save(application)

            accepted = product.accepts(
                application.requested_amount, application.requested_term_months
            )
            if accepted:
                application.transition_to(
                    ApplicationStatus.DOCUMENT_PROCESSING,
                    reason="intake validation passed: within product catalog bounds",
                    clock=self._clock,
                )
                await uow.applications.save(application)
            else:
                await enter_human_review(
                    uow=uow,
                    application=application,
                    reason=(
                        f"intake validation flagged: product {application.product_id} catalog "
                        f"bounds do not cover amount={application.requested_amount.amount} "
                        f"term_months={application.requested_term_months} -- requires human review"
                    ),
                    clock=self._clock,
                )

            await uow.record_domain_events(application.pull_events())
            await uow.commit()

            return AdvanceIntakeValidationResult(
                application_id=application.application_id,
                status=application.status,
                version=application.version,
                accepted=accepted,
            )
