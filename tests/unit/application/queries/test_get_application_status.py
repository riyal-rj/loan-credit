from __future__ import annotations

import pytest

from finassist.application.queries.get_application_status import (
    GetApplicationStatusHandler,
    GetApplicationStatusQuery,
)
from finassist.domain.applications.exceptions import ApplicationNotFoundError
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.identifiers import ApplicationId, TenantId, new_id

from ..commands._fakes import FakeUnitOfWorkFactory
from ..commands._helpers import make_product, seed_application_at


@pytest.mark.asyncio
async def test_returns_current_status_and_active_workflow_id() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.SUBMITTED
    )
    # Directly mutate the stored aggregate rather than going through `save()`: attaching a
    # workflow ID with no accompanying state transition doesn't match `save()`'s "exactly one
    # version bump since load" optimistic-concurrency contract, which every real caller
    # (`submit_application`/`resubmit_application`) always satisfies by transitioning first.
    factory.store.applications[(str(tenant_id), str(application_id))].active_workflow_id = (
        "application:t:a:v2"
    )

    result = await GetApplicationStatusHandler(uow_factory=factory).handle(
        GetApplicationStatusQuery(tenant_id=tenant_id, application_id=application_id)
    )

    assert result.status is ApplicationStatus.SUBMITTED
    assert result.active_workflow_id == "application:t:a:v2"


@pytest.mark.asyncio
async def test_unknown_application_raises() -> None:
    factory = FakeUnitOfWorkFactory()
    with pytest.raises(ApplicationNotFoundError):
        await GetApplicationStatusHandler(uow_factory=factory).handle(
            GetApplicationStatusQuery(
                tenant_id=TenantId(new_id()), application_id=ApplicationId(new_id())
            )
        )
