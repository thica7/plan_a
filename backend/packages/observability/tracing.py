from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from app.events import RunEvent, RunEventType

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)


class RetrievalObservability(BaseModel):
    query: str
    preset_used: str | None = None
    dense_hits: int = Field(default=0, ge=0)
    sparse_hits: int = Field(default=0, ge=0)
    reranked_hits: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    cache_hit: bool = False
    crawl_run_id: str | None = None
    competitor: str | None = None
    dimension: str | None = None
    source_type: str | None = None
    retrieval_preset: str | None = None
    metadata: dict[str, Any] = {}


def sanitize_for_trace(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = "[redacted]"
            else:
                sanitized[key_text] = sanitize_for_trace(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_trace(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_trace(item) for item in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return "[redacted]"
    return value


def build_run_event(
    *,
    event_id: int,
    run_id: str,
    event_type: str,
    agent: str | None,
    subagent: str | None,
    message: str,
    payload: dict[str, Any] | None = None,
) -> RunEvent:
    return RunEvent(
        id=event_id,
        run_id=run_id,
        type=cast(RunEventType, event_type),
        agent=agent,
        subagent=subagent,
        swimlane=subagent or agent,
        message=message,
        payload=sanitize_for_trace(payload or {}),
    )


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)
