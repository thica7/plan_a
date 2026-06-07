from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.identity import stable_prefixed_id
from packages.schema.models import RedoScope

QualityFindingSeverity = Literal["info", "warn", "blocker"]
QualityFindingStatus = Literal["open", "resolved", "deferred", "accepted_risk"]
QualityFindingRequiredAction = Literal[
    "none",
    "add_evidence",
    "rewrite_claim",
    "downgrade_claim",
    "delete_claim",
    "rewrite_report",
    "rerun_scope",
    "human_review",
    "monitor",
]


class QualityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    source_agent: str
    framework: str = ""
    source_id: str = ""
    severity: QualityFindingSeverity
    status: QualityFindingStatus = "open"
    issue_type: str
    competitor_id: str | None = None
    competitor_name: str | None = None
    dimension: str | None = None
    field_path: str | None = None
    report_section: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    message: str
    recommendation: str = ""
    required_action: QualityFindingRequiredAction = "human_review"
    repairable: bool = False
    acceptance_rule: str = ""
    redo_scope: RedoScope | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def fill_stable_id(self) -> QualityFinding:
        if not self.id:
            self.id = stable_prefixed_id(
                "quality-finding",
                self.source_agent,
                self.source_id,
                self.severity,
                self.issue_type,
                self.competitor_id or self.competitor_name or "",
                self.dimension or "",
                self.field_path or "",
                self.claim_ids,
                self.evidence_ids,
                self.message,
                length=20,
            )
        self.repairable = (
            self.repairable
            or self.redo_scope is not None
            or self.required_action
            in {
                "add_evidence",
                "rewrite_claim",
                "downgrade_claim",
                "delete_claim",
                "rewrite_report",
                "rerun_scope",
            }
        )
        return self


class QualityFindingBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_agent: str
    findings: list[QualityFinding] = Field(default_factory=list)
    blocker_count: int = Field(default=0, ge=0)
    warn_count: int = Field(default=0, ge=0)
    info_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def count_findings(self) -> QualityFindingBundle:
        self.blocker_count = sum(1 for item in self.findings if item.severity == "blocker")
        self.warn_count = sum(1 for item in self.findings if item.severity == "warn")
        self.info_count = sum(1 for item in self.findings if item.severity == "info")
        return self
