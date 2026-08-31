"""Typed identifiers.

Master instruction §8: "Use rich domain types rather than primitive strings for ... case ID,
tenant ID, evidence ID". Each ID type below wraps a UUIDv4 string so a `TenantId` can never be
passed where an `ApplicationId` is expected, even though both are strings underneath -- mypy
strict catches the mixup at the call site instead of it surfacing as a cross-tenant data bug.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Id:
    value: str

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.value)
        except ValueError as exc:
            raise ValueError(
                f"{type(self).__name__} value {self.value!r} is not a valid UUID"
            ) from exc

    def __str__(self) -> str:
        return self.value


class TenantId(_Id):
    """Identifies a tenant. Present on every row of every tenant-scoped table."""


class ApplicantId(_Id):
    """Identifies a synthetic applicant."""


class ApplicationId(_Id):
    """Identifies a loan application case -- the aggregate root ID for the applications context."""


class ProductId(_Id):
    """Identifies a lending product (product/policy applicability, §8 context 5)."""


def new_id() -> str:
    """Return a fresh UUIDv4 string. Prefer the injectable `IdGenerator` port at call sites that
    need deterministic tests; this helper exists for the port's default production implementation.
    """
    return str(uuid.uuid4())
