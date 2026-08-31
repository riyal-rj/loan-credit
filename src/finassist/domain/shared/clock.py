"""Injectable clock port.

Lives in `domain.shared`, not `application.ports`, because domain aggregates (e.g. `Application.
create`/`transition_to`) take a `Clock` directly -- putting it in the application layer would
have domain code importing application code, inverting the dependency direction the import-linter
layers contract enforces. Master instruction §23: "Use UTC, monotonic clocks for durations, and
injectable clock/ID providers for deterministic tests."
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current instant, timezone-aware in UTC."""
        ...


class SystemClock:
    """Production `Clock` backed by the real system clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Test `Clock` that always returns the same instant unless explicitly advanced."""

    def __init__(self, fixed_at: datetime) -> None:
        self._fixed_at = fixed_at

    def now(self) -> datetime:
        return self._fixed_at

    def advance(self, new_fixed_at: datetime) -> None:
        self._fixed_at = new_fixed_at
