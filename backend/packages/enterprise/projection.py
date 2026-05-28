from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime

from packages.identity import (
    compute_claim_id,
    compute_competitor_set_hash,
    compute_evidence_id,
    compute_topic_normalized,
    normalize_dimension_key,
    normalize_text,
    normalize_url,
)
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import (
    ClaimRecord,
    EnterpriseRunProjection,
    EvidenceRecord,
    ReportVersionRecord,
)
from packages.schema.models import CompetitorKnowledge, KnowledgeClaim, RawSource


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
            evidence_id = compute_evidence_id(
                normalize_url(str(source.url) if source.url is not None else ""),
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
                    snippet=source.snippet,
                    content_hash=source.content_hash,
                    reliability_score=source.confidence,
                    freshness_score=1.0,
                    quality_label=_quality_label(source),
                    captured_at=source.extracted_at,
                    metadata={"source_competitor": source.competitor},
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
                evidence_ids = _evidence_ids_for_claim(claim, competitor_id, evidence_by_source)
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
                        status="proposed",
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
    return ReportVersionRecord(
        id=f"report-{detail.id}-v{version_number}",
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=detail.id,
        version_number=version_number,
        topic_normalized=compute_topic_normalized(detail.topic),
        competitor_layer=competitor_layer,
        competitor_set_hash=competitor_set_hash,
        report_md=detail.report_md,
        claim_ids=[claim.id for claim in claim_records],
        evidence_ids=[evidence.id for evidence in evidence_records],
        created_at=_parse_datetime(detail.updated_at),
    )


def _index_evidence_by_source(
    evidence_records: list[EvidenceRecord],
) -> dict[tuple[str, str], list[EvidenceRecord]]:
    index: dict[tuple[str, str], list[EvidenceRecord]] = defaultdict(list)
    for record in evidence_records:
        index[(record.raw_source_id, record.competitor_id)].append(record)
        index[(record.raw_source_id, "*")].append(record)
    return index


def _evidence_ids_for_claim(
    claim: KnowledgeClaim,
    competitor_id: str,
    evidence_by_source: dict[tuple[str, str], list[EvidenceRecord]],
) -> list[str]:
    evidence_ids: list[str] = []
    seen: set[str] = set()
    for source_id in claim.source_ids:
        candidates = evidence_by_source.get((source_id, competitor_id)) or evidence_by_source.get(
            (source_id, "*"),
            [],
        )
        for evidence in candidates:
            if evidence.id not in seen:
                seen.add(evidence.id)
                evidence_ids.append(evidence.id)
    return evidence_ids


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
    normalized = normalize_text(value)
    return normalized.replace(" ", "_")


def _competitor_id_for(
    value: str,
    competitor_id_map: Mapping[str, str] | None,
) -> str:
    if competitor_id_map is None:
        return _record_id(value)
    return (
        competitor_id_map.get(value)
        or competitor_id_map.get(_record_id(value))
        or competitor_id_map.get(normalize_text(value))
        or _record_id(value)
    )


def _quality_label(source: RawSource) -> str:
    if source.source_type == "webpage_verified":
        return "accepted"
    return "unreviewed"


def _parse_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
