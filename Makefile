.PHONY: help db-up db-down install init-db seed api simulate test lint dev-frontend

help:
	@echo "make db-up      - start Postgres (docker compose)"
	@echo "make install    - install backend deps into backend/.venv"
	@echo "make init-db    - create tables"
	@echo "make seed       - seed the BrightHome Services demo business"
	@echo "make api        - run the FastAPI server"
	@echo "make simulate   - send a simulated customer message to the agent"
	@echo "make test       - run the test suite"
	@echo "make lint       - ruff check"

db-up:
	docker compose up -d postgres
	@echo "waiting for postgres..." && sleep 3 && docker compose exec -T postgres pg_isready -U opsagent -d opsagent

db-down:
	docker compose down

install:
	cd backend && uv sync

init-db:
	cd backend && .venv/bin/python -m scripts.init_db

seed:
	cd backend && .venv/bin/python -m scripts.seed

reset-db:
	cd backend && .venv/bin/python -m scripts.init_db --drop && .venv/bin/python -m scripts.seed

api:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8010

worker:
	cd backend && .venv/bin/python -m scripts.worker

simulate:
	cd backend && .venv/bin/python -m scripts.simulate_event $(ARGS)

test:
	cd backend && .venv/bin/python -m pytest -q

lint:
	cd backend && .venv/bin/ruff check app scripts tests

dev-frontend:
	cd frontend && npm run dev
