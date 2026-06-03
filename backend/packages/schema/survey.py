from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SurveyResponseType = Literal["likert", "multiple_choice", "free_text"]
ResearchSourceType = Literal[
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
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
