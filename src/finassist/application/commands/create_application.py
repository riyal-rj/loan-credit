"""`CreateApplicationCommand`: the applicant-facing entry point (`POST /applications`).

Creates both the `Applicant` and the `Application` in one transaction. Idempotent: a retried
request with the same `idempotency_key` raises `DuplicateRequestError` instead of creating a
second application (invariant §5.7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from finassist.application.ports.id_generator import IdGenerator
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.domain.applications.applicant import Applicant
from finassist.domain.applications.application import Application
from finassist.domain.applications.exceptions import (
    DuplicateRequestError,
    ProductNotFoundError,
    ProductRejectedRequestError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import (
    ApplicantId,
    ApplicationId,
    ProductId,
    TenantId,
)
from finassist.domain.shared.money import Money

_OPERATION_NAME = "create_application"


@dataclass(frozen=True, slots=True)
class CreateApplicationCommand:
    tenant_id: TenantId
    idempotency_key: str
    applicant_given_name: str
    applicant_family_name: str
    applicant_date_of_birth: date
    applicant_email: str
    product_id: ProductId
    requested_amount: Money
    requested_term_months: int


@dataclass(frozen=True, slots=True)
class CreateApplicationResult:
    application_id: ApplicationId
    applicant_id: ApplicantId
    status: ApplicationStatus
    version: int


class CreateApplicationHandler:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        id_generator: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._id_generator = id_generator
        self._clock = clock

    async def handle(self, command: CreateApplicationCommand) -> CreateApplicationResult:
        async with self._uow_factory.begin(tenant_id=command.tenant_id) as uow:
            reserved = await uow.reserve_idempotency_key(
                key=command.idempotency_key, operation_name=_OPERATION_NAME
            )
            if not reserved:
                raise DuplicateRequestError(_OPERATION_NAME, command.idempotency_key)

            product = await uow.products.get(product_id=command.product_id)
            if product is None:
                raise ProductNotFoundError(str(command.product_id))
            if not product.accepts(command.requested_amount, command.requested_term_months):
                raise ProductRejectedRequestError(
                    str(command.product_id),
                    str(command.requested_amount.amount),
                    command.requested_term_months,
                )

            applicant = Applicant(
                applicant_id=ApplicantId(self._id_generator.new_id()),
                tenant_id=command.tenant_id,
                given_name=command.applicant_given_name,
                family_name=command.applicant_family_name,
                date_of_birth=command.applicant_date_of_birth,
                email=command.applicant_email,
            )
            await uow.applicants.add(applicant)

            application = Application.create(
                application_id=ApplicationId(self._id_generator.new_id()),
                tenant_id=command.tenant_id,
                applicant_id=applicant.applicant_id,
                product=product,
                requested_amount=command.requested_amount,
                requested_term_months=command.requested_term_months,
                clock=self._clock,
            )
            await uow.applications.add(application)
            await uow.record_domain_events(application.pull_events())
            await uow.commit()

            return CreateApplicationResult(
                application_id=application.application_id,
                applicant_id=applicant.applicant_id,
                status=application.status,
                version=application.version,
            )
