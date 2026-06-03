from __future__ import annotations

from packages.schema.enterprise import ModelRouteCandidate, ModelRouteDecision


def build_model_route_decision(settings: object) -> ModelRouteDecision:
    redaction_enabled = bool(getattr(settings, "compliance_redaction_enabled", True))
    trace_required = bool(getattr(settings, "compliance_require_trace_context", True))
    default_mode = str(getattr(settings, "default_execution_mode", "demo"))
    candidates = [
        _primary_candidate(settings, redaction_enabled=redaction_enabled, trace_required=trace_required),
        _backup_candidate(settings, redaction_enabled=redaction_enabled, trace_required=trace_required),
        _demo_candidate(settings, redaction_enabled=redaction_enabled, trace_required=trace_required),
    ]
    blocked_reasons: list[str] = []
    if not redaction_enabled:
        blocked_reasons.append("PII/credential redaction is disabled.")
    if not trace_required:
        blocked_reasons.append("Trace context is not required by policy.")

    configured_real = [
        item for item in candidates if item.provider_kind in {"primary", "backup"} and item.configured
    ]
    selected: ModelRouteCandidate | None = None
    if not blocked_reasons:
        selected = next((item for item in configured_real if item.provider_kind == "primary"), None)
        if selected is None:
            selected = next((item for item in configured_real if item.provider_kind == "backup"), None)
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
    configured = bool(getattr(settings, "ark_api_key", None) and getattr(settings, "ark_model", None))
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
