"""Canonical scope resolution and per-call immutable evidence credentials."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from packages.knowledge.models import KnowledgeScope
from packages.knowledge.repository import KnowledgeRepository
from packages.research.evidence.snapshot import (
    _chunk_references,
    _document_problem,
    _document_reference,
    _gap,
    _seal_snapshot,
    current_snapshot,
)
from packages.research.evidence.snapshot_models import (
    EvidenceConsumption,
    EvidencePhase,
    RunEvidenceSnapshot,
    StageEvidenceView,
)
from packages.research.evidence.views import select_evidence_view

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord

_DEPTH_BYTES = {"quick": 8192, "standard": 16384, "deep": 24576}


class EvidenceUseRejectedError(ValueError):
    """A fixed producer credential cannot commit against the current dependencies."""


class EvidenceContextMixin:
    async def _prepare_evidence_snapshot(
        self, record: RunRecord, *, phase: EvidencePhase
    ) -> RunEvidenceSnapshot:
        detail = record.detail
        scope = KnowledgeScope(
            workspace_id=detail.workspace_id,
            project_id=detail.project_id,
            include_workspace_library=True,
        )
        references = []
        documents, rejected, chunks = {}, {}, {}
        for source in detail.raw_sources:
            document_id, reference_problem = _document_reference(source)
            if reference_problem:
                rejected[source.id] = _gap(source, reference_problem, document_id)
            elif document_id:
                references.append((source, document_id))
        if references:
            async with KnowledgeRepository() as repo:
                for source, document_id in references:
                    document = documents.get(document_id)
                    if document is None:
                        document = await repo.get_document(document_id, scope=scope)
                    if document is None:
                        rejected[source.id] = _gap(
                            source, "canonical_document_unavailable", document_id
                        )
                        continue
                    documents[document_id] = document
                    reason = _document_problem(source, document, scope)
                    if reason:
                        rejected[source.id] = _gap(source, reason, document_id)
                        continue
                    reference_ids, reason = _chunk_references(source)
                    if reason:
                        rejected[source.id] = _gap(source, reason, document_id)
                        continue
                    if reference_ids:
                        if document_id not in chunks:
                            chunks[document_id] = await repo.get_chunks_for_document(document_id)
                        known = {chunk.id: chunk for chunk in chunks[document_id]}
                        for chunk_id in reference_ids:
                            chunk = known.get(chunk_id)
                            reason = (
                                "chunk_reference_unavailable"
                                if chunk is None
                                else "chunk_identity_mismatch"
                                if chunk.document_id != document_id
                                else None
                            )
                            if reason:
                                rejected[source.id] = _gap(source, reason, document_id)
                                break
        snapshot = _seal_snapshot(
            detail, phase=phase, canonical_documents=documents, rejected_sources=rejected
        )
        self._persist_run(detail.id)
        return snapshot

    @staticmethod
    def _current_evidence_snapshot(record: RunRecord) -> RunEvidenceSnapshot:
        snapshot = current_snapshot(record.detail)
        if snapshot is None:
            raise ValueError("an explicit evidence snapshot is required before consumption")
        if (
            snapshot.workspace_id != record.detail.workspace_id
            or snapshot.project_id != record.detail.project_id
        ):
            raise EvidenceUseRejectedError("evidence snapshot scope mismatch")
        return snapshot

    def _begin_evidence_use(
        self,
        record: RunRecord,
        *,
        agent: str,
        competitor: str | None = None,
        dimension: str | None = None,
        source_ids: Iterable[str] | None = None,
    ) -> tuple[StageEvidenceView, EvidenceConsumption]:
        snapshot = self._current_evidence_snapshot(record)
        budget = _DEPTH_BYTES.get(record.detail.plan.research_depth, 8192)
        requested_ids = tuple(sorted(set(source_ids))) if source_ids is not None else None
        view = select_evidence_view(
            snapshot,
            agent=agent,
            competitor=competitor,
            dimension=dimension,
            source_ids=requested_ids,
            max_bytes=budget,
        )
        use = EvidenceConsumption(
            id=f"evidence-use-{uuid4().hex}",
            run_id=record.detail.id,
            workspace_id=record.detail.workspace_id,
            project_id=record.detail.project_id,
            agent=agent,
            snapshot_id=snapshot.id,
            snapshot_version=snapshot.version,
            dependency_hash=view.dependency_hash,
            competitor=competitor,
            dimension=dimension,
            source_ids=view.source_ids,
            requested_source_ids=requested_ids,
            fact_ids=view.fact_ids,
            max_bytes=budget,
            estimated_bytes=view.estimated_bytes,
            estimated_tokens=view.estimated_tokens,
            created_at=datetime.now(UTC),
        )
        record.detail.evidence_consumptions = [*record.detail.evidence_consumptions, use]
        self._persist_run(record.detail.id)
        return view, use

    def _validate_evidence_use(self, record: RunRecord, use: EvidenceConsumption) -> None:
        stored = next(
            (item for item in record.detail.evidence_consumptions if item.id == use.id), None
        )
        if stored is None or stored.model_dump(
            exclude={"status", "validated_snapshot_id"}
        ) != use.model_dump(exclude={"status", "validated_snapshot_id"}):
            raise EvidenceUseRejectedError("unknown or changed evidence credential")
        try:
            if (
                use.run_id != record.detail.id
                or use.workspace_id != record.detail.workspace_id
                or use.project_id != record.detail.project_id
            ):
                raise EvidenceUseRejectedError("evidence credential scope mismatch")
            if stored.status == "rejected":
                raise EvidenceUseRejectedError("evidence credential was already rejected")
            snapshot = self._current_evidence_snapshot(record)
            if (
                use.agent in {"analyst", "comparator", "reflector", "writer"}
                and snapshot.phase != "analysis"
            ):
                raise EvidenceUseRejectedError("analysis evidence is not currently accepted")
            current = select_evidence_view(
                snapshot,
                agent=use.agent,
                competitor=use.competitor,
                dimension=use.dimension,
                source_ids=use.requested_source_ids,
                max_bytes=use.max_bytes,
            )
            if current.dependency_hash != use.dependency_hash:
                raise EvidenceUseRejectedError("evidence dependencies changed or became invalid")
        except ValueError as error:
            updated = stored.model_copy(update={"status": "rejected"})
            record.detail.evidence_consumptions = [
                updated if item.id == use.id else item
                for item in record.detail.evidence_consumptions
            ]
            self._persist_run(record.detail.id)
            raise EvidenceUseRejectedError(f"evidence credential rejected: {error}") from error
        updated = stored.model_copy(
            update={"status": "validated", "validated_snapshot_id": snapshot.id}
        )
        record.detail.evidence_consumptions = [
            updated if item.id == use.id else item for item in record.detail.evidence_consumptions
        ]
        self._persist_run(record.detail.id)
