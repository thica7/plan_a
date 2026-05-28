from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_app_settings
from packages.config import Settings
from packages.schema.api_dto import RuntimeConfig

router = APIRouter()
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@router.get("/runtime", response_model=RuntimeConfig)
def get_runtime(settings: SettingsDep) -> RuntimeConfig:
    return RuntimeConfig(
        default_execution_mode=settings.default_execution_mode,
        demo_mode=settings.demo_mode,
        has_ark_api_key=bool(settings.ark_api_key),
        has_ark_model=bool(settings.ark_model),
        ark_base_url=settings.ark_base_url,
        ark_model=settings.ark_model,
        web_search_provider=settings.web_search_provider,
        has_web_search_key=settings.has_web_search_credentials,
        auto_redo_enabled=settings.auto_redo_enabled,
        auto_redo_warn_enabled=settings.auto_redo_warn_enabled,
        hitl_enabled=settings.hitl_enabled,
        hitl_timeout_seconds=settings.hitl_timeout_seconds,
    )
