from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.enterprise import EnterpriseStore
from packages.schema.enterprise import (
    ModelProviderKind,
    ModelRouteDecision,
    ToolRegistryEntry,
    WorkspaceQuotaDecision,
)

from .model_policy import ModelPolicyReport, build_model_policy_report
from .model_router import build_model_route_decision
from .tool_registry import build_tool_registry_report

RUNTIME_POLICY_VERSION = "c5.6-runtime-policy"
DEFAULT_RUNTIME_TOOL_NAMES = (
    "web_search",
    "fetch_page",
    "advanced_fetch_page",
    "rag_search_evidence",
    "online_gap_fill",
    "memory_recall",
    "claim_validator",
    "self_consistency_sampler",
    "source_snapshot",
    "model_backed_agent",
)

ExecutionMode = Literal["demo", "real"]
RuntimePolicyStatus = Literal["allow", "warn", "deny"]
RuntimeToolDecisionStatus = Literal["allowed", "guarded", "denied"]


class RuntimeToolPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: RuntimeToolDecisionStatus
    registry_status: str
    allowed_in_real_mode: bool
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    side_effects: list[str] = Field(default_factory=list)
    policy_tags: list[str] = Field(default_factory=list)
    reason: str = ""


class RuntimePolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = RUNTIME_POLICY_VERSION
    status: RuntimePolicyStatus
    workspace_id: str
    execution_mode: ExecutionMode
    selected_provider_kind: ModelProviderKind | None = None
    selected_provider_name: str | None = None
    selected_model: str | None = None
    fallback_provider_kind: ModelProviderKind | None = None
    fallback_provider_name: str | None = None
    fallback_model: str | None = None
    model_route_status: str
    model_route_policy_version: str
    model_policy_status: str
    model_policy_version: str
    model_policy_finding_ids: list[str] = Field(default_factory=list)
    tool_decisions: list[RuntimeToolPolicyDecision] = Field(default_factory=list)
    allowed_tool_count: int = Field(ge=0)
    guarded_tool_count: int = Field(ge=0)
    denied_tool_count: int = Field(ge=0)
    quota_allowed: bool
    quota_status: str
    quota_enforcement: str
    quota_pressure: str
    quota_decision: WorkspaceQuotaDecision
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    compliance_constraints: list[str] = Field(default_factory=list)
    audit_reason: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)


def build_runtime_policy_decision(
    settings: object,
    *,
    store: EnterpriseStore,
    workspace_id: str,
    execution_mode: ExecutionMode = "real",
    requested_tools: list[str] | tuple[str, ...] | None = None,
    estimated_input_tokens: int = 0,
    estimated_output_tokens: int = 0,
) -> RuntimePolicyDecision:
    route = build_model_route_decision(settings)
    model_policy = build_model_policy_report(settings)
    quota = store.check_workspace_quota(workspace_id)
    tool_decisions = _tool_decisions(
        settings,
        requested_tools=requested_tools or DEFAULT_RUNTIME_TOOL_NAMES,
        execution_mode=execution_mode,
    )
    estimated_cost = round(
        _estimate_model_cost_usd(
            route,
            input_tokens=max(0, estimated_input_tokens),
            output_tokens=max(0, estimated_output_tokens),
        )
        + sum(item.estimated_cost_usd for item in tool_decisions),
        6,
    )
    denied_tool_count = sum(1 for item in tool_decisions if item.status == "denied")
    guarded_tool_count = sum(1 for item in tool_decisions if item.status == "guarded")
    allowed_tool_count = sum(1 for item in tool_decisions if item.status == "allowed")
    blocking_reasons = _blocking_reasons(
        execution_mode=execution_mode,
        route=route,
        model_policy=model_policy,
        quota=quota,
        denied_tool_count=denied_tool_count,
    )
    warning_reasons = _warning_reasons(
        route=route,
        model_policy=model_policy,
        quota=quota,
        guarded_tool_count=guarded_tool_count,
    )
    status: RuntimePolicyStatus = "allow"
    if blocking_reasons:
        status = "deny"
    elif warning_reasons:
        status = "warn"
    selected = route.selected
    fallback = route.fallback
    return RuntimePolicyDecision(
        status=status,
        workspace_id=workspace_id,
        execution_mode=execution_mode,
        selected_provider_kind=selected.provider_kind if selected else None,
        selected_provider_name=selected.provider_name if selected else None,
        selected_model=selected.model_name if selected else None,
        fallback_provider_kind=fallback.provider_kind if fallback else None,
        fallback_provider_name=fallback.provider_name if fallback else None,
        fallback_model=fallback.model_name if fallback else None,
        model_route_status=route.status,
        model_route_policy_version=route.routing_policy_version,
        model_policy_status=model_policy.status,
        model_policy_version=model_policy.policy_version,
        model_policy_finding_ids=[item.id for item in model_policy.findings],
        tool_decisions=tool_decisions,
        allowed_tool_count=allowed_tool_count,
        guarded_tool_count=guarded_tool_count,
        denied_tool_count=denied_tool_count,
        quota_allowed=quota.allowed,
        quota_status=quota.status,
        quota_enforcement=quota.enforcement,
        quota_pressure=_quota_pressure(quota),
        quota_decision=quota,
        estimated_cost_usd=estimated_cost,
        compliance_constraints=_compliance_constraints(settings),
        audit_reason=_audit_reason(
            status=status,
            blocking_reasons=blocking_reasons,
            warning_reasons=warning_reasons,
        ),
    )


