# syntax=docker/dockerfile:1.7
# Multi-stage, non-root, minimal-base build. Phase 9 (docs/adr/0008) adds SBOM/signing on top of
# this image; this stage set is what gets scanned by `make security` / Trivy in the meantime.

FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/
# Builder WORKDIR must match the runtime stage's WORKDIR (/app): uv bakes the venv's absolute
# path into the `uvicorn` console-script shebang and into the editable install of this project,
# so a mismatched path here breaks both at runtime ("no such file or directory" / ModuleNotFoundError).
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev || uv sync --no-install-project --no-dev
COPY src ./src
COPY apps ./apps
COPY migrations ./migrations
COPY alembic.ini ./
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable || uv sync --no-dev --no-editable

FROM python:3.11-slim AS runtime
RUN groupadd --system --gid 10001 finassist \
    && useradd --system --uid 10001 --gid finassist --no-create-home finassist
WORKDIR /app
COPY --from=builder --chown=finassist:finassist /app/.venv /app/.venv
COPY --from=builder --chown=finassist:finassist /app/src /app/src
COPY --from=builder --chown=finassist:finassist /app/apps /app/apps
COPY --from=builder --chown=finassist:finassist /app/migrations /app/migrations
COPY --from=builder --chown=finassist:finassist /app/alembic.ini /app/alembic.ini
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER finassist
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/live', timeout=3).status == 200 else 1)"
ENTRYPOINT ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
