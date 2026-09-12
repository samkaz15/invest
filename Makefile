# MIOS developer entry points. `make check` must pass before every commit.

PYTHON ?= python3.12
VENV := .venv
PIP := $(VENV)/bin/pip
RUN := $(VENV)/bin/python -m

.PHONY: install lint fmt typecheck test check collect health clean

$(VENV)/bin/python:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: $(VENV)/bin/python  ## Create venv and install package with dev tools
	$(PIP) install -e ".[dev]"

lint:  ## Static lint (no fixes)
	$(RUN) ruff check src tests
	$(RUN) ruff format --check src tests

fmt:  ## Auto-format and fix lint
	$(RUN) ruff format src tests
	$(RUN) ruff check --fix src tests

typecheck:  ## Strict mypy over the package
	$(RUN) mypy

test:  ## Tests (integration tests skip without PostgreSQL; CI runs them)
	$(RUN) pytest

check: lint typecheck test  ## Full local gate (mirrors CI)

collect:  ## Collect every enabled source once
	$(RUN) mios.cli collect

health:  ## Per-source health; non-zero exit if any source is failing
	$(RUN) mios.cli health

clean:
	rm -rf $(VENV) .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
