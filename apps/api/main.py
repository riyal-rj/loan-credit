"""API process entrypoint.

Run with: ``uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000``
or simply ``make run-api`` (see Makefile), which uses the same command with settings from `.env`.
"""

from __future__ import annotations

from finassist.api.app import create_app
from finassist.bootstrap.settings import get_settings

app = create_app(get_settings())
