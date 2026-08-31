.PHONY: sync lint format typecheck test test-integration coverage-check test-cov security import-lint ci ci-full migrate run-api run-worker compose-up compose-down pre-commit-install clean

UV := uv

sync:
	$(UV) sync --all-extras

lint:
	$(UV) run ruff check src apps tests

format:
	$(UV) run ruff format src apps tests

typecheck:
	$(UV) run mypy src apps

test:
	rm -f .coverage
	$(UV) run pytest

# Needs Docker (spins up a real, disposable PostgreSQL container per master instruction §21.1).
# Not part of plain `test`/`ci`: see the testpaths comment in pyproject.toml for why these can't
# safely share a process with the unit-test run. Appends to the same .coverage data file `test`
# started, so `coverage-check` sees combined unit+integration coverage.
test-integration:
	$(UV) run pytest tests/integration --cov=finassist --cov-append --cov-report=

# The real 90% gate (docs/architecture/phase-1b-completion.md), checked once against the combined
# .coverage data from `test` + `test-integration` -- never auto-enforced per-invocation (see the
# comment on [tool.coverage.report] in pyproject.toml).
coverage-check:
	$(UV) run coverage report --fail-under=90 --show-missing

migrate:
	$(UV) run alembic upgrade head

security:
	$(UV) run bandit -q -r src apps -c pyproject.toml
	$(UV) run pip-audit --skip-editable

import-lint:
	$(UV) run lint-imports

# Composite gate: what "CI" means in Phase 1A (docs/adr/0004). Must pass with zero errors before
# any phase is marked accepted. Docker-free by design so it runs anywhere.
ci: lint typecheck import-lint test security

# Same as `ci` plus the Docker-dependent integration suite and the combined coverage gate. Run
# this before accepting a phase that touches persistence; `ci` alone is not sufficient once real
# database code exists.
ci-full: lint typecheck import-lint test test-integration coverage-check security

run-api:
	$(UV) run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

run-worker:
	$(UV) run python -m apps.worker.main

compose-up:
	docker compose --profile core up --build

compose-down:
	docker compose --profile core down -v

pre-commit-install:
	$(UV) run pre-commit install

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
