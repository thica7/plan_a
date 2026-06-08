from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime

from packages.enterprise.advisory_context import build_run_advisory_context_metadata
from packages.identity import (
    compute_claim_id,
    compute_competitor_set_hash,
    compute_evidence_id,
    compute_report_version_id,
    compute_topic_normalized,
    normalize_dimension_key,
    normalize_url,
)
from packages.refs import normalize_competitor_key
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import (
    ClaimRecord,
    EnterpriseRunProjection,
    EvidenceRecord,
    ReportVersionRecord,
)
from packages.schema.models import CompetitorKnowledge, KnowledgeClaim, QCIssue, RawSource
from packages.sources import normalize_report_source_tokens, raw_source_alias_metadata

_SURVEY_SOURCE_TYPES = {"survey_simulated", "survey_response"}
_INTERVIEW_SOURCE_TYPES = {"interview_record"}
_MANUAL_RESEARCH_SOURCE_TYPES = {"manual_transcript", "manual_note", "manual"}
_USER_RESEARCH_SOURCE_TYPES = (
    _SURVEY_SOURCE_TYPES | _INTERVIEW_SOURCE_TYPES | _MANUAL_RESEARCH_SOURCE_TYPES
)
_MIN_RELEASE_CLAIM_SOURCE_CONFIDENCE = 0.75


def build_enterprise_projection(
    detail: RunDetail,
    *,
    workspace_id: str = "default-workspace",
    project_id: str | None = None,
    version_number: int = 1,
    competitor_layer: str = "unknown",
    competitor_id_map: Mapping[str, str] | None = None,
) -> EnterpriseRunProjection:
    """Project the current run-centric DTO into Phase 1 enterprise records."""

    resolved_project_id = project_id or f"project-{detail.id}"
    evidence_records = _build_evidence_records(
        detail,
        workspace_id,
        resolved_project_id,
        competitor_id_map,
    )
    evidence_by_source = _index_evidence_by_source(evidence_records)
    claim_records = _build_claim_records(
        detail,
        workspace_id,
        resolved_project_id,
        evidence_by_source,
        competitor_id_map,
    )
    report_version = _build_report_version(
        detail,
        workspace_id,
        resolved_project_id,
        version_number,
        competitor_layer,
        claim_records,
        evidence_records,
        competitor_id_map,
    )
    return EnterpriseRunProjection(
        workspace_id=workspace_id,
        project_id=resolved_project_id,
        run_id=detail.id,
        evidence_records=evidence_records,
        claim_records=claim_records,
        report_version=report_version,
    )


def _build_evidence_records(
    detail: RunDetail,
    workspace_id: str,
    project_id: str,
    competitor_id_map: Mapping[str, str] | None,
) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    seen: set[str] = set()
    for source in detail.raw_sources:
        for competitor in _source_competitors(source):
            competitor_id = _competitor_id_for(competitor, competitor_id_map)
            canonical_url = normalize_url(str(source.url) if source.url is not None else "")
            evidence_id = compute_evidence_id(
                canonical_url,
                source.content_hash,
                competitor_id,
                source.dimension,
            )
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            records.append(
                EvidenceRecord(
                    id=evidence_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    run_id=detail.id,
                    raw_source_id=source.id,
                    competitor_id=competitor_id,
                    dimension=normalize_dimension_key(source.dimension),
                    source_type=source.source_type,
                    title=source.title,
                    url=source.url,
                    canonical_url=canonical_url,
                    snippet=source.snippet,
                    content_hash=source.content_hash,
                    reliability_score=source.confidence,
                    freshness_score=1.0,
                    quality_label=_quality_label(source),
                    first_seen_run_id=detail.id,
                    last_seen_run_id=detail.id,
                    seen_count=1,
                    captured_at=source.extracted_at,
                    metadata=_source_metadata(source),
                )
            )
    return records


