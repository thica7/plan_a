from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING

from packages.agents import SubagentContext
from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource
from packages.schema.survey import (
    InterviewSynthesis,
    SurveyEvidenceBundle,
    SurveyQuestion,
    SurveyResponse,
)
from packages.tools import survey_simulator

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


USER_RESEARCH_DIMENSION_HINTS = (
    "persona",
    "user",
    "customer",
    "buyer",
    "review",
    "feedback",
    "adoption",
    "switching",
    "use_case",
    "use case",
)


class SurveyInterviewAgentMixin:
    async def _run_survey_interview_enrichment(
        self,
        record: RunRecord,
        dimensions: list[str],
        competitors: list[str],
    ) -> None:
        detail = record.detail
        target_dimensions = [
            dimension for dimension in dimensions if self._dimension_needs_user_research(dimension)
        ]
        detail.current_node = "survey_interview"
        await self.emit(
            detail.id,
            "node_started",
            "survey_interview",
            None,
            "Preparing survey/interview evidence enrichment.",
            {"dimensions": target_dimensions, "competitors": competitors},
        )
        if not target_dimensions:
            self._append_agent_message(
                record,
                from_agent="survey_interview",
                to_agent="collect_qa",
                message_type="survey_interview_skipped",
                payload_schema="SurveyEvidenceBundle[]",
                payload={"reason": "no_user_research_dimensions", "bundles": []},
            )
            await self.emit(
                detail.id,
                "node_completed",
                "survey_interview",
                None,
                "Survey/interview enrichment skipped for this run.",
                {"added": 0},
            )
            return

        bundles: list[SurveyEvidenceBundle] = []
        added_sources: list[RawSource] = []
        for dimension in target_dimensions:
            for competitor in competitors:
                if self._has_user_research_source(detail, dimension, competitor):
                    continue
                qa_feedback = self._qa_feedback_for_branch(
                    detail,
                    "collector",
                    dimension,
                    competitor,
                )
                bundle = self._build_survey_interview_bundle(
                    detail,
                    dimension=dimension,
                    competitor=competitor,
                    qa_feedback=qa_feedback,
                )
                context = SubagentContext(
                    run_id=detail.id,
                    agent="survey_interview",
                    subagent=self._analyst_branch_id(dimension, competitor),
                )
                self._trace_local_tool(
                    record,
                    agent="survey_interview",
                    subagent=context.subagent,
                    name="survey_interview_agent",
                    input_text=json.dumps(
                        {
                            "topic": detail.topic,
                            "competitor": competitor,
                            "dimension": dimension,
                            "qa_feedback": qa_feedback,
                        },
                        ensure_ascii=False,
                    ),
                    output_text=bundle.model_dump_json(),
                    context=context,
                    metadata={
                        "source_type": bundle.source_type,
                        "question_count": len(bundle.questions),
                        "response_count": len(bundle.responses),
                        "interview_count": len(bundle.interviews),
                    },
                )
                source = self._source_from_survey_bundle(detail, bundle, dimension, competitor)
                if self._source_is_usable(source):
                    detail.raw_sources.append(source)
                    added_sources.append(source)
                    bundles.append(bundle)

        self._append_agent_message(
            record,
            from_agent="survey_interview",
            to_agent="collect_qa",
            message_type="survey_interview_evidence_collected",
            payload_schema="SurveyEvidenceBundle[]",
            payload={
                "dimensions": target_dimensions,
                "competitors": competitors,
                "source_ids": [source.id for source in added_sources],
                "bundles": [bundle.model_dump(mode="json") for bundle in bundles],
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "survey_interview",
            None,
            f"Survey/interview enrichment added {len(added_sources)} research evidence source(s).",
            {"added": len(added_sources), "source_ids": [source.id for source in added_sources]},
        )

    def _dimension_needs_user_research(self, dimension: str) -> bool:
        normalized = dimension.casefold().replace("-", "_")
        return any(hint in normalized for hint in USER_RESEARCH_DIMENSION_HINTS)

    def _has_user_research_source(
        self,
        detail: RunDetail,
        dimension: str,
        competitor: str,
    ) -> bool:
        return any(
            source.dimension == dimension
            and source.source_type in {"survey_simulated", "interview_record", "manual_transcript"}
            and self._source_matches_competitor(source, competitor)
            for source in detail.raw_sources
        )

    def _build_survey_interview_bundle(
        self,
        detail: RunDetail,
        *,
        dimension: str,
        competitor: str,
        qa_feedback: list[dict[str, object]],
    ) -> SurveyEvidenceBundle:
        interviews = survey_simulator(
            topic=detail.topic,
            competitor=competitor,
            dimension=dimension,
            qa_feedback=qa_feedback,
        )
        questions = [
            SurveyQuestion(
                id=self._research_question_id(dimension, "fit"),
                dimension=dimension,
                prompt=(
                    f"How well does {competitor} fit the respondent's {dimension} needs "
                    f"for {detail.topic}?"
                ),
                response_type="likert",
                options=["1", "2", "3", "4", "5"],
            ),
            SurveyQuestion(
                id=self._research_question_id(dimension, "switching"),
                dimension=dimension,
                prompt=(
                    f"What switching risk, adoption blocker, or user pain point matters "
                    f"most for {competitor}?"
                ),
                response_type="free_text",
            ),
        ]
        responses = [
            SurveyResponse(
                respondent_id=f"{self._issue_id_fragment(competitor)}-proxy-1",
                competitor=competitor,
                dimension=dimension,
                role="target user proxy",
                answers={
                    questions[0].id: "4",
                    questions[1].id: (
                        "Users and enterprise buyers weigh workflow fit, onboarding effort, "
                        "customer support, and switching cost before adoption."
                    ),
                },
                quote=(
                    f"{competitor} is evaluated through user workflow fit, customer adoption "
                    "risk, and switching cost."
                ),
                source_type="survey_simulated",
            )
        ]
        synthesized_interviews = [
            InterviewSynthesis(
                respondent=item.respondent,
                role=item.role,
                competitor=competitor,
                dimension=dimension,
                summary=item.summary,
                pain_points=[
                    "workflow fit uncertainty",
                    "onboarding effort",
                    "switching cost",
                ],
                use_cases=[
                    f"{detail.topic} evaluation",
                    f"{dimension} buying criteria review",
                ],
                content_hash=item.content_hash,
            )
            for item in interviews
        ]
        evidence_summary = self._survey_evidence_summary(
            detail,
            dimension,
            competitor,
            synthesized_interviews,
            responses,
        )
        content_hash = hashlib.sha256(evidence_summary.encode("utf-8")).hexdigest()[:16]
        return SurveyEvidenceBundle(
            topic=detail.topic,
            competitor=competitor,
            dimension=dimension,
            questions=questions,
            responses=responses,
            interviews=synthesized_interviews,
            evidence_summary=evidence_summary,
            source_type="survey_simulated",
            confidence=0.58,
            content_hash=content_hash,
        )

    def _source_from_survey_bundle(
        self,
        detail: RunDetail,
        bundle: SurveyEvidenceBundle,
        dimension: str,
        competitor: str,
    ) -> RawSource:
        return RawSource(
            id=self._new_source_id(dimension),
            competitor=competitor,
            dimension=dimension,
            source_type=bundle.source_type,
            title=f"{competitor} {dimension} survey/interview synthesis",
            snippet=bundle.evidence_summary,
            content_hash=bundle.content_hash,
            confidence=bundle.confidence,
            extracted_at=detail.updated_at,
        )

    def _survey_evidence_summary(
        self,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        interviews: list[InterviewSynthesis],
        responses: list[SurveyResponse],
    ) -> str:
        interview_summary = interviews[0].summary if interviews else ""
        quote = responses[0].quote if responses else ""
        return (
            f"Simulated survey and interview research for {competitor} in {detail.topic}: "
            f"target users, customers, enterprise teams, and buyer personas evaluate "
            f"{dimension} by workflow fit, adoption risk, onboarding effort, customer support, "
            f"use case coverage, and switching cost. {interview_summary} {quote}"
        )

    def _research_question_id(self, dimension: str, suffix: str) -> str:
        return f"{self._issue_id_fragment(dimension)}-{suffix}"
