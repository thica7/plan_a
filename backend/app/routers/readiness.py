"""Deployment probes: process liveness and required dependency readiness."""

import asyncio
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.deps import get_app_settings, get_run_journal
from app.routers.health import _enterprise_store_check
from packages.config import Settings
from packages.infrastructure.redis_config import get_redis_runtime, redis_options
from packages.memory import RunJournal

router = APIRouter()


@router.get("/livez")
def livez():
    return {"status": "ok"}


async def _temporal_probe(settings):
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
    from temporalio.client import Client

    try:
        async with asyncio.timeout(2):
            client = await Client.connect(settings.temporal_address)
            await client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=settings.temporal_namespace)
            )
        return True
    except Exception:
        return False


async def _qdrant_probe(url):
    try:
        headers = {"api-key": os.environ["QDRANT_API_KEY"]} if os.getenv("QDRANT_API_KEY") else {}
        async with httpx.AsyncClient(timeout=2, follow_redirects=False) as client:
            response = await client.get(url.rstrip("/") + "/readyz", headers=headers)
        return response.status_code == 200
    except Exception:
        return False


async def probe_dependencies(settings, journal):
    checks = []
    try:
        journal_ok = journal.ping()
    except Exception:
        journal_ok = False
    checks.append({"name": "run_journal", "status": "ok" if journal_ok else "error"})
    try:
        async with asyncio.timeout(2):
            enterprise = await asyncio.to_thread(_enterprise_store_check, settings)
        enterprise_ok = enterprise.status == "ok"
    except Exception:
        enterprise_ok = False
    checks.append({"name": "enterprise_store", "status": "ok" if enterprise_ok else "error"})
    if not settings.demo_mode:
        checks.append(
            {
                "name": "llm_configuration",
                "status": "ok" if settings.has_llm_credentials else "error",
            }
        )
    qdrant_url = os.getenv("QDRANT_URL")
    if qdrant_url:
        checks.append(
            {"name": "qdrant", "status": "ok" if await _qdrant_probe(qdrant_url) else "error"}
        )
    elif os.getenv("KB_RETRIEVAL_MODE", "sparse") in {"hybrid", "dense"}:
        checks.append({"name": "qdrant", "status": "error"})
    if settings.run_orchestration_backend == "temporal":
        checks.append(
            {"name": "temporal", "status": "ok" if await _temporal_probe(settings) else "error"}
        )
    options = redis_options()
    if options.cache_enabled or options.rate_limit_enabled:
        redis_ok = await get_redis_runtime().ping()
        checks.append(
            {
                "name": "redis",
                "status": "ok" if redis_ok else "error" if options.rate_limit_enabled else "warn",
            }
        )
    return checks


@router.get("/readyz")
async def readyz(
    settings: Annotated[Settings, Depends(get_app_settings)],
    journal: Annotated[RunJournal, Depends(get_run_journal)],
):
    checks = await probe_dependencies(settings, journal)
    status = (
        "error"
        if any(c["status"] == "error" for c in checks)
        else "warn"
        if any(c["status"] == "warn" for c in checks)
        else "ok"
    )
    return JSONResponse(
        {"status": status, "checks": checks}, status_code=503 if status == "error" else 200
    )
