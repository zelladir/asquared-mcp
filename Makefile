.PHONY: install up down logs test lint typecheck clean tunnel build

install:
	pip install -e ".[dev]"

up:
	docker compose up -d
	@echo "Server: http://localhost:8765 (health: /health)"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	pytest -v

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .

typecheck:
	mypy src

build:
	docker build -t asquared-mcp:dev .

tunnel:
	cloudflared tunnel run pfit-coord

clean:
	rm -rf data/*.db data/*.db-wal data/*.db-shm
	docker compose down -v
