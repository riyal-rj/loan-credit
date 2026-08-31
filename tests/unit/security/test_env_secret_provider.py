from __future__ import annotations

import pytest

from finassist.security.env_secret_provider import EnvSecretProvider
from finassist.security.ports import SecretNotFoundError


@pytest.mark.asyncio
async def test_resolves_configured_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINASSIST_SECRET_MY_KEY", "super-secret-value")
    provider = EnvSecretProvider()

    value = await provider.get_secret("my_key")

    assert value == "super-secret-value"


@pytest.mark.asyncio
async def test_raises_for_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINASSIST_SECRET_MISSING_ONE", raising=False)
    provider = EnvSecretProvider()

    with pytest.raises(SecretNotFoundError, match="missing_one"):
        await provider.get_secret("missing_one")


@pytest.mark.asyncio
async def test_custom_prefix_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTOM_PREFIX_TOKEN", "abc123")
    provider = EnvSecretProvider(prefix="CUSTOM_PREFIX_")

    value = await provider.get_secret("token")

    assert value == "abc123"
