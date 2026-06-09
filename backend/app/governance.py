from __future__ import annotations

from fastapi import HTTPException, status

from packages.config import Settings
from packages.governance import build_model_policy_report, model_policy_block_message


def ensure_model_policy_allows_execution_mode(
    execution_mode: str,
    settings: Settings,
) -> None:
    if execution_mode != "real":
        return
    report = build_model_policy_report(settings)
    if report.real_execution_allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "message": model_policy_block_message(report),
            "policy_version": report.policy_version,
            "blocking_finding_ids": report.blocking_finding_ids,
            "status": report.status,
        },
    )