def _tool_decisions(
    settings: object,
    *,
    requested_tools: list[str] | tuple[str, ...],
    execution_mode: ExecutionMode,
) -> list[RuntimeToolPolicyDecision]:
    registry = build_tool_registry_report(settings)
    entries_by_name = {entry.name: entry for entry in registry.entries}
    decisions: list[RuntimeToolPolicyDecision] = []
    seen: set[str] = set()
    for tool_name in requested_tools:
        if tool_name in seen:
            continue
        seen.add(tool_name)
        entry = entries_by_name.get(tool_name)
        if entry is None:
            decisions.append(
                RuntimeToolPolicyDecision(
                    tool_name=tool_name,
                    status="denied",
                    registry_status="missing",
                    allowed_in_real_mode=False,
                    reason="Tool is not registered in the enterprise tool registry.",
                )
            )
            continue
        decisions.append(_tool_decision(entry, execution_mode=execution_mode))
    return decisions


def _tool_decision(
    entry: ToolRegistryEntry,
    *,
    execution_mode: ExecutionMode,
) -> RuntimeToolPolicyDecision:
    if entry.status == "disabled":
        status: RuntimeToolDecisionStatus = "denied"
        reason = entry.reason or "Tool is disabled by policy."
    elif execution_mode == "real" and not entry.allowed_in_real_mode:
        status = "denied"
        reason = entry.reason or "Tool is not allowed in real execution mode."
    elif entry.status == "guarded":
        status = "guarded"
        reason = entry.reason or "Tool requires additional runtime guardrails."
    else:
        status = "allowed"
        reason = entry.reason or "Tool is allowed by runtime policy."
    return RuntimeToolPolicyDecision(
        tool_name=entry.name,
        status=status,
        registry_status=entry.status,
        allowed_in_real_mode=entry.allowed_in_real_mode,
        estimated_cost_usd=entry.estimated_cost_usd,
        side_effects=list(entry.side_effects),
        policy_tags=list(entry.policy_tags),
        reason=reason,
    )


def _blocking_reasons(
    *,
    execution_mode: ExecutionMode,
    route: ModelRouteDecision,
    model_policy: ModelPolicyReport,
    quota: WorkspaceQuotaDecision,
    denied_tool_count: int,
) -> list[str]:
    reasons: list[str] = []
    if route.status == "blocked":
        reasons.append("model route is blocked")
    if execution_mode == "real" and not model_policy.real_execution_allowed:
        reasons.append("model policy blocks real execution")
    if not quota.allowed:
        reasons.append("workspace quota blocks new runs")
    if execution_mode == "real" and denied_tool_count:
        reasons.append(f"{denied_tool_count} requested tool(s) are denied in real mode")
    return reasons


def _warning_reasons(
    *,
    route: ModelRouteDecision,
    model_policy: ModelPolicyReport,
    quota: WorkspaceQuotaDecision,
    guarded_tool_count: int,
) -> list[str]:
    reasons: list[str] = []
    if route.status == "fallback":
        reasons.append("model router selected fallback provider")
    if model_policy.status == "warn":
        reasons.append("model policy has warnings")
    if quota.status != "ok":
        reasons.append(f"workspace quota is {quota.status}")
    if guarded_tool_count:
        reasons.append(f"{guarded_tool_count} requested tool(s) are guarded")
    return reasons


def _estimate_model_cost_usd(
    route: ModelRouteDecision,
    *,
    input_tokens: int,
    output_tokens: int,
) -> float:
    if route.selected is None:
        return 0.0
    total_tokens = input_tokens + output_tokens
    per_1k = {
        "primary": 0.002,
        "backup": 0.0015,
        "demo": 0.0,
    }.get(route.selected.provider_kind, 0.0)
    return (total_tokens / 1000.0) * per_1k


def _quota_pressure(quota: WorkspaceQuotaDecision) -> str:
    usage = quota.usage
    pressure = max(
        ("runs", usage.run_usage_ratio),
        ("tokens", usage.token_usage_ratio),
        ("cost", usage.cost_usage_ratio),
        key=lambda item: item[1],
    )
    return f"{pressure[0]}:{pressure[1]:.0%}"


def _compliance_constraints(settings: object) -> list[str]:
    constraints = [
        "redaction:enabled"
        if bool(getattr(settings, "compliance_redaction_enabled", True))
        else "redaction:disabled",
        "trace_context:required"
        if bool(getattr(settings, "compliance_require_trace_context", True))
        else "trace_context:not_required",
        "source_urls:required"
        if bool(getattr(settings, "compliance_require_source_urls", False))
        else "source_urls:not_required",
    ]
    allowed_domains = tuple(getattr(settings, "compliance_allowed_domains", ()))
    blocked_domains = tuple(getattr(settings, "compliance_blocked_domains", ()))
    if allowed_domains:
        constraints.append(f"allowed_domains:{','.join(allowed_domains)}")
    if blocked_domains:
        constraints.append(f"blocked_domains:{','.join(blocked_domains)}")
    return constraints


def _audit_reason(
    *,
    status: RuntimePolicyStatus,
    blocking_reasons: list[str],
    warning_reasons: list[str],
) -> str:
    if status == "deny":
        return "Runtime policy denied execution: " + "; ".join(blocking_reasons) + "."
    if status == "warn":
        return "Runtime policy allows execution with warnings: " + "; ".join(warning_reasons) + "."
    return "Runtime policy allows execution."
