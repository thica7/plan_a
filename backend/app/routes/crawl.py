"""Crawler API routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.deps import get_enterprise_store, get_enterprise_user_context
from app.knowledge_access import resolve_knowledge_scope, select_project, stored_job_scope
from app.routes.knowledge import get_embedding_provider, ingest_crawl_result
from packages.auth import EnterpriseUserContext, can_access_workspace
from packages.crawler.models import (
    CrawlFrontierStats,
    CrawlRequest,
    CrawlResult,
    CrawlSource,
    CrawlSourceCreate,
)
from packages.crawler.repository import CrawlerRepository
from packages.crawler.sources import processor_for
from packages.enterprise.store import DEFAULT_WORKSPACE_ID, EnterpriseStore
from packages.knowledge.models import KnowledgeScope
from packages.knowledge.repository import KnowledgeRepository

router = APIRouter()
EnterpriseUserDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]
EnterpriseStoreDep = Annotated[EnterpriseStore, Depends(get_enterprise_store)]


class CrawlJobCreate(BaseModel):
    project_id: str | None = None
    market: str | None = None
    url: str
    run_id: str | None = None
    competitor: str | None = None
    dimension: str | None = None


class CrawlJob(BaseModel):
    workspace_id: str | None = None
    project_id: str | None = None
    market: str | None = None
    id: str
    run_id: str | None = None
    url: str
    competitor: str | None = None
    dimension: str | None = None
    status: str
    attempt_count: int
    error: str | None = None
    result_metadata: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime


class CrawlSourceDetail(BaseModel):
    source: CrawlSource
    progress: CrawlFrontierStats
    discovered_count: int = 0
    warnings: list[str] = Field(default_factory=list)


async def _open_repository() -> KnowledgeRepository:
    repo = KnowledgeRepository()
    await repo.initialise()
    return repo


async def _open_crawler_repository() -> CrawlerRepository:
    repo = CrawlerRepository()
    await repo.initialise()
    return repo


async def _fetch_jobs(
    *,
    status: str | None = None,
    scope: KnowledgeScope,
    limit: int = 50,
    offset: int = 0,
) -> list[CrawlJob]:
    repo = await _open_repository()
    try:
        rows = await repo.list_crawl_jobs(status=status, limit=limit, offset=offset, scope=scope)
        return [_row_to_crawl_job(row) for row in rows]
    finally:
        await repo.close()


async def _fetch_job(job_id: str, *, scope: KnowledgeScope | None = None) -> CrawlJob | None:
    repo = await _open_repository()
    try:
        row = await repo.get_crawl_job(job_id, scope=scope)
        return _row_to_crawl_job(row) if row else None
    finally:
        await repo.close()


def _row_to_crawl_job(row: aiosqlite.Row) -> CrawlJob:
    return CrawlJob(
        workspace_id=dict(row).get("workspace_id"),
        project_id=dict(row).get("project_id"),
        market=dict(row).get("market"),
        id=row["id"],
        run_id=row["run_id"],
        url=row["url"],
        competitor=row["competitor"],
        dimension=row["dimension"],
        status=row["status"],
        attempt_count=row["attempt_count"],
        error=row["error"],
        result_metadata=_load_result_metadata(row["result_metadata_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _load_result_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


@router.get("/crawl/jobs", response_model=list[CrawlJob])
async def list_crawl_jobs(
    user: EnterpriseUserDep,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    store: EnterpriseStoreDep = None,
    project_id: str | None = None,
    include_workspace_library: bool = False,
) -> list[CrawlJob]:
    scope = resolve_knowledge_scope(
        user, "source:read", store=store,
        project_id=select_project(project_id, None),
        include_workspace_library=include_workspace_library,
    )
    return await _fetch_jobs(status=status, limit=limit, offset=offset, scope=scope)


@router.post("/crawl/sources", response_model=CrawlSourceDetail, status_code=201)
async def create_crawl_source(
    request: CrawlSourceCreate,
    user: EnterpriseUserDep,
    store: EnterpriseStoreDep = None,
    project_id: str | None = None,
    include_workspace_library: bool = False,
) -> CrawlSourceDetail:
    scope = resolve_knowledge_scope(
        user, "source:write", store=store,
        project_id=select_project(project_id, request.project_id),
        include_workspace_library=False,
    )
    repo = await _open_crawler_repository()
    try:
        config = request.config
        competitor = (
            request.competitor if request.competitor is not None else config.get("competitor")
        )
        dimension = request.dimension if request.dimension is not None else config.get("dimension")
        priority = (
            request.priority if request.priority is not None else int(config.get("priority") or 100)
        )
        source = await repo.create_source(
            request.type,
            config,
            competitor=competitor,
            dimension=dimension,
            priority=priority,
            scope=scope,
            market=request.market,
        )
        urls = await processor_for(source.type).expand(source)
        warnings = _crawl_source_warnings(source.type, urls)
        if urls:
            await repo.add_frontier_items(
                urls,
                source_type=source.type,
                source_id=source.id,
                competitor=source.competitor,
                dimension=source.dimension,
                priority=source.priority,
                run_id=source.id,
                max_urls=int(config.get("max_urls") or len(urls) or 1),
                require_source=True,
            )
        progress = await repo.stats(source_id=source.id, scope=scope)
    finally:
        await repo.close()

    if urls:
        asyncio.create_task(_run_frontier_until_idle())
    return CrawlSourceDetail(
        source=source,
        progress=progress,
        discovered_count=len(urls),
        warnings=warnings,
    )


@router.get("/crawl/sources", response_model=list[CrawlSource])
async def list_crawl_sources(
    user: EnterpriseUserDep, store: EnterpriseStoreDep = None,
    project_id: str | None = None, include_workspace_library: bool = False,
) -> list[CrawlSource]:
    scope = resolve_knowledge_scope(
        user, "source:read", store=store, project_id=select_project(project_id, None),
        include_workspace_library=include_workspace_library,
    )
    repo = await _open_crawler_repository()
    try:
        return await repo.list_sources(scope=scope)
    finally:
        await repo.close()


@router.get("/crawl/sources/{source_id}", response_model=CrawlSourceDetail)
async def get_crawl_source(
    source_id: str, user: EnterpriseUserDep, store: EnterpriseStoreDep = None,
    project_id: str | None = None, include_workspace_library: bool = False,
) -> CrawlSourceDetail:
    scope = resolve_knowledge_scope(
        user, "source:read", store=store, project_id=select_project(project_id, None),
        include_workspace_library=include_workspace_library,
    )
    repo = await _open_crawler_repository()
    try:
        source = await repo.get_source(source_id, scope=scope)
        if source is None:
            raise HTTPException(status_code=404, detail="Crawl source not found")
        progress = await repo.stats(source_id=source_id, scope=scope)
        return CrawlSourceDetail(source=source, progress=progress)
    finally:
        await repo.close()


@router.delete("/crawl/sources/{source_id}", status_code=204)
async def delete_crawl_source(
    source_id: str, user: EnterpriseUserDep, store: EnterpriseStoreDep = None,
    project_id: str | None = None, include_workspace_library: bool = False,
) -> None:
    scope = resolve_knowledge_scope(
        user, "source:write", store=store, project_id=select_project(project_id, None),
        include_workspace_library=False,
    )
    repo = await _open_crawler_repository()
    try:
        deleted = await repo.delete_source(source_id, scope=scope)
        if not deleted:
            raise HTTPException(status_code=404, detail="Crawl source not found")
    finally:
        await repo.close()


@router.post("/crawl/sources/{source_id}/retry", response_model=CrawlSourceDetail)
async def retry_crawl_source(
    source_id: str, user: EnterpriseUserDep, store: EnterpriseStoreDep = None,
    project_id: str | None = None, include_workspace_library: bool = False,
) -> CrawlSourceDetail:
    scope = resolve_knowledge_scope(
        user, "source:write", store=store, project_id=select_project(project_id, None),
        include_workspace_library=False,
    )
    repo = await _open_crawler_repository()
    try:
        source = await repo.get_source(source_id, scope=scope)
        if source is None:
            raise HTTPException(status_code=404, detail="Crawl source not found")
        await repo.retry_failed(source_id, scope=scope)
        progress = await repo.stats(source_id=source_id, scope=scope)
    finally:
        await repo.close()

    asyncio.create_task(_run_frontier_until_idle())
    return CrawlSourceDetail(source=source, progress=progress)


def _crawl_source_warnings(source_type: str, urls: list[str]) -> list[str]:
    if urls:
        return []
    if source_type in {"web_search", "pricing", "official_docs", "changelog", "review_site"}:
        return [
            "source expanded to 0 URLs; check PPLX_API_KEY, query, include_domains, "
            "and url_patterns"
        ]
    return ["source expanded to 0 URLs"]


@router.get("/crawl/frontier/stats", response_model=CrawlFrontierStats)
async def get_crawl_frontier_stats(
    user: EnterpriseUserDep, store: EnterpriseStoreDep = None,
    project_id: str | None = None, include_workspace_library: bool = False,
) -> CrawlFrontierStats:
    scope = resolve_knowledge_scope(
        user, "source:read", store=store, project_id=select_project(project_id, None),
        include_workspace_library=include_workspace_library,
    )
    repo = await _open_crawler_repository()
    try:
        return await repo.stats(scope=scope)
    finally:
        await repo.close()


@router.post("/crawl/jobs", response_model=CrawlJob, status_code=201)
async def create_crawl_job(
    request: CrawlJobCreate, user: EnterpriseUserDep,
    store: EnterpriseStoreDep = None,
    project_id: str | None = None,
    include_workspace_library: bool = False,
) -> CrawlJob:
    scope = resolve_knowledge_scope(
        user, "source:write", store=store,
        project_id=select_project(project_id, request.project_id),
        include_workspace_library=False,
    )
    repo = await _open_repository()
    try:
        job_id = await repo.create_crawl_job(
            request.url,
            scope=scope, market=request.market,
            run_id=request.run_id,
            competitor=request.competitor,
            dimension=request.dimension,
        )
    finally:
        await repo.close()

    asyncio.create_task(_run_crawl_job(job_id))
    job = await _fetch_job(job_id, scope=scope)
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return job


@router.get("/crawl/jobs/{job_id}", response_model=CrawlJob)
async def get_crawl_job(
    job_id: str, user: EnterpriseUserDep,
    store: EnterpriseStoreDep = None,
    project_id: str | None = None,
    include_workspace_library: bool = False,
) -> CrawlJob:
    scope = resolve_knowledge_scope(
        user, "source:read", store=store,
        project_id=select_project(project_id, None),
        include_workspace_library=include_workspace_library,
    )
    job = await _fetch_job(job_id, scope=scope)
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return job


@router.get("/crawl/jobs/{job_id}/stream")
async def stream_crawl_job(
    job_id: str,
    request: Request,
    user: EnterpriseUserDep,
    store: EnterpriseStoreDep = None,
    project_id: str | None = None,
    include_workspace_library: bool = False,
) -> EventSourceResponse:
    scope = resolve_knowledge_scope(
        user, "source:read", store=store,
        project_id=select_project(project_id, None),
        include_workspace_library=include_workspace_library,
    )
    if await _fetch_job(job_id, scope=scope) is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        previous_payload = ""
        while True:
            if await request.is_disconnected():
                break
            job = await _fetch_job(job_id, scope=scope)
            if job is None:
                yield {"event": "error", "data": "Crawl job not found"}
                break
            payload = json.dumps(job.model_dump(mode="json"))
            if payload != previous_payload:
                previous_payload = payload
                yield {"event": "job", "data": payload}
            if job.status in {"success", "failed", "cancelled"}:
                break
            await asyncio.sleep(1.0)

    return EventSourceResponse(event_generator())


async def _run_crawl_job(job_id: str) -> CrawlJob:
    job = await _fetch_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")

    repo = await _open_repository()
    try:
        row = await repo.get_crawl_job(job_id)
        try:
            scope = stored_job_scope(row)
        except ValueError as exc:
            await repo.update_crawl_job(job_id, status="failed", error=str(exc))
            return (await _fetch_job(job_id))
        await repo.update_crawl_job(job_id, status="running")
    finally:
        await repo.close()

    from packages.crawler.scheduler import CrawlerScheduler

    scheduler = CrawlerScheduler()
    try:
        result = await scheduler.crawl_sync(
            CrawlRequest(
                url=job.url,
                run_id=job.run_id,
                competitor=job.competitor,
                dimension=job.dimension,
            )
        )
        final_status = "success" if result.success else "failed"
        error = result.error
        result_metadata: dict[str, Any] = {}
        if result.success:
            ingest_repo = await _open_repository()
            try:
                result_metadata = await ingest_crawl_result(
                    ingest_repo,
                    result,
                    embedding_provider=get_embedding_provider(),
                    scope=scope, market=job.market,
                )
            finally:
                await ingest_repo.close()
    except Exception as exc:
        final_status = "failed"
        error = str(exc)
        result_metadata = {}
    finally:
        await scheduler.stop()

    repo = await _open_repository()
    try:
        await repo.update_crawl_job(
            job_id,
            status=final_status,
            error=error,
            result_metadata=result_metadata,
        )
    finally:
        await repo.close()

    updated = await _fetch_job(job_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return updated


async def _run_frontier_until_idle() -> None:
    from packages.crawler.scheduler import CrawlerScheduler

    scheduler = CrawlerScheduler(
        max_concurrent=2,
        pending_batch_size=4,
        on_result=_ingest_frontier_result,
    )
    await scheduler.start()
    try:
        for _ in range(300):
            repo = await _open_crawler_repository()
            try:
                stats = await repo.stats()
            finally:
                await repo.close()
            if stats.queued == 0 and stats.running == 0:
                break
            await asyncio.sleep(1.0)
    finally:
        await scheduler.stop()


async def _ingest_frontier_result(result: CrawlResult) -> None:
    if not result.success or not result.request.source_id:
        return
    crawler_repo = await _open_crawler_repository()
    try:
        source = await crawler_repo.get_source(result.request.source_id)
    finally:
        await crawler_repo.close()
    if source is None or not source.workspace_id or not source.workspace_id.strip():
        return
    scope = KnowledgeScope(workspace_id=source.workspace_id, project_id=source.project_id)
    result = result.model_copy(update={"request": result.request.model_copy(update={
        "competitor": source.competitor, "dimension": source.dimension,
    })})
    repo = await _open_repository()
    try:
        await ingest_crawl_result(
            repo,
            result,
            embedding_provider=get_embedding_provider(),
            scope=scope,
            market=source.market,
            crawl_source_id=source.id,
        )
    finally:
        await repo.close()


def _require_crawl_access(user: EnterpriseUserContext, action: str) -> None:
    workspace_id = user.workspace_id or DEFAULT_WORKSPACE_ID
    if not can_access_workspace(user, workspace_id, action):
        raise HTTPException(status_code=403, detail="Insufficient workspace permission")
