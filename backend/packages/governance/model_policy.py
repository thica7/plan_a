from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelPolicyFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Literal["info", "warn", "blocker"]
    category: Literal["provider", "compliance", "cost", "routing"]
    message: str
    recommendation: str


class ModelPolicyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pass", "warn", "fail"]
    policy_version: str = "2026-05-phase5-model-policy"
    default_execution_mode: str
    primary_provider_configured: bool
    backup_provider_configured: bool
    real_execution_allowed: bool
    fallback_allowed: bool
    redaction_required: bool
    trace_context_required: bool
    max_timeout_seconds: float
    finding_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    warn_count: int = Field(ge=0)
    blocking_finding_ids: list[str] = Field(default_factory=list)
    findings: list[ModelPolicyFinding] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def build_model_policy_report(settings: object) -> ModelPolicyReport:
    findings: list[ModelPolicyFinding] = []
    has_primary = bool(
        getattr(settings, "ark_api_key", None) and getattr(settings, "ark_model", None)
    )
    has_backup = bool(
        getattr(settings, "backup_llm_api_key", None)
        and getattr(settings, "backup_llm_model", None)
    )
    redaction_required = bool(getattr(settings, "compliance_redaction_enabled", True))
    trace_context_required = bool(getattr(settings, "compliance_require_trace_context", True))
    timeout = float(getattr(settings, "llm_timeout_seconds", 60.0))

    if not has_primary and not has_backup:
        findings.append(
            _finding(
                "provider.no_real_provider",
                "warn",
                "provider",
                "No real LLM provider is configured.",
                "Configure primary or backup credentials before real enterprise runs.",
            )
        )
    if not redaction_required:
        findings.append(
            _finding(
                "compliance.redaction_disabled",
                "blocker",
                "compliance",
                "PII and credential redaction is disabled.",
                "Enable COMPLIANCE_REDACTION_ENABLED before production use.",
            )
        )
    if not trace_context_required:
        findings.append(
            _finding(
                "compliance.trace_context_not_required",
                "warn",
                "compliance",
                "Trace context is not required by policy.",
                "Enable COMPLIANCE_REQUIRE_TRACE_CONTEXT for audit-grade traces.",
            )
        )
    if timeout > 120:
        findings.append(
            _finding(
                "cost.timeout_high",
                "warn",
                "cost",
                "LLM timeout is above the Phase 5 governance threshold.",
                "Keep LLM_TIMEOUT_SECONDS at or below 120 unless explicitly approved.",
            )
        )
    if has_backup:
        findings.append(
            _finding(
                "routing.backup_provider_enabled",
                "info",
                "routing",
                "Backup LLM provider is configured for failover.",
                "Monitor provider routing and cost metrics during real runs.",
            )
        )

    blocking_finding_ids: list[str] = []
    if not has_primary and not has_backup:
        blocking_finding_ids.append("provider.no_real_provider")
    if not redaction_required:
        blocking_finding_ids.append("compliance.redaction_disabled")

    blocker_count = sum(1 for item in findings if item.severity == "blocker")
    warn_count = sum(1 for item in findings if item.severity == "warn")
    status: Literal["pass", "warn", "fail"] = "pass"
    if blocker_count:
        status = "fail"
    elif warn_count:
        status = "warn"
    return ModelPolicyReport(
        status=status,
        default_execution_mode=str(getattr(settings, "default_execution_mode", "demo")),
        primary_provider_configured=has_primary,
        backup_provider_configured=has_backup,
        real_execution_allowed=(has_primary or has_backup) and redaction_required,
        fallback_allowed=has_backup,
        redaction_required=redaction_required,
        trace_context_required=trace_context_required,
        max_timeout_seconds=timeout,
        finding_count=len(findings),
        blocker_count=blocker_count,
        warn_count=warn_count,
        blocking_finding_ids=blocking_finding_ids,
        findings=findings,
    )


def model_policy_block_message(report: ModelPolicyReport) -> str:
    blocking_ids = report.blocking_finding_ids or ["policy.real_execution_not_allowed"]
    return (
        f"Real mode is blocked by model policy {report.policy_version}: "
        f"{', '.join(blocking_ids)}."
    )


def _finding(
    finding_id: str,
    severity: Literal["info", "warn", "blocker"],
    category: Literal["provider", "compliance", "cost", "routing"],
    message: str,
    recommendation: str,
) -> ModelPolicyFinding:
    return ModelPolicyFinding(
        id=finding_id,
        severity=severity,
        category=category,
        message=message,
        recommendation=recommendation,
    )
