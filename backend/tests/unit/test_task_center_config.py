import pytest

from packages.config.settings import get_settings


@pytest.fixture(autouse=True)
def isolate_task_center_config(monkeypatch):
    import os

    for key in tuple(os.environ):
        if key.startswith("TASK_CENTER_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("COMPETISCOPE_LOAD_ENV_FILES", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_task_center_defaults_are_disabled_and_bounded() -> None:
    settings = get_settings()
    assert getattr(settings, "task_center_enabled", None) is False
    assert settings.task_center_database_url == ""
    assert settings.task_center_pool_min_size == 1
    assert settings.task_center_pool_max_size == 8
    assert settings.task_center_pool_max_waiting == 128
    assert settings.task_center_pool_timeout_seconds == 5
    assert settings.task_center_statement_timeout_ms == 3000
    assert settings.task_center_lock_timeout_ms == 1000
    assert settings.task_center_dispatch_lease_seconds == 30
    assert settings.task_center_dispatch_max_attempts == 3
    assert settings.task_center_dispatch_retry_seconds == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("TASK_CENTER_DATABASE_URL", ""),
        ("TASK_CENTER_POOL_MIN_SIZE", "0"),
        ("TASK_CENTER_POOL_MAX_SIZE", "0"),
        ("TASK_CENTER_POOL_MAX_WAITING", "0"),
        ("TASK_CENTER_POOL_TIMEOUT_SECONDS", "nan"),
        ("TASK_CENTER_STATEMENT_TIMEOUT_MS", "-1"),
        ("TASK_CENTER_LOCK_TIMEOUT_MS", "oops-secret"),
        ("TASK_CENTER_DISPATCH_LEASE_SECONDS", "0"),
        ("TASK_CENTER_DISPATCH_MAX_ATTEMPTS", "0"),
        ("TASK_CENTER_DISPATCH_RETRY_SECONDS", "-1"),
    ],
)
def test_enabled_task_center_rejects_bad_configuration(monkeypatch, key, value) -> None:
    monkeypatch.setenv("TASK_CENTER_ENABLED", "true")
    monkeypatch.setenv("TASK_CENTER_DATABASE_URL", "postgresql://app:secret@localhost/db")
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError) as caught:
        get_settings()
    assert "secret" not in str(caught.value)


def test_enabled_task_center_rejects_inverted_pool_sizes(monkeypatch) -> None:
    monkeypatch.setenv("TASK_CENTER_ENABLED", "true")
    monkeypatch.setenv("TASK_CENTER_DATABASE_URL", "postgresql://app:secret@localhost/db")
    monkeypatch.setenv("TASK_CENTER_POOL_MIN_SIZE", "3")
    monkeypatch.setenv("TASK_CENTER_POOL_MAX_SIZE", "2")
    with pytest.raises(ValueError, match="TASK_CENTER_POOL"):
        get_settings()


def test_enterprise_pool_env_has_bounded_configuration(monkeypatch):
    from packages.config.settings import get_settings
    monkeypatch.setenv("ENTERPRISE_POOL_MAX_SIZE", "2")
    monkeypatch.setenv("ENTERPRISE_POOL_TIMEOUT_SECONDS", "0.25")
    monkeypatch.setenv("ENTERPRISE_STATEMENT_TIMEOUT_MS", "1200")
    monkeypatch.setenv("ENTERPRISE_LOCK_TIMEOUT_MS", "150")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.enterprise_pool_max_size == 2
        assert settings.enterprise_pool_timeout_seconds == 0.25
        assert settings.enterprise_statement_timeout_ms == 1200
        assert settings.enterprise_lock_timeout_ms == 150
    finally:
        get_settings.cache_clear()
