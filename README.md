# Competiscope v2

> ## 本次改动（中文）
>
> 本分支 `rag-kb-optimize` 是在 Plan A 基础上做的一次端到端整合与优化，主要面向 **RAG / KB 爬虫闭环** 与 **报告质量 / 工程可观测性** 两条主线。下面按维度汇总本次涉及的关键改动。
>
> ### 1. RAG / KB / 爬虫闭环
>
> - **爬虫源扩展到 8 种**：`sitemap`、`rss`、`web_search`、`manual`、`pricing`、`official_docs`、`changelog`、`review_site`，统一通过 crawl source registry 接入，支持 include / exclude 过滤。
> - **KB 治理**：入库阶段引入 SimHash 近重复检测、过期文档权重衰减、`crawl_run_id` 全链路可追踪；检索阶段新增 `general` / `pricing` / `comparison` 三个预设，并把每次命中的检索 trace 写回 SQLite 便于回放。
> - **评估集**：`eval/competitor-analysis-eval.jsonl` 收录 30 条人工标注的竞品分析 query，可用于回归 / 离线打分。
> - **真实 API 模式**：`.env` 中提供 `ARK_API_KEY` / `ARK_MODEL` / `PPLX_API_KEY` 后，collector 子 Agent 会优先 Perplexity `web_search`，抓取并 hash 页面；不可用时降级到 LLM 生成的候选证据。启动时新增 env var 校验，缺关键 key 直接报错。
>
> ### 2. 图驱动优化（LangGraph）
>
> - **DAG 升级**：把固定的 5 类节点 + Send fan-out 升级为 *Plan-Execute 元循环 + 维度 plug-in*，新增 `comparator`（产出 `ComparisonMatrix`）与 `reflector`（主动生成 self-found gaps）两个节点。
> - **scoped redo**：QA 输出 `QCIssue.redo_scope`（`blocker` / `warn` / `none`）决定窄化重跑粒度，不再为单个 finding 触发全图重跑；`AUTO_REDO_ENABLED` 与 `HITL_ENABLED` 互斥。
> - **HITL 双层 interrupt**：planner 之后与 QA 之后各设一个 `interrupt()`，前端可"修改 plan / 覆盖 finding / 强制通过"。
> - **writer 段责任化**：writer 拆分为 segment shard owner，deep dive 段落锚定到 H2，输出需满足对比矩阵引用一致性 QA。
> - **agent handoff**：planner → collector → analyst → writer 的上下文传递摘要现在会在 Run Detail 页直接展示，便于答辩演示。
>
> ### 3. 报告质量加固（近期主要 commit）
>
> - `fix: surface agent handoff summary in run detail` / `refine agent handoff and scenario classification`
> - `fix: isolate temporal visibility repair` / `fix: defer temporal visibility repair`
> - `feat: rate limit run creation` / `fix: serialize postgres store migrations`
> - `fix: gate report quality hygiene` / `fix: harden segmented writer report quality`
> - `fix: close segment writer review gaps` / `fix: structure writer deep dive backfill by competitor`
> - `fix: anchor writer hardening on h2 sections` / `fix: model writer shard ownership in segment contract`
>
> ### 4. 工程化与部署
>
> - 新增跨平台一键启动脚本：`scripts/start.ps1` 与 `scripts/start.sh`，等待 Postgres healthy → 启动 backend / worker / frontend / nginx，再做 `/api/health` 健康检查。
> - Docker Compose 栈新增 Qdrant、Temporal UI、Temporal worker，RAG/KB demo 路径使用 `QDRANT_URL=http://qdrant:6333` + `KB_DB_PATH=/app/runs/knowledge_docker.db`。
> - 启动时校验 `ARK_API_KEY` / `ARK_MODEL` / `BACKUP_LLM_*` / `PPLX_API_KEY`，缺关键变量直接报错并打印具体缺失项。
> - 前端 console 覆盖 run / history / crawl / search / knowledge / enterprise / evidence / competitor / report / trace / revision 全部视图。
> - `.gitignore` 新增 `tmp/`、`plan_a_deploy.tar.gz` 等部署产物屏蔽，避免历史归档污染仓库。
>
> ### 5. 关联文档
>
> - `docs/USER_GUIDE.md`：面向操作者与开发者的完整使用指南
> - `docs/ARCHITECTURE_DIAGRAM.md`：爬虫 → 入库 → RAG 检索架构图
> - `docs/E2E_DEMO_DESIGN.md`：端到端演示流程设计
> - `docs/DEMO_VIDEO_SCRIPT.md`：录屏 / 现场演示旁白脚本
> - `方案A_图驱动优化版.md`：图驱动改造的设计稿（仓库根目录，但已在 `.gitignore` 中屏蔽，不入版本库）
>
> ---

