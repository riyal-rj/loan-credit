"""Port for the immutable, versioned, tenant-isolated object store (master instruction §10.2).

Tenant isolation here is enforced by key-prefixing in the adapter (`ObjectStore` implementations
must reject any operation that isn't scoped through `tenant_id`), because S3-compatible object
storage has no equivalent to PostgreSQL's row-level security -- there is no policy engine to fall
back on if an adapter forgets to prefix a key, so the port signature makes `tenant_id` mandatory
on every method rather than optional.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from finassist.domain.shared.identifiers import TenantId


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    key: str
    checksum_sha256: str
    size_bytes: int
    content_type: str
    version_id: str | None
    uploaded_at: datetime


class ObjectNotFoundError(LookupError):
    def __init__(self, key: str) -> None:
        super().__init__(f"object {key!r} does not exist")
        self.key = key


@runtime_checkable
class ObjectStore(Protocol):
    async def ensure_ready(self) -> None:
        """Idempotent one-time setup (e.g. create a backing bucket/versioning config). Call once
        at process startup before serving traffic. A no-op for adapters with no such concept."""
        ...

    async def check_connectivity(self) -> None:
        """Cheap, read-only reachability check for `/health/ready`. Raises on failure."""
        ...

    async def put_object(
        self,
        *,
        tenant_id: TenantId,
        key: str,
        data: bytes,
        content_type: str,
    ) -> ObjectMetadata:
        """Upload `data` as an immutable, versioned object. A second `put_object` with the same
        `key` creates a new version rather than overwriting -- the object store must have
        versioning enabled (master instruction §10.2)."""
        ...

    async def get_object(self, *, tenant_id: TenantId, key: str) -> bytes:
        """Return the latest version's bytes. Raises `ObjectNotFoundError` if absent."""
        ...

    async def get_object_metadata(self, *, tenant_id: TenantId, key: str) -> ObjectMetadata:
        """Return the latest version's metadata without downloading the object body."""
        ...

    async def generate_presigned_get_url(
        self, *, tenant_id: TenantId, key: str, expires_in_seconds: int
    ) -> str:
        """Return a short-lived signed URL for direct client download.

        The only way a browser/client is ever given access to an object -- bucket credentials are
        never exposed (master instruction §10.2: "never expose bucket credentials to the
        browser").
        """
        ...
