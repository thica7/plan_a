from __future__ import annotations

from collections.abc import Iterable

from packages.schema.enterprise import ModelRouteCandidate, ModelRouteDecision

ROUTING_POLICY_WEIGHTS = {
    "quality": 0.45,
    "compliance": 0.35,
    "cost": 0.20,
}


def build_model_route_decision(settings: object) -> ModelRouteDecision:
    redaction_enabled = bool(getattr(settings, "compliance_redaction_enabled", True))
    trace_required = bool(getattr(settings, "compliance_require_trace_context", True))
    default_mode = str(getattr(settings, "default_execution_mode", "demo"))
    candidates = [
        _primary_candidate(
            settings,
            redaction_enabled=redaction_enabled,
            trace_required=trace_required,
        ),
        _backup_candidate(
            settings,
            redaction_enabled=redaction_enabled,
            trace_required=trace_required,
        ),
        _demo_candidate(
            settings,
            redaction_enabled=redaction_enabled,
            trace_required=trace_required,
        ),
    ]
    candidates = [_score_candidate(item) for item in candidates]
    blocked_reasons: list[str] = []
    if not redaction_enabled:
        blocked_reasons.append("PII/credential redaction is disabled.")
    if not trace_required:
        blocked_reasons.append("Trace context is not required by policy.")

    configured_real = _rank_candidates(
        item
        for item in candidates
        if item.provider_kind in {"primary", "backup"} and item.configured
    )
    selected: ModelRouteCandidate | None = None
    if not blocked_reasons:
        selected = configured_real[0] if configured_real else None
        if selected is None and default_mode == "demo":
            selected = candidates[-1]

    if selected is None:
        if not configured_real:
            blocked_reasons.append("No primary or backup LLM provider is configured.")
        return ModelRouteDecision(
            status="blocked",
            selected=None,
            fallback=None,
            candidates=candidates,
            blocked_reasons=blocked_reasons,
        )

    fallback = next(
        (
            item
            for item in configured_real
            if selected is not None and item.provider_kind != selected.provider_kind
        ),
        None,
    )
    status = "selected" if selected.provider_kind == "primary" else "fallback"
    return ModelRouteDecision(
        status=status,
        selected=selected,
        fallback=fallback,
        candidates=candidates,
        blocked_reasons=blocked_reasons,
    )


def _primary_candidate(
    settings: object,
    *,
    redaction_enabled: bool,
    trace_required: bool,
) -> ModelRouteCandidate:
    configured = bool(
        getattr(settings, "ark_api_key", None) and getattr(settings, "ark_model", None)
    )
    return ModelRouteCandidate(
        provider_kind="primary",
        provider_name="ark",
        model_name=str(getattr(settings, "ark_model", "") or ""),
        configured=configured,
        quality_score=88 if configured else 0,
        cost_score=72 if configured else 0,
        compliance_score=_compliance_score(redaction_enabled, trace_required),
        reason="Primary provider is preferred for quality when configured."
        if configured
        else "Primary provider credentials are missing.",
    )


def _backup_candidate(
    settings: object,
    *,
    redaction_enabled: bool,
    trace_required: bool,
) -> ModelRouteCandidate:
    configured = bool(
        getattr(settings, "backup_llm_api_key", None)
        and getattr(settings, "backup_llm_model", None)
    )
    return ModelRouteCandidate(
        provider_kind="backup",
        provider_name="openrouter",
        model_name=str(getattr(settings, "backup_llm_model", "") or ""),
        configured=configured,
        quality_score=82 if configured else 0,
        cost_score=78 if configured else 0,
        compliance_score=_compliance_score(redaction_enabled, trace_required),
        reason="Backup provider is ready for failover."
        if configured
        else "Backup provider credentials are missing.",
    )


def _demo_candidate(
    settings: object,
    *,
    redaction_enabled: bool,
    trace_required: bool,
) -> ModelRouteCandidate:
    demo_mode = bool(getattr(settings, "demo_mode", True))
    return ModelRouteCandidate(
        provider_kind="demo",
        provider_name="deterministic",
        model_name="demo-fixture",
        configured=demo_mode,
        quality_score=58 if demo_mode else 0,
        cost_score=100 if demo_mode else 0,
        compliance_score=_compliance_score(redaction_enabled, trace_required),
        supports_tool_calling=False,
        supports_json_schema=True,
        reason="Demo route is deterministic and cost-free, but report quality is limited."
        if demo_mode
        else "Demo mode is disabled.",
    )


def _compliance_score(redaction_enabled: bool, trace_required: bool) -> int:
    score = 40
    if redaction_enabled:
        score += 35
    if trace_required:
        score += 25
    return score


def _score_candidate(candidate: ModelRouteCandidate) -> ModelRouteCandidate:
    score = 0
    if candidate.configured:
        score = round(
            candidate.quality_score * ROUTING_POLICY_WEIGHTS["quality"]
            + candidate.compliance_score * ROUTING_POLICY_WEIGHTS["compliance"]
            + candidate.cost_score * ROUTING_POLICY_WEIGHTS["cost"]
        )
    reasons = [
        f"quality_weight={ROUTING_POLICY_WEIGHTS['quality']:.2f}",
        f"compliance_weight={ROUTING_POLICY_WEIGHTS['compliance']:.2f}",
        f"cost_weight={ROUTING_POLICY_WEIGHTS['cost']:.2f}",
    ]
    risks: list[str] = []
    if not candidate.configured:
        risks.append("missing_credentials")
    if candidate.compliance_score < 100:
        risks.append("policy_guardrail_incomplete")
    if not candidate.supports_tool_calling:
        risks.append("limited_tool_calling")
    if not candidate.supports_json_schema:
        risks.append("limited_schema_output")
    if candidate.provider_kind == "demo":
        risks.append("deterministic_demo")
    return candidate.model_copy(
        update={
            "routing_score": max(0, min(100, score)),
            "routing_reasons": reasons,
            "risk_flags": risks,
        }
    )


def _rank_candidates(candidates: Iterable[ModelRouteCandidate]) -> list[ModelRouteCandidate]:
    return sorted(
        list(candidates),
        key=lambda item: (item.routing_score, _provider_preference(item.provider_kind)),
        reverse=True,
    )


def _provider_preference(provider_kind: str) -> int:
    return {"primary": 3, "backup": 2, "demo": 1}.get(provider_kind, 0)
