from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_app_settings
from packages.config import Settings
from packages.schema.api_dto import RuntimeConfig
from packages.workflows.service import temporal_cutover_status

router = APIRouter()
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@router.get("/runtime", response_model=RuntimeConfig)
def get_runtime(settings: SettingsDep) -> RuntimeConfig:
    cutover = temporal_cutover_status(settings)
    return RuntimeConfig(
        default_execution_mode=settings.default_execution_mode,
        run_orchestration_backend=settings.run_orchestration_backend,
        demo_mode=settings.demo_mode,
        has_ark_api_key=bool(settings.ark_api_key),
        has_ark_model=bool(settings.ark_model),
        ark_base_url=settings.ark_base_url,
        ark_model=settings.ark_model,
        has_backup_llm_api_key=bool(settings.backup_llm_api_key),
        has_backup_llm_model=bool(settings.backup_llm_model),
        backup_llm_base_url=settings.backup_llm_base_url,
        backup_llm_model=settings.backup_llm_model,
        web_search_provider=settings.web_search_provider,
        has_web_search_key=settings.has_web_search_credentials,
        auto_redo_enabled=settings.auto_redo_enabled,
        auto_redo_warn_enabled=settings.auto_redo_warn_enabled,
        hitl_enabled=settings.hitl_enabled,
        hitl_timeout_seconds=settings.hitl_timeout_seconds,
        temporal_address=settings.temporal_address,
        temporal_namespace=settings.temporal_namespace,
        temporal_task_queue=settings.temporal_task_queue,
        temporal_traffic_percent=settings.temporal_traffic_percent,
        temporal_cutover_ready=cutover.ready,
        temporal_cutover_reason=cutover.reason,
        compliance_redaction_enabled=settings.compliance_redaction_enabled,
        compliance_redact_api_keys=settings.compliance_redact_api_keys,
        compliance_redact_emails=settings.compliance_redact_emails,
        compliance_redact_phones=settings.compliance_redact_phones,
        compliance_allowed_domains=list(settings.compliance_allowed_domains),
        compliance_blocked_domains=list(settings.compliance_blocked_domains),
        compliance_require_source_urls=settings.compliance_require_source_urls,
        compliance_require_trace_context=settings.compliance_require_trace_context,
        pydantic_ai_model_backed_enabled=settings.pydantic_ai_model_backed_enabled,
        pydantic_ai_model_name=settings.pydantic_ai_model_name,
        artifact_storage_backend=settings.artifact_storage_backend,
        artifact_storage_root=settings.artifact_storage_root,
    )
