from __future__ import annotations

import pytest

from finassist.bootstrap.container import (
    UnsupportedProviderConfigurationError,
    build_container,
    shutdown_container,
)
from finassist.bootstrap.settings import Settings
from finassist.security.dev_auth import AllowAllAuthorizationProvider
from finassist.security.env_secret_provider import EnvSecretProvider


def test_build_container_wires_dev_adapters_for_local_environment() -> None:
    settings = Settings(environment="local", log_format="console")

    container = build_container(settings)

    assert isinstance(container.secret_provider, EnvSecretProvider)
    assert isinstance(container.authorization_provider, AllowAllAuthorizationProvider)
    assert container.settings is settings

    shutdown_container(container)


def test_build_container_rejects_openbao_provider_not_yet_implemented() -> None:
    settings = Settings(
        environment="staging",
        secret_provider="openbao",
        log_format="console",
    )

    with pytest.raises(
        UnsupportedProviderConfigurationError, match="OpenBao adapter lands in Phase 9"
    ):
        build_container(settings)
