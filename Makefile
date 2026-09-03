.PHONY: signal test conformance seed-duress demo

signal:
	PYTHONPATH=packages .venv/bin/python -m uvicorn signal_intel.service:app --port 8001 --reload

test:
	PYPATH=packages PYTHONPATH=packages .venv/bin/python -m pytest -q

conformance:
	PYTHONPATH=packages .venv/bin/python -m pytest tests/conformance -q

# Regenerate the gitignored dev-only duress markers (never committed)
seed-duress:
	@echo "Duress markers live only in contracts/duress.json as HMAC digests."
	@echo "No plaintext marker file exists in this repository by design."

demo: signal
	@echo "open http://localhost:8001/v1/samples"