def _build_claim_records(
    detail: RunDetail,
    workspace_id: str,
    project_id: str,
    evidence_by_source: dict[tuple[str, str], list[EvidenceRecord]],
    competitor_id_map: Mapping[str, str] | None,
) -> list[ClaimRecord]:
    records: list[ClaimRecord] = []
    seen: set[str] = set()
    for competitor, knowledge in detail.competitor_knowledge.items():
        competitor_id = _competitor_id_for(competitor, competitor_id_map)
        for dimension in detail.plan.dimensions:
            for claim in _claims_for_dimension(knowledge, dimension):
                candidate_evidence = _evidence_for_claim(claim, competitor_id, evidence_by_source)
                evidence_ids = _release_claim_evidence_ids(candidate_evidence) or [
                    evidence.id for evidence in candidate_evidence
                ]
                if not evidence_ids:
                    continue
                claim_id = compute_claim_id(
                    evidence_ids[0],
                    claim.claim,
                    normalize_dimension_key(dimension),
                )
                if claim_id in seen:
                    continue
                seen.add(claim_id)
                records.append(
                    ClaimRecord(
                        id=claim_id,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        run_id=detail.id,
                        competitor_id=competitor_id,
                        claim_type=normalize_dimension_key(dimension),
                        claim_text=claim.claim,
                        evidence_ids=evidence_ids,
                        confidence=claim.confidence,
                        status="proposed"
                        if _release_claim_evidence_ids(candidate_evidence)
                        else "deprecated",
                        created_by_agent="analyst",
                    )
                )
    return records


def _build_report_version(
    detail: RunDetail,
    workspace_id: str,
    project_id: str,
    version_number: int,
    competitor_layer: str,
    claim_records: list[ClaimRecord],
    evidence_records: list[EvidenceRecord],
    competitor_id_map: Mapping[str, str] | None,
) -> ReportVersionRecord:
    competitor_ids = [_competitor_id_for(c, competitor_id_map) for c in detail.plan.competitors]
    competitor_set_hash = compute_competitor_set_hash(competitor_ids)
    topic_normalized = compute_topic_normalized(detail.topic)
    evidence_ids = [evidence.id for evidence in evidence_records]
    normalized_report = normalize_report_source_tokens(
        detail.report_md,
        evidence_records,
        scoped_evidence_ids=evidence_ids,
    )
    release_claim_records = _release_claim_records(claim_records)
    report_version = ReportVersionRecord(
        id=compute_report_version_id(
            run_id=detail.id,
            version_number=version_number,
            topic_normalized=topic_normalized,
            competitor_set_hash=competitor_set_hash,
        ),
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=detail.id,
        version_number=version_number,
        topic_normalized=topic_normalized,
        competitor_layer=competitor_layer,
        competitor_set_hash=competitor_set_hash,
        report_md=normalized_report.report_md,
        claim_ids=[claim.id for claim in release_claim_records],
        evidence_ids=normalized_report.evidence_ids,
        quality_metadata={
            **_build_quality_metadata(
                detail,
                evidence_records,
                source_reconciliation=normalized_report.reconciliation(evidence_records),
            ),
            "release_claim_admission": _release_claim_admission_metadata(
                claim_records,
                release_claim_records,
                evidence_records,
            ),
            "report_competitors": list(detail.plan.competitors),
            "report_competitor_ids": competitor_ids,
            "report_competitor_homepages": _report_competitor_homepage_metadata(
                detail,
                competitor_ids,
            ),
        },
        created_at=_parse_datetime(detail.updated_at),
    )
    quality_metadata = dict(report_version.quality_metadata)
    quality_metadata["advisory_context"] = build_run_advisory_context_metadata(
        version=report_version,
        memory_candidate_ids=detail.plan.memory_candidate_ids,
        memory_prompt_context=detail.plan.memory_prompt_context,
    )
    return report_version.model_copy(update={"quality_metadata": quality_metadata})


def _index_evidence_by_source(
    evidence_records: list[EvidenceRecord],
) -> dict[tuple[str, str], list[EvidenceRecord]]:
    index: dict[tuple[str, str], list[EvidenceRecord]] = defaultdict(list)
    for record in evidence_records:
        index[(record.raw_source_id, record.competitor_id)].append(record)
        index[(record.raw_source_id, "*")].append(record)
    return index


