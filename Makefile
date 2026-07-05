.PHONY: venv install test run demo docker-up docker-down clean

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

venv:
	python3 -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

test:
	$(PY) -m pytest

# Run locally with real Phase 1 timing (SQLite).
run:
	$(PY) -m uvicorn conflux.main:app --host 127.0.0.1 --port 8080 --reload

# Run locally with compressed time so the absence ladder is visible in seconds.
demo:
	CONFLUX_TIME_SCALE=0.03 CONFLUX_SMS_INTERVAL_SECONDS=15 CONFLUX_TICK_INTERVAL=2 \
	$(PY) -m uvicorn conflux.main:app --host 127.0.0.1 --port 8080

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

clean:
	rm -f conflux.db
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
