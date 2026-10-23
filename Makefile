.PHONY: backend frontend dev test lint format

backend:
	cd backend && python3 -m uvicorn app.main:app --reload --host $${BACKEND_HOST:-127.0.0.1} --port $${BACKEND_PORT:-8000}

frontend:
	cd frontend && npm run dev

dev:
	@echo "Run 'make backend' and 'make frontend' in separate terminals."

test:
	cd backend && python3 -m pytest
	cd frontend && npm run build

lint:
	cd backend && python3 -m ruff check .
	cd frontend && npm run lint

format:
	cd backend && python3 -m ruff format .
	cd frontend && npm run format
