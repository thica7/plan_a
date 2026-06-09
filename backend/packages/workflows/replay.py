from __future__ import annotations

from dataclasses import dataclass

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from packages.workflows.competitive_intel import CompetitiveIntelWorkflow
from packages.workflows.report_approval import ReportApprovalWorkflow


@dataclass(frozen=True)
class ReplayCheckResult:
    workflow_id: str
    event_count: int
    ok: bool
    failure: str = ""


async def replay_temporal_history(history: WorkflowHistory) -> ReplayCheckResult:
    result = await Replayer(
        workflows=[CompetitiveIntelWorkflow, ReportApprovalWorkflow],
    ).replay_workflow(history, raise_on_replay_failure=False)
    failure = result.replay_failure
    return ReplayCheckResult(
        workflow_id=history.workflow_id,
        event_count=len(history.events),
        ok=failure is None,
        failure=str(failure) if failure else "",
    )
