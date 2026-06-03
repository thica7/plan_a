from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvalOpsStatus = Literal["pass", "warn", "fail"]
EvalJudgeMode = Literal["heuristic", "llm"]


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


class EvalOpsQualityChainStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: Literal[
        "real_collection",
        "real_llm",
        "report_quality",
        "rag_gap_fill",
        "human_review",
        "decision_replay",
    ]
    label: str
    total_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    failed_run_ids: list[str] = Field(default_factory=list)
    summary: str = ""


class EvalOpsRegressionGateIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["comparison", "metric", "case"]
    id: str
    status: EvalOpsStatus
    summary: str = ""


class EvalOpsGoldenCohortSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cohort: str
    case_count: int = Field(ge=0)
    matched_run_count: int = Field(ge=0)
    coverage_rate: float = Field(ge=0.0, le=1.0)
    expected_layers: list[str] = Field(default_factory=list)


class EvalOpsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_count: int = Field(ge=0)
    evaluated_run_ids: list[str] = Field(default_factory=list)
    baseline_run_id: str | None = None
    real_run_count: int = Field(ge=0)
    demo_run_count: int = Field(ge=0)
    real_run_ratio: float = Field(ge=0.0, le=1.0)
    real_quality_chain_rate: float = Field(ge=0.0, le=1.0)
    real_quality_chain_failed_run_ids: list[str] = Field(default_factory=list)
    decision_replay_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    decision_replay_failed_run_ids: list[str] = Field(default_factory=list)
    quality_chain_steps: list[EvalOpsQualityChainStep] = Field(default_factory=list)
    average_delta_score: float | None = None
    regressed_run_count: int = Field(ge=0)
    judge_mode: EvalJudgeMode = "heuristic"
    judge_avg_score: float = Field(default=0.0, ge=0.0, le=100.0)
    llm_judge_avg_score: float | None = Field(default=None, ge=0.0, le=100.0)
    judge_fallback_reason: str = ""
    hitl_enabled_run_rate: float = Field(ge=0.0, le=1.0)
    human_correction_rate: float = Field(ge=0.0, le=1.0)
    hitl_redo_loop_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    user_research_evidence_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    rag_gap_fill_context_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    rag_gap_fill_section_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    redo_iteration_count: int = Field(ge=0)
    redo_convergence_ratio: float = Field(ge=0.0)
    golden_set_size: int = Field(ge=0)
    golden_set_pass_rate: float = Field(ge=0.0, le=1.0)
    golden_catalog_size: int = Field(default=0, ge=0)
    golden_catalog_covered_case_count: int = Field(default=0, ge=0)
    golden_catalog_coverage_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    golden_catalog_cohorts: list[EvalOpsGoldenCohortSummary] = Field(default_factory=list)
    report_quality_score: int = Field(ge=0, le=100)
    source_recall: float = Field(ge=0.0, le=1.0)
    compliance_pass_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    compliance_fail_count: int = Field(default=0, ge=0)
    compliance_blocker_count: int = Field(default=0, ge=0)
    coverage_lift_rate: float | None = Field(default=None, ge=-1.0, le=1.0)
    manual_baseline_hours_per_report: float = Field(ge=0.0)
    manual_baseline_hours: float = Field(ge=0.0)
    automation_runtime_hours: float = Field(ge=0.0)
    manual_time_saved_hours: float = Field(ge=0.0)
    task_time_saved_hours: float = Field(ge=0.0)
    time_savings_rate: float = Field(ge=0.0, le=1.0)
    cost_per_report_usd: float = Field(ge=0.0)
    regression_gate_status: EvalOpsStatus
    regression_gate_reason: str
    regression_gate_issues: list[EvalOpsRegressionGateIssue] = Field(default_factory=list)
    metrics: list[EvalOpsMetric] = Field(default_factory=list)
    cases: list[EvalOpsCaseResult] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
