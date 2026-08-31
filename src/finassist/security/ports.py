"""Security ports: typed boundaries for secrets, authentication, and authorization.

Every concrete implementation lives outside this module (see docs/adr/0005). Application and API
code depend only on these Protocols/value objects so that swapping the env-based dev secret
provider for OpenBao, or the dev auth stub for Keycloak/OPA in Phase 9, is an adapter change at
the composition root -- never a call-site rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


class SecretNotFoundError(RuntimeError):
    """Raised when a requested secret name has no value in the configured provider."""

    def __init__(self, secret_name: str) -> None:
        super().__init__(f"secret '{secret_name}' is not configured")
        self.secret_name = secret_name


@runtime_checkable
class SecretProvider(Protocol):
    """Resolves a named secret to its current value.

    Implementations must never log the resolved value. Callers must never persist a resolved
    value outside process memory (no writing it to a cache, log, or database column).
    """

    async def get_secret(self, name: str) -> str:
        """Return the current value of ``name``, or raise :class:`SecretNotFoundError`."""
        ...


@dataclass(frozen=True, slots=True)
class AuthenticationContext:
    """The authenticated identity for the current request/activity, constructed only by an
    :class:`AuthenticationProvider`.

    Application and API code must treat this as opaque identity data -- it is never constructed
    by hand from raw request headers/claims outside an ``AuthenticationProvider`` implementation.
    """

    subject_id: str
    tenant_id: str
    roles: frozenset[str]
    auth_method: str
    authenticated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class AuthenticationProvider(Protocol):
    """Resolves inbound credentials/tokens into an :class:`AuthenticationContext`."""

    async def authenticate(self, credential: str) -> AuthenticationContext:
        """Validate ``credential`` and return the resulting authentication context.

        Must raise a domain-specific exception (not return ``None``/a falsy sentinel) when the
        credential is invalid, expired, or revoked.
        """
        ...


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """The outcome of an authorization check. Always carries a reason, including on allow, so a
    deny in an audit log is never a bare boolean.
    """

    allowed: bool
    reason: str


@runtime_checkable
class AuthorizationProvider(Protocol):
    """Deny-by-default resource/action authorization check."""

    async def check(
        self,
        *,
        context: AuthenticationContext,
        action: str,
        resource_type: str,
        resource_id: str,
    ) -> AuthorizationDecision:
        """Return whether ``context`` may perform ``action`` on the named resource."""
        ...
