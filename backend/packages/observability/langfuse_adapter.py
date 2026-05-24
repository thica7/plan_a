from __future__ import annotations

from dataclasses import dataclass

from packages.schema.models import TraceSpan


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
        self._client = None
        if not config.enabled:
            return
        try:
            from langfuse import Langfuse  # type: ignore
        except Exception:  # noqa: BLE001 - optional dependency.
            return
        self._client = Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.host,
        )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def mirror_span(self, run_id: str, span: TraceSpan) -> None:
        if self._client is None:
            return
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
        except Exception:
            return
