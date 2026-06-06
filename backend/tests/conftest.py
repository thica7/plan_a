import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def pytest_addoption(parser):
    parser.addoption(
        "--print-timeout", action="store_true", default=False, help="Print timeout configuration and exit"
    )


def pytest_configure(config):
    if config.getoption("--print-timeout"):
        import pytest
        from packages.config import get_settings
        settings = get_settings()
        print(f"llm_timeout_seconds={settings.llm_timeout_seconds}")
        print(f"hitl_timeout_seconds={settings.hitl_timeout_seconds}")
        pytest.exit("Printed timeout settings", returncode=0)


