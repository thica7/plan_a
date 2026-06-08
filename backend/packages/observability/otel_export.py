from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.schema.models import TraceSpan


class OtelSpanExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    kind: str
    status_code: Literal["OK", "ERROR"]
    start_time_unix_nano: int
    end_time_unix_nano: int
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class OtelTraceExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    exporter: Literal["otlp-json-compatible"] = "otlp-json-compatible"
    trace_id: str
    resource: dict[str, str] = Field(default_factory=dict)
    spans: list[OtelSpanExport] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TraceObservabilityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["info", "warn", "blocker"]
    field: str
    message: str
    span_id: str | None = None


class TraceObservabilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["pass", "warn", "fail"]
    span_count: int = Field(ge=0)
    trace_id_coverage: float = Field(ge=0.0, le=1.0)
    traceparent_coverage: float = Field(ge=0.0, le=1.0)
    otel_span_id_coverage: float = Field(ge=0.0, le=1.0)
    parent_link_count: int = Field(ge=0)
    errored_span_count: int = Field(ge=0)
    otel_export_ready: bool
    issues: list[TraceObservabilityIssue] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def build_otel_trace_export(run_id: str, spans: list[TraceSpan]) -> OtelTraceExport:
    trace_id = _first_present([span.trace_id for span in spans]) or ""
    return OtelTraceExport(
        run_id=run_id,
        trace_id=trace_id,
        resource={
            "service.name": "competiscope-api",
            "service.namespace": "competitive-intelligence",
            "run.id": run_id,
        },
        spans=[_span_to_otel(span) for span in spans],
    )


def evaluate_trace_observability(
    run_id: str,
    spans: list[TraceSpan],
) -> TraceObservabilityReport:
    issues: list[TraceObservabilityIssue] = []
    span_count = len(spans)
    if span_count == 0:
        issues.append(
            TraceObservabilityIssue(
                severity="warn",
                field="trace_spans",
                message="Run has no trace spans; replay and dashboard correlation are limited.",
            )
        )
        return TraceObservabilityReport(
            run_id=run_id,
            status="warn",
            span_count=0,
            trace_id_coverage=0.0,
            traceparent_coverage=0.0,
            otel_span_id_coverage=0.0,
            parent_link_count=0,
            errored_span_count=0,
            otel_export_ready=False,
            issues=issues,
        )

    trace_id_count = sum(1 for span in spans if span.trace_id)
    traceparent_count = sum(1 for span in spans if span.traceparent)
    otel_span_id_count = sum(1 for span in spans if span.otel_span_id)
    parent_link_count = sum(1 for span in spans if span.parent_span_id)
    errored_span_count = sum(1 for span in spans if span.status == "error")

    for span in spans:
        if not span.trace_id:
            issues.append(
                _issue("blocker", "trace_id", "Trace span is missing trace_id.", span.id)
            )
        if not span.otel_span_id:
            issues.append(
                _issue(
                    "blocker",
                    "otel_span_id",
                    "Trace span is missing OpenTelemetry span id.",
                    span.id,
                )
            )
        if not span.traceparent:
            issues.append(
                _issue(
                    "warn",
                    "traceparent",
                    "Trace span is missing W3C traceparent propagation value.",
                    span.id,
                )
            )

    trace_ids = {span.trace_id for span in spans if span.trace_id}
    if len(trace_ids) > 1:
        issues.append(
            TraceObservabilityIssue(
                severity="warn",
                field="trace_id",
                message="Run spans contain multiple trace ids; dashboard correlation may split.",
            )
        )

    blocker_count = sum(1 for issue in issues if issue.severity == "blocker")
    warn_count = sum(1 for issue in issues if issue.severity == "warn")
    status: Literal["pass", "warn", "fail"] = "pass"
    if blocker_count:
        status = "fail"
    elif warn_count:
        status = "warn"

    return TraceObservabilityReport(
        run_id=run_id,
        status=status,
        span_count=span_count,
        trace_id_coverage=trace_id_count / span_count,
        traceparent_coverage=traceparent_count / span_count,
        otel_span_id_coverage=otel_span_id_count / span_count,
        parent_link_count=parent_link_count,
        errored_span_count=errored_span_count,
        otel_export_ready=blocker_count == 0,
        issues=issues,
    )


def _span_to_otel(span: TraceSpan) -> OtelSpanExport:
    start = _as_utc(span.created_at)
    end = start + timedelta(milliseconds=span.duration_ms)
    attributes: dict[str, str | int | float | bool | None] = {
        "agent.name": span.agent,
        "agent.subagent": span.subagent,
        "span.kind": span.kind,
        "llm.provider": span.provider,
        "llm.model": span.model,
        "llm.input_tokens_estimate": span.input_tokens_estimate,
        "llm.output_tokens_estimate": span.output_tokens_estimate,
        "cost.estimate_usd": span.cost_estimate_usd,
    }
    for key, value in span.metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            attributes[f"competiscope.{key}"] = value
    return OtelSpanExport(
        trace_id=span.trace_id,
        span_id=span.otel_span_id,
        parent_span_id=span.parent_span_id,
        name=span.name,
        kind=span.kind.upper(),
        status_code="ERROR" if span.status == "error" else "OK",
        start_time_unix_nano=_unix_nano(start),
        end_time_unix_nano=_unix_nano(end),
        attributes=attributes,
    )


def _issue(
    severity: Literal["info", "warn", "blocker"],
    field: str,
    message: str,
    span_id: str,
) -> TraceObservabilityIssue:
    return TraceObservabilityIssue(
        severity=severity,
        field=field,
        message=message,
        span_id=span_id,
    )


def _first_present(values: list[str]) -> str | None:
    return next((value for value in values if value), None)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _unix_nano(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)
