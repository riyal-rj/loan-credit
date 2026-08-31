"""SQLAlchemy-backed implementations of the `ApplicationRepository`/`ApplicantRepository` ports.

Each `add`/`save` call also writes one `ApplicationVersionRow` snapshot (docs/adr/0009), all
within the caller's existing session/transaction -- these classes never call `session.commit()`
themselves; that is `SqlAlchemyUnitOfWork`'s responsibility.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.application.ports.applicant_repository import ApplicantRepository
from finassist.application.ports.application_repository import ApplicationRepository
from finassist.domain.applications.applicant import Applicant
from finassist.domain.applications.application import Application
from finassist.domain.applications.exceptions import ConcurrencyConflictError
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicantId, ApplicationId, ProductId, TenantId
from finassist.domain.shared.money import Money
from finassist.infrastructure.postgres.orm_models import (
    ApplicantRow,
    ApplicationRow,
    ApplicationVersionRow,
)


def _application_to_row(application: Application) -> ApplicationRow:
    return ApplicationRow(
        application_id=str(application.application_id),
        tenant_id=str(application.tenant_id),
        applicant_id=str(application.applicant_id),
        product_id=str(application.product_id),
        requested_amount=application.requested_amount.amount,
        currency=application.requested_amount.currency,
        requested_term_months=application.requested_term_months,
        status=application.status.value,
        version=application.version,
        created_at=application.created_at,
        updated_at=application.updated_at,
        active_workflow_id=application.active_workflow_id,
    )


def _row_to_application(row: ApplicationRow) -> Application:
    return Application(
        application_id=ApplicationId(row.application_id),
        tenant_id=TenantId(row.tenant_id),
        applicant_id=ApplicantId(row.applicant_id),
        product_id=ProductId(row.product_id),
        requested_amount=Money(row.requested_amount, row.currency),
        requested_term_months=row.requested_term_months,
        status=ApplicationStatus(row.status),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        active_workflow_id=row.active_workflow_id,
    )


def _version_snapshot_row(application: Application, snapshot_id: str) -> ApplicationVersionRow:
    return ApplicationVersionRow(
        id=snapshot_id,
        application_id=str(application.application_id),
        tenant_id=str(application.tenant_id),
        version=application.version,
        status=application.status.value,
        requested_amount=application.requested_amount.amount,
        currency=application.requested_amount.currency,
        requested_term_months=application.requested_term_months,
        applicant_id=str(application.applicant_id),
        product_id=str(application.product_id),
        recorded_at=application.updated_at,
    )


class SqlAlchemyApplicationRepository(ApplicationRepository):
    def __init__(self, session: AsyncSession, new_id: Callable[[], str]) -> None:
        self._session = session
        self._new_id = new_id

    async def get(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> Application | None:
        row = await self._session.get(ApplicationRow, str(application_id))
        if row is None or row.tenant_id != str(tenant_id):
            return None
        return _row_to_application(row)

    async def add(self, application: Application) -> None:
        self._session.add(_application_to_row(application))
        self._session.add(_version_snapshot_row(application, self._new_id()))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ValueError(f"application {application.application_id} already exists") from exc

    async def save(self, application: Application) -> None:
        result = await self._session.execute(
            select(ApplicationRow).where(
                ApplicationRow.application_id == str(application.application_id)
            )
        )
        existing = result.scalar_one_or_none()
        expected_prior_version = application.version - 1
        if existing is None or existing.version != expected_prior_version:
            actual_version = existing.version if existing is not None else 0
            raise ConcurrencyConflictError(
                str(application.application_id), expected_prior_version, actual_version
            )

        existing.status = application.status.value
        existing.version = application.version
        existing.updated_at = application.updated_at
        existing.requested_amount = application.requested_amount.amount
        existing.requested_term_months = application.requested_term_months
        existing.active_workflow_id = application.active_workflow_id
        self._session.add(_version_snapshot_row(application, self._new_id()))
        await self._session.flush()


class SqlAlchemyApplicantRepository(ApplicantRepository):
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def add(self, applicant: Applicant) -> None:
        self._session.add(
            ApplicantRow(
                applicant_id=str(applicant.applicant_id),
                tenant_id=str(applicant.tenant_id),
                given_name=applicant.given_name,
                family_name=applicant.family_name,
                date_of_birth=applicant.date_of_birth,
                email=applicant.email,
                created_at=self._clock.now(),
            )
        )
        await self._session.flush()

    async def get(self, *, tenant_id: TenantId, applicant_id: ApplicantId) -> Applicant | None:
        row = await self._session.get(ApplicantRow, str(applicant_id))
        if row is None or row.tenant_id != str(tenant_id):
            return None
        return Applicant(
            applicant_id=ApplicantId(row.applicant_id),
            tenant_id=TenantId(row.tenant_id),
            given_name=row.given_name,
            family_name=row.family_name,
            date_of_birth=row.date_of_birth,
            email=row.email,
        )
