"""S3-compatible (MinIO) `ObjectStore` adapter.

A fresh `aioboto3` client is opened per call rather than held open for the process lifetime --
simpler lifecycle management, and aioboto3/aiobotocore pool the underlying HTTP connections
regardless, so this does not mean a new TCP connection per call.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, NoReturn

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from finassist.application.ports.object_store import ObjectMetadata, ObjectNotFoundError
from finassist.domain.shared.identifiers import TenantId

_CHECKSUM_METADATA_KEY = "sha256"


def _scoped_key(tenant_id: TenantId, key: str) -> str:
    if key.startswith("/") or ".." in key.split("/"):
        raise ValueError(f"object key {key!r} must be a relative path with no '..' segments")
    return f"{tenant_id}/{key}"


class S3ObjectStore:
    def __init__(
        self,
        session: aioboto3.Session,
        *,
        endpoint_url: str,
        bucket: str,
        use_ssl: bool,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        self._session = session
        self._endpoint_url = endpoint_url
        self._bucket = bucket
        self._use_ssl = use_ssl
        # Explicit, short timeouts and no automatic retries: botocore's defaults (a ~60s connect
        # timeout with several retries) turned a MinIO-unreachable case into an ~80s hang in this
        # project's own tests -- exactly the "never rely on library defaults" failure master
        # instruction §20 warns about, caught by running the code rather than by review.
        self._boto_config = Config(
            connect_timeout=request_timeout_seconds,
            read_timeout=request_timeout_seconds,
            retries={"max_attempts": 1, "mode": "standard"},
        )

    def _client(self) -> Any:
        # aioboto3 ships no type stubs/py.typed marker, so the returned async-context-manager
        # client is untyped at the boundary regardless of annotation; every call site treats the
        # yielded client as duck-typed (matching how the AWS/MinIO S3 API itself is used).
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            use_ssl=self._use_ssl,
            config=self._boto_config,
        )

    async def check_connectivity(self) -> None:
        """Pure connectivity/existence check, no side effects. Used by `/health/ready`; separate
        from `ensure_bucket_ready` so a readiness probe never creates infrastructure."""
        async with self._client() as s3:
            await s3.head_bucket(Bucket=self._bucket)

    async def ensure_ready(self) -> None:
        """Idempotently create the bucket and enable versioning. Call once at process startup."""
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except ClientError:
                await s3.create_bucket(Bucket=self._bucket)
            await s3.put_bucket_versioning(
                Bucket=self._bucket, VersioningConfiguration={"Status": "Enabled"}
            )

    async def put_object(
        self, *, tenant_id: TenantId, key: str, data: bytes, content_type: str
    ) -> ObjectMetadata:
        scoped_key = _scoped_key(tenant_id, key)
        checksum = hashlib.sha256(data).hexdigest()
        async with self._client() as s3:
            response = await s3.put_object(
                Bucket=self._bucket,
                Key=scoped_key,
                Body=data,
                ContentType=content_type,
                Metadata={_CHECKSUM_METADATA_KEY: checksum},
            )
        return ObjectMetadata(
            key=key,
            checksum_sha256=checksum,
            size_bytes=len(data),
            content_type=content_type,
            version_id=response.get("VersionId"),
            uploaded_at=datetime.now(UTC),
        )

    async def get_object(self, *, tenant_id: TenantId, key: str) -> bytes:
        scoped_key = _scoped_key(tenant_id, key)
        async with self._client() as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=scoped_key)
            except ClientError as exc:
                self._raise_mapped(exc, key)
            body = await response["Body"].read()
            return bytes(body)

    async def get_object_metadata(self, *, tenant_id: TenantId, key: str) -> ObjectMetadata:
        scoped_key = _scoped_key(tenant_id, key)
        async with self._client() as s3:
            try:
                response = await s3.head_object(Bucket=self._bucket, Key=scoped_key)
            except ClientError as exc:
                self._raise_mapped(exc, key)
        return ObjectMetadata(
            key=key,
            checksum_sha256=response.get("Metadata", {}).get(_CHECKSUM_METADATA_KEY, ""),
            size_bytes=response["ContentLength"],
            content_type=response.get("ContentType", "application/octet-stream"),
            version_id=response.get("VersionId"),
            uploaded_at=response["LastModified"],
        )

    async def generate_presigned_get_url(
        self, *, tenant_id: TenantId, key: str, expires_in_seconds: int
    ) -> str:
        scoped_key = _scoped_key(tenant_id, key)
        async with self._client() as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": scoped_key},
                ExpiresIn=expires_in_seconds,
            )
            return url

    @staticmethod
    def _raise_mapped(exc: ClientError, key: str) -> NoReturn:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in {"NoSuchKey", "404"}:
            raise ObjectNotFoundError(key) from exc
        raise exc
