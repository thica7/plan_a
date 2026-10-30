from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# isort: split
from app import deps
from app.routers import runtime
from packages.config.settings import Settings, get_settings
from packages.schema.api_dto import RuntimeConfig


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setenv("COMPETISCOPE_LOAD_ENV_FILES", "0")
    monkeypatch.delenv("GRAPH_CHECKPOINT_PATH", raising=False)
    monkeypatch.delenv("TASK_CENTER_ENABLED", raising=False)
    get_settings.cache_clear()
    deps.get_graph_checkpointer.cache_clear()
    yield
    get_settings.cache_clear()
    deps.get_graph_checkpointer.cache_clear()


def test_checkpoint_default_and_env_override(monkeypatch, tmp_path):
    assert getattr(Settings(), "graph_checkpoint_path", None) == "runs/graph_checkpoints.db"
    path = str(tmp_path / "isolated" / "graph.db")
    monkeypatch.setenv("GRAPH_CHECKPOINT_PATH", path)
    assert getattr(get_settings(), "graph_checkpoint_path", None) == path


@pytest.mark.parametrize(
    "field,env_key,getter,filename",
    [
        ("kb_cache_path", "KB_CACHE_PATH", deps.get_kb_cache, "kb_cache.db"),
        ("trace_db_path", "TRACE_DB_PATH", deps.get_trace_store, "traces.db"),
        (
            "preference_memory_path",
            "PREFERENCE_MEMORY_PATH",
            deps.get_preference_memory,
            "preference_memory.db",
        ),
    ],
)
def test_profile_stores_use_explicit_settings_and_preserve_legacy_defaults(
    monkeypatch,
    tmp_path,
    field,
    env_key,
    getter,
    filename,
):
    assert getattr(Settings(), field, None) == f"runs/{filename}"
    paths = []
    try:
        for profile in ("one", "two"):
            path = tmp_path / profile / filename
            monkeypatch.setenv(env_key, str(path))
            get_settings.cache_clear()
            settings = get_settings()
            assert getattr(settings, field, None) == str(path)
            monkeypatch.setattr(deps, "get_app_settings", lambda value=settings: value)
            getter.cache_clear()
            store = getter()
            assert store._db_path == path
            assert path.is_file()
            paths.append(path)
        assert paths[0] != paths[1]
    finally:
        getter.cache_clear()


def test_real_checkpointer_uses_settings_dependency(monkeypatch, tmp_path):
    path = tmp_path / "isolated" / "graph.db"
    monkeypatch.setattr(deps, "get_app_settings", lambda: Settings(graph_checkpoint_path=str(path)))
    checkpointer = deps.get_graph_checkpointer()
    assert checkpointer._db_path == path

    async def open_and_close():
        await checkpointer.open()
        await checkpointer.aclose()

    asyncio.run(open_and_close())
    assert path.is_file()


@pytest.mark.parametrize("enabled", [False, True])
def test_runtime_api_maps_capability_without_checkpoint_path(enabled):
    app = FastAPI()
    app.include_router(runtime.router, prefix="/api")
    settings = Settings(task_center_enabled=enabled, task_center_database_url="app-only")
    app.dependency_overrides[deps.get_app_settings] = lambda: settings
    with TestClient(app) as client:
        response = client.get("/api/runtime")
    assert response.status_code == 200
    assert response.json().get("task_center_enabled") is enabled
    assert "graph_checkpoint_path" not in response.json()


def test_runtime_dto_accepts_legacy_payload_with_disabled_default():
    payload = runtime.get_runtime(Settings()).model_dump()
    payload.pop("task_center_enabled", None)
    assert getattr(RuntimeConfig.model_validate(payload), "task_center_enabled", None) is False
