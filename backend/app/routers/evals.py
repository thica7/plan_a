from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_run_service
from packages.evals import build_enterprise_evalops_report
from packages.orchestrator.service import RunService
from packages.schema.evals import EvalJudgeMode, EvalOpsReport

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]


@router.get("/evals/enterprise", response_model=EvalOpsReport)
async def get_enterprise_evalops_report(
    service: RunServiceDep,
    project_id: str | None = None,
    baseline_run_id: str | None = None,
    limit: int = Query(default=30, ge=1, le=200),
    judge_mode: EvalJudgeMode = "heuristic",
) -> EvalOpsReport:
    runs = [
        detail
        for summary in service.list_runs()
        if (detail := service.get_run(summary.id)) is not None
        and (project_id is None or detail.project_id == project_id)
    ]
    baseline = None
    if baseline_run_id:
        baseline = service.get_run(baseline_run_id)
        if baseline is None:
            raise HTTPException(status_code=404, detail="Baseline run not found")
    return build_enterprise_evalops_report(
        runs,
        baseline=baseline,
        limit=limit,
        judge_mode=judge_mode,
    )
