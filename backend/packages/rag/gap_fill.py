from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Protocol

from packages.rag.gap_retrieval import EvidenceRetriever, decorate_evidence_gap_report_with_retrieval
from packages.schema.enterprise import (
    EvidenceGapFillResult,
    EvidenceGapItem,
    EvidenceGapReport,
    ReportVersionRecord,
)


class GapFillStore(EvidenceRetriever, Protocol):
    def list_report_versions(self, project_id: str | None = None) -> list[ReportVersionRecord]: ...

    def upsert_report_version(self, version: ReportVersionRecord) -> ReportVersionRecord: ...


def fill_evidence_gaps(
    report: EvidenceGapReport,
    *,
    store: GapFillStore,
    workspace_id: str,
    project_id: str | None = None,
    source_report_version: ReportVersionRecord | None = None,
    limit: int = 3,
) -> EvidenceGapFillResult:
    project_id = project_id or report.project_id
    decorated = decorate_evidence_gap_report_with_retrieval(
        report,
        store=store,
        workspace_id=workspace_id,
        project_id=project_id,
        limit=limit,
    )
    updated_gaps, filled_gap_ids, candidate_ids = _filled_gaps(decorated.gaps)
    updated_report = decorated.model_copy(update={"gaps": updated_gaps})
    remaining_gap_ids = [gap.id for gap in updated_gaps if not gap.evidence_ids]
    updated_version = (
        _write_gap_fill_report_version(
            source=source_report_version,
            store=store,
            report=updated_report,
            candidate_ids=candidate_ids,
            filled_gap_ids=filled_gap_ids,
            remaining_gap_ids=remaining_gap_ids,
        )
        if source_report_version is not None
        else None
    )
    return EvidenceGapFillResult(
        project_id=project_id,
        workspace_id=workspace_id,
        source_report_version_id=source_report_version.id if source_report_version else None,
        updated_report_version_id=updated_version.id if updated_version else None,
        gap_count=len(updated_gaps),
        filled_gap_count=len(filled_gap_ids),
        added_evidence_count=len(candidate_ids),
        candidate_evidence_ids=candidate_ids,
        filled_gap_ids=filled_gap_ids,
        remaining_gap_ids=remaining_gap_ids,
        report=updated_report,
        updated_report_version=updated_version,
    )


def _filled_gaps(
    gaps: list[EvidenceGapItem],
) -> tuple[list[EvidenceGapItem], list[str], list[str]]:
    updated_gaps: list[EvidenceGapItem] = []
    filled_gap_ids: list[str] = []
    all_candidate_ids: list[str] = []
    for gap in gaps:
        candidate_ids = _unique_ids(
            [record.evidence_id for record in gap.retrieval_records]
            + list(gap.retrieval_candidate_ids)
        )
        new_candidate_ids = [item for item in candidate_ids if item not in gap.evidence_ids]
        if new_candidate_ids:
            filled_gap_ids.append(gap.id)
            all_candidate_ids.extend(new_candidate_ids)
        updated_gaps.append(
            gap.model_copy(update={"evidence_ids": _unique_ids(gap.evidence_ids + new_candidate_ids)})
        )
    return updated_gaps, _unique_ids(filled_gap_ids), _unique_ids(all_candidate_ids)


def _write_gap_fill_report_version(
    *,
    source: ReportVersionRecord,
    store: GapFillStore,
    report: EvidenceGapReport,
    candidate_ids: list[str],
    filled_gap_ids: list[str],
    remaining_gap_ids: list[str],
) -> ReportVersionRecord:
    metadata = dict(source.quality_metadata)
    metadata["rag_gap_fill"] = {
        "source_report_version_id": source.id,
        "filled_gap_ids": filled_gap_ids,
        "remaining_gap_ids": remaining_gap_ids,
        "candidate_evidence_ids": candidate_ids,
        "retrieval_records": [
            record.model_dump(mode="json")
            for gap in report.gaps
            for record in gap.retrieval_records
        ],
        "generated_at": datetime.utcnow().isoformat(),
    }
    version = source.model_copy(
        update={
            "id": _gap_fill_report_version_id(source, filled_gap_ids, candidate_ids),
            "parent_version_id": source.id,
            "version_number": _next_version_number(store, source.project_id),
            "status": "draft",
            "report_md": _append_gap_fill_section(
                source.report_md,
                report.gaps,
                filled_gap_ids=filled_gap_ids,
            ),
            "evidence_ids": _unique_ids(source.evidence_ids + candidate_ids),
            "quality_metadata": metadata,
            "created_at": datetime.utcnow(),
            "published_at": None,
        }
    )
    return store.upsert_report_version(version)


def _append_gap_fill_section(
    report_md: str,
    gaps: list[EvidenceGapItem],
    *,
    filled_gap_ids: list[str],
) -> str:
    lines = [report_md.rstrip(), "", "## RAG Gap Fill", ""]
    if not filled_gap_ids:
        lines.append("- No retrieval candidates were strong enough to fill open evidence gaps.")
        return "\n".join(lines).strip() + "\n"
    for gap in gaps:
        if gap.id not in filled_gap_ids:
            continue
        added = ", ".join(gap.evidence_ids)
        lines.append(f"- {gap.id}: linked evidence candidates {added}.")
        if gap.retrieval_grounded_context:
            lines.append(f"  - Grounded context: {gap.retrieval_grounded_context[:600]}")
    return "\n".join(lines).strip() + "\n"


def _gap_fill_report_version_id(
    source: ReportVersionRecord,
    filled_gap_ids: list[str],
    candidate_ids: list[str],
) -> str:
    digest = hashlib.sha256(
        "|".join([source.id, *filled_gap_ids, *candidate_ids]).encode("utf-8")
    ).hexdigest()[:16]
    return f"report-version-gap-fill-{digest}"


def _next_version_number(store: GapFillStore, project_id: str) -> int:
    versions = store.list_report_versions(project_id=project_id)
    if not versions:
        return 1
    return max(version.version_number for version in versions) + 1


def _unique_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
