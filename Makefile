PYTHON ?= $(shell if [ -f .venv/bin/python3 ]; then echo .venv/bin/python3; else echo python3; fi)
export PYTHONPATH := .

.PHONY: test test-python test-signal test-core test-audit test-console conformance bench build clean demo demo-reset dev-console dev-signal dev-core dev-audit dev-all

test: test-python test-console

test-python:
	$(PYTHON) -m pytest packages/signal_intel/tests tests/core services/audit/tests

test-signal:
	python3 -m pytest packages/signal_intel/tests

test-core:
	python3 -m pytest tests/core

test-audit:
	python3 -m pytest services/audit/tests

test-console:
	npm --prefix apps/console test -- --run

conformance:
	$(PYTHON) -m pytest tests/conformance

bench:
	$(PYTHON) -m services.audit.app.bench

build:
	npm --prefix apps/console run build

demo:
	python3 services/audit/app/server.py

demo-reset:
	rm -f var/audit.db* var/audit_head.txt var/canary.jsonl
	mkdir -p var
	@echo "Audit chain reset to genesis. Breaker state clean."

clean:
	rm -rf .pytest_cache var/pipeline.ndjson apps/console/dist
	find . -type d -name __pycache__ -exec rm -rf {} +

dev-console:
	npm --prefix apps/console run dev

dev-signal:
	$(PYTHON) -m uvicorn packages.signal_intel.service:app --port 8001 --host 127.0.0.1

dev-core:
	$(PYTHON) -m packages.core.service

dev-audit:
	$(PYTHON) -m uvicorn services.audit.app.main:app --port 8003 --host 127.0.0.1

dev-server: dev-audit
