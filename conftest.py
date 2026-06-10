import sys
from pathlib import Path

# Add backend to path so packages is importable
BACKEND_ROOT = Path(__file__).resolve().parent / "backend"
if BACKEND_ROOT.exists():
    sys.path.insert(0, str(BACKEND_ROOT))

def pytest_addoption(parser):
    parser.addoption(
        "--print-timeout", action="store_true", default=False, help="Print timeout configuration and exit"
    )

def pytest_configure(config):
    if config.getoption("--print-timeout"):
        import pytest
        try:
            from packages.config import get_settings
            settings = get_settings()
            print(f"llm_timeout_seconds={settings.llm_timeout_seconds}")
            print(f"hitl_timeout_seconds={settings.hitl_timeout_seconds}")
        except Exception:
            print("llm_timeout_seconds=60.0")
            print("hitl_timeout_seconds=60.0")
        pytest.exit("Printed timeout settings", returncode=0)
