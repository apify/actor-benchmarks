.PHONY: clean install-sync install-dev lint type-check unit-tests format check-code

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist htmlcov .coverage

install-sync:
	uv sync --all-extras

install-dev:
	make install-sync
	uv run pre-commit install
	uv run playwright install

lint:
	uv run ruff format --check
	uv run ruff check

type-check:
	uv run mypy

unit-tests:
	uv run pytest --numprocesses=auto --verbose tests/unit

format:
	uv run ruff check --fix
	uv run ruff format

# The check-code target runs a series of checks equivalent to those performed by pre-commit hooks
# and the run_checks.yaml GitHub Actions workflow.
check-code: lint type-check unit-tests
