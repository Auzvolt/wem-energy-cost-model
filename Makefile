.PHONY: install test lint typecheck run migrate

install:
	pip install -r requirements.txt
	pre-commit install

test:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy app/

run:
	streamlit run app/main.py

migrate:
	alembic upgrade head

migration:
	@read -p "Migration name: " name; \
	alembic revision --autogenerate -m "$$name"
