.PHONY: install dev test lint migrate seed up down

install:
	pip install -r requirements-dev.txt

dev:
	uvicorn app.main:app --reload

test:
	pytest -q

lint:
	ruff format --check . && ruff check . && mypy

migrate:
	alembic upgrade head

seed:
	python -m scripts.seed

up:
	docker compose up --build

down:
	docker compose down
