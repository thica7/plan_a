.DEFAULT_GOAL := help
SHELL := bash

.PHONY: dev-backend dev-frontend test-backend test-frontend sync-openapi smoke-llm smoke-search smoke-fetch smoke-minimal-run smoke-enterprise-postgres m0-check demo-build demo demo-down demo-logs help

dev-backend: ## Start FastAPI in reload mode
	conda run -n bd-competiscope-v2 uvicorn app.main:app --reload --port 8000 --app-dir backend

dev-frontend: ## Start Vite dev server
	cd frontend && pnpm dev

test-backend: ## Run backend tests
	conda run -n bd-competiscope-v2 pytest backend/tests -q

test-frontend: ## Run frontend tests
	cd frontend && pnpm test

sync-openapi: ## Export OpenAPI and generate frontend types
	conda run -n bd-competiscope-v2 python backend/scripts/export_openapi.py > frontend/openapi.json
	cd frontend && pnpm openapi-typescript openapi.json -o src/api/types.ts

smoke-llm: ## Run a real Doubao/ARK LLM smoke test
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_llm.py

smoke-search: ## Run a real Perplexity search smoke test
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_search.py

smoke-fetch: ## Run a real page fetch smoke test
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_fetch.py

smoke-minimal-run: ## Run the minimal demo graph pipeline smoke test
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_minimal_run.py

smoke-enterprise-postgres: ## Verify enterprise projection persistence against local Postgres
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_enterprise_postgres.py

m0-check: test-backend smoke-minimal-run ## Verify M0 foundation without external APIs

demo-build: ## Build demo containers
	docker compose build

demo: ## Run demo stack
	docker compose up -d
	@echo "http://localhost:8080"

demo-down: ## Stop demo stack
	docker compose down -v

demo-logs: ## Follow demo logs
	docker compose logs -f --tail=100

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "%-20s %s\n", $$1, $$2}'
