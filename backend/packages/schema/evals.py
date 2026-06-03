from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EvalOpsStatus = Literal["pass", "warn", "fail"]


class EvalOpsMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    target: float
    unit: str = ""
    status: EvalOpsStatus
    summary: str = ""


class EvalOpsCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    name: str
    status: EvalOpsStatus
    score: int = Field(ge=0, le=100)
    target_run_id: str | None = None
    baseline_run_id: str | None = None
    summary: str = ""


class EvalOpsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_count: int = Field(ge=0)
    evaluated_run_ids: list[str] = Field(default_factory=list)
    baseline_run_id: str | None = None
    real_run_count: int = Field(ge=0)
    demo_run_count: int = Field(ge=0)
    real_run_ratio: float = Field(ge=0.0, le=1.0)
    real_quality_chain_rate: float = Field(ge=0.0, le=1.0)
    average_delta_score: float | None = None
    regressed_run_count: int = Field(ge=0)
    hitl_enabled_run_rate: float = Field(ge=0.0, le=1.0)
    human_correction_rate: float = Field(ge=0.0, le=1.0)
    redo_iteration_count: int = Field(ge=0)
    redo_convergence_ratio: float = Field(ge=0.0)
    golden_set_size: int = Field(ge=0)
    golden_set_pass_rate: float = Field(ge=0.0, le=1.0)
    report_quality_score: int = Field(ge=0, le=100)
    source_recall: float = Field(ge=0.0, le=1.0)
    task_time_saved_hours: float = Field(ge=0.0)
    cost_per_report_usd: float = Field(ge=0.0)
    regression_gate_status: EvalOpsStatus
    regression_gate_reason: str
    metrics: list[EvalOpsMetric] = Field(default_factory=list)
    cases: list[EvalOpsCaseResult] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
