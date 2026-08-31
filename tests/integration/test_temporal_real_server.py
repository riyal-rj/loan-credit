"""One end-to-end test against a *real* local Temporal server (not the time-skipping test
double `tests/workflow/` uses) with activities running against real PostgreSQL -- this repo's
established "caught real bugs by running against real dependencies" practice (Phases 1B/2)
applied to the Temporal/Kafka infrastructure adapters themselves (`TemporalWorkflowRunner`,
`build_worker`), which `tests/workflow/test_application_workflow.py` exercises only through the
in-memory fake unit-of-work.

Downloads/launches `temporal server start-dev` via the SDK's own test-server management (the same
mechanism `docker compose`'s `temporal` service uses, docs/adr/0011) -- no Docker container
needed for the server itself, only a free local TCP port.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.testing import WorkflowEnvironment

from finassist.application.commands.create_application import (
    CreateApplicationCommand,
    CreateApplicationHandler,
)
from finassist.application.commands.submit_application import (
    SubmitApplicationCommand,
    SubmitApplicationHandler,
)
from finassist.application.ports.id_generator import UuidIdGenerator
from finassist.bootstrap.settings import Settings
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock, SystemClock
from finassist.domain.shared.identifiers import ProductId, TenantId, new_id
from finassist.domain.shared.money import Money
from finassist.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWorkFactory
from finassist.infrastructure.temporal.client import TemporalWorkflowRunner
from finassist.infrastructure.temporal.worker import build_worker
from finassist.infrastructure.temporal.workflows import ApplicationWorkflow

from .test_application_repository import _seed_tenant_and_product

pytestmark = pytest.mark.asyncio(loop_scope="session")

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def real_temporal_env() -> AsyncIterator[tuple[WorkflowEnvironment, int]]:
    port = _free_port()
    env = await WorkflowEnvironment.start_local(ip="127.0.0.1", port=port)
    yield env, port
    await env.shutdown()


async def test_golden_path_against_real_temporal_and_postgres(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
    real_temporal_env: tuple[WorkflowEnvironment, int],
) -> None:
    env, port = real_temporal_env
    tenant_id, product_id = new_id(), new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=tenant_id, product_id=product_id
    )
    uow_factory = SqlAlchemyUnitOfWorkFactory(
        session_factory, clock=FixedClock(_NOW), id_generator=UuidIdGenerator()
    )

    settings = Settings(temporal_host="127.0.0.1", temporal_port=port)
    worker = await build_worker(settings=settings, uow_factory=uow_factory, clock=SystemClock())
    worker_task = asyncio.create_task(worker.run())

    workflow_runner = TemporalWorkflowRunner(
        target_host=f"127.0.0.1:{port}",
        namespace=settings.temporal_namespace,
        task_queue=settings.temporal_task_queue,
        tls=False,
        human_review_sla_seconds=60.0,
    )
    await workflow_runner.ensure_ready()

    try:
        create_result = await CreateApplicationHandler(
            uow_factory=uow_factory, id_generator=UuidIdGenerator(), clock=FixedClock(_NOW)
        ).handle(
            CreateApplicationCommand(
                tenant_id=TenantId(tenant_id),
                idempotency_key=new_id(),
                applicant_given_name="Ada",
                applicant_family_name="Lovelace",
                applicant_date_of_birth=date(1990, 1, 1),
                applicant_email="ada@example.test",
                product_id=ProductId(product_id),
                requested_amount=Money.of("5000.00", "USD"),
                requested_term_months=24,
            )
        )
        submit_result = await SubmitApplicationHandler(
            uow_factory=uow_factory, clock=FixedClock(_NOW), workflow_runner=workflow_runner
        ).handle(
            SubmitApplicationCommand(
                tenant_id=TenantId(tenant_id),
                application_id=create_result.application_id,
                idempotency_key=new_id(),
            )
        )
        assert submit_result.workflow_id is not None

        # No documents uploaded -> the workflow escalates directly to AWAITING_HUMAN_REVIEW.
        # Poll until the review queue entry lands (the workflow runs asynchronously against the
        # real worker) before signaling.
        handle = env.client.get_workflow_handle_for(
            ApplicationWorkflow.run, workflow_id=submit_result.workflow_id
        )
        deadline = asyncio.get_event_loop().time() + 20.0
        while asyncio.get_event_loop().time() < deadline:
            async with uow_factory.begin(tenant_id=TenantId(tenant_id)) as uow:
                current = await uow.applications.get(
                    tenant_id=TenantId(tenant_id),
                    application_id=create_result.application_id,
                )
            assert current is not None
            if current.status is ApplicationStatus.AWAITING_HUMAN_REVIEW:
                break
            await asyncio.sleep(0.5)
        else:
            raise AssertionError("workflow never reached AWAITING_HUMAN_REVIEW in time")

        await workflow_runner.signal_review_decision(
            workflow_id=submit_result.workflow_id,
            decision=ApplicationStatus.APPROVED.value,
            reason="looks good",
            reviewer_id="reviewer-1",
        )
        result = await handle.result()
        assert result.final_status == ApplicationStatus.APPROVED.value
    finally:
        await worker.shutdown()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(worker_task, timeout=10.0)

    async with uow_factory.begin(tenant_id=TenantId(tenant_id)) as uow:
        final = await uow.applications.get(
            tenant_id=TenantId(tenant_id), application_id=create_result.application_id
        )
    assert final is not None
    assert final.status is ApplicationStatus.APPROVED
    assert final.active_workflow_id is None