Plan A is a competitive intelligence workbench with a FastAPI backend, a
React/Vite console, graph-driven run orchestration, RAG/KB ingestion, enterprise
data boundaries, and Docker-first deployment scaffolding.

## Quick Start

Docker deployment:

```powershell
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File scripts\docker_deploy.ps1 -Build
```

Then open `http://localhost:8080`. See `docs/docker_deployment.md` for the
deployment contract and production notes.

Windows one-command development startup:

```powershell
.\scripts\dev_start.ps1
```

This starts local Postgres, Temporal, Temporal UI, the FastAPI backend, the
Temporal worker, and the Vite frontend. To stop or inspect the local stack:

```powershell
.\scripts\dev_stop.ps1
.\scripts\dev_status.ps1
```

The backend runs on `http://localhost:8000`. The frontend runs on
`http://localhost:5173` and proxies `/api` to the backend. Temporal exposes gRPC
on `127.0.0.1:7233` and UI on `http://localhost:8233` when the full stack is
running.

For the lighter RAG/KB demo path, Qdrant remains in `docker-compose.yml` and the
backend uses `QDRANT_URL=http://qdrant:6333` plus
`KB_DB_PATH=/app/runs/knowledge_docker.db`.

## Real API Mode

Create a root `.env` from `.env.example`, then set the provider keys you need:

```text
DEMO_MODE=false
ARK_API_KEY=your_key
ARK_MODEL=your_model_or_endpoint_id
PPLX_API_KEY=your_perplexity_key
BACKUP_LLM_API_KEY=your_backup_key
BACKUP_LLM_MODEL=your_backup_model
```

Leave Competitors on `Auto-discover` to provide only a topic; the planner will
search and select direct competitors before evidence collection. When
`PPLX_API_KEY` is present, collector subagents prefer official source registry
candidates, then Perplexity `web_search` results, fetch and hash returned pages,
and fall back to LLM-generated evidence candidates when search is unavailable.

## Current Slice

- FastAPI backend with run, stream, HITL, health, metrics, skills, runtime,
  trace, crawl, knowledge, KB, revision, enterprise, eval, and workflow routers.
- RAG/KB ingestion with crawl sources, document parsing, SimHash deduplication,
  retrieval presets, Qdrant vector support, and retrieval trace recording.
- Enterprise boundary for workspace, project, competitor, evidence, claim,
  report version, audit log, auth/RBAC, compliance, and Postgres storage.
- Temporal thin shell for retry-safe workflow wrapping and report approval
  signals.
- Observability coverage for local traces, decision replay, OpenTelemetry export,
  Langfuse mirroring, and compliance redaction.
- React + Vite + TypeScript console with run, history, crawl, search, knowledge,
  enterprise, evidence, competitor, report, trace, and revision views.
- Docker Compose stack with Nginx, frontend, backend, Qdrant, Postgres, Temporal,
  Temporal UI, and a Temporal worker.

## Useful Commands

```bash
make test-backend
make test-frontend
make sync-openapi
make secret-scan
make m0-check
```

Enterprise and workflow smoke checks:

```bash
docker compose up -d postgres temporal temporal-ui
make smoke-enterprise-postgres
make smoke-temporal-thin-shell
make smoke-temporal-server
```

## Project Layout

```text
backend/      FastAPI app, schema, agents, orchestration, RAG, enterprise code
frontend/     React/Vite console and generated OpenAPI client types
docs/         Architecture, deployment, ADR, contract, and eval notes
docker/       Nginx reverse proxy config
data/         Seed data and golden sets
eval/         RAG evaluation data
third_party/  Vendored runtime helpers, including webfetch_v2
```
