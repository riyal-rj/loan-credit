from __future__ import annotations

import pytest

from finassist.domain.shared.identifiers import ApplicationId, TenantId, new_id


def test_new_id_is_a_valid_uuid_string() -> None:
    value = new_id()
    # round-trips through the same validation the ID types perform
    TenantId(value)


def test_rejects_non_uuid_value() -> None:
    with pytest.raises(ValueError, match="not a valid UUID"):
        ApplicationId("not-a-uuid")


def test_distinct_id_types_are_not_interchangeable_by_equality() -> None:
    value = new_id()
    tenant_id = TenantId(value)
    application_id = ApplicationId(value)
    assert tenant_id != application_id
    assert str(tenant_id) == str(application_id) == value
