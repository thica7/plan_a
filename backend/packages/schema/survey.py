from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

SurveyResponseType = Literal["likert", "multiple_choice", "free_text"]
ResearchSourceType = Literal[
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
]
ImportedResearchSourceType = Literal[
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
]


class SurveyQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dimension: str
    prompt: str
    response_type: SurveyResponseType = "free_text"
    options: list[str] = Field(default_factory=list)


class SurveyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    respondent_id: str
    competitor: str
    dimension: str
    role: str
    answers: dict[str, str] = Field(default_factory=dict)
    quote: str = ""
    source_type: ResearchSourceType = "survey_simulated"


class InterviewSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    respondent: str
    role: str
    competitor: str
    dimension: str
    summary: str
    pain_points: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    content_hash: str


class SurveyEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    competitor: str
    dimension: str
    questions: list[SurveyQuestion] = Field(default_factory=list)
    responses: list[SurveyResponse] = Field(default_factory=list)
    interviews: list[InterviewSynthesis] = Field(default_factory=list)
    evidence_summary: str
    source_type: ResearchSourceType = "survey_simulated"
    confidence: float = Field(default=0.56, ge=0.0, le=1.0)
    content_hash: str
    redaction_counts: dict[str, int] = Field(default_factory=dict)


class UserResearchMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    source_type: ImportedResearchSourceType
    competitor: str = Field(min_length=1)
    dimension: str = Field(default="persona", min_length=1)
    title: str = ""
    text: str = Field(min_length=1)
    respondent: str = "anonymous"
    role: str = "unknown"
    source_url: HttpUrl | None = None
    collected_at: datetime | None = None
    confidence: float = Field(default=0.78, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserResearchImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    materials: list[UserResearchMaterial] = Field(min_length=1)
    imported_by: str = "manual_import"


class ImportedUserResearchMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: str
    source_id: str
    source_type: ImportedResearchSourceType
    competitor: str
    dimension: str
    title: str
    confidence: float = Field(ge=0.0, le=1.0)
    redaction_counts: dict[str, int] = Field(default_factory=dict)


class UserResearchImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    imported_count: int = Field(ge=0)
    source_ids: list[str] = Field(default_factory=list)
    materials: list[ImportedUserResearchMaterial] = Field(default_factory=list)
    bundles: list[SurveyEvidenceBundle] = Field(default_factory=list)
    redaction_counts: dict[str, int] = Field(default_factory=dict)
    projection_synced: bool = False
