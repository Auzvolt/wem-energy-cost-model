.PHONY: install test lint format run migrate clean

install:
	pip install -e ".[dev]"

test:
	pytest tests/ --cov=. --cov-report=term-missing -v

lint:
	ruff check .
	mypy . --ignore-missing-imports

format:
	ruff format .
	ruff check . --fix

run:
	streamlit run app/streamlit_app.py

migrate:
	alembic -c db/alembic.ini upgrade head

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache .mypy_cache
