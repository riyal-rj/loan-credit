"""Integration tests against a real MinIO container (master instruction §21.1 / §10.2)."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator

import aioboto3
import httpx
import pytest
import pytest_asyncio
from testcontainers.community.minio import MinioContainer

from finassist.application.ports.object_store import ObjectNotFoundError
from finassist.domain.shared.identifiers import TenantId, new_id
from finassist.infrastructure.object_store.minio_client import S3ObjectStore

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="session")
def minio_config() -> Iterator[dict[str, str]]:
    with MinioContainer() as minio:
        yield minio.get_config()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def object_store(minio_config: dict[str, str]) -> AsyncIterator[S3ObjectStore]:
    store = S3ObjectStore(
        aioboto3.Session(
            aws_access_key_id=minio_config["access_key"],
            aws_secret_access_key=minio_config["secret_key"],
        ),
        endpoint_url=f"http://{minio_config['endpoint']}",
        bucket="finassist-documents-test",
        use_ssl=False,
    )
    await store.ensure_ready()
    yield store


async def test_put_then_get_round_trips_bytes(object_store: S3ObjectStore) -> None:
    tenant_id = TenantId(new_id())
    content = b"%PDF-1.4 synthetic document body"

    await object_store.put_object(
        tenant_id=tenant_id, key="docs/a.pdf", data=content, content_type="application/pdf"
    )
    retrieved = await object_store.get_object(tenant_id=tenant_id, key="docs/a.pdf")

    assert retrieved == content


async def test_metadata_reports_correct_checksum_and_size(object_store: S3ObjectStore) -> None:
    tenant_id = TenantId(new_id())
    content = b"pay stub contents"

    await object_store.put_object(
        tenant_id=tenant_id, key="docs/paystub.pdf", data=content, content_type="application/pdf"
    )
    metadata = await object_store.get_object_metadata(tenant_id=tenant_id, key="docs/paystub.pdf")

    assert metadata.checksum_sha256 == hashlib.sha256(content).hexdigest()
    assert metadata.size_bytes == len(content)
    assert metadata.content_type == "application/pdf"
    assert metadata.version_id is not None


async def test_get_missing_object_raises_not_found(object_store: S3ObjectStore) -> None:
    tenant_id = TenantId(new_id())
    with pytest.raises(ObjectNotFoundError):
        await object_store.get_object(tenant_id=tenant_id, key="docs/does-not-exist.pdf")


async def test_tenant_isolation_same_key_different_tenants(object_store: S3ObjectStore) -> None:
    owner_tenant = TenantId(new_id())
    other_tenant = TenantId(new_id())
    await object_store.put_object(
        tenant_id=owner_tenant,
        key="docs/shared-key-name.pdf",
        data=b"owner content",
        content_type="application/pdf",
    )

    with pytest.raises(ObjectNotFoundError):
        await object_store.get_object(tenant_id=other_tenant, key="docs/shared-key-name.pdf")


async def test_second_put_creates_a_new_version_and_get_returns_latest(
    object_store: S3ObjectStore,
) -> None:
    tenant_id = TenantId(new_id())
    await object_store.put_object(
        tenant_id=tenant_id, key="docs/versioned.pdf", data=b"v1", content_type="application/pdf"
    )
    first_metadata = await object_store.get_object_metadata(
        tenant_id=tenant_id, key="docs/versioned.pdf"
    )

    await object_store.put_object(
        tenant_id=tenant_id, key="docs/versioned.pdf", data=b"v2", content_type="application/pdf"
    )
    second_metadata = await object_store.get_object_metadata(
        tenant_id=tenant_id, key="docs/versioned.pdf"
    )

    assert first_metadata.version_id != second_metadata.version_id
    latest = await object_store.get_object(tenant_id=tenant_id, key="docs/versioned.pdf")
    assert latest == b"v2"


async def test_presigned_url_allows_direct_download(object_store: S3ObjectStore) -> None:
    tenant_id = TenantId(new_id())
    content = b"downloadable via presigned url"
    await object_store.put_object(
        tenant_id=tenant_id, key="docs/presigned.pdf", data=content, content_type="application/pdf"
    )

    url = await object_store.generate_presigned_get_url(
        tenant_id=tenant_id, key="docs/presigned.pdf", expires_in_seconds=60
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10)
    assert response.status_code == 200
    assert response.content == content
