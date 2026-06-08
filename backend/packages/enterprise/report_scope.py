from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from packages.enterprise.store import EnterpriseStore
from packages.schema.enterprise import (
    ClaimRecord,
    CompetitorRecord,
    EvidenceRecord,
    ProjectRecord,
    ReportVersionRecord,
)

RecordWithIdT = TypeVar("RecordWithIdT", bound=CompetitorRecord | EvidenceRecord | ClaimRecord)


@dataclass(frozen=True)
class ReportScope:
    """Frozen publication scope for one report version.

    The enterprise project can hold history, memory, and stale competitors. This
    object describes the exact records used for release decisions and keeps
    historical context advisory unless it is explicitly linked to the report
    version.
    """

    competitors: list[CompetitorRecord]
    evidence: list[EvidenceRecord]
    claims: list[ClaimRecord]
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_release_gate_tuple(
        self,
    ) -> tuple[list[CompetitorRecord], list[EvidenceRecord], list[ClaimRecord]]:
        return self.competitors, self.evidence, self.claims


def report_release_gate_scope(
    version: ReportVersionRecord,
    *,
    project: ProjectRecord,
    store: EnterpriseStore,
) -> tuple[list[CompetitorRecord], list[EvidenceRecord], list[ClaimRecord]]:
    """Return the exact records that a report version is allowed to publish.

    Project stores can contain long-lived memory and previous run artifacts. Release
    decisions must instead evaluate the frozen report version: the competitors,
    evidence, and claims that the report actually cites.
    """

    return build_report_scope(version, project=project, store=store).as_release_gate_tuple()


def build_report_scope(
    version: ReportVersionRecord,
    *,
    project: ProjectRecord,
    store: EnterpriseStore,
) -> ReportScope:
    projection = store.get_run_projection(version.run_id) if version.run_id else None
    scope_source = "report_version_ids"
    if projection is not None and projection.report_version.id == version.id:
        evidence = projection.evidence_records
        claims = projection.claim_records
        scope_source = "run_projection"
    else:
        evidence = _records_in_id_order(
            store.list_evidence(project_id=project.id),
            version.evidence_ids,
        )
        claims = _records_in_id_order(
            store.list_claims(project_id=project.id),
            version.claim_ids,
        )
    competitors = report_scope_competitors(
        version,
        project=project,
        store=store,
        evidence=evidence,
        claims=claims,
    )
    return ReportScope(
        competitors=competitors,
        evidence=evidence,
        claims=claims,
        metadata=_report_scope_metadata(
            version,
            project=project,
            store=store,
            competitors=competitors,
            evidence=evidence,
            claims=claims,
            scope_source=scope_source,
        ),
    )


def report_scope_metadata(
    version: ReportVersionRecord,
    *,
    project: ProjectRecord,
    store: EnterpriseStore,
) -> dict[str, Any]:
    return build_report_scope(version, project=project, store=store).metadata


def report_scope_competitors(
    version: ReportVersionRecord,
    *,
    project: ProjectRecord,
    store: EnterpriseStore,
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> list[CompetitorRecord]:
    scoped_ids = report_scope_competitor_ids(version, evidence=evidence, claims=claims)
    project_competitors = store.list_competitors(project_id=project.id)
    if not scoped_ids:
        return project_competitors
    competitors_by_id = {item.id: item for item in project_competitors}
    if any(item not in competitors_by_id for item in scoped_ids):
        workspace_competitors = store.list_competitors(workspace_id=project.workspace_id)
        competitors_by_id.update({item.id: item for item in workspace_competitors})
    return [competitors_by_id[item] for item in scoped_ids if item in competitors_by_id]


def report_scope_competitor_ids(
    version: ReportVersionRecord,
    *,
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> list[str]:
    metadata_ids = version.quality_metadata.get("report_competitor_ids")
    if isinstance(metadata_ids, list):
        ids = [str(item).strip() for item in metadata_ids if str(item).strip()]
        if ids:
            return _dedupe_ordered_strings(ids)
    return _dedupe_ordered_strings(
        [
            *[item.competitor_id for item in evidence],
            *[item.competitor_id for item in claims],
        ]
    )


def _records_in_id_order(
    records: Iterable[RecordWithIdT],
    ids: Iterable[str],
) -> list[RecordWithIdT]:
    records_by_id = {item.id: item for item in records}
    return [records_by_id[item] for item in ids if item in records_by_id]


def _dedupe_ordered_strings(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _report_scope_metadata(
    version: ReportVersionRecord,
    *,
    project: ProjectRecord,
    store: EnterpriseStore,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
    scope_source: str,
) -> dict[str, Any]:
    project_competitors = store.list_competitors(project_id=project.id)
    project_evidence = store.list_evidence(project_id=project.id)
    project_claims = store.list_claims(project_id=project.id)
    scoped_competitor_ids = [item.id for item in competitors]
    memory_used = version.quality_metadata.get("memory_used")
    return {
        "scope_policy": "report_version_scope_only",
        "history_policy": "project_history_and_memory_are_advisory_context",
        "scope_source": scope_source,
        "report_version_id": version.id,
        "run_id": version.run_id,
        "project_id": project.id,
        "scoped_competitor_ids": scoped_competitor_ids,
        "scoped_evidence_ids": [item.id for item in evidence],
        "scoped_claim_ids": [item.id for item in claims],
        "project_competitor_count": len(project_competitors),
        "project_evidence_count": len(project_evidence),
        "project_claim_count": len(project_claims),
        "excluded_project_competitor_ids": [
            item.id for item in project_competitors if item.id not in scoped_competitor_ids
        ],
        "advisory_memory": memory_used if isinstance(memory_used, dict) else {},
    }
