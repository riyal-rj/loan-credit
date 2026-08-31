from __future__ import annotations

import pytest

from finassist.domain.shared.identifiers import TenantId, new_id
from finassist.infrastructure.object_store.minio_client import _scoped_key


def test_scoped_key_prefixes_with_tenant_id() -> None:
    tenant_id = TenantId(new_id())
    assert _scoped_key(tenant_id, "applications/app-1/paystub.pdf") == (
        f"{tenant_id}/applications/app-1/paystub.pdf"
    )


def test_scoped_key_rejects_leading_slash() -> None:
    with pytest.raises(ValueError, match="relative path"):
        _scoped_key(TenantId(new_id()), "/etc/passwd")


def test_scoped_key_rejects_parent_directory_traversal() -> None:
    with pytest.raises(ValueError, match="relative path"):
        _scoped_key(TenantId(new_id()), "../other-tenant/secret.pdf")


def test_different_tenants_never_produce_the_same_scoped_key() -> None:
    key = "applications/app-1/paystub.pdf"
    first = _scoped_key(TenantId(new_id()), key)
    second = _scoped_key(TenantId(new_id()), key)
    assert first != second
