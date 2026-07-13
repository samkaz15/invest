# BIOS developer entry points. `make check` must pass before every commit.

PYTHON ?= python3.12
VENV := .venv
PIP := $(VENV)/bin/pip
RUN := $(VENV)/bin/python -m

.PHONY: install lint fmt typecheck test check clean

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

test:  ## Unit tests
	$(RUN) pytest

check: lint typecheck test  ## Full local gate (mirrors CI)

clean:
	rm -rf $(VENV) .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
