.PHONY: sync lint format typecheck test test-cov security import-lint ci run-api run-worker compose-up compose-down pre-commit-install clean

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
	$(UV) run pytest

security:
	$(UV) run bandit -q -r src apps -c pyproject.toml
	$(UV) run pip-audit --skip-editable

import-lint:
	$(UV) run lint-imports

# Composite gate: what "CI" means in Phase 1A (docs/adr/0004). Must pass with zero errors before
# any phase is marked accepted.
ci: lint typecheck import-lint test security

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
