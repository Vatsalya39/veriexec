.PHONY: test test-python test-signal test-core test-audit test-console conformance bench build clean demo demo-reset

test: test-python test-console

test-python:
	python3 -m pytest packages/signal_intel/tests tests/core services/audit/tests

test-signal:
	python3 -m pytest packages/signal_intel/tests

test-core:
	python3 -m pytest tests/core

test-audit:
	python3 -m pytest services/audit/tests

test-console:
	npm --prefix apps/console test -- --run

conformance:
	python3 -m pytest tests/conformance

bench:
	python3 -m services.audit.app.bench

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
