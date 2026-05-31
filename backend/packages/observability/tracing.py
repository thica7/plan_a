from __future__ import annotations

import hashlib
from typing import Any, cast

from app.events import RunEvent, RunEventType
from packages.compliance import redact_text

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)


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
    if isinstance(value, str):
        return redact_text(value).text
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
        trace_id=trace_id_for_run(run_id),
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


def trace_id_for_run(run_id: str) -> str:
    return hashlib.sha256(f"competiscope-trace:{run_id}".encode()).hexdigest()[:32]


def otel_span_id_for_span(run_id: str, span_id: str) -> str:
    return hashlib.sha256(f"competiscope-span:{run_id}:{span_id}".encode()).hexdigest()[
        :16
    ]


def traceparent_for_span(trace_id: str, otel_span_id: str) -> str:
    return f"00-{trace_id}-{otel_span_id}-01"
