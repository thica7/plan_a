from __future__ import annotations

import socket
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
from packages.workflows.service import temporal_cutover_status

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
            detail=_llm_credentials_detail(settings),
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
            status="ok" if journal.ping() else "error",
            detail="run journal opened",
        ),
        _enterprise_store_check(settings),
        _auth_policy_check(settings),
        _temporal_cutover_check(settings),
        _temporal_server_check(settings),
        HealthCheck(
            name="compliance",
            status="ok" if settings.compliance_redaction_enabled else "warn",
            detail=(
                f"redaction_enabled={settings.compliance_redaction_enabled} "
                f"api_keys={settings.compliance_redact_api_keys} "
                f"emails={settings.compliance_redact_emails} "
                f"phones={settings.compliance_redact_phones}"
            ),
        ),
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
        raise HTTPException(
            status_code=400,
            detail=(
                "ARK_API_KEY and ARK_MODEL or BACKUP_LLM_API_KEY and "
                "BACKUP_LLM_MODEL are required."
            ),
        )

    start = perf_counter()
    client = DoubaoClient(settings)
    try:
        content = await client.complete_text(
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
            "provider": client.last_provider(),
            "model": client.last_model(),
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


def _llm_credentials_detail(settings: Settings) -> str:
    if settings.has_primary_llm_credentials and settings.has_backup_llm_credentials:
        return "primary ARK and backup LLM credentials detected"
    if settings.has_primary_llm_credentials:
        return "primary ARK credentials detected"
    if settings.has_backup_llm_credentials:
        return "backup LLM credentials detected"
    return "Real mode requires primary ARK or BACKUP_LLM credentials"


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


def _auth_policy_check(settings: Settings) -> HealthCheck:
    engine = settings.auth_policy_engine
    if engine == "internal":
        return HealthCheck(
            name="auth_policy",
            status="ok",
            detail="engine=internal",
        )
    if not settings.auth_policy_url:
        return HealthCheck(
            name="auth_policy",
            status="error",
            detail=f"engine={engine} AUTH_POLICY_URL is required",
        )
    return HealthCheck(
        name="auth_policy",
        status="ok",
        detail=f"engine={engine} url_configured=true",
    )


def _temporal_cutover_check(settings: Settings) -> HealthCheck:
    cutover = temporal_cutover_status(settings)
    return HealthCheck(
        name="temporal_cutover",
        status="ok" if cutover.ready else "error",
        detail=(
            f"backend={cutover.backend} target_percent={cutover.target_percent} "
            f"reason={cutover.reason}"
        ),
    )


def _temporal_server_check(settings: Settings) -> HealthCheck:
    host, port = _parse_host_port(settings.temporal_address)
    if host is None or port is None:
        return HealthCheck(
            name="temporal_server",
            status="error" if settings.run_orchestration_backend == "temporal" else "warn",
            detail=f"invalid address={settings.temporal_address}",
        )
    try:
        with socket.create_connection((host, port), timeout=0.5):
            pass
    except OSError:
        return HealthCheck(
            name="temporal_server",
            status="error" if settings.run_orchestration_backend == "temporal" else "warn",
            detail=(
                f"unreachable address={settings.temporal_address} "
                f"backend={settings.run_orchestration_backend}"
            ),
        )
    return HealthCheck(
        name="temporal_server",
        status="ok",
        detail=(
            f"address={settings.temporal_address} namespace={settings.temporal_namespace} "
            f"task_queue={settings.temporal_task_queue}"
        ),
    )


def _parse_host_port(address: str) -> tuple[str | None, int | None]:
    if ":" not in address:
        return None, None
    host, raw_port = address.rsplit(":", 1)
    host = host.strip("[]") or "127.0.0.1"
    try:
        port = int(raw_port)
    except ValueError:
        return None, None
    return host, port


def _elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)