def _evidence_for_claim(
    claim: KnowledgeClaim,
    competitor_id: str,
    evidence_by_source: dict[tuple[str, str], list[EvidenceRecord]],
) -> list[EvidenceRecord]:
    evidence_records: list[EvidenceRecord] = []
    seen: set[str] = set()
    for source_id in claim.source_ids:
        candidates = evidence_by_source.get((source_id, competitor_id)) or evidence_by_source.get(
            (source_id, "*"),
            [],
        )
        for evidence in candidates:
            if evidence.id not in seen:
                seen.add(evidence.id)
                evidence_records.append(evidence)
    return evidence_records


def _release_claim_evidence_ids(evidence: list[EvidenceRecord]) -> list[str]:
    return [item.id for item in evidence if _is_release_claim_evidence(item)]


def _is_release_claim_evidence(evidence: EvidenceRecord) -> bool:
    if (
        evidence.source_type == "webpage_verified"
        and evidence.reliability_score >= _MIN_RELEASE_CLAIM_SOURCE_CONFIDENCE
        and evidence.quality_label not in {"rejected", "stale"}
    ):
        return True
    return (
        evidence.source_type
        in {"survey_response", "interview_record", "manual_transcript", "manual_note", "manual"}
        and bool(evidence.metadata.get("imported_user_research"))
        and evidence.reliability_score >= _MIN_RELEASE_CLAIM_SOURCE_CONFIDENCE
        and evidence.quality_label not in {"rejected", "stale"}
    )


def _release_claim_records(claim_records: list[ClaimRecord]) -> list[ClaimRecord]:
    return [claim for claim in claim_records if claim.status not in {"deprecated", "rejected"}]


def _release_claim_admission_metadata(
    claim_records: list[ClaimRecord],
    release_claim_records: list[ClaimRecord],
    evidence_records: list[EvidenceRecord],
) -> dict[str, object]:
    release_claim_ids = {claim.id for claim in release_claim_records}
    evidence_by_id = {item.id: item for item in evidence_records}
    excluded = [
        {
            "claim_id": claim.id,
            "competitor_id": claim.competitor_id,
            "dimension": claim.claim_type,
            "status": claim.status,
            "evidence_ids": claim.evidence_ids,
            "source_types": sorted(
                {
                    evidence.source_type
                    for evidence_id in claim.evidence_ids
                    if (evidence := evidence_by_id.get(evidence_id)) is not None
                }
            ),
            "reason": "release_claim_requires_verified_webpage_evidence",
        }
        for claim in claim_records
        if claim.id not in release_claim_ids
    ]
    return {
        "admitted_claim_count": len(release_claim_records),
        "excluded_claim_count": len(excluded),
        "excluded_claims": excluded,
    }


def _report_competitor_homepage_metadata(
    detail: RunDetail,
    competitor_ids: list[str],
) -> list[dict[str, object]]:
    return [
        {
            "competitor_id": competitor_id,
            "competitor_name": name,
            "homepage_url": detail.plan.homepage_hints.get(name),
            "homepage_verified": detail.plan.homepage_verified.get(name, False),
        }
        for name, competitor_id in zip(detail.plan.competitors, competitor_ids, strict=False)
    ]


def _claims_for_dimension(
    knowledge: CompetitorKnowledge | None,
    dimension: str,
) -> list[KnowledgeClaim]:
    if knowledge is None:
        return []
    dimension_key = dimension.casefold()
    if "pricing" in dimension_key:
        return [
            *knowledge.pricing_model.notes,
            *[claim for tier in knowledge.pricing_model.tiers for claim in tier.claims],
        ]
    if "persona" in dimension_key or "user" in dimension_key:
        return [
            *knowledge.user_personas.summary_claims,
            *[claim for segment in knowledge.user_personas.segments for claim in segment.claims],
        ]
    return [
        *knowledge.feature_tree.summary_claims,
        *[claim for node in knowledge.feature_tree.nodes for claim in node.claims],
    ]


