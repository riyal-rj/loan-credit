from __future__ import annotations

import pytest

from finassist.application.commands.resubmit_application import (
    ResubmitApplicationCommand,
    ResubmitApplicationHandler,
)
from finassist.domain.applications.exceptions import IllegalStateTransitionError
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import TenantId, new_id

from ._fakes import FakeUnitOfWorkFactory, FakeWorkflowRunner
from ._helpers import NOW, make_product, seed_application_at


@pytest.mark.asyncio
async def test_resubmit_transitions_to_document_processing_and_starts_new_workflow() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory,
        tenant_id=tenant_id,
        product=product,
        status=ApplicationStatus.NEEDS_MORE_INFORMATION,
    )
    workflow_runner = FakeWorkflowRunner()
    handler = ResubmitApplicationHandler(
        uow_factory=factory, clock=FixedClock(NOW), workflow_runner=workflow_runner
    )

    result = await handler.handle(
        ResubmitApplicationCommand(
            tenant_id=tenant_id, application_id=application_id, idempotency_key="k1"
        )
    )

    assert result.status is ApplicationStatus.DOCUMENT_PROCESSING
    assert result.workflow_id is not None
    assert len(workflow_runner.started) == 1
    started = workflow_runner.started[0]
    assert started.workflow_id == result.workflow_id
    assert started.starting_status == ApplicationStatus.DOCUMENT_PROCESSING.value
    saved = factory.store.applications[(str(tenant_id), str(application_id))]
    assert saved.active_workflow_id == result.workflow_id


@pytest.mark.asyncio
async def test_resubmit_from_wrong_status_is_illegal() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.SUBMITTED
    )
    handler = ResubmitApplicationHandler(
        uow_factory=factory, clock=FixedClock(NOW), workflow_runner=FakeWorkflowRunner()
    )

    with pytest.raises(IllegalStateTransitionError):
        await handler.handle(
            ResubmitApplicationCommand(
                tenant_id=tenant_id, application_id=application_id, idempotency_key="k1"
            )
        )


@pytest.mark.asyncio
async def test_workflow_start_failure_does_not_fail_the_command() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory,
        tenant_id=tenant_id,
        product=product,
        status=ApplicationStatus.NEEDS_MORE_INFORMATION,
    )
    handler = ResubmitApplicationHandler(
        uow_factory=factory,
        clock=FixedClock(NOW),
        workflow_runner=FakeWorkflowRunner(fail_on_start=True),
    )

    result = await handler.handle(
        ResubmitApplicationCommand(
            tenant_id=tenant_id, application_id=application_id, idempotency_key="k1"
        )
    )

    assert result.status is ApplicationStatus.DOCUMENT_PROCESSING
