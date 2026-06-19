import sqlite3
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header

from packages.artifacts import ArtifactStorage, build_artifact_storage
from packages.auth import EnterpriseUserContext, normalize_role
from packages.config import Settings, get_settings
from packages.enterprise import EnterpriseMemoryStore, EnterprisePostgresStore, EnterpriseStore
from packages.enterprise.store import DEFAULT_USER_ID
from packages.memory import KBCache, PreferenceMemoryStore, RunJournal
from packages.observability import TraceStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.runtime import RuntimeCommandService
from packages.skills.registry import SkillRegistry
from packages.workflows.service import TemporalWorkflowService


@lru_cache
def get_skill_registry() -> SkillRegistry:
    return SkillRegistry.from_default_path()


@lru_cache
def get_app_settings() -> Settings:
    return get_settings()


@lru_cache
def get_run_journal() -> RunJournal:
    return RunJournal.from_default_path()


@lru_cache
def get_kb_cache() -> KBCache:
    return KBCache.from_default_path()


@lru_cache
def get_preference_memory() -> PreferenceMemoryStore:
    try:
        return PreferenceMemoryStore.from_default_path()
    except (OSError, sqlite3.Error):
        return PreferenceMemoryStore.in_memory()


@lru_cache
def get_trace_store() -> TraceStore:
    return TraceStore.from_default_path()


@lru_cache
def get_graph_checkpointer() -> GraphCheckpointer:
    return GraphCheckpointer.from_default_path()


_RUN_SERVICE_CACHE: dict[tuple[int, ...], RunService] = {}


@lru_cache
def get_enterprise_store() -> EnterpriseStore:
    settings = get_app_settings()
    if settings.enterprise_store_backend == "postgres":
        if not settings.enterprise_database_url:
            raise RuntimeError(
                "ENTERPRISE_DATABASE_URL is required when enterprise store is postgres."
            )
        return EnterprisePostgresStore(settings.enterprise_database_url)
    if settings.enterprise_store_backend == "memory":
        return EnterpriseMemoryStore()
    raise RuntimeError(f"Unknown enterprise store backend: {settings.enterprise_store_backend}")


@lru_cache
def get_artifact_storage() -> ArtifactStorage:
    settings = get_app_settings()
    return build_artifact_storage(
        settings.artifact_storage_backend,
        settings.artifact_storage_root,
    )


def get_enterprise_user_context(
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> EnterpriseUserContext:
    return EnterpriseUserContext(
        user_id=x_user_id or DEFAULT_USER_ID,
        role=normalize_role(x_user_role),
        workspace_id=x_workspace_id or None,
        policy_engine=settings.auth_policy_engine,
        policy_url=settings.auth_policy_url,
        policy_timeout_seconds=settings.auth_policy_timeout_seconds,
    )


def get_run_service(
    skill_registry: Annotated[SkillRegistry | None, Depends(get_skill_registry)] = None,
    settings: Annotated[Settings | None, Depends(get_app_settings)] = None,
    journal: Annotated[RunJournal | None, Depends(get_run_journal)] = None,
    kb_cache: Annotated[KBCache | None, Depends(get_kb_cache)] = None,
    preference_memory: Annotated[
        PreferenceMemoryStore | None, Depends(get_preference_memory)
    ] = None,
    trace_store: Annotated[TraceStore | None, Depends(get_trace_store)] = None,
    graph_checkpointer: Annotated[GraphCheckpointer | None, Depends(get_graph_checkpointer)] = None,
    enterprise_store: Annotated[EnterpriseStore | None, Depends(get_enterprise_store)] = None,
) -> RunService:
    skill_registry = skill_registry or get_skill_registry()
    settings = settings or get_app_settings()
    journal = journal or get_run_journal()
    kb_cache = kb_cache or get_kb_cache()
    preference_memory = preference_memory or get_preference_memory()
    trace_store = trace_store or get_trace_store()
    graph_checkpointer = graph_checkpointer or get_graph_checkpointer()
    enterprise_store = enterprise_store or get_enterprise_store()

    cache_key = (
        id(skill_registry),
        id(settings),
        id(journal),
        id(kb_cache),
        id(preference_memory),
        id(trace_store),
        id(graph_checkpointer),
        id(enterprise_store),
    )
    service = _RUN_SERVICE_CACHE.get(cache_key)
    if service is None:
        service = RunService(
            skill_registry=skill_registry,
            settings=settings,
            journal=journal,
            kb_cache=kb_cache,
            preference_memory=preference_memory,
            trace_store=trace_store,
            graph_checkpointer=graph_checkpointer,
            enterprise_store=enterprise_store,
        )
        _RUN_SERVICE_CACHE[cache_key] = service
    return service


@lru_cache
def get_temporal_workflow_service() -> TemporalWorkflowService:
    return TemporalWorkflowService(get_app_settings())


def get_runtime_command_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    run_service: Annotated[RunService, Depends(get_run_service)],
    workflow_service: Annotated[TemporalWorkflowService, Depends(get_temporal_workflow_service)],
    preference_memory: Annotated[PreferenceMemoryStore, Depends(get_preference_memory)],
) -> RuntimeCommandService:
    enterprise_store = run_service.enterprise_store or get_enterprise_store()
    return RuntimeCommandService(
        settings=settings,
        run_service=run_service,
        workflow_service=workflow_service,
        enterprise_store=enterprise_store,
        preference_memory=preference_memory,
    )
