import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("COMPETISCOPE_LOAD_ENV_FILES", "0")

_HOST_ENV_ISOLATION_FLAG = "COMPETISCOPE_TEST_ALLOW_HOST_ENV"
_ISOLATED_SETTINGS_ENV_VARS = {
    "ARK_API_KEY",
    "ARK_MODEL",
    "ARK_BASE_URL",
    "BACKUP_LLM_API_KEY",
    "BACKUP_LLM_BASE_URL",
    "BACKUP_LLM_MODEL",
    "PPLX_API_KEY",
    "PERPLEXITY_API_KEY",
    "PPLX_BASE_URL",
    "WEB_SEARCH_PROVIDER",
    "DEMO_MODE",
    "LLM_TIMEOUT_SECONDS",
    "LLM_TEMPERATURE",
    "LLM_MAX_RETRIES",
    "LLM_RETRY_BACKOFF_SECONDS",
    "ENTERPRISE_STORE_BACKEND",
    "ENTERPRISE_DATABASE_URL",
    "RUN_ORCHESTRATION_BACKEND",
    "TEMPORAL_TRAFFIC_PERCENT",
    "WRITER_TIMEOUT_SECONDS",
}

if os.getenv(_HOST_ENV_ISOLATION_FLAG, "").strip().lower() not in {"1", "true", "yes", "on"}:
    for env_name in _ISOLATED_SETTINGS_ENV_VARS:
        os.environ.pop(env_name, None)


def pytest_addoption(parser):
    parser.addoption(
        "--print-timeout",
        action="store_true",
        default=False,
        help="Print timeout configuration and exit",
    )


def pytest_configure(config):
    if config.getoption("--print-timeout"):
        import pytest

        from packages.config import get_settings

        settings = get_settings()
        print(f"llm_timeout_seconds={settings.llm_timeout_seconds}")
        print(f"hitl_timeout_seconds={settings.hitl_timeout_seconds}")
        pytest.exit("Printed timeout settings", returncode=0)
