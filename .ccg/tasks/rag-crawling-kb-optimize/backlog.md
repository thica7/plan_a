# Backlog: RAG + Crawling + KB Optimization

> **Author:** Claude (orchestrator) — synthesis of `gap-analysis-backend.md` (codex) and `gap-analysis-frontend.md` (antigravity).
> **Date:** 2026-06-06
> **Scope:** Optimize offline DB, online KB, RAG, multi-source crawling, and multi-format file handling.
> **Scale target:** ~50k docs, ~500k chunks. Qdrant single-node, SQLite WAL.

## 0. Arbitration Notes (Cross-Model Conflicts)

Codex and antigravity converged on the same high-priority issues. A few conflicts/overlaps the orchestrator resolved:

1. **Embedding wiring (codex B3) is the single highest-leverage backend change.** It unblocks true RAG, dedupes the "sparse-only silent regression", and is required by both ingestion and retrieval. Frontend F3 (RetrievalParamsDrawer) and F4 (EvalPanel) cannot ship without it.
2. **Crawl-to-ingest (codex B5) closes a fundamental gap**: `crawl_page_tool` parses but never writes to KB. This is the root cause of the "successful crawl but empty KB" UX problem. Frontend F5/F6/F7 (multi-source + queue) require this to be meaningful.
3. **SQLite lifecycle + chunk-level FTS (codex B1+B2) is foundational.** Without WAL and chunk FTS, the RRF fusion and chunk-level rerank have no data to work on. The class-level shared connection in `KnowledgeRepository` is a known foot-gun — must fix before adding concurrent batch ingest.
4. **Parser abstraction (codex B7) precedes PDF/DOCX ingestion (B8) precedes bulk upload UI (F1).** Strict ordering.
5. **Durable crawl frontier (codex B9) precedes multi-source UI (F5).** Without persistence, restart wipes the queue.
6. **Crawler policy + SSRF (codex B10) is a security gate.** Must land before opening crawler to any external URL source (sitemap/RSS), otherwise public-internet crawling can be turned into SSRF.
7. **Frontend foundational bugs (F8 polling leak, F9 module-level timers) are P0** because they break the very features we are about to scale up. They are also tiny (S effort) — fix first.
8. **OpenAPI sync (F10) gates every other frontend change.** No new client modules without regenerating types from a stable backend.

## 1. Dependency Graph (Critical Path)

```
B1 (SQLite WAL+migration) ─┐
B2 (chunk FTS) ────────────┤
B10 (SSRF policy) ─────────┼─→ B3 (embeddings) ─┬─→ B4 (reranker) ─┐
                            │                    │                   ├─→ B5 (crawl→ingest)
                            │                    │                   │
                            │                    ├─→ B6 (tests) ────┤
                            │                    │                   │
                            │                    └─→ B7 (parsers) ──┴─→ B8 (PDF/DOCX)
                            │
                            └─→ B9 (durable frontier) ──→ B11 (JS render)
                                                       └─→ B12 (Qdrant tune)

Frontend critical path (in parallel with backend):
F8 (polling cleanup) ──→ F9 (timer state) ──→ F1 (bulk upload) ──→ F2 (version view)
F10 (openapi sync) ────────────────────────────────→ F3 (params drawer) ──→ F4 (eval panel)
                                                       F5 (multi-source) ──→ F6 (queue) ──→ F7 (failure drill)
```

## 2. Master Backlog (P0/P1/P2)

### P0 — Foundations (must land before any feature work)

