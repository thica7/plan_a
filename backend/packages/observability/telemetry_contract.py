from __future__ import annotations

from packages.schema.api_dto import TelemetryChannelStatus, TelemetryRuntimeContract

TELEMETRY_EVENT_TYPES = [
    "trace_span",
    "tool_call",
    "model_call",
    "token_cost",
    "quality_finding",
    "decision_event",
    "audit_event",
    "compliance_event",
    "hitl_lifecycle_event",
    "workflow_event",
]


def build_telemetry_contract(settings: object) -> TelemetryRuntimeContract:
    langfuse_configured = bool(
        getattr(settings, "langfuse_public_key", None)
        and getattr(settings, "langfuse_secret_key", None)
    )
    otel_endpoint = getattr(settings, "otel_export_endpoint", None)
    otel_configured = bool(otel_endpoint)
    compliance_redaction_enabled = bool(
        getattr(settings, "compliance_redaction_enabled", False)
    )
    return TelemetryRuntimeContract(
        local_trace=TelemetryChannelStatus(
            name="local_trace",
            enabled=True,
            configured=True,
            baseline=True,
            adapter="TraceStore + RunDetail.trace_spans",
            event_types=["trace_span", "tool_call", "model_call", "token_cost"],
        ),
        decision_replay=TelemetryChannelStatus(
            name="decision_replay",
            enabled=True,
            configured=True,
            baseline=True,
            adapter="local_decision_replay",
            event_types=[
                "decision_event",
                "quality_finding",
                "hitl_lifecycle_event",
                "workflow_event",
            ],
        ),
        audit=TelemetryChannelStatus(
            name="audit",
            enabled=True,
            configured=True,
            baseline=True,
            adapter="EnterpriseStore.audit_logs",
            event_types=["audit_event", "workflow_event", "hitl_lifecycle_event"],
        ),
        compliance_redaction=TelemetryChannelStatus(
            name="compliance_redaction",
            enabled=compliance_redaction_enabled,
            configured=True,
            baseline=True,
            adapter="local_redaction_policy",
            disabled_reason="" if compliance_redaction_enabled else "disabled_by_policy",
            event_types=["compliance_event"],
        ),
        langfuse=TelemetryChannelStatus(
            name="langfuse",
            enabled=langfuse_configured,
            configured=langfuse_configured,
            baseline=False,
            adapter="LangfuseAdapter",
            disabled_reason="" if langfuse_configured else _langfuse_disabled_reason(settings),
            event_types=["trace_span", "model_call", "tool_call"],
        ),
        otel=TelemetryChannelStatus(
            name="otel",
            enabled=otel_configured,
            configured=otel_configured,
            baseline=False,
            adapter="OTLP exporter",
            disabled_reason="" if otel_configured else "not_configured",
            event_types=["trace_span", "workflow_event"],
        ),
        event_types=list(TELEMETRY_EVENT_TYPES),
        hosted_exporters_configured=langfuse_configured or otel_configured,
    )


def _langfuse_disabled_reason(settings: object) -> str:
    has_public = bool(getattr(settings, "langfuse_public_key", None))
    has_secret = bool(getattr(settings, "langfuse_secret_key", None))
    if has_public or has_secret:
        return "incomplete_config"
    return "not_configured"
