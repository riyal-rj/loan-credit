"""Development-only authentication/authorization stubs.

These exist solely so API/application code from Phase 1B onward can be written against
`AuthenticationProvider`/`AuthorizationProvider` immediately. They are intentionally named
`Static*`/`Dev*` so they cannot be mistaken for production-capable code, and they are never wired
up under `Environment.PRODUCTION` (enforced the same way as `EnvSecretProvider`: the composition
root refuses to build a production app with a dev provider -- see `finassist.bootstrap.container`).

Real identity/authorization (Keycloak OIDC + OPA, docs/adr/0005) replaces this module in Phase 9.
"""

from __future__ import annotations

from finassist.security.ports import (
    AuthenticationContext,
    AuthorizationDecision,
    AuthorizationProvider,
)


class InvalidDevCredentialError(RuntimeError):
    """Raised by :class:`StaticAuthenticationProvider` for an unrecognized dev credential."""


class StaticAuthenticationProvider:
    """Maps a fixed set of dev bearer tokens to synthetic identities.

    Configured with an explicit, in-memory token map rather than reading arbitrary claims, so a
    dev token can never accidentally resolve to an identity nobody configured.
    """

    def __init__(self, token_to_context: dict[str, AuthenticationContext]) -> None:
        self._token_to_context = dict(token_to_context)

    async def authenticate(self, credential: str) -> AuthenticationContext:
        context = self._token_to_context.get(credential)
        if context is None:
            raise InvalidDevCredentialError("dev credential not recognized")
        return context


class AllowAllAuthorizationProvider(AuthorizationProvider):
    """Authorization stub that allows every action.

    Deliberately the *opposite* of deny-by-default so it is unmistakable in any audit event it
    produces (``reason`` always says so explicitly) and cannot be misread as a real policy
    decision. Used only in local development composition; Phase 9's OPA-backed provider is
    deny-by-default per docs/adr/0005.
    """

    async def check(
        self,
        *,
        context: AuthenticationContext,
        action: str,
        resource_type: str,
        resource_id: str,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=True,
            reason=(
                "ALLOWED BY DEV STUB (AllowAllAuthorizationProvider) -- not a real policy "
                "decision; OPA integration lands in Phase 9"
            ),
        )