| ID | Item | Owner | Effort | Phase | Depends on | Acceptance |
|---|---|---|---|---|---|---|
| B1 | Stabilize SQLite repository (WAL, busy_timeout, migrations table, app-scoped lifecycle) | codex | M | 2 | — | Existing tests pass; concurrent ingest demo passes; no class-level shared connection |
| B2 | Chunk-level sparse search (FTS on `chunks`, not `documents`) | codex | M | 2 | B1 | Hybrid retrieval uses chunk-level BM25; filters apply to sparse branch |
| B3 | Wire bge-m3 embedding provider (embeddings.py + DI in routes/tools) | codex | L | 2 | B1, runtime decision | Ingested docs create Qdrant vectors; `/api/knowledge/search` runs dense path automatically; `embedding_model` persisted on chunks |
| B6 | Backend unit tests for knowledge, retrieval, crawler core | codex | M | 2 | B1, B2, B3 | Tests pass for repo, FTS, RRF, parser, policy, tool wrappers (mocked providers) |
| B10 | Strengthen SSRF protections (DNS-resolved IP deny + per-domain rate config) | codex | M | 2 | — | Fetcher rejects private/loopback/link-local/metadata IPs after DNS resolution; tests cover SSRF bypasses |
| F8 | Cleanup `CrawlPage` polling leak (useEffect cleanup) | antigravity | S | 6 | — | React DevTools shows no orphan intervals after page navigation |
| F9 | Move `knowledgeStore` timers into Zustand state | antigravity | S | 6 | — | No module-level timers; bulk operations don't race |
| F10 | Wire new API client modules + openapi-typescript sync | antigravity | S | 6 | B3, B4, B5 backend endpoints stable | TS types match openapi.json; CI step enforces diff |

### P1 — Core Features (the actual product value)

| ID | Item | Owner | Effort | Phase | Depends on | Acceptance |
|---|---|---|---|---|---|---|
| B4 | Reranker provider + retrieval diagnostics | codex | M | 2 | B3 | Rerank scores surface; window/top-k configurable; tests cover ordering and fallback |
| B5 | Wire crawl success → KB ingestion | codex | M | 2 | B3 (preferred) | Successful crawl creates searchable document; `document_id` recorded; idempotent on content hash |
| B7 | Parser abstraction + MD/JSON/CSV support | codex | M | 3 | B3 | `ParsedDocument` schema; MD/JSON/CSV ingest works; structured errors for invalid files |
| B8 | PDF + DOCX ingestion | codex | M | 3 | B7 | PDF/DOCX extract text+metadata; parser version + MIME persisted; scanned/empty behavior explicit |
| B9 | Durable crawl frontier (SQLite-persisted queue, seeds, dedupe, depth) | codex | L | 4 | B1 | Restart preserves queue; discovered links deduped; status exposes queued/running/done/failed counts |
| B11 | JS render fallback (Playwright) | codex | L | 4 | B10, runtime decision | `render_js` honored; triggers configurable; policy + timeouts preserved |
| B12 | Qdrant tuning (payload indexes, HNSW config, maintenance API) | codex | M | 4 | B3 | Payload indexes created; HNSW/optimizer configurable; stats/reindex endpoints exposed |
| F1 | Bulk upload drawer (drag-drop, multi-format) | antigravity | L | 6 | B7, B8 backend | Drag 5 mixed files → progress per file → retry; max size enforced |
| F2 | Document version/merge view | antigravity | M | 6 | B5, backend version metadata | Timeline UI; diff two versions; merge by hash |
| F3 | Retrieval parameter drawer (dense_weight, sparse_weight, top_k) | antigravity | S | 6 | B4 | Sliders; live re-search on change; params in request body |
| F4 | Retrieval evaluation panel (recall@k, MRR, nDCG) | antigravity | M | 6 | B4 (eval endpoint) | Runs against labeled JSONL; metric tooltips; empty state for no labels |
| F5 | Multi-source crawl input (URL list / sitemap / RSS) | antigravity | L | 6 | B9 | Three tabs; preview first 10 URLs before submit; format auto-detect |
| F6 | Multi-job queue + concurrency UI | antigravity | M | 6 | B9 | All jobs visible with priority/progress; reorder; pause/resume |
| F7 | Failed URLs drill-down panel | antigravity | S | 6 | B9 | Per-job failure list with reason; one-click retry |

### P2 — Quality + Scale (after MVP)

