from __future__ import annotations

from datetime import datetime

from packages.schema.enterprise import (
    QuotaEnforcementMode,
    WorkspaceQuotaDecision,
    WorkspaceRecord,
    WorkspaceUsageStatus,
    WorkspaceUsageSummary,
)

USAGE_WARNING_RATIO = 0.8


class WorkspaceQuotaExceededError(ValueError):
    def __init__(self, decision: WorkspaceQuotaDecision) -> None:
        super().__init__(decision.reason or "Workspace quota exceeded.")
        self.decision = decision


def current_month_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.utcnow()
    period_start = datetime(current.year, current.month, 1)
    if current.month == 12:
        period_end = datetime(current.year + 1, 1, 1)
    else:
        period_end = datetime(current.year, current.month + 1, 1)
    return period_start, period_end


def build_workspace_usage_summary(
    workspace: WorkspaceRecord,
    *,
    period_start: datetime,
    period_end: datetime,
    run_count: int,
    completed_run_count: int,
    failed_run_count: int,
    interrupted_run_count: int,
    input_tokens_estimate: int,
    output_tokens_estimate: int,
    cost_estimate_usd: float,
) -> WorkspaceUsageSummary:
    total_tokens = input_tokens_estimate + output_tokens_estimate
    run_ratio = _usage_ratio(run_count, workspace.monthly_run_quota)
    token_ratio = _usage_ratio(total_tokens, workspace.monthly_token_quota)
    cost_ratio = _usage_ratio(cost_estimate_usd, workspace.monthly_cost_quota_usd)
    status = _usage_status(run_ratio, token_ratio, cost_ratio)
    return WorkspaceUsageSummary(
        workspace_id=workspace.id,
        period_start=period_start,
        period_end=period_end,
        run_count=run_count,
        completed_run_count=completed_run_count,
        failed_run_count=failed_run_count,
        interrupted_run_count=interrupted_run_count,
        input_tokens_estimate=input_tokens_estimate,
        output_tokens_estimate=output_tokens_estimate,
        total_tokens_estimate=total_tokens,
        cost_estimate_usd=round(cost_estimate_usd, 6),
        monthly_run_quota=workspace.monthly_run_quota,
        monthly_token_quota=workspace.monthly_token_quota,
        monthly_cost_quota_usd=workspace.monthly_cost_quota_usd,
        run_usage_ratio=round(run_ratio, 4),
        token_usage_ratio=round(token_ratio, 4),
        cost_usage_ratio=round(cost_ratio, 4),
        status=status,
    )


def build_quota_decision(
    usage: WorkspaceUsageSummary,
    enforcement: QuotaEnforcementMode,
) -> WorkspaceQuotaDecision:
    allowed = usage.status != "exceeded" or enforcement == "monitor"
    return WorkspaceQuotaDecision(
        workspace_id=usage.workspace_id,
        allowed=allowed,
        status=usage.status,
        enforcement=enforcement,
        reason=_quota_reason(usage, enforcement),
        usage=usage,
    )


def _usage_ratio(used: int | float, quota: int | float) -> float:
    if quota <= 0:
        return 1.0
    return max(0.0, float(used) / float(quota))


def _usage_status(*ratios: float) -> WorkspaceUsageStatus:
    if any(ratio >= 1.0 for ratio in ratios):
        return "exceeded"
    if any(ratio >= USAGE_WARNING_RATIO for ratio in ratios):
        return "warn"
    return "ok"


def _quota_reason(
    usage: WorkspaceUsageSummary,
    enforcement: QuotaEnforcementMode,
) -> str:
    if usage.status == "ok":
        return "Workspace usage is within quota."
    pressure = max(
        ("runs", usage.run_usage_ratio),
        ("tokens", usage.token_usage_ratio),
        ("cost", usage.cost_usage_ratio),
        key=lambda item: item[1],
    )
    if usage.status == "warn":
        return (
            f"Workspace {usage.workspace_id} is approaching its monthly "
            f"{pressure[0]} quota ({pressure[1]:.0%})."
        )
    if enforcement == "monitor":
        return (
            f"Workspace {usage.workspace_id} exceeded its monthly "
            f"{pressure[0]} quota ({pressure[1]:.0%}); monitor mode allows runs."
        )
    return (
        f"Workspace {usage.workspace_id} exceeded its monthly "
        f"{pressure[0]} quota ({pressure[1]:.0%}); new runs are blocked."
    )
