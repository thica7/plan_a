.DEFAULT_GOAL := help
SHELL := bash
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173

.PHONY: dev dev-stop dev-status dev-backend dev-frontend temporal-worker qdrant-up qdrant-down test-backend test-frontend test-engineering sync-openapi secret-scan smoke-llm smoke-search smoke-fetch smoke-minimal-run smoke-enterprise-postgres smoke-temporal-thin-shell smoke-temporal-server smoke-phase2-business-intel smoke-phase3-strict phase4-readiness eval-baseline eval-baseline-full m0-check demo-build demo demo-down demo-logs help

dev: ## Start local services with configured ports and recorded PIDs
	$(PYTHON) scripts/dev_runtime.py start $(DEV_ARGS)

dev-stop: ## Stop only verified project PIDs
	$(PYTHON) scripts/dev_runtime.py stop $(DEV_ARGS)

dev-status: ## Show actual local endpoints and PID ownership
	$(PYTHON) scripts/dev_runtime.py status

dev-backend: ## Start FastAPI in reload mode
	$(PYTHON) -m uvicorn app.main:app --reload --port $(BACKEND_PORT) --app-dir backend

dev-frontend: ## Start Vite dev server
	cd frontend && BACKEND_PORT=$(BACKEND_PORT) FRONTEND_PORT=$(FRONTEND_PORT) pnpm dev --port $(FRONTEND_PORT) --strictPort

temporal-worker: ## Start the Phase 4 Temporal worker
	$(PYTHON) backend/scripts/run_temporal_worker.py

qdrant-up: ## Start local Qdrant
	docker compose up -d qdrant

qdrant-down: ## Stop local Qdrant
	docker compose stop qdrant

test-backend: ## Run backend tests
	$(PYTHON) -m pytest backend/tests -q

test-frontend: ## Run frontend tests
	cd frontend && pnpm test

test-engineering: ## Verify local ports and PID ownership
	$(PYTHON) -m pytest backend/tests/unit/test_dev_runtime.py -q

sync-openapi: ## Export OpenAPI and generate frontend types
	$(PYTHON) backend/scripts/export_openapi.py > frontend/openapi.json
	cd frontend && pnpm openapi-typescript openapi.json -o src/api/openapi.ts

secret-scan: ## Fail if tracked project files contain provider key patterns
	$(PYTHON) backend/scripts/scan_secrets.py

smoke-llm: ## Run a real Doubao/ARK LLM smoke test
	$(PYTHON) backend/scripts/smoke_llm.py

smoke-search: ## Run a real Perplexity search smoke test
	$(PYTHON) backend/scripts/smoke_search.py

smoke-fetch: ## Run a real page fetch smoke test
	$(PYTHON) backend/scripts/smoke_fetch.py

smoke-minimal-run: ## Run the minimal demo graph pipeline smoke test
	$(PYTHON) backend/scripts/smoke_minimal_run.py

smoke-enterprise-postgres: ## Verify enterprise projection persistence against local Postgres
	$(PYTHON) backend/scripts/smoke_enterprise_postgres.py

smoke-temporal-thin-shell: ## Verify the Phase 4 Temporal activity shell without a server
	$(PYTHON) backend/scripts/smoke_temporal_thin_shell.py

smoke-temporal-server: ## Verify CompetitiveIntelWorkflow against a running Temporal server
	$(PYTHON) backend/scripts/smoke_temporal_server.py --report docs/reports/temporal_replay_report.md

smoke-phase2-business-intel: ## Verify Phase 2 business intel gates
	$(PYTHON) backend/scripts/smoke_phase2_business_intel.py

smoke-phase3-strict: ## Verify strict Phase 3 product-agent gates
	$(PYTHON) backend/scripts/smoke_phase3_strict.py

phase4-readiness: ## Generate the strict Phase 4 readiness report
	$(PYTHON) backend/scripts/phase4_readiness_report.py --require-server --report docs/reports/phase4_readiness_report.md
	$(PYTHON) backend/scripts/smoke_temporal_server.py --report docs/reports/temporal_replay_report.md

eval-baseline: ## Run Phase 1 baseline eval smoke cases without external APIs
	$(PYTHON) backend/scripts/eval_baseline.py

eval-baseline-full: ## Run all Phase 2 golden-set baseline eval cases
	$(PYTHON) backend/scripts/eval_baseline.py --limit 0 --report docs/reports/golden_eval_report.md

m0-check: secret-scan test-backend smoke-minimal-run eval-baseline ## Verify M0 foundation without external APIs

demo-build: ## Build demo containers
	docker compose build

demo: ## Run demo stack
	$(PYTHON) scripts/docker_deploy.py

demo-down: ## Stop demo stack
	docker compose down -v

demo-logs: ## Follow demo logs
	docker compose logs -f --tail=100

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "%-20s %s\n", $$1, $$2}'
