from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING

from packages.agents import SubagentContext
from packages.compliance import compliance_policy_from_settings, redact_text
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    CompetitorKB,
    CompetitorKnowledge,
    KnowledgeClaim,
    RawSource,
    UserPersonaSegment,
)
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
USER_RESEARCH_SOURCE_TYPES = {
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
}


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
                sources = self._sources_from_survey_bundle(detail, bundle, dimension, competitor)
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
                        "redaction_count": sum(bundle.redaction_counts.values()),
                        **self._research_redaction_metadata(bundle.redaction_counts),
                    },
                )
                usable_sources = [source for source in sources if self._source_is_usable(source)]
                for source in usable_sources:
                    detail.raw_sources.append(source)
                    added_sources.append(source)
                if usable_sources:
                    self._apply_survey_bundle_to_knowledge(
                        detail,
                        bundle,
                        dimension=dimension,
                        competitor=competitor,
                        source_ids=[source.id for source in usable_sources],
                    )
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
        redaction_counts = self._merge_research_redaction_counts(bundles)
        await self.emit(
            detail.id,
            "node_completed",
            "survey_interview",
            None,
            f"Survey/interview enrichment added {len(added_sources)} research evidence source(s).",
            {
                "added": len(added_sources),
                "source_ids": [source.id for source in added_sources],
                "source_types": sorted({source.source_type for source in added_sources}),
                "dimension_count": len(target_dimensions),
                "bundle_count": len(bundles),
                "question_count": sum(len(bundle.questions) for bundle in bundles),
                "response_count": sum(len(bundle.responses) for bundle in bundles),
                "interview_count": sum(len(bundle.interviews) for bundle in bundles),
                "redaction_counts": redaction_counts,
                "redaction_count": sum(redaction_counts.values()),
                **self._research_redaction_metadata(redaction_counts),
            },
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
            and source.source_type in USER_RESEARCH_SOURCE_TYPES
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
        redaction_counts: dict[str, int] = {}
        redacted_topic = self._redact_research_text(detail.topic, redaction_counts)
        redacted_competitor = self._redact_research_text(competitor, redaction_counts)
        redacted_dimension = self._redact_research_text(dimension, redaction_counts)
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
                prompt=self._redact_research_text(
                    (
                        f"How well does {redacted_competitor} fit the respondent's "
                        f"{redacted_dimension} needs for {redacted_topic}?"
                    ),
                    redaction_counts,
                ),
                response_type="likert",
                options=["1", "2", "3", "4", "5"],
            ),
            SurveyQuestion(
                id=self._research_question_id(dimension, "switching"),
                dimension=dimension,
                prompt=self._redact_research_text(
                    (
                        f"What switching risk, adoption blocker, or user pain point matters "
                        f"most for {redacted_competitor}?"
                    ),
                    redaction_counts,
                ),
                response_type="free_text",
            ),
        ]
        responses = [
            SurveyResponse(
                respondent_id=f"{self._issue_id_fragment(competitor)}-proxy-1",
                competitor=redacted_competitor,
                dimension=redacted_dimension,
                role="target user proxy",
                answers={
                    questions[0].id: "4",
                    questions[1].id: self._redact_research_text(
                        (
                            "Users and enterprise buyers weigh workflow fit, onboarding effort, "
                            "customer support, and switching cost before adoption."
                        ),
                        redaction_counts,
                    ),
                },
                quote=self._redact_research_text(
                    (
                        f"{competitor} is evaluated through user workflow fit, customer adoption "
                        "risk, and switching cost."
                    ),
                    redaction_counts,
                ),
                source_type="survey_simulated",
            )
        ]
        synthesized_interviews = [
            InterviewSynthesis(
                respondent=self._redact_research_text(item.respondent, redaction_counts),
                role=self._redact_research_text(item.role, redaction_counts),
                competitor=redacted_competitor,
                dimension=redacted_dimension,
                summary=self._redact_research_text(item.summary, redaction_counts),
                pain_points=[
                    "workflow fit uncertainty",
                    "onboarding effort",
                    "switching cost",
                ],
                use_cases=[
                    f"{redacted_topic} evaluation",
                    f"{redacted_dimension} buying criteria review",
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
        evidence_summary = self._redact_research_text(evidence_summary, redaction_counts)
        content_hash = hashlib.sha256(evidence_summary.encode("utf-8")).hexdigest()[:16]
        return SurveyEvidenceBundle(
            topic=redacted_topic,
            competitor=redacted_competitor,
            dimension=redacted_dimension,
            questions=questions,
            responses=responses,
            interviews=synthesized_interviews,
            evidence_summary=evidence_summary,
            source_type="survey_simulated",
            confidence=0.58,
            content_hash=content_hash,
            redaction_counts=redaction_counts,
        )

    def _sources_from_survey_bundle(
        self,
        detail: RunDetail,
        bundle: SurveyEvidenceBundle,
        dimension: str,
        competitor: str,
    ) -> list[RawSource]:
        redaction_counts = dict(bundle.redaction_counts)
        redacted_competitor = self._redact_research_text(competitor, redaction_counts)
        redacted_dimension = self._redact_research_text(dimension, redaction_counts)
        bundle.redaction_counts = redaction_counts
        sources = [
            RawSource(
                id=self._new_source_id(f"{dimension}-survey"),
                competitor=redacted_competitor,
                dimension=redacted_dimension,
                source_type=bundle.source_type,
                title=f"{redacted_competitor} {redacted_dimension} survey synthesis",
                snippet=bundle.evidence_summary,
                content_hash=bundle.content_hash,
                confidence=bundle.confidence,
                extracted_at=detail.updated_at,
            )
        ]
        if bundle.interviews:
            interview_summary = self._interview_evidence_summary(
                detail,
                dimension=dimension,
                competitor=competitor,
                interviews=bundle.interviews,
            )
            interview_summary = self._redact_research_text(interview_summary, redaction_counts)
            bundle.redaction_counts = redaction_counts
            sources.append(
                RawSource(
                    id=self._new_source_id(f"{dimension}-interview"),
                    competitor=redacted_competitor,
                    dimension=redacted_dimension,
                    source_type="interview_record",
                    title=f"{redacted_competitor} {redacted_dimension} interview synthesis",
                    snippet=interview_summary,
                    content_hash=hashlib.sha256(
                        interview_summary.encode("utf-8")
                    ).hexdigest()[:16],
                    confidence=max(bundle.confidence, 0.62),
                    extracted_at=detail.updated_at,
                )
            )
        return sources

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

    def _interview_evidence_summary(
        self,
        detail: RunDetail,
        *,
        dimension: str,
        competitor: str,
        interviews: list[InterviewSynthesis],
    ) -> str:
        pain_points = sorted({point for item in interviews for point in item.pain_points})
        use_cases = sorted({use_case for item in interviews for use_case in item.use_cases})
        summaries = " ".join(item.summary for item in interviews)
        return (
            f"Synthetic interview record for {competitor} in {detail.topic}: "
            f"respondents discussed {dimension} pain points "
            f"({', '.join(pain_points) or 'none'}) and use cases "
            f"({', '.join(use_cases) or 'none'}). {summaries}"
        )

    def _apply_survey_bundle_to_knowledge(
        self,
        detail: RunDetail,
        bundle: SurveyEvidenceBundle,
        *,
        dimension: str,
        competitor: str,
        source_ids: list[str],
    ) -> None:
        if not source_ids:
            return
        knowledge = detail.competitor_knowledge.get(competitor) or CompetitorKnowledge(
            competitor=competitor
        )
        claim = KnowledgeClaim(
            claim=(
                f"{bundle.competitor} user research indicates {bundle.dimension} decisions "
                "are shaped by workflow fit, onboarding effort, adoption risk, and switching "
                "cost."
            ),
            source_ids=source_ids,
            confidence=min(0.72, max(bundle.confidence, 0.62)),
        )
        existing_summary_claims = knowledge.user_personas.summary_claims
        if not any(existing.claim == claim.claim for existing in existing_summary_claims):
            knowledge.user_personas.summary_claims.append(claim)

        segment = UserPersonaSegment(
            name=f"{bundle.dimension.title()} buyer/user proxy",
            role="target user proxy",
            company_size="unknown",
            pain_points=sorted(
                {
                    point
                    for interview in bundle.interviews
                    for point in interview.pain_points
                }
            )
            or ["workflow fit uncertainty", "switching cost"],
            use_cases=sorted(
                {use_case for interview in bundle.interviews for use_case in interview.use_cases}
            )
            or [f"{bundle.topic} evaluation"],
            claims=[claim],
        )
        if not any(existing.name == segment.name for existing in knowledge.user_personas.segments):
            knowledge.user_personas.segments.append(segment)
        knowledge.source_ids = sorted({*knowledge.source_ids, *source_ids})
        existing_confidence = knowledge.confidence if knowledge.confidence > 0 else claim.confidence
        knowledge.confidence = round((existing_confidence + claim.confidence) / 2, 3)
        detail.competitor_knowledge[competitor] = knowledge

        kb = detail.competitor_kbs.get(competitor) or CompetitorKB(competitor=competitor)
        findings = kb.slices.get(dimension, [])
        finding = f"{claim.claim} [source:{source_ids[0]}]"
        if finding not in findings:
            findings.append(finding)
        kb.slices[dimension] = findings
        kb.sources = sorted({*kb.sources, *source_ids})
        kb.confidence = max(kb.confidence, claim.confidence)
        detail.competitor_kbs[competitor] = kb

    def _redact_research_text(self, text: str, counts: dict[str, int]) -> str:
        policy = compliance_policy_from_settings(getattr(self, "_settings", object()))
        result = redact_text(text, policy=policy)
        for key, count in result.counts.items():
            counts[key] = counts.get(key, 0) + count
        return result.text

    def _research_redaction_metadata(
        self,
        counts: dict[str, int],
    ) -> dict[str, int | bool]:
        return {
            "research_redacted": bool(counts),
            **{f"research_redaction_{key}_count": value for key, value in counts.items()},
        }

    def _merge_research_redaction_counts(
        self,
        bundles: list[SurveyEvidenceBundle],
    ) -> dict[str, int]:
        merged: dict[str, int] = {}
        for bundle in bundles:
            for key, value in bundle.redaction_counts.items():
                merged[key] = merged.get(key, 0) + value
        return merged

    def _research_question_id(self, dimension: str, suffix: str) -> str:
        return f"{self._issue_id_fragment(dimension)}-{suffix}"
