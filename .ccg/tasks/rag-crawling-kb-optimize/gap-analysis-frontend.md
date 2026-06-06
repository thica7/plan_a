# Frontend Gap Analysis — RAG + Crawling + KB Optimization

> **Note:** The original antgravity analysis came as a `-p` (print) mode stdout dump, not a file. This file reconstructs the report Claude received from the antigravity sub-agent's terminal output, organized to match the same template as the backend gap analysis for cross-comparison.

## 1. Summary

The frontend currently exposes a working operations console (New Run → Run Detail → KB/Search/Crawl) but ships without the deliverables implied by the new RAG + Crawling + KB subsystems:

- The **Knowledge Page** renders list/detail/delete but has no upload surface, no batch ingest, and no document-version/merge UI.
- The **Search Page** posts to `/api/knowledge/search` but does not expose retrieval parameters (dense/sparse weight, top-k, query rewriting) and shows no evaluation panel.
- The **Crawl Page** accepts single URL submissions and reads back job state, but does not provide multi-source input (sitemap, RSS, bulk URL list), failure recovery, or rate-limit visibility.

The Zustand stores mirror the backend CRUD surface, and the React Query hooks are not yet introduced. Several latent bugs leak timers and create cross-instance race conditions (see §5).

## 2. Current State Inventory

| File | Status | Notes |
|---|---|---|
| `frontend/src/api/knowledge.ts` | Real | `listDocuments`, `getDocument`, `deleteDocument`, `searchKnowledge` — uses `signal` for cancellation and `X-Total-Count` parsing |
| `frontend/src/api/crawl.ts` | Real | `listCrawlJobs`, `createCrawlJob`, `getCrawlJob`, `deleteCrawlJob`, `retryCrawlJob` — all wired to backend |
| `frontend/src/stores/knowledgeStore.ts` | Real but fragile | Global `debounceTimer`/`errorTimer` declared outside Zustand state — multi-instance race |
| `frontend/src/stores/crawlStore.ts` | Real but leaks | `setInterval` polling never cleared on component unmount |
| `frontend/src/pages/KnowledgePage.tsx` | Real | List + filter + detail modal + delete, no upload, no version/merge view |
| `frontend/src/pages/SearchPage.tsx` | Real | Search input + result list with rerank badge, no parameter tuning, no eval panel |
| `frontend/src/pages/CrawlPage.tsx` | Real | URL input + job list + per-job detail with stream events, no multi-source input |
| `frontend/src/components/SourceCard.tsx` | Real | Renders chunk text, citation, rerank score, metadata |
| `frontend/src/api/index.ts` | Real | Re-exports `knowledge` and `crawl` only — no `search`, no `eval` |
| `frontend/src/api/types.ts` | Real | Generated from `openapi.json`; missing fields from any backend additions |

## 3. Gap Matrix (user perspective)

| Requirement | Current UX | Missing | Proposed Change |
|---|---|---|---|
| Offline DB optimization | Filter + delete by id; no bulk operations; no version visibility | Bulk select + batch delete; per-doc version timeline; merge duplicate preview | `KnowledgePage.tsx`: add bulk action bar; new `DocumentVersionDrawer`; wire `POST /api/knowledge/batch` |
| Online KB optimization | One URL → one job; no multi-source; no failure detail | Sitemap.xml paste, RSS feed URL, bulk URL list; failed-URL drill-down; per-domain rate limit visualization | `CrawlPage.tsx`: add source-type tabs (URL list / sitemap / RSS); new `FailedUrlsPanel`; `crawlStore` exposes `progress.failure_breakdown` |
| RAG optimization | Search box → top-K chunks with rerank badge; no parameter control; no eval | Sliders for `dense_weight`/`sparse_weight`/`top_k`; query-rewrite transparency (show rewrites & fused result); eval panel with recall@k/MRR/nDCG | `SearchPage.tsx`: new `RetrievalParamsDrawer`; `EvalPanel` consuming `POST /api/knowledge/eval`; new `api/eval.ts` client |
| Data collection scale-up | Single concurrent job in UI; no scheduling | Multi-job queue with priorities; bulk submit progress; concurrency limit setting | `CrawlPage.tsx`: add `JobQueueTable` with `priority` column; submit bulk via `POST /api/crawl/jobs/batch` |
| File format handling | Backend ingests text only (HTML→markdown via trafilatura); no PDF/CSV/DOCX/JSON upload path | Drag-and-drop multi-format uploader; per-format preview; format-aware chunk count | `KnowledgePage.tsx`: add `UploadDrawer` accepting `.pdf .docx .csv .json .md .html`; previews use `react-pdf`, `react-docx-preview`, or simple table render |

