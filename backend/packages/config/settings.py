from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

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


def _env_file_candidates(
    *,
    cwd: Path | None = None,
    project_root: Path | None = None,
) -> list[Path]:
    runtime_cwd = cwd or Path.cwd()
    source_root = project_root or Path(__file__).resolve().parents[3]
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in (runtime_cwd, source_root):
        for path in (root / ".env", root / "backend" / ".env"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(path)
    return candidates


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        return default
    return value


def _env_csv(name: str) -> tuple[str, ...]:
    value = os.getenv(name, "")
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class Settings:
    demo_mode: bool
    ark_api_key: str | None
    ark_model: str | None
    ark_base_url: str
    llm_timeout_seconds: float
    llm_temperature: float
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 0.25
    backup_llm_api_key: str | None = None
    backup_llm_base_url: str = "https://openrouter.ai/api/v1"
    backup_llm_model: str | None = None
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
    collector_target_verified_sources_per_branch: int = 3
    collector_search_max_results: int = 6
    analyst_react_enabled: bool = True
    analyst_react_max_turns: int = 3
    analyst_react_fanout_threshold: int = 8
    analyst_branch_timeout_seconds: float = 25.0
    analyst_fanout_branch_timeout_seconds: float = 8.0
    comparator_timeout_seconds: float = 8.0
    writer_timeout_seconds: float = 90.0
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    otel_export_endpoint: str | None = None
    enterprise_store_backend: str = "postgres"
    enterprise_database_url: str | None = DEFAULT_ENTERPRISE_DATABASE_URL
    run_orchestration_backend: Literal["langgraph", "temporal"] = "temporal"
    temporal_traffic_percent: int = 100
    temporal_address: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "competitive-intel"
    compliance_redaction_enabled: bool = True
    compliance_redact_api_keys: bool = True
    compliance_redact_emails: bool = True
    compliance_redact_phones: bool = True
    compliance_allowed_domains: tuple[str, ...] = ()
    compliance_blocked_domains: tuple[str, ...] = ()
    compliance_require_source_urls: bool = False
    compliance_require_trace_context: bool = True
    retention_project_days: int = 1095
    retention_evidence_days: int = 730
    retention_artifact_days: int = 730
    retention_report_version_days: int = 1095
    retention_audit_log_days: int = 2555
    retention_expiring_soon_days: int = 30
    retention_physical_delete_enabled: bool = False
    pydantic_ai_model_backed_enabled: bool = False
    pydantic_ai_model_name: str | None = None
    artifact_storage_backend: Literal["local", "external", "s3", "oss"] = "local"
    artifact_storage_root: str = "data/artifacts"
    auth_policy_engine: Literal["internal", "opa", "cerbos"] = "internal"
    auth_policy_url: str | None = None
    auth_policy_timeout_seconds: float = 1.0

    @property
    def has_llm_credentials(self) -> bool:
        return self.has_primary_llm_credentials or self.has_backup_llm_credentials

    @property
    def has_primary_llm_credentials(self) -> bool:
        return bool(self.ark_api_key and self.ark_model)

    @property
    def has_backup_llm_credentials(self) -> bool:
        return bool(self.backup_llm_api_key and self.backup_llm_model)

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
    for path in _env_file_candidates():
        _load_env_file(path)
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
        backup_llm_api_key=os.getenv("BACKUP_LLM_API_KEY") or None,
        backup_llm_base_url=os.getenv(
            "BACKUP_LLM_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/"),
        backup_llm_model=os.getenv("BACKUP_LLM_MODEL") or None,
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        llm_max_retries=_env_int("LLM_MAX_RETRIES", 2, minimum=0, maximum=5),
        llm_retry_backoff_seconds=_env_float(
            "LLM_RETRY_BACKOFF_SECONDS",
            0.25,
            minimum=0.0,
            maximum=5.0,
        ),
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
        collector_target_verified_sources_per_branch=_env_int(
            "COLLECTOR_TARGET_VERIFIED_SOURCES_PER_BRANCH",
            3,
            minimum=1,
            maximum=5,
        ),
        collector_search_max_results=_env_int(
            "COLLECTOR_SEARCH_MAX_RESULTS",
            6,
            minimum=3,
            maximum=10,
        ),
        analyst_react_enabled=_env_bool("ANALYST_REACT_ENABLED", True),
        analyst_react_max_turns=max(1, min(6, int(os.getenv("ANALYST_REACT_MAX_TURNS", "3")))),
        analyst_react_fanout_threshold=_env_int(
            "ANALYST_REACT_FANOUT_THRESHOLD",
            8,
            minimum=1,
            maximum=64,
        ),
        analyst_branch_timeout_seconds=_env_float(
            "ANALYST_BRANCH_TIMEOUT_SECONDS",
            25.0,
            minimum=0.05,
            maximum=120.0,
        ),
        analyst_fanout_branch_timeout_seconds=_env_float(
            "ANALYST_FANOUT_BRANCH_TIMEOUT_SECONDS",
            8.0,
            minimum=0.05,
            maximum=120.0,
        ),
        comparator_timeout_seconds=_env_float(
            "COMPARATOR_TIMEOUT_SECONDS",
            8.0,
            minimum=0.05,
            maximum=120.0,
        ),
        writer_timeout_seconds=_env_float(
            "WRITER_TIMEOUT_SECONDS",
            90.0,
            minimum=0.05,
            maximum=120.0,
        ),
        langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY") or None,
        langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY") or None,
        langfuse_host=os.getenv("LANGFUSE_HOST") or None,
        otel_export_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
        enterprise_store_backend=enterprise_backend,
        enterprise_database_url=enterprise_database_url,
        run_orchestration_backend=cast(
            Literal["langgraph", "temporal"],
            _env_choice(
                "RUN_ORCHESTRATION_BACKEND",
                "temporal",
                {"langgraph", "temporal"},
            ),
        ),
        temporal_address=os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7233"),
        temporal_namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
        temporal_task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "competitive-intel"),
        temporal_traffic_percent=_env_int(
            "TEMPORAL_TRAFFIC_PERCENT",
            100,
            minimum=0,
            maximum=100,
        ),
        compliance_redaction_enabled=_env_bool("COMPLIANCE_REDACTION_ENABLED", True),
        compliance_redact_api_keys=_env_bool("COMPLIANCE_REDACT_API_KEYS", True),
        compliance_redact_emails=_env_bool("COMPLIANCE_REDACT_EMAILS", True),
        compliance_redact_phones=_env_bool("COMPLIANCE_REDACT_PHONES", True),
        compliance_allowed_domains=_env_csv("COMPLIANCE_ALLOWED_DOMAINS"),
        compliance_blocked_domains=_env_csv("COMPLIANCE_BLOCKED_DOMAINS"),
        compliance_require_source_urls=_env_bool("COMPLIANCE_REQUIRE_SOURCE_URLS", False),
        compliance_require_trace_context=_env_bool("COMPLIANCE_REQUIRE_TRACE_CONTEXT", True),
        retention_project_days=_env_int(
            "RETENTION_PROJECT_DAYS",
            1095,
            minimum=1,
            maximum=36500,
        ),
        retention_evidence_days=_env_int(
            "RETENTION_EVIDENCE_DAYS",
            730,
            minimum=1,
            maximum=36500,
        ),
        retention_artifact_days=_env_int(
            "RETENTION_ARTIFACT_DAYS",
            730,
            minimum=1,
            maximum=36500,
        ),
        retention_report_version_days=_env_int(
            "RETENTION_REPORT_VERSION_DAYS",
            1095,
            minimum=1,
            maximum=36500,
        ),
        retention_audit_log_days=_env_int(
            "RETENTION_AUDIT_LOG_DAYS",
            2555,
            minimum=1,
            maximum=36500,
        ),
        retention_expiring_soon_days=_env_int(
            "RETENTION_EXPIRING_SOON_DAYS",
            30,
            minimum=1,
            maximum=3650,
        ),
        retention_physical_delete_enabled=_env_bool(
            "RETENTION_PHYSICAL_DELETE_ENABLED",
            False,
        ),
        pydantic_ai_model_backed_enabled=_env_bool(
            "PYDANTIC_AI_MODEL_BACKED_ENABLED",
            False,
        ),
        pydantic_ai_model_name=os.getenv("PYDANTIC_AI_MODEL_NAME") or None,
        artifact_storage_backend=cast(
            Literal["local", "external", "s3", "oss"],
            _env_choice("ARTIFACT_STORAGE_BACKEND", "local", {"local", "external", "s3", "oss"}),
        ),
        artifact_storage_root=os.getenv("ARTIFACT_STORAGE_ROOT", "data/artifacts"),
        auth_policy_engine=cast(
            Literal["internal", "opa", "cerbos"],
            _env_choice("AUTH_POLICY_ENGINE", "internal", {"internal", "opa", "cerbos"}),
        ),
        auth_policy_url=os.getenv("AUTH_POLICY_URL") or None,
        auth_policy_timeout_seconds=max(
            0.1,
            min(10.0, float(os.getenv("AUTH_POLICY_TIMEOUT_SECONDS", "1.0"))),
        ),
    )