def _source_competitors(source: RawSource) -> list[str]:
    competitors = source.covered_competitors or [source.competitor]
    seen: set[str] = set()
    normalized: list[str] = []
    for competitor in competitors:
        key = _record_id(competitor)
        if key and key not in seen:
            seen.add(key)
            normalized.append(competitor)
    return normalized


def _record_id(value: str) -> str:
    return normalize_competitor_key(value)


def _competitor_id_for(
    value: str,
    competitor_id_map: Mapping[str, str] | None,
) -> str:
    if competitor_id_map is None:
        return _record_id(value)
    key = normalize_competitor_key(value)
    return competitor_id_map.get(value) or competitor_id_map.get(key) or _record_id(value)


def _quality_label(source: RawSource) -> str:
    if source.source_type == "webpage_verified":
        return "accepted"
    return "unreviewed"


def _source_metadata(source: RawSource) -> dict[str, object]:
    return raw_source_alias_metadata(
        source.id,
        {
            **source.metadata,
            "source_competitor": source.competitor,
            "candidate_origin": source.candidate_origin,
            "candidate_rank": source.candidate_rank,
            "candidate_confidence": source.candidate_confidence,
            "fetch_method": source.fetch_method,
            "quality_score": source.quality_score,
            "failure_reason": source.failure_reason,
        },
    )


def _build_quality_metadata(
    detail: RunDetail,
    evidence_records: list[EvidenceRecord],
    *,
    source_reconciliation: dict[str, object],
) -> dict[str, object]:
    run_quality_findings = _run_quality_findings(detail)
    low_confidence_source_ids = [
        source.id for source in detail.raw_sources if source.confidence < 0.75
    ]
    search_only_source_ids = [
        source.id for source in detail.raw_sources if source.source_type == "web_search_result"
    ]
    llm_public_knowledge_source_ids = [
        source.id for source in detail.raw_sources if source.source_type == "llm_public_knowledge"
    ]
    research_source_ids = _classify_user_research_sources(detail.raw_sources)
    return {
        "run_id": detail.id,
        "schema_pass_rate": detail.metrics.schema_pass_rate,
        "memory_used": {
            "candidate_ids": detail.plan.memory_candidate_ids,
            "prompt_context": detail.plan.memory_prompt_context,
            "recall_score": detail.plan.memory_recall_score,
        },
        "memory_observations": _build_memory_observations(
            detail,
            low_confidence_source_ids=low_confidence_source_ids,
            search_only_source_ids=search_only_source_ids,
            llm_public_knowledge_source_ids=llm_public_knowledge_source_ids,
            survey_source_ids=research_source_ids["survey_source_ids"],
            interview_source_ids=research_source_ids["interview_source_ids"],
            manual_research_source_ids=research_source_ids["manual_research_source_ids"],
            user_research_source_ids=research_source_ids["user_research_source_ids"],
        ),
        "run_qa_findings": [
            {
                "id": issue.id,
                "severity": issue.severity,
                "detected_by": issue.detected_by,
                "target_agent": issue.target_agent,
                "target_subagent": issue.target_subagent,
                "target_competitor": issue.target_competitor,
                "field_path": issue.field_path,
                "problem": issue.problem,
                "redo_scope": issue.redo_scope.model_dump(mode="json"),
            }
            for issue in run_quality_findings
        ],
        "run_qa_warning_count": sum(
            1 for issue in run_quality_findings if issue.severity == "warn"
        ),
        "run_qa_blocker_count": sum(
            1 for issue in run_quality_findings if issue.severity == "blocker"
        ),
        "low_confidence_source_ids": low_confidence_source_ids,
        "search_only_source_ids": search_only_source_ids,
        "llm_public_knowledge_source_ids": llm_public_knowledge_source_ids,
        **research_source_ids,
        "source_reconciliation": source_reconciliation,
        "reflection_gaps": [
            {
                "coverage_gaps": reflection.coverage_gaps,
                "confidence_outliers": reflection.confidence_outliers,
                "cross_competitor_gaps": reflection.cross_competitor_gaps,
            }
            for reflection in detail.reflections[-1:]
        ],
    }


