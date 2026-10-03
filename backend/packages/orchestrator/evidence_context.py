"""Canonical scope resolution and per-call immutable evidence credentials."""

from __future__ import annotations

import hashlib
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
    _verify,
    current_snapshot,
)
from packages.research.evidence.snapshot_models import (
    EvidenceArtifactDependency,
    EvidenceConsumption,
    EvidencePhase,
    RunEvidenceSnapshot,
    StageEvidenceView,
    canonical_json,
)
from packages.research.evidence.views import select_evidence_view

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord

_DEPTH_BYTES = {"quick": 8192, "standard": 16384, "deep": 24576}


class EvidenceUseRejectedError(ValueError):
    """A fixed producer credential cannot commit against the current dependencies."""


class EvidenceContextMixin:
    @staticmethod
    def _evidence_live_record(record: RunRecord) -> RunRecord:
        return record.evidence_origin or record

    async def _ensure_analysis_evidence(self, record: RunRecord) -> RunEvidenceSnapshot:
        record = self._evidence_live_record(record)
        snapshot = current_snapshot(record.detail)
        if snapshot is None:
            # Compatibility for explicit direct downstream calls. A known collect/HITL
            # entry must reach Graph's acceptance boundary rather than seal itself.
            if (
                record.detail.current_node
                in {
                    "planner_hitl",
                    "collector",
                    "collector_dispatch",
                    "collect_join",
                    "collect_qa",
                    "evidence_hitl",
                }
                or record.detail.evidence_refresh_active
                or (record.detail.current_node == "planner" and record.graph_execution_depth > 0)
            ):
                raise EvidenceUseRejectedError("analysis requires accepted evidence")
            snapshot = await self._prepare_evidence_snapshot(record, phase="analysis")
        snapshot = self._current_evidence_snapshot(record)
        if snapshot.phase != "analysis":
            raise EvidenceUseRejectedError("analysis requires accepted evidence")
        return snapshot

    @staticmethod
    def _evidence_artifact_hash(payload: object) -> str:
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def _record_evidence_artifact(
        self,
        record: RunRecord,
        *,
        kind: str,
        payload: object,
        uses: Iterable[EvidenceConsumption],
        competitor: str | None = None,
        dimension: str | None = None,
    ) -> None:
        record = self._evidence_live_record(record)
        dependency = EvidenceArtifactDependency(
            kind=kind,
            competitor=competitor,
            dimension=dimension,
            consumption_ids=tuple(use.id for use in uses),
            payload_hash=self._evidence_artifact_hash(payload),
        )
        record.detail.evidence_artifact_dependencies = [
            item
            for item in record.detail.evidence_artifact_dependencies
            if (item.kind, item.competitor, item.dimension) != (kind, competitor, dimension)
        ] + [dependency]
        self._persist_run(record.detail.id)

    def _evidence_artifact_valid(
        self,
        record: RunRecord,
        *,
        kind: str,
        payload: object,
        competitor: str | None = None,
        dimension: str | None = None,
        view_source_ids=None,
        view_fact_ids=None,
    ) -> bool:
        record = self._evidence_live_record(record)
        dependency = next(
            (
                item
                for item in record.detail.evidence_artifact_dependencies
                if (item.kind, item.competitor, item.dimension) == (kind, competitor, dimension)
            ),
            None,
        )
        if dependency is None or dependency.payload_hash != self._evidence_artifact_hash(payload):
            return False
        for use_id in dependency.consumption_ids:
            use = next(
                (item for item in record.detail.evidence_consumptions if item.id == use_id), None
            )
            if use is None or use.status not in {"validated", "reused"}:
                return False
            if view_source_ids is not None and not set(use.source_ids) <= view_source_ids:
                return False
            if view_fact_ids is not None and not set(use.fact_ids) <= view_fact_ids:
                return False
            try:
                self._validate_evidence_use(record, use)
            except EvidenceUseRejectedError:
                return False
        return bool(dependency.consumption_ids)

    def _project_evidence_detail(self, record: RunRecord, views, *, verify_analysis=True):
        """A private read projection; never replace the live RawSource collection."""
        record = self._evidence_live_record(record)
        detail = record.detail.model_copy(deep=True)
        detail.evidence_snapshots = []
        detail.evidence_snapshot_id = None
        selected = {source.id: source.to_raw_source() for view in views for source in view.sources}
        detail.raw_sources = list(selected.values())
        selected_fact_ids = {fact.id for view in views for fact in view.facts}
        selected_source_ids = set(selected)
        gaps = []
        if verify_analysis:
            for competitor in detail.plan.competitors:
                knowledge = detail.competitor_knowledge.get(competitor)
                kb = detail.competitor_kbs.get(competitor)
                for dimension in detail.plan.dimensions:
                    payload = self._analyst_evidence_artifact_payload(
                        record.detail, competitor, dimension
                    )
                    if self._evidence_artifact_valid(
                        record,
                        kind="analyst",
                        payload=payload,
                        competitor=competitor,
                        dimension=dimension,
                        view_source_ids=selected_source_ids,
                        view_fact_ids=selected_fact_ids,
                    ):
                        continue
                    gaps.append(
                        f"Analysis dependency unavailable: {competitor} / {dimension}; reanalyse."
                    )
                    if kb:
                        kb.slices.pop(dimension, None)
                    if knowledge:
                        key = (
                            "pricing_model"
                            if "pricing" in dimension.casefold()
                            else "user_personas"
                            if any(term in dimension.casefold() for term in ("persona", "user"))
                            else "feature_tree"
                        )
                        setattr(knowledge, key, type(getattr(knowledge, key))())
                        if self._dimension_uses_review_summary(dimension):
                            knowledge.review_summary = type(knowledge.review_summary)()
                    detail.claim_card_bundles = [
                        item
                        for item in detail.claim_card_bundles
                        if (item.competitor, item.dimension) != (competitor, dimension)
                    ]
            allowed = set(selected)
            for kb in detail.competitor_kbs.values():
                kb.sources = [source_id for source_id in kb.sources if source_id in allowed]
            for knowledge in detail.competitor_knowledge.values():
                knowledge.source_ids = [
                    source_id for source_id in knowledge.source_ids if source_id in allowed
                ]
            for competitor in detail.plan.competitors:
                knowledge = detail.competitor_knowledge.get(competitor)
                if knowledge:
                    for dimension in detail.plan.dimensions:
                        self._sanitize_structured_knowledge_slice_sources(
                            detail,
                            competitor,
                            dimension,
                            knowledge,
                            sanitize_review_summary=self._dimension_uses_review_summary(dimension),
                        )
            if not self._evidence_artifact_valid(
                record,
                kind="comparator",
                payload=self._comparator_evidence_artifact_payload(record.detail),
                view_source_ids=selected_source_ids,
                view_fact_ids=selected_fact_ids,
            ):
                detail.comparison_matrix = None
                detail.decision_card_bundle = None
                for knowledge in detail.competitor_knowledge.values():
                    knowledge.swot_analysis = type(knowledge.swot_analysis)()
        return detail, gaps

    @staticmethod
    def _bounded_analysis_json(view, payload):
        text = canonical_json(payload)
        if len(view.to_prompt_json().encode("utf-8")) + len(text.encode("utf-8")) <= view.max_bytes:
            return text
        return '{"analysis_gap":"analysis_context_budget_exceeded"}'

    def _analysis_artifacts_hash(self, detail):
        return self._evidence_artifact_hash(
            {
                "knowledge": {
                    key: value.model_dump(mode="json")
                    for key, value in detail.competitor_knowledge.items()
                },
                "kbs": {
                    key: value.model_dump(mode="json")
                    for key, value in detail.competitor_kbs.items()
                },
                "cards": [item.model_dump(mode="json") for item in detail.claim_card_bundles],
                "comparison": self._comparator_evidence_artifact_payload(detail),
                "reflections": [item.model_dump(mode="json") for item in detail.reflections],
            }
        )

    @staticmethod
    def _writer_evidence_artifact_payload(detail):
        return {
            "report_md": detail.report_md,
            "artifact": detail.report_artifact.model_dump(mode="json")
            if detail.report_artifact
            else None,
        }

    def _final_qa_producer_verified(self, record, snapshot):
        dependency = next(
            (
                item
                for item in record.detail.evidence_artifact_dependencies
                if item.kind == "writer"
            ),
            None,
        )
        # Direct legacy citation audits have no Writer commit. Explicit preservation
        # without a proven producer is persisted as an empty consumption list.
        if dependency is None:
            return True
        if (
            not dependency.consumption_ids
            or dependency.payload_hash
            != self._evidence_artifact_hash(self._writer_evidence_artifact_payload(record.detail))
        ):
            return False
        for use_id in dependency.consumption_ids:
            use = next(
                (item for item in record.detail.evidence_consumptions if item.id == use_id), None
            )
            if use is None or use.status not in {"validated", "reused"}:
                return False
            view = select_evidence_view(
                snapshot,
                agent="writer",
                competitor=use.competitor,
                dimension=use.dimension,
                source_ids=use.requested_source_ids,
                max_bytes=use.view_max_bytes or use.max_bytes,
            )
            if (
                view.dependency_hash != use.dependency_hash
                or view.source_ids != use.source_ids
                or view.fact_ids != use.fact_ids
                or use.snapshot_id != snapshot.id
                or use.snapshot_version != snapshot.version
            ):
                return False
        return True

    def _final_qa_snapshot(self, record):
        record = self._evidence_live_record(record)
        dependency = next(
            (
                item
                for item in record.detail.evidence_artifact_dependencies
                if item.kind == "writer"
            ),
            None,
        )
        historical = None
        if dependency is not None:
            for use_id in dependency.consumption_ids:
                producer = next(
                    (item for item in record.detail.evidence_consumptions if item.id == use_id),
                    None,
                )
                if producer is None:
                    continue
                snapshot = next(
                    (
                        item
                        for item in record.detail.evidence_snapshots
                        if item.id == producer.snapshot_id
                    ),
                    None,
                )
                if snapshot is None:
                    continue
                identity = (record.detail.id, record.detail.workspace_id, record.detail.project_id)
                if (
                    (snapshot.run_id, snapshot.workspace_id, snapshot.project_id) != identity
                    or (producer.run_id, producer.workspace_id, producer.project_id) != identity
                    or producer.agent != "writer"
                ):
                    raise EvidenceUseRejectedError(
                        "historical Writer evidence identity/scope mismatch"
                    )
                if snapshot.phase != "analysis":
                    raise EvidenceUseRejectedError(
                        "historical Writer evidence phase must be analysis"
                    )
                try:
                    _verify(snapshot)
                except ValueError as error:
                    raise EvidenceUseRejectedError(
                        "historical Writer snapshot hash invalid"
                    ) from error
                if historical is not None and historical.id != snapshot.id:
                    raise EvidenceUseRejectedError("historical Writer producer snapshot mismatch")
                historical = snapshot
        if historical is not None:
            return historical
        return self._current_evidence_snapshot(record)

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
        record = self._evidence_live_record(record)
        snapshot = self._current_evidence_snapshot(record)
        if agent == "qa":
            snapshot = self._final_qa_snapshot(record)
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
        record = self._evidence_live_record(record)
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
                use.agent in {"analyst", "analyst_qa", "comparator", "reflector", "writer", "qa"}
                and snapshot.phase != "analysis"
            ):
                raise EvidenceUseRejectedError("analysis evidence is not currently accepted")
            if use.view_max_bytes is not None and not 0 < use.view_max_bytes <= use.max_bytes:
                raise EvidenceUseRejectedError("evidence view budget exceeds stage budget")
            validated_snapshot = self._final_qa_snapshot(record) if use.agent == "qa" else snapshot
            current = select_evidence_view(
                validated_snapshot,
                agent=use.agent,
                competitor=use.competitor,
                dimension=use.dimension,
                source_ids=use.requested_source_ids,
                max_bytes=use.view_max_bytes or use.max_bytes,
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
            update={
                "status": "reused" if stored.status == "reused" else "validated",
                "validated_snapshot_id": validated_snapshot.id,
            }
        )
        record.detail.evidence_consumptions = [
            updated if item.id == use.id else item for item in record.detail.evidence_consumptions
        ]
        self._persist_run(record.detail.id)
