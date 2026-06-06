from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

from packages.enterprise.store import EnterpriseStore
from packages.schema.enterprise import (
    ClaimRecord,
    CompetitorRecord,
    EvidenceRecord,
    ProjectRecord,
    ReportVersionRecord,
)

RecordWithIdT = TypeVar("RecordWithIdT", bound=CompetitorRecord | EvidenceRecord | ClaimRecord)


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

    projection = store.get_run_projection(version.run_id) if version.run_id else None
    if projection is not None and projection.report_version.id == version.id:
        evidence = projection.evidence_records
        claims = projection.claim_records
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
    return competitors, evidence, claims


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