def _build_memory_observations(
    detail: RunDetail,
    *,
    low_confidence_source_ids: list[str],
    search_only_source_ids: list[str],
    llm_public_knowledge_source_ids: list[str],
    survey_source_ids: list[str],
    interview_source_ids: list[str],
    manual_research_source_ids: list[str],
    user_research_source_ids: list[str],
) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = [
        {
            "id": f"{detail.id}:plan",
            "kind": "analysis_plan",
            "topic": detail.topic,
            "competitor_layer": detail.plan.competitor_layer,
            "scenario_id": detail.plan.scenario_id,
            "dimensions": detail.plan.dimensions,
            "competitors": detail.plan.competitors,
            "qa_rule_ids": detail.plan.qa_rule_ids,
        }
    ]
    if low_confidence_source_ids or search_only_source_ids or llm_public_knowledge_source_ids:
        observations.append(
            {
                "id": f"{detail.id}:source-risk",
                "kind": "source_risk",
                "low_confidence_source_ids": low_confidence_source_ids,
                "search_only_source_ids": search_only_source_ids,
                "llm_public_knowledge_source_ids": llm_public_knowledge_source_ids,
            }
        )
    if user_research_source_ids:
        observations.append(
            {
                "id": f"{detail.id}:customer-signal",
                "kind": "customer_signal",
                "survey_source_ids": survey_source_ids,
                "interview_source_ids": interview_source_ids,
                "manual_research_source_ids": manual_research_source_ids,
                "user_research_source_ids": user_research_source_ids,
            }
        )
    run_quality_findings = _run_quality_findings(detail)
    if run_quality_findings:
        observations.append(
            {
                "id": f"{detail.id}:qa-findings",
                "kind": "quality_pattern",
                "warn_count": sum(
                    1 for issue in run_quality_findings if issue.severity == "warn"
                ),
                "blocker_count": sum(
                    1 for issue in run_quality_findings if issue.severity == "blocker"
                ),
                "target_agents": sorted(
                    {issue.target_agent for issue in run_quality_findings if issue.target_agent}
                ),
                "problems": [issue.problem for issue in run_quality_findings[:10]],
            }
        )
    if detail.reflections:
        latest = detail.reflections[-1]
        observations.append(
            {
                "id": f"{detail.id}:reflection",
                "kind": "reflection",
                "coverage_gaps": latest.coverage_gaps,
                "confidence_outliers": latest.confidence_outliers,
                "cross_competitor_gaps": latest.cross_competitor_gaps,
            }
        )
    return observations


def _classify_user_research_sources(raw_sources: list[RawSource]) -> dict[str, list[str]]:
    survey_source_ids = [
        source.id for source in raw_sources if source.source_type.casefold() in _SURVEY_SOURCE_TYPES
    ]
    interview_source_ids = [
        source.id
        for source in raw_sources
        if source.source_type.casefold() in _INTERVIEW_SOURCE_TYPES
    ]
    manual_research_source_ids = [
        source.id
        for source in raw_sources
        if source.source_type.casefold() in _MANUAL_RESEARCH_SOURCE_TYPES
    ]
    return {
        "survey_source_ids": survey_source_ids,
        "interview_source_ids": interview_source_ids,
        "manual_research_source_ids": manual_research_source_ids,
        "user_research_source_ids": [
            source.id
            for source in raw_sources
            if source.source_type.casefold() in _USER_RESEARCH_SOURCE_TYPES
        ],
    }


def _run_quality_findings(detail: RunDetail) -> list[QCIssue]:
    return [
        issue
        for issue in detail.qa_findings
        if not issue.field_path.startswith("release_gate.")
    ]


def _parse_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
