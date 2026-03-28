.PHONY: dev down build test lint seed migrate clean help

# --- Development ---

dev: ## Start all services with Docker Compose
	docker compose -f infra/compose/docker-compose.yml up --build

dev-detached: ## Start all services in background
	docker compose -f infra/compose/docker-compose.yml up --build -d

down: ## Stop all services
	docker compose -f infra/compose/docker-compose.yml down

down-volumes: ## Stop all services and remove volumes
	docker compose -f infra/compose/docker-compose.yml down -v

logs: ## Tail logs from all services
	docker compose -f infra/compose/docker-compose.yml logs -f

logs-api: ## Tail API server logs
	docker compose -f infra/compose/docker-compose.yml logs -f api

# --- Build ---

build: ## Build all Docker images
	docker compose -f infra/compose/docker-compose.yml build

build-api: ## Build API image only
	docker build -f infra/docker/api.Dockerfile -t netgraphy-api .

build-web: ## Build Web image only
	docker build -f infra/docker/web.Dockerfile -t netgraphy-web apps/web

# --- Testing ---

test: ## Run all tests
	cd apps/api && python -m pytest ../../tests/ -v

test-unit: ## Run unit tests only
	cd apps/api && python -m pytest ../../tests/unit/ -v

test-integration: ## Run integration tests (requires running Neo4j)
	cd apps/api && python -m pytest ../../tests/integration/ -v

test-parsers: ## Run parser fixture tests
	cd apps/api && python -m pytest ../../tests/unit/ingestion/ -v

test-frontend: ## Run frontend tests
	cd apps/web && npm test

test-e2e: ## Run end-to-end tests
	cd tests/e2e && npx playwright test

# --- Linting ---

lint: ## Run all linters
	cd apps/api && ruff check .
	cd apps/web && npm run lint

lint-fix: ## Auto-fix linting issues
	cd apps/api && ruff check --fix .

format: ## Format Python code
	cd apps/api && ruff format .

# --- Database ---

seed: ## Seed the database with example data
	PYTHONPATH=. python -m content.seed.seed_data

migrate: ## Apply schema migrations to Neo4j
	@echo "TODO: Implement schema migration CLI"

# --- Schema ---

validate-schemas: ## Validate all YAML schema files
	PYTHONPATH=. python -c "from packages.schema_engine.registry import SchemaRegistry; import asyncio; r = SchemaRegistry(); asyncio.run(r.load_from_directories(['schemas/core', 'schemas/mixins', 'schemas/examples']))"

# --- Frontend ---

web-install: ## Install frontend dependencies
	cd apps/web && npm install

web-dev: ## Run frontend dev server (without Docker)
	cd apps/web && npm run dev

web-build: ## Build frontend for production
	cd apps/web && npm run build

# --- API ---

api-dev: ## Run API server locally (without Docker)
	cd apps/api && PYTHONPATH=../.. uvicorn netgraphy_api.app:app --reload --port 8000

# --- Worker ---

worker-dev: ## Run Celery worker locally
	cd apps/api && PYTHONPATH=../.. celery -A apps.worker.main worker --loglevel=info

# --- Cleanup ---

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name dist -exec rm -rf {} + 2>/dev/null || true

# --- Help ---

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
