"""Injectable ID-generation port. See `finassist.domain.shared.clock` for the same rationale."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from finassist.domain.shared.identifiers import new_id


@runtime_checkable
class IdGenerator(Protocol):
    def new_id(self) -> str:
        """Return a fresh, globally-unique identifier string (UUIDv4 in the production impl)."""
        ...


class UuidIdGenerator:
    """Production `IdGenerator` backed by `uuid.uuid4`."""

    def new_id(self) -> str:
        return new_id()


class SequentialIdGenerator:
    """Deterministic test `IdGenerator` producing predictable, still-valid-UUID-shaped IDs."""

    def __init__(self, seed_uuid: str = "00000000-0000-4000-8000-000000000000") -> None:
        prefix, _, _ = seed_uuid.rpartition("-")
        self._prefix = prefix
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._prefix}-{self._counter:012d}"
