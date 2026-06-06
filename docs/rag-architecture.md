# RAG + Crawling + Knowledge Base Architecture

## Overview

Competiscope v2 adds three new subsystems for retrieval-augmented analysis:

```
┌─────────────────────────────────────────────────────────┐
│                   React Frontend                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ Run      │ │Knowledge │ │  Search  │ │   Crawl   │  │
│  │ Pages    │ │  Page    │ │  Page    │ │   Page    │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬─────┘  │
│       └────────────┼────────────┼──────────────┘         │
│  ┌─────────────────┴────────────┴────────────────────┐  │
│  │         Zustand Stores + API Client               │  │
│  └──────────────────────┬────────────────────────────┘  │
└─────────────────────────┼──────────────────────────────┘
                          │ REST / SSE
┌─────────────────────────┼──────────────────────────────┐
│                   FastAPI Backend                        │
│  ┌──────────────────────┴────────────────────────────┐  │
│  │           API Routes (knowledge, crawl)            │  │
│  └───┬───────────┬───────────────┬───────────────────┘  │
│  ┌───┴────┐ ┌───┴──────┐ ┌─────┴───────┐              │
│  │  RAG   │ │ Crawler  │ │  Knowledge  │              │
│  │Service │ │ Service  │ │  Repository │              │
│  └───┬────┘ └───┬──────┘ └─────┬───────┘              │
│      └──────────┼──────────────┘                       │
│  ┌──────────────┴──────────────────────────────────┐   │
│  │        LangGraph Collector Tools                 │   │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────────┐  │   │
│  │  │rag_      │ │crawl_    │ │ingest_         │  │   │
│  │  │retrieve  │ │page      │ │document        │  │   │
│  │  └──────────┘ └──────────┘ └────────────────┘  │   │
│  └─────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Storage Layer                       │   │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────────┐  │   │
│  │  │  Qdrant  │ │  SQLite  │ │    FTS5 Index  │  │   │
│  │  │(vectors) │ │(metadata)│ │  (keyword BM25)│  │   │
│  │  └──────────┘ └──────────┘ └────────────────┘  │   │
│  └─────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Choice | Rationale |
|---|---|---|
| Vector DB | Qdrant (Docker) | Open source, HNSW, payload filter, good Python SDK |
| Metadata | SQLite + aiosqlite | Reuse existing architecture, WAL mode |
| Embedding | BAAI/bge-m3 | Multilingual (ZH+EN), open source, 1024 dim |
| Reranker | BAAI/bge-reranker-v2-m3 | Same series, high precision |
| Crawler | httpx + trafilatura | Lightweight, async, good content extraction |
| JS Render | Playwright (optional) | Dynamic page fallback |
| Frontend | React + Zustand + Tailwind | Reuse existing stack |

## Module Structure

```
backend/packages/
  knowledge/
    models.py          # Pydantic: Document, Chunk, Citation, RetrievalHit
    repository.py      # SQLite CRUD (KnowledgeRepository)
    vector_store.py    # Qdrant adapter (VectorStore)
    ingestion.py       # chunk → embed → upsert pipeline
    retrieval.py       # hybrid retrieve + RRF fusion + rerank
  crawler/
    models.py          # CrawlRequest, CrawlResult, ParsedPage
    fetcher.py         # httpx async fetch
    parser.py          # trafilatura HTML → text/markdown
    policy.py          # robots.txt + per-domain rate limits
    scheduler.py       # async crawl queue with concurrency control
  tools/
    rag_retrieve.py    # LangGraph tool: rag_retrieve_tool()
    crawl_page.py      # LangGraph tool: crawl_page_tool()
    ingest_document.py # LangGraph tool: ingest_document_tool()

backend/app/routes/
    knowledge.py       # REST: documents CRUD + RAG search
    crawl.py           # REST: crawl jobs + SSE progress stream

frontend/src/
    api/
      knowledge.ts     # API client: listDocuments, getDocument, deleteDocument, searchKnowledge
      crawl.ts         # API client: listCrawlJobs, createCrawlJob, getCrawlJob
      index.ts         # Re-export all
    stores/
      knowledgeStore.ts
      searchStore.ts
      crawlStore.ts
    pages/
      KnowledgePage.tsx
      SearchPage.tsx
      CrawlPage.tsx
    components/
      SourceCard.tsx
      CitationInline.tsx
```

## LangGraph Integration

No new nodes added. Collector tools are extended:

```yaml
tools_allowlist:
  - rag_retrieve    # NEW: query knowledge base
  - web_search      # existing
  - crawl_page      # NEW: fetch + parse page
  - ingest_document # NEW: store document in KB
```

Collector strategy:
1. `rag_retrieve(query)` — check existing KB first
2. `web_search(query)` — if KB insufficient
3. `crawl_page(url)` — fetch candidate URLs
4. `ingest_document(page)` — store new pages
5. `finish(RawSource[])` — close with citations

## Retrieval Pipeline

```
query → embed → dense search (Qdrant)  ─┐
query → FTS5 keyword search (SQLite)    ─┤→ RRF fusion → reranker → top-K hits
```

## Crawl Pipeline

```
URL → robots.txt check → rate limit → httpx fetch → trafilatura parse → content_hash → dedup → ingest
```

## Docker

Qdrant is added to `docker-compose.yml`:
```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /api/knowledge/documents | List + filter documents |
| GET | /api/knowledge/documents/{id} | Document detail |
| DELETE | /api/knowledge/documents/{id} | Delete document |
| POST | /api/knowledge/search | RAG retrieval |
| GET | /api/crawl/jobs | List crawl jobs |
| POST | /api/crawl/jobs | Create crawl job |
| GET | /api/crawl/jobs/{id} | Job detail |
| GET | /api/crawl/jobs/{id}/stream | SSE progress |

## Phase 1 → Phase 2 → Phase 3 Evolution

1. **Phase 1 (current)**: SQLite + Qdrant local + httpx/trafilatura + bge-m3
2. **Phase 2**: Add Playwright fallback + reranker + crawl queue (asyncio.Queue → Celery)
3. **Phase 3**: SQLite → PostgreSQL, Qdrant local → Qdrant Cloud, crawler → independent service