## 4. Backlog (Phase 6, owner=antigravity)

| # | Item | Effort | Target Files | Depends On | Acceptance |
|---|---|---|---|---|---|
| F1 | Bulk upload drawer (drag-drop) | L | `KnowledgePage.tsx`, new `UploadDrawer.tsx`, `api/knowledge.ts` | B2 (batch ingest) | User can drag 5 mixed-format files; progress per file; retry on failure |
| F2 | Document version/merge view | M | `KnowledgePage.tsx`, new `VersionDrawer.tsx` | B2 | User sees version timeline, can compare two versions diff, can merge by hash |
| F3 | Retrieval parameter drawer | S | `SearchPage.tsx`, new `RetrievalParamsDrawer.tsx` | B5 (RAG tuning) | Sliders for dense_weight, sparse_weight, top_k; live re-search on change |
| F4 | Retrieval evaluation panel | M | `SearchPage.tsx`, new `EvalPanel.tsx`, `api/eval.ts` | B5 (eval endpoint) | Run eval against labeled set; show recall@k, MRR, nDCG, latency |
| F5 | Multi-source crawl input | L | `CrawlPage.tsx`, new `SitemapTab.tsx`, new `RssTab.tsx`, `crawlStore` | B4 (multi-source) | Three tabs: URL list / sitemap.xml / RSS feed; preview first 10 URLs before submit |
| F6 | Multi-job queue & concurrency | M | `CrawlPage.tsx`, new `JobQueueTable.tsx`, `crawlStore` | B4 | Show all jobs with status, priority, progress; allow reorder and pause/resume |
| F7 | Failed URLs drill-down | S | `CrawlPage.tsx`, new `FailedUrlsPanel.tsx` | B4 | Per job, list failed URLs with reason; one-click retry |
| F8 | Cleanup CrawlPage polling leak | S | `CrawlPage.tsx`, `crawlStore.ts` | — | `useEffect` cleanup calls `stopPolling()`; verify with React DevTools |
| F9 | Move `knowledgeStore` timers into state | S | `knowledgeStore.ts` | — | `debounceTimer`/`errorTimer` move to zustand state; no module globals |
| F10 | Wire new API client modules | S | `api/eval.ts`, `api/crawl.ts` (add bulk), `api/index.ts` | B2, B5 | TS types match openapi.json; tests for cancellation signal |

## 5. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| FR1 | CrawlPage polling leak exhausts browser/backend under heavy use | High | Med | F8 (must-do before multi-job queue) |
| FR2 | Module-level timer in knowledgeStore breaks bulk operations | High | Med | F9 (must-do before bulk features) |
| FR3 | Upload of large files crashes browser memory | Med | High | F1 must stream chunks; set max-file-size env var; use `URL.createObjectURL` for previews only |
| FR4 | Eval panel shows numbers that users misinterpret (precision vs recall) | Med | Med | F4 — include tooltip explaining each metric; default view shows "no labeled set" empty state |
| FR5 | OpenAPI drift between codex backend and frontend types | Med | High | F10 + CI step `git diff --exit-code frontend/openapi.json frontend/src/api/types.ts` |

## 6. Open Questions

- **Upload size limit** — backend currently has none defined; recommend `MAX_UPLOAD_MB=50` env var with 413 response
- **Drag-drop UX** — single drop zone or per-format targets? Recommend single drop zone with format auto-detect
- **Progress granularity** — backend SSE or client-side chunked upload progress? Recommend chunked + SSE for batch finalization
- **Eval data source** — labeled set curated manually, or auto-derived from KB? Recommend manual `eval/` JSONL files; document authoring format
- **Polling vs SSE** — CrawlPage currently polls; new multi-source work should use existing `/api/crawl/jobs/{id}/stream` SSE and fall back to polling if SSE drops

## 7. Cross-References (to be used by orchestrator Claude)

The following backend work items (from `gap-analysis-backend.md`) unblock frontend features:

- B2 (batch ingest) → F1, F2
- B4 (multi-source crawling) → F5, F6, F7
- B5 (RAG tuning + eval) → F3, F4

Recommend Claude sequence: B2 → B4 → B5 (backend) then F1+F8+F9 first (frontend foundational), then F2/F5/F3, then F4+F6+F7.
