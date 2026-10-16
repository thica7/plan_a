import pytest

from packages.infrastructure import redis_config


@pytest.fixture(autouse=True)
def clean_redis_config(monkeypatch):
    for name in (
        "REDIS_CACHE_ENABLED",
        "REDIS_RATE_LIMIT_ENABLED",
        "REDIS_URL",
        "REDIS_CACHE_TTL_SECONDS",
        "REDIS_RATE_LIMIT_REQUESTS",
        "REDIS_RATE_LIMIT_WINDOW_SECONDS",
        "REDIS_CONNECT_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    redis_config.redis_options.cache_clear()
    redis_config.get_redis_runtime.cache_clear()
    yield
    redis_config.redis_options.cache_clear()
    redis_config.get_redis_runtime.cache_clear()


def test_defaults_disable_both_features_and_hide_url_in_repr(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://user:private@localhost:6379/0")
    options = redis_config.redis_options()
    assert not options.cache_enabled and not options.rate_limit_enabled
    assert "private" not in repr(options)
    assert options.cache_ttl_seconds == 300


@pytest.mark.parametrize(
    "name,value",
    [
        ("REDIS_CACHE_ENABLED", "maybe"),
        ("REDIS_RATE_LIMIT_ENABLED", "yes"),
        ("REDIS_CACHE_TTL_SECONDS", "0"),
        ("REDIS_CACHE_TTL_SECONDS", "86401"),
        ("REDIS_RATE_LIMIT_REQUESTS", "-1"),
        ("REDIS_RATE_LIMIT_WINDOW_SECONDS", "3601"),
        ("REDIS_CONNECT_TIMEOUT_SECONDS", "nan"),
        ("REDIS_CONNECT_TIMEOUT_SECONDS", "inf"),
        ("REDIS_CONNECT_TIMEOUT_SECONDS", "0"),
        ("REDIS_CONNECT_TIMEOUT_SECONDS", "3"),
    ],
)
def test_invalid_configuration_is_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        redis_config.redis_options()
