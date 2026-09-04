PYTHON ?= $(shell if [ -f .venv/bin/python3 ]; then echo .venv/bin/python3; else echo python3; fi)
export PYTHONPATH := .

.PHONY: test test-python test-console conformance bench build clean demo dev-console dev-signal dev-core dev-audit dev-all

test: test-python test-console

test-python:
	$(PYTHON) -m pytest packages/signal_intel/tests tests/core services/audit/tests

test-console:
	npm --prefix apps/console test -- --run

conformance:
	$(PYTHON) -m pytest tests/conformance

bench:
	$(PYTHON) -m services.audit.app.bench

build:
	npm --prefix apps/console run build

dev-console:
	npm --prefix apps/console run dev

dev-signal:
	$(PYTHON) -m uvicorn packages.signal_intel.service:app --port 8001 --host 127.0.0.1

dev-core:
	$(PYTHON) -m packages.core.service

dev-audit:
	$(PYTHON) -m uvicorn services.audit.app.main:app --port 8003 --host 127.0.0.1

dev-server: dev-audit


