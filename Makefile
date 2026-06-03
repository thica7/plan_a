.DEFAULT_GOAL := help
SHELL := bash

.PHONY: dev-backend dev-frontend temporal-worker test-backend test-frontend sync-openapi secret-scan smoke-llm smoke-search smoke-fetch smoke-minimal-run smoke-enterprise-postgres smoke-temporal-thin-shell smoke-temporal-server smoke-phase2-business-intel smoke-phase3-strict phase4-readiness eval-baseline eval-baseline-full m0-check demo-build demo demo-down demo-logs help

dev-backend: ## Start FastAPI in reload mode
	conda run -n bd-competiscope-v2 uvicorn app.main:app --reload --port 8000 --app-dir backend

dev-frontend: ## Start Vite dev server
	cd frontend && pnpm dev

temporal-worker: ## Start the Phase 4 Temporal worker
	conda run -n bd-competiscope-v2 python backend/scripts/run_temporal_worker.py

test-backend: ## Run backend tests
	conda run -n bd-competiscope-v2 pytest backend/tests -q

test-frontend: ## Run frontend tests
	cd frontend && pnpm test

sync-openapi: ## Export OpenAPI and generate frontend types
	conda run -n bd-competiscope-v2 python backend/scripts/export_openapi.py > frontend/openapi.json
	cd frontend && pnpm openapi-typescript openapi.json -o src/api/openapi.ts

secret-scan: ## Fail if tracked project files contain provider key patterns
	conda run -n bd-competiscope-v2 python backend/scripts/scan_secrets.py

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

smoke-temporal-thin-shell: ## Verify the Phase 4 Temporal activity shell without a server
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_temporal_thin_shell.py

smoke-temporal-server: ## Verify CompetitiveIntelWorkflow against a running Temporal server
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_temporal_server.py --report docs/reports/temporal_replay_report.md

smoke-phase2-business-intel: ## Verify Phase 2 business intel gates
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_phase2_business_intel.py

smoke-phase3-strict: ## Verify strict Phase 3 product-agent gates
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_phase3_strict.py

phase4-readiness: ## Generate the strict Phase 4 readiness report
	conda run -n bd-competiscope-v2 python backend/scripts/phase4_readiness_report.py --require-server --report docs/reports/phase4_readiness_report.md
	conda run -n bd-competiscope-v2 python backend/scripts/smoke_temporal_server.py --report docs/reports/temporal_replay_report.md

eval-baseline: ## Run Phase 1 baseline eval smoke cases without external APIs
	conda run -n bd-competiscope-v2 python backend/scripts/eval_baseline.py

eval-baseline-full: ## Run all Phase 2 golden-set baseline eval cases
	conda run -n bd-competiscope-v2 python backend/scripts/eval_baseline.py --limit 0 --report docs/reports/golden_eval_report.md

m0-check: secret-scan test-backend smoke-minimal-run eval-baseline ## Verify M0 foundation without external APIs

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
