from __future__ import annotations

from collections import Counter
from datetime import datetime

from packages.compliance import CompliancePolicy, redact_text
from packages.identity import (
    compute_content_hash,
    compute_raw_source_id,
    compute_survey_respondent_id,
    stable_prefixed_id,
)
from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource
from packages.schema.survey import (
    ImportedUserResearchMaterial,
    InterviewSynthesis,
    SurveyEvidenceBundle,
    SurveyResponse,
    UserResearchImportRequest,
    UserResearchImportResult,
    UserResearchMaterial,
)


def build_user_research_import(
    detail: RunDetail,
    request: UserResearchImportRequest,
    *,
    policy: CompliancePolicy,
) -> tuple[list[RawSource], list[SurveyEvidenceBundle], UserResearchImportResult]:
    sources: list[RawSource] = []
    bundles: list[SurveyEvidenceBundle] = []
    material_results: list[ImportedUserResearchMaterial] = []
    total_redactions: Counter[str] = Counter()

    for index, material in enumerate(request.materials, start=1):
        source, bundle, material_result = _build_material_import(
            detail,
            material,
            material_index=index,
            imported_by=request.imported_by,
            policy=policy,
        )
        sources.append(source)
        bundles.append(bundle)
        material_results.append(material_result)
        total_redactions.update(material_result.redaction_counts)

    result = UserResearchImportResult(
        run_id=detail.id,
        imported_count=len(sources),
        source_ids=[source.id for source in sources],
        materials=material_results,
        bundles=bundles,
        redaction_counts=dict(total_redactions),
    )
    return sources, bundles, result


def _build_material_import(
    detail: RunDetail,
    material: UserResearchMaterial,
    *,
    material_index: int,
    imported_by: str,
    policy: CompliancePolicy,
) -> tuple[RawSource, SurveyEvidenceBundle, ImportedUserResearchMaterial]:
    redaction_counts: Counter[str] = Counter()
    material_id = material.id or stable_prefixed_id(
        "user-research-material",
        detail.id,
        material.source_type,
        material.competitor,
        material.dimension,
        material_index,
        material.text,
        length=16,
    )
    competitor = _redact(material.competitor, policy, redaction_counts)
    dimension = _redact(material.dimension, policy, redaction_counts)
    respondent = _redact(material.respondent, policy, redaction_counts)
    role = _redact(material.role, policy, redaction_counts)
    body = _redact(material.text, policy, redaction_counts)
    default_title = f"{competitor} {dimension} {material.source_type.replace('_', ' ')}"
    title = _redact(material.title or default_title, policy, redaction_counts)
    source_url = str(material.source_url) if material.source_url is not None else None
    content_hash = compute_content_hash(body)
    evidence_summary = _research_evidence_summary(
        source_type=material.source_type,
        topic=detail.topic,
        competitor=competitor,
        dimension=dimension,
        body=body,
    )
    source = RawSource(
        id=compute_raw_source_id(
            source_type=material.source_type,
            competitor=competitor,
            dimension=dimension,
            url=source_url,
            content_hash=content_hash,
            title=title,
            snippet=evidence_summary,
            run_id=detail.id,
            source_role="user_research",
        ),
        competitor=competitor,
        covered_competitors=[competitor],
        dimension=dimension,
        source_type=material.source_type,
        title=title,
        url=source_url,
        snippet=evidence_summary,
        content_hash=content_hash,
        confidence=material.confidence,
        candidate_origin="user_research_import",
        candidate_confidence=material.confidence,
        fetch_method="manual_import",
        quality_score=material.confidence,
        metadata={
            **material.metadata,
            "material_id": material_id,
            "imported_by": imported_by,
            "imported_user_research": True,
            "respondent": respondent,
            "role": role,
            "source_type": material.source_type,
            "collected_at": material.collected_at.isoformat() if material.collected_at else None,
            "redaction_counts": dict(redaction_counts),
            "redaction_total": sum(redaction_counts.values()),
        },
        extracted_at=detail.updated_at or datetime.utcnow(),
    )
    response = SurveyResponse(
        respondent_id=compute_survey_respondent_id(
            detail.id,
            competitor,
            dimension,
            material_index,
        ),
        competitor=competitor,
        dimension=dimension,
        role=role,
        answers={"imported_material": body},
        quote=_quote_from_body(body),
        source_type=material.source_type,
    )
    bundle = SurveyEvidenceBundle(
        topic=_redact(detail.topic, policy, redaction_counts),
        competitor=competitor,
        dimension=dimension,
        responses=[response],
        interviews=_interviews_from_material(
            material=material,
            competitor=competitor,
            dimension=dimension,
            respondent=respondent,
            role=role,
            body=body,
            content_hash=content_hash,
        ),
        evidence_summary=evidence_summary,
        source_type=material.source_type,
        confidence=material.confidence,
        content_hash=content_hash[:16],
        redaction_counts=dict(redaction_counts),
    )
    source.metadata["redaction_counts"] = dict(redaction_counts)
    source.metadata["redaction_total"] = sum(redaction_counts.values())
    material_result = ImportedUserResearchMaterial(
        material_id=material_id,
        source_id=source.id,
        source_type=material.source_type,
        competitor=competitor,
        dimension=dimension,
        title=title,
        confidence=material.confidence,
        redaction_counts=dict(redaction_counts),
    )
    return source, bundle, material_result


def _redact(text: str, policy: CompliancePolicy, counts: Counter[str]) -> str:
    result = redact_text(text, policy=policy)
    counts.update(result.counts)
    return result.text


def _research_evidence_summary(
    *,
    source_type: str,
    topic: str,
    competitor: str,
    dimension: str,
    body: str,
) -> str:
    label = source_type.replace("_", " ")
    return (
        f"Imported {label} for {competitor} in {topic}: {dimension} evidence says "
        f"{_normalize_body(body)}"
    )


def _normalize_body(body: str) -> str:
    return " ".join(body.split())


def _quote_from_body(body: str) -> str:
    normalized = _normalize_body(body)
    if len(normalized) <= 360:
        return normalized
    return f"{normalized[:357].rstrip()}..."


def _interviews_from_material(
    *,
    material: UserResearchMaterial,
    competitor: str,
    dimension: str,
    respondent: str,
    role: str,
    body: str,
    content_hash: str,
) -> list[InterviewSynthesis]:
    if material.source_type not in {"interview_record", "manual_transcript", "manual_note"}:
        return []
    return [
        InterviewSynthesis(
            respondent=respondent,
            role=role,
            competitor=competitor,
            dimension=dimension,
            summary=_quote_from_body(body),
            pain_points=_extract_signal_phrases(
                body,
                fallback=["workflow fit uncertainty", "adoption friction"],
            ),
            use_cases=_extract_signal_phrases(
                body,
                fallback=[f"{dimension} evaluation", f"{competitor} adoption review"],
            ),
            content_hash=content_hash[:16],
        )
    ]


def _extract_signal_phrases(body: str, *, fallback: list[str]) -> list[str]:
    clauses = [
        clause.strip(" .;:-")
        for clause in body.replace("\n", ". ").split(".")
        if clause.strip()
    ]
    keywords = (
        "adoption",
        "workflow",
        "onboarding",
        "switch",
        "friction",
        "risk",
        "use case",
        "enterprise",
        "team",
        "developer",
        "customer",
    )
    matches = [
        clause[:96]
        for clause in clauses
        if any(keyword in clause.casefold() for keyword in keywords)
    ]
    deduped: list[str] = []
    for match in matches:
        if match and match not in deduped:
            deduped.append(match)
    return deduped[:4] or fallback
