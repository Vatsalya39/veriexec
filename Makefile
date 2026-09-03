.PHONY: test test-python test-console conformance bench build clean demo

test: test-python test-console

test-python:
	python3 -m pytest packages/signal_intel/tests tests/core services/audit/tests

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
