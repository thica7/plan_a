from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_ENTERPRISE_DATABASE_URL = (
    "postgresql://competiscope:competiscope@127.0.0.1:55432/competiscope?connect_timeout=5"
)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    demo_mode: bool
    ark_api_key: str | None
    ark_model: str | None
    ark_base_url: str
    llm_timeout_seconds: float
    llm_temperature: float
    pplx_api_key: str | None = None
    pplx_base_url: str = "https://api.perplexity.ai"
    web_search_provider: str = "perplexity"
    max_iterations: int = 2
    auto_redo_enabled: bool = True
    auto_redo_warn_enabled: bool = True
    hitl_enabled: bool = False
    hitl_timeout_seconds: float = 60.0
    collector_react_enabled: bool = True
    collector_react_max_turns: int = 3
    analyst_react_enabled: bool = True
    analyst_react_max_turns: int = 3
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    enterprise_store_backend: str = "postgres"
    enterprise_database_url: str | None = DEFAULT_ENTERPRISE_DATABASE_URL

    @property
    def has_llm_credentials(self) -> bool:
        return bool(self.ark_api_key and self.ark_model)

    @property
    def has_web_search_credentials(self) -> bool:
        return self.web_search_provider == "perplexity" and bool(self.pplx_api_key)

    @property
    def default_execution_mode(self) -> str:
        if not self.demo_mode and self.has_llm_credentials:
            return "real"
        return "demo"


@lru_cache
def get_settings() -> Settings:
    root = Path.cwd()
    _load_env_file(root / ".env")
    _load_env_file(root / "backend" / ".env")
    enterprise_backend = os.getenv("ENTERPRISE_STORE_BACKEND", "postgres").strip().lower()
    enterprise_database_url = os.getenv("ENTERPRISE_DATABASE_URL")
    if enterprise_backend == "postgres" and not enterprise_database_url:
        enterprise_database_url = DEFAULT_ENTERPRISE_DATABASE_URL
    return Settings(
        demo_mode=_env_bool("DEMO_MODE", True),
        ark_api_key=os.getenv("ARK_API_KEY") or None,
        ark_model=os.getenv("ARK_MODEL") or None,
        ark_base_url=os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip(
            "/"
        ),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        pplx_api_key=os.getenv("PPLX_API_KEY") or os.getenv("PERPLEXITY_API_KEY") or None,
        pplx_base_url=os.getenv("PPLX_BASE_URL", "https://api.perplexity.ai").rstrip("/"),
        web_search_provider=os.getenv("WEB_SEARCH_PROVIDER", "perplexity").strip().lower(),
        max_iterations=max(1, int(os.getenv("MAX_ITERATIONS", "2"))),
        auto_redo_enabled=_env_bool("AUTO_REDO_ENABLED", True),
        auto_redo_warn_enabled=_env_bool("AUTO_REDO_WARN_ENABLED", True),
        hitl_enabled=_env_bool("HITL_ENABLED", False),
        hitl_timeout_seconds=max(1.0, float(os.getenv("HITL_TIMEOUT_SECONDS", "60"))),
        collector_react_enabled=_env_bool("COLLECTOR_REACT_ENABLED", True),
        collector_react_max_turns=max(1, min(6, int(os.getenv("COLLECTOR_REACT_MAX_TURNS", "3")))),
        analyst_react_enabled=_env_bool("ANALYST_REACT_ENABLED", True),
        analyst_react_max_turns=max(1, min(6, int(os.getenv("ANALYST_REACT_MAX_TURNS", "3")))),
        langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY") or None,
        langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY") or None,
        langfuse_host=os.getenv("LANGFUSE_HOST") or None,
        enterprise_store_backend=enterprise_backend,
        enterprise_database_url=enterprise_database_url,
    )
