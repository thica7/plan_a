# Observability And Governance Contract

Last updated: 2026-06-07

## Purpose

This contract closes Checkpoint 4 C4.7. It defines how local trace, decision
replay, audit, compliance redaction, Langfuse, and OTel relate to each other.

The key rule:

> Local observability is the baseline. Langfuse and OTel are optional hosted
> exporters. A run must remain reviewable even when hosted exporters are not
> configured.

## Telemetry Event Types

Canonical telemetry event types are defined in
`backend/packages/observability/telemetry_contract.py`:

```text
trace_span
tool_call
model_call
token_cost
quality_finding
decision_event
audit_event
compliance_event
hitl_lifecycle_event
workflow_event
```

## Channels

| Channel | Baseline | Enabled Without Hosted Config | Owner |
|---|---:|---:|---|
| local_trace | yes | yes | `TraceStore` + `RunDetail.trace_spans` |
| decision_replay | yes | yes | `packages/observability/decision_replay.py` |
| audit | yes | yes | `EnterpriseStore.audit_logs` |
| compliance_redaction | yes | yes, unless disabled by policy | `packages/compliance` |
| langfuse | no | no | `LangfuseAdapter` |
| otel | no | no | OTLP deployment adapter |

## Runtime Status

`/api/runtime` returns `telemetry` with:

- local trace status;
- decision replay status;
- audit status;
- compliance redaction status;
- Langfuse configured/enabled/disabled reason;
- OTel configured/enabled/disabled reason;
- canonical event type list;
- whether any hosted exporter is configured.

This is the user-facing explanation for the common local state:

```text
Langfuse disabled because not_configured, but local trace + decision replay
are enabled and sufficient for local review.
```

## Configuration

Langfuse:

```text
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
LANGFUSE_HOST
```

OTel:

```text
OTEL_EXPORTER_OTLP_ENDPOINT
```

If neither hosted exporter is configured, C4.7 is still considered healthy as
long as local trace, decision replay, audit, and compliance redaction are
available.

## Boundaries

Observability may:

- record spans;
- export spans;
- mirror to Langfuse;
- build OTel payloads;
- build decision replay;
- expose runtime status;
- show audit/compliance events.

Observability must not:

- decide whether a report is publishable;
- rewrite report text;
- own source admission;
- own HITL decisions;
- own Temporal workflow transitions.

## Validation

C4.7 validation includes:

```text
ruff:
  backend/packages/observability
  backend/app/routers/runtime.py
  backend/packages/schema/api_dto.py

pytest:
  backend/tests/unit/test_observability.py::test_telemetry_contract_separates_local_baseline_from_hosted_exporters
  backend/tests/unit/test_health_router.py::test_runtime_reports_hitl_and_pydantic_ai_readiness
```

