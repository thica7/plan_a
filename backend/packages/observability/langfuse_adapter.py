from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from packages.schema.models import TraceSpan

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"(public_key|secret_key|api_key)=([^,\s)]+)", re.IGNORECASE),
)


@dataclass(frozen=True)
class LangfuseConfig:
    public_key: str | None
    secret_key: str | None
    host: str | None

    @property
    def enabled(self) -> bool:
        return bool(self.public_key and self.secret_key)


class LangfuseAdapter:
    def __init__(self, config: LangfuseConfig) -> None:
        self._config = config
        self._client: Any | None = None
        self._disabled_reason = "" if config.enabled else "not_configured"
        self._error_count = 0
        self._last_error = ""
        if not config.enabled:
            return
        try:
            from langfuse import Langfuse  # type: ignore
        except Exception as exc:  # noqa: BLE001 - optional dependency.
            self._disabled_reason = "dependency_unavailable"
            self._record_error(self._disabled_reason, exc)
            return
        try:
            self._client = Langfuse(
                public_key=config.public_key,
                secret_key=config.secret_key,
                host=config.host,
            )
            self._disabled_reason = ""
        except Exception as exc:  # noqa: BLE001 - observability must degrade safely.
            self._disabled_reason = "client_init_failed"
            self._record_error(self._disabled_reason, exc)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def configured(self) -> bool:
        return self._config.enabled

    @property
    def disabled_reason(self) -> str:
        return self._disabled_reason

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def last_error(self) -> str:
        return self._last_error

    def health(self) -> dict[str, bool | int | str]:
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
            "error_count": self.error_count,
            "last_error": self.last_error,
        }

    def mirror_span(self, run_id: str, span: TraceSpan) -> bool:
        if self._client is None:
            return False
        try:
            trace = self._client.trace(id=run_id, name="competiscope_run")
            trace.span(
                id=span.id,
                name=f"{span.agent}:{span.name}",
                input=span.full_input,
                output=span.full_output,
                metadata={
                    **span.metadata,
                    "agent": span.agent,
                    "subagent": span.subagent,
                    "kind": span.kind,
                    "status": span.status,
                    "input_tokens_estimate": span.input_tokens_estimate,
                    "output_tokens_estimate": span.output_tokens_estimate,
                    "cost_estimate_usd": span.cost_estimate_usd,
                },
            )
        except Exception as exc:  # noqa: BLE001 - keep the primary run path alive.
            self._record_error("mirror_failed", exc)
            return False
        return True

    def _record_error(self, code: str, exc: Exception) -> None:
        self._error_count += 1
        self._last_error = f"{code}:{_safe_error(exc)}"


def _safe_error(exc: Exception, *, limit: int = 180) -> str:
    message = " ".join(str(exc).split())
    if not message:
        message = exc.__class__.__name__
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(_redacted_secret_match, message)
    if len(message) > limit:
        return f"{message[: limit - 3]}..."
    return message


def _redacted_secret_match(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 2:
        return f"{match.group(1)}=[redacted]"
    if match.group(0).lower().startswith("bearer"):
        return "Bearer [redacted]"
    return "[redacted]"
