from functools import lru_cache

from packages.config import Settings, get_settings
from packages.memory import RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.skills.registry import SkillRegistry


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
def get_graph_checkpointer() -> GraphCheckpointer:
    return GraphCheckpointer.from_default_path()


@lru_cache
def get_run_service() -> RunService:
    return RunService(
        skill_registry=get_skill_registry(),
        settings=get_app_settings(),
        journal=get_run_journal(),
        graph_checkpointer=get_graph_checkpointer(),
    )