| ID | Item | Owner | Effort | Phase | Depends on |
|---|---|---|---|---|---|
| B13 | Observability for ingest/retrieve/crawl (latency, errors, Qdrant/SQLite health) | codex | M | 4 | B3, B4, B5 |
| B14 | Split crawler worker from API process (durable queue) | codex | L | 5 | B9 |
| B15 | Lifecycle governance: retention, freshness, revalidation | codex | M | 5 | B1 |
| B16 | API contract docs sync (`docs/api_contract.md` lists /knowledge/*, /crawl/*) | codex | S | 7 | All backend work landed |

## 3. Sequencing Recommendation

### Phase 2 (Backend P0): 5–7 days, codex-led
B1, B2, B3, B6, B10, B4, B5 — all foundation + first RAG truth. Antigravity works on F8, F9, F10 in parallel (don't depend on backend).

### Phase 3 (Backend P0 cont.): 3–4 days, codex-led
B7, B8 — parser abstraction + PDF/DOCX. Antigravity on F1, F2, F3 in parallel.

### Phase 4 (Backend P1): 5–7 days, codex-led
B9, B11, B12, B13. Antigravity on F5, F6, F7.

### Phase 5 (Backend P1 cont.): 3–4 days, codex-led
B14, B15. Antigravity on F4 (eval panel needs labels curated, do in this phase).

### Phase 6 (Frontend cont.): overlap with 2-5
F4 if not done in phase 5, F7 polish.

### Phase 7 (Orchestrator): 1–2 days
B16 (api_contract.md sync), end-to-end smoke (upload PDF → ingest → search → eval), generate `progress-report.md`, regenerate openapi.json + types.

### Phase 8 (GitHub push)
BLOCKED — awaiting user confirmation of: branch name, whether to carry uncommitted `plan_a` changes, definition of "code standards", and whether `runs/` data is committed.

## 4. Open Questions for the User (carry over from codex + frontend)

Top 5 that need user decision:

1. **Embedding runtime** — bge-m3 local in-process / local service / remote endpoint? Affects B3 implementation. (Codex §4 Q1)
2. **Reranker runtime** — mandatory / feature-flagged / threshold-triggered? (Q2)
3. **Chunking policy** — token-based with what defaults? (Q3)
4. **Crawl scope** — explicit URLs only, or same-domain depth expansion? (Q8)
5. **API surface** — keep both `/api/knowledge/crawl-jobs` and `/api/crawl/jobs` or unify? (Q9)

Items 6, 7, 10 are deferrable to phase 5.

## 5. Risk Register (top 5, ranked by impact)

1. **Sparse-only silent regression** — RAG looks alive but only does FTS. Mitigation: B3 + add retrieval-mode flag to `/api/knowledge/search` response.
2. **SQLite contention** under batch ingest. Mitigation: B1 (WAL + app-scoped lifecycle) + B6 tests.
3. **Crawler → SSRF** when opening to sitemap/RSS sources. Mitigation: B10 must land before B9 multi-source.
4. **Successful crawl but no KB** — UX break. Mitigation: B5 wires `_run_crawl_job` → ingestion; add acceptance test.
5. **Parser inconsistency** between formats → low-quality chunks/citations. Mitigation: B7's `ParsedDocument` contract enforced; B6 tests.

## 6. Acceptance Signals (when to declare Phases done)

- **Phase 2 done** when: pytest passes, `/api/knowledge/search` returns chunks (not documents), `/api/knowledge/search` response includes `retrieval_mode: "hybrid"`, manual SSRF test (`http://127.0.0.2:8080`) is blocked.
- **Phase 3 done** when: a 5-page PDF and a 10-row CSV can be ingested via the new `POST /api/knowledge/batch` and show up in search.
- **Phase 4 done** when: a sitemap.xml with 100 URLs is processed durably, jobs survive a restart, and `/api/crawl/jobs/{id}/stream` emits per-URL progress.
- **Phase 5 done** when: an eval JSONL produces metric numbers; a `runs/` instance is restarted mid-crawl and resumes correctly.
- **Phase 6 done** when: knowledge, search, and crawl pages all expose the new affordances; React DevTools show no orphan intervals; openapi.json diff is empty after regeneration.
- **Phase 7 done** when: full demo (upload → search → eval) runs in a fresh docker compose, progress-report.md exists, api_contract.md reflects reality.

## 7. File Output Map

- `gap-analysis-backend.md` — codex detailed report
- `gap-analysis-frontend.md` — antigravity detailed report (reconstructed from -p stdout)
- `backlog.md` — this file
- `progress-report.md` — written in Phase 7 by orchestrator
- All under `F:/platform/competition/.ccg/tasks/rag-crawling-kb-optimize/`
