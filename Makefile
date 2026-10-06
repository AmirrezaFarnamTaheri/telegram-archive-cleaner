.PHONY: install install-dev test lint format web scan build-exe clean

PY := python3

install:
	$(PY) -m pip install -e .

install-dev:
	$(PY) -m pip install -e ".[dev,optional]"

test:
	$(PY) -m pytest tests/ -v

lint:
	ruff check src tests

format:
	ruff format src tests

web:
	$(PY) -m tg_cleaner.cli web --host 0.0.0.0 --port 8000

scan:
	$(PY) -m tg_cleaner.cli scan me

build-exe:
	$(PY) scripts/build_exe.py

clean:
	find . -name '__pycache__' -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache build dist data/*.db-wal data/*.db-shm
