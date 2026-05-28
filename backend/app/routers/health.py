from __future__ import annotations

from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_app_settings, get_run_journal, get_skill_registry
from packages.config import Settings
from packages.enterprise import EnterprisePostgresStore
from packages.llm import DoubaoClient, LLMError
from packages.memory import RunJournal
from packages.schema.api_dto import (
    FetchSmokeRequest,
    HealthCheck,
    HealthStatus,
    LlmSmokeRequest,
    SearchSmokeRequest,
    SmokeResult,
)
from packages.search import PerplexitySearchClient, WebSearchError
from packages.skills.registry import SkillRegistry
from packages.tools import fetch_page

router = APIRouter()
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SkillRegistryDep = Annotated[SkillRegistry, Depends(get_skill_registry)]
RunJournalDep = Annotated[RunJournal, Depends(get_run_journal)]


@router.get("/health", response_model=HealthStatus)
def health(
    settings: SettingsDep,
    skill_registry: SkillRegistryDep,
    journal: RunJournalDep,
) -> HealthStatus:
    checks = [
        HealthCheck(
            name="config",
            status="ok",
            detail=f"default_execution_mode={settings.default_execution_mode}",
        ),
        HealthCheck(
            name="llm_credentials",
            status="ok" if settings.has_llm_credentials else "warn",
            detail="ARK_API_KEY and ARK_MODEL detected"
            if settings.has_llm_credentials
            else "Real mode requires ARK_API_KEY and ARK_MODEL",
        ),
        HealthCheck(
            name="web_search_credentials",
            status="ok" if settings.has_web_search_credentials else "warn",
            detail=f"provider={settings.web_search_provider}",
        ),
        HealthCheck(
            name="skills",
            status="ok" if skill_registry.names() else "error",
            detail=f"{len(skill_registry.names())} skill(s) loaded",
        ),
        HealthCheck(
            name="sqlite",
            status="ok" if journal.load_runs() is not None else "error",
            detail="run journal opened",
        ),
        _enterprise_store_check(settings),
    ]
    status = _rollup_status(checks)
    return HealthStatus(
        status=status,
        service="competiscope-v2-api",
        version="0.1.0",
        checks=checks,
    )


@router.post("/smoke/llm", response_model=SmokeResult)
async def smoke_llm(
    request: LlmSmokeRequest,
    settings: SettingsDep,
) -> SmokeResult:
    if not settings.has_llm_credentials:
        raise HTTPException(status_code=400, detail="ARK_API_KEY and ARK_MODEL are required.")

    start = perf_counter()
    try:
        content = await DoubaoClient(settings).complete_text(
            system="You are a smoke-test assistant. Keep the answer short.",
            user=request.prompt,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SmokeResult(
        component="llm",
        ok=True,
        message="LLM responded.",
        elapsed_ms=_elapsed_ms(start),
        details={
            "model": settings.ark_model,
            "response_chars": len(content),
            "preview": content[:80],
        },
    )


@router.post("/smoke/search", response_model=SmokeResult)
async def smoke_search(
    request: SearchSmokeRequest,
    settings: SettingsDep,
) -> SmokeResult:
    if not settings.has_web_search_credentials:
        raise HTTPException(
            status_code=400,
            detail="PPLX_API_KEY is required for Perplexity search.",
        )

    start = perf_counter()
    try:
        results = await PerplexitySearchClient(settings).search(
            request.query,
            max_results=request.max_results,
        )
    except WebSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    first = results[0] if results else None
    return SmokeResult(
        component="search",
        ok=bool(results),
        message=f"Search returned {len(results)} result(s).",
        elapsed_ms=_elapsed_ms(start),
        details={
            "provider": settings.web_search_provider,
            "query": request.query,
            "result_count": len(results),
            "first_title": first.title if first else None,
            "first_url": first.url if first else None,
        },
    )


@router.post("/smoke/fetch", response_model=SmokeResult)
async def smoke_fetch(request: FetchSmokeRequest) -> SmokeResult:
    start = perf_counter()
    result = await fetch_page(str(request.url))
    return SmokeResult(
        component="fetch",
        ok=result.ok,
        message="Fetch completed." if result.ok else "Fetch failed.",
        elapsed_ms=_elapsed_ms(start),
        details={
            "url": result.url,
            "status_code": result.status_code,
            "title": result.title,
            "content_hash": result.content_hash,
            "error": result.error,
            "text_chars": len(result.text),
        },
    )


def _rollup_status(checks: list[HealthCheck]) -> str:
    if any(check.status == "error" for check in checks):
        return "error"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "ok"


def _enterprise_store_check(settings: Settings) -> HealthCheck:
    backend = settings.enterprise_store_backend
    if backend == "memory":
        return HealthCheck(
            name="enterprise_store",
            status="ok",
            detail="backend=memory",
        )
    if backend == "postgres":
        if not settings.enterprise_database_url:
            return HealthCheck(
                name="enterprise_store",
                status="error",
                detail="ENTERPRISE_DATABASE_URL is required",
            )
        try:
            detail = EnterprisePostgresStore(
                settings.enterprise_database_url,
                auto_migrate=False,
            ).ping()
        except Exception:
            return HealthCheck(
                name="enterprise_store",
                status="error",
                detail="backend=postgres unreachable",
            )
        return HealthCheck(
            name="enterprise_store",
            status="ok",
            detail=detail,
        )
    return HealthCheck(
        name="enterprise_store",
        status="error",
        detail=f"unknown backend={backend}",
    )


def _elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)
