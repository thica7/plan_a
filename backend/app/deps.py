import sqlite3
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header

from packages.artifacts import LocalArtifactStorage
from packages.auth import EnterpriseUserContext, normalize_role
from packages.config import Settings, get_settings
from packages.enterprise import EnterpriseMemoryStore, EnterprisePostgresStore, EnterpriseStore
from packages.enterprise.store import DEFAULT_USER_ID
from packages.memory import KBCache, PreferenceMemoryStore, RunJournal
from packages.observability import TraceStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
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
def get_artifact_storage() -> LocalArtifactStorage:
    settings = get_app_settings()
    if settings.artifact_storage_backend != "local":
        raise RuntimeError(f"Unknown artifact storage backend: {settings.artifact_storage_backend}")
    return LocalArtifactStorage(settings.artifact_storage_root)


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


@lru_cache
def get_run_service() -> RunService:
    return RunService(
        skill_registry=get_skill_registry(),
        settings=get_app_settings(),
        journal=get_run_journal(),
        kb_cache=get_kb_cache(),
        preference_memory=get_preference_memory(),
        trace_store=get_trace_store(),
        graph_checkpointer=get_graph_checkpointer(),
        enterprise_store=get_enterprise_store(),
    )


@lru_cache
def get_temporal_workflow_service() -> TemporalWorkflowService:
    return TemporalWorkflowService(get_app_settings())
