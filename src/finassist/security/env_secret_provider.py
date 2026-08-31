"""Development-only `SecretProvider` backed by process environment variables.

Never wired up when ``Settings.environment is Environment.PRODUCTION`` -- that combination is
rejected at settings-construction time (see `finassist.bootstrap.settings`). This adapter exists
so every downstream module can be written against `SecretProvider` from Phase 1A onward; the
OpenBao-backed production adapter (docs/adr/0005) replaces it in Phase 9 without any call-site
change.
"""

from __future__ import annotations

import os

from finassist.security.ports import SecretNotFoundError, SecretProvider


class EnvSecretProvider(SecretProvider):
    """Resolves secrets from environment variables named ``{prefix}{SECRET_NAME}``."""

    def __init__(self, prefix: str = "FINASSIST_SECRET_") -> None:
        self._prefix = prefix

    async def get_secret(self, name: str) -> str:
        env_name = f"{self._prefix}{name.upper()}"
        value = os.environ.get(env_name)
        if value is None:
            raise SecretNotFoundError(name)
        return value
