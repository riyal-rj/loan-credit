from __future__ import annotations

import pytest

from finassist.security.dev_auth import (
    AllowAllAuthorizationProvider,
    InvalidDevCredentialError,
    StaticAuthenticationProvider,
)
from finassist.security.ports import AuthenticationContext


@pytest.mark.asyncio
async def test_static_authentication_provider_resolves_known_token() -> None:
    context = AuthenticationContext(
        subject_id="user-1",
        tenant_id="demo-bank",
        roles=frozenset({"credit-reviewer"}),
        auth_method="dev-static",
    )
    provider = StaticAuthenticationProvider({"token-abc": context})

    resolved = await provider.authenticate("token-abc")

    assert resolved is context


@pytest.mark.asyncio
async def test_static_authentication_provider_rejects_unknown_token() -> None:
    provider = StaticAuthenticationProvider({})

    with pytest.raises(InvalidDevCredentialError):
        await provider.authenticate("does-not-exist")


@pytest.mark.asyncio
async def test_allow_all_authorization_provider_always_allows_and_explains_why() -> None:
    context = AuthenticationContext(
        subject_id="user-1", tenant_id="demo-bank", roles=frozenset(), auth_method="dev-static"
    )
    provider = AllowAllAuthorizationProvider()

    decision = await provider.check(
        context=context, action="review:decide", resource_type="application", resource_id="app-1"
    )

    assert decision.allowed is True
    assert "DEV STUB" in decision.reason
