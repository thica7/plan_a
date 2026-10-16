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
    changed_evidence,
    current_snapshot,
)
from packages.research.evidence.snapshot_models import (
    FACT_MARKET_POLICY_VERSION,
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
        if snapshot is not None:
            snapshot = self._current_evidence_snapshot(record, require_current_policy=False)
            if snapshot.phase != "analysis":
                raise EvidenceUseRejectedError("analysis requires accepted evidence")
        if snapshot is None or snapshot.fact_market_policy_version != FACT_MARKET_POLICY_VERSION:
            accepted_inputs = self._accepted_analysis_inputs_hash(record)
            snapshot = await self._prepare_evidence_snapshot(
                record, phase="analysis", accepted_inputs=accepted_inputs
            )
        snapshot = self._current_evidence_snapshot(record)
        if snapshot.phase != "analysis":
            raise EvidenceUseRejectedError("analysis requires accepted evidence")
        return snapshot

    def _accepted_analysis_inputs_hash(self, record: RunRecord) -> str:
        # Explicit direct downstream calls retain their compatibility path.
        # Collect/HITL inputs must reach Graph's acceptance boundary first.
        detail = record.detail
        if (
            detail.current_node in {
                "planner_hitl", "collector", "collector_dispatch", "collect_join",
                "survey_interview", "collect_qa", "evidence_hitl",
            }
            or detail.evidence_refresh_active
            or detail.evidence_inputs_dirty
            or (detail.current_node == "planner" and record.graph_execution_depth > 0)
        ):
            raise EvidenceUseRejectedError("analysis requires accepted evidence")
        if current_snapshot(detail) is not None:
            snapshot = self._current_evidence_snapshot(record, require_current_policy=False)
            if snapshot.phase != "analysis":
                raise EvidenceUseRejectedError("analysis requires accepted evidence")
            accepted_sources = {source.id: source for source in snapshot.sources}
            # Historical gaps do not retain an accepted body hash. Their IDs
            # cannot authorize replacement material during automatic migration.
            if any(
                source.id not in accepted_sources
                or source.content_hash != accepted_sources[source.id].content_hash
                for source in detail.raw_sources
            ):
                raise EvidenceUseRejectedError(
                    "original evidence inputs require accepted resealing"
                )
        return self._evidence_artifact_hash({
            "run_id": detail.id, "workspace_id": detail.workspace_id,
            "project_id": detail.project_id,
            "competitors": detail.plan.competitors, "dimensions": detail.plan.dimensions,
            "sources": [source.model_dump(mode="json") for source in detail.raw_sources],
            "retired_source_ids": detail.evidence_retired_source_ids,
        })

    @staticmethod
    def _evidence_artifact_hash(payload: object) -> str:
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def _artifact_upstream_hash(self, detail, kind):
        if kind == "writer":
            return self._analysis_artifacts_hash(detail)
        if kind in {"comparator", "reflector"}:
            return self._evidence_artifact_hash({
                "analysts": [self._analyst_evidence_artifact_payload(detail, product, dimension)
                             for product in detail.plan.competitors
                             for dimension in detail.plan.dimensions],
                "comparison": self._comparator_evidence_artifact_payload(detail)
                              if kind == "reflector" else None,
            })
        return None

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
            upstream_hash=self._artifact_upstream_hash(record.detail, kind),
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
        expected_upstream = self._artifact_upstream_hash(record.detail, kind)
        if expected_upstream is not None and dependency.upstream_hash != expected_upstream:
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
                    producer_valid = self._evidence_artifact_valid(
                        record, kind="analyst", payload=payload,
                        competitor=competitor, dimension=dimension,
                    )
                    gaps.append(
                        f"Analysis context omitted: {competitor} / {dimension}; select complete producer facts."
                        if producer_valid else
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

    def _producer_coverage_digest(self, record, view, *, max_bytes):
        """Current producer references prove coverage, never unsent fact content."""
        record = self._evidence_live_record(record)
        detail = record.detail
        uses = {use.id: use for use in detail.evidence_consumptions}
        dependencies = {(d.kind, d.competitor, d.dimension): d
                        for d in detail.evidence_artifact_dependencies}
        analysts, valid_scopes, scope_sources = [], set(), {}
        for product in detail.plan.competitors:
            for dimension in detail.plan.dimensions:
                payload = self._analyst_evidence_artifact_payload(detail, product, dimension)
                dependency = dependencies.get(("analyst", product, dimension))
                receipts = [uses.get(key) for key in dependency.consumption_ids] if dependency else []
                valid = bool(receipts) and all(use is not None
                    and (use.agent, use.competitor, use.dimension) == ("analyst", product, dimension)
                    for use in receipts) and self._evidence_artifact_valid(
                        record, kind="analyst", payload=payload, competitor=product, dimension=dimension)
                row = {"competitor": product, "dimension": dimension,
                       "status": "validated" if valid else "dependency_unavailable"}
                if valid:
                    fact_ids = {fid for key in dependency.consumption_ids for fid in uses[key].fact_ids}
                    row.update(producer_hash=dependency.payload_hash,
                               consumption_ids=list(dependency.consumption_ids),
                               fact_count=len(fact_ids),
                               omitted_fact_count=len(fact_ids - set(view.fact_ids)))
                    valid_scopes.add((product, dimension))
                    scope_sources[(product, dimension)] = {sid for key in dependency.consumption_ids
                                                          for sid in uses[key].source_ids}
                analysts.append(row)
        payload = self._comparator_evidence_artifact_payload(detail)
        valid_matrix = detail.comparison_matrix is not None and self._evidence_artifact_valid(
            record, kind="comparator", payload=payload)
        result = {"kind": "producer_coverage_only", "snapshot_id": view.snapshot_id,
                  "analysts": analysts, "cells": [],
                  "matrix_status": "validated" if valid_matrix else "dependency_unavailable"}
        if valid_matrix:
            result["producer_hash"] = dependencies[("comparator", None, None)].payload_hash
            source_ids = {source.id for source in self._current_evidence_snapshot(record).sources}
            result["cells"] = [
                {"competitor": cell.competitor, "dimension": cell.dimension,
                 "source_ids": cell.source_ids, "confidence": cell.confidence}
                for cell in detail.comparison_matrix.cells
                if (cell.competitor, cell.dimension) in valid_scopes
                and set(cell.source_ids) <= source_ids
                and set(cell.source_ids) <= scope_sources[(cell.competitor, cell.dimension)]]
            result["assessments"] = {dimension: {"status": assessment.status,
                "gap_count": len(assessment.gaps)}
                for dimension, assessment in detail.comparison_matrix.assessments.items()}
        if len(canonical_json(result).encode("utf-8")) > max_bytes:
            expected = {(product, dimension) for product in detail.plan.competitors
                        for dimension in detail.plan.dimensions}
            cells = result["cells"]
            return {"context_omitted": True, "matrix_valid": bool(valid_matrix),
                    "unavailable_count": len(analysts) - len(valid_scopes),
                    "missing_cell_count": len(expected - {(cell["competitor"], cell["dimension"]) for cell in cells}),
                    "uncited_cell_count": sum(not cell["source_ids"] for cell in cells),
                    "confidence_min": min((cell["confidence"] for cell in cells), default=1),
                    "producer_hash": self._evidence_artifact_hash(result)}
        return result

    @staticmethod
    def _bounded_analysis_json(view, payload, *, max_bytes=None):
        text = canonical_json(payload)
        if len(view.to_prompt_json().encode("utf-8")) + len(text.encode("utf-8")) <= (max_bytes or view.max_bytes):
            return text
        return '{"analysis_gap":"analysis_context_budget_exceeded"}'

    def _analysis_artifacts_hash(self, detail):
        payload = {
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
        if detail.plan.answer_requirements:
            payload["answer_requirements"] = [
                item.model_dump(mode="json") for item in detail.plan.answer_requirements
            ]
        brief = detail.plan.decision_brief
        if brief and brief.decision_question.strip():
            payload['writer_question_scope'] = {
                'topic': detail.topic, 'question': brief.decision_question,
            }
        return self._evidence_artifact_hash(payload)

    @staticmethod
    def _writer_evidence_artifact_payload(detail):
        payload = {
            "report_md": detail.report_md,
            "artifact": detail.report_artifact.model_dump(mode="json")
            if detail.report_artifact
            else None,
        }
        if detail.report_answer_boundaries:
            payload["answer_boundaries"] = [
                item.model_dump(mode="json") for item in detail.report_answer_boundaries
            ]
        if detail.report_dimension_audits:
            payload["dimension_audits"] = [item.model_dump(mode="json") for item in detail.report_dimension_audits]
        return payload

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
            return not record.detail.report_answer_boundaries
        if (
            not dependency.consumption_ids
            or dependency.payload_hash
            != self._evidence_artifact_hash(self._writer_evidence_artifact_payload(record.detail))
        ):
            return False
        if dependency.upstream_hash != self._artifact_upstream_hash(record.detail, "writer"):
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
                fact_ids=use.requested_fact_ids,
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
        self, record: RunRecord, *, phase: EvidencePhase, accepted_inputs: str | None = None
    ) -> RunEvidenceSnapshot:
        detail = record.detail
        previous = current_snapshot(detail)
        if phase == "analysis":
            # Collect snapshots are provisional and cannot be the analysis reuse baseline.
            previous = next(
                (item for item in reversed(detail.evidence_snapshots) if item.phase == "analysis"),
                None,
            )
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
        if (
            accepted_inputs is not None
            and self._accepted_analysis_inputs_hash(record) != accepted_inputs
        ):
            raise EvidenceUseRejectedError("accepted evidence inputs changed before resealing")
        baseline_id = getattr(record, "collector_redo_snapshot_id", None)
        if phase == "analysis":
            record.collector_redo_no_new_evidence = False
        if phase == "analysis" and baseline_id is not None:
            baseline = next((item for item in detail.evidence_snapshots
                if item.id == baseline_id and item.phase == "analysis"), None)
            # Seal a private candidate only after reading real canonical records.
            # A provisional collect snapshot must not reject the old producer
            # credentials before semantic equality has been established.
            candidate_detail = detail.model_copy(deep=True)
            candidate = _seal_snapshot(candidate_detail, phase=phase,
                canonical_documents=documents, rejected_sources=rejected)
            if baseline is not None:
                # A successfully admitted replacement for the same original page
                # supersedes the old body. Keep its raw audit record, never both
                # sets of contradictory facts as current accepted evidence.
                accepted_sources = {source.id: source for source in candidate.sources}
                admitted = set(accepted_sources)
                baseline_ids = {source.id for source in baseline.sources}
                replacements = [source for source in detail.raw_sources
                    if source.id not in baseline_ids and source.id in admitted
                    and not source.failure_reason and (
                        _document_reference(source)[0] in documents
                        or (source.metadata.get("captured_page_id")
                            and source.metadata.get("capture_content_hash")
                            and source.metadata.get("fetched_at")
                            and source.fetch_method not in {"", "rag_kb_retrieve"}))]
                for original in baseline.sources:
                    if any(self._collector_replacement_preserves_authority(
                            original, accepted_sources[replacement.id], admitted)
                            for replacement in replacements):
                        if original.id not in detail.evidence_retired_source_ids:
                            detail.evidence_retired_source_ids.append(original.id)
                candidate_detail = detail.model_copy(deep=True)
                candidate = _seal_snapshot(candidate_detail, phase=phase,
                    canonical_documents=documents, rejected_sources=rejected)
            if baseline is not None and candidate.content_hash == baseline.content_hash:
                prior_pointer = detail.evidence_snapshot_id
                detail.evidence_snapshot_id = baseline.id
                detail.evidence_inputs_dirty = False
                if self._collector_redo_producers_valid(record, baseline):
                    record.collector_redo_no_new_evidence = True
                    record.collector_redo_snapshot_id = None
                    previous_findings = getattr(record, "collector_redo_qa_findings", [])
                    previous_ids = {issue.id for issue in previous_findings}
                    detail.qa_findings = [*previous_findings, *(
                        issue for issue in detail.qa_findings if issue.id not in previous_ids)]
                    record.collector_redo_qa_findings = []
                    await self.emit(detail.id, "node_completed", "collector", None,
                        "Recollection produced no new accepted evidence; reviewed outputs retained.",
                        {"outcome": "no_new_evidence", "snapshot_id": baseline.id,
                         "qa_findings_retained": len(detail.qa_findings)})
                    self._persist_run(detail.id)
                    return baseline
                detail.evidence_snapshot_id = prior_pointer
            record.collector_redo_no_new_evidence = False
            record.collector_redo_snapshot_id = None
            record.collector_redo_qa_findings = []
        snapshot = _seal_snapshot(
            detail, phase=phase, canonical_documents=documents, rejected_sources=rejected
        )
        detail.evidence_inputs_dirty = False
        if previous is not None and snapshot.phase == "analysis" and previous.id != snapshot.id:
            changes = changed_evidence(previous, snapshot)
            if (changes.added_sources or changes.removed_sources or changes.changed_sources
                    or changes.added_facts or changes.removed_facts or changes.changed_facts):
                self._reconcile_evidence_artifacts(record)
        self._persist_run(detail.id)
        return snapshot

    @staticmethod
    def _collector_replacement_preserves_authority(original, replacement, admitted_ids):
        if (original.competitor, original.dimension, original.url, original.market, original.role) != (
                replacement.competitor, replacement.dimension, replacement.url,
                replacement.market, replacement.role):
            return False
        authority = {"historical_report": 0, "unknown": 1, "summary": 1,
                     "search_summary": 1, "full_source": 2, "kb_document": 2}
        if authority[replacement.material_level] < authority[original.material_level]:
            return False
        if original.document_id:
            if original.id in admitted_ids and replacement.document_id != original.document_id:
                # Another still-active canonical document is independent context,
                # even if its URL happens to match. Repository correction/revocation
                # is validated separately and invalidates the original as usual.
                return False
            if (original.document_workspace_id, original.document_project_id) != (
                    replacement.document_workspace_id, replacement.document_project_id):
                return False
        return True

    def _collector_redo_producers_valid(self, record, snapshot):
        detail = record.detail
        # Require the actual complete Writer credential. Never infer validity
        # from a report string or migrate a producer across snapshot versions.
        if not detail.report_md or not any(d.kind == "writer" for d in detail.evidence_artifact_dependencies):
            return False
        if not self._final_qa_producer_verified(record, snapshot):
            return False
        analyst_scopes = {(d.competitor, d.dimension) for d in detail.evidence_artifact_dependencies
                          if d.kind == "analyst"}
        for product in detail.plan.competitors:
            for dimension in detail.plan.dimensions:
                payload = self._analyst_evidence_artifact_payload(detail, product, dimension)
                knowledge = payload.get("knowledge") or {}
                review = payload.get("review_summary") or {}
                has_output = (any(knowledge.values()) or payload.get("kb_slice") or payload.get("cards")
                    or review.get("source_ids") or any(review.get(key) for key in (
                        "praise_themes", "complaint_themes", "adoption_blockers", "switching_triggers")))
                if has_output and (product, dimension) not in analyst_scopes:
                    return False
        for dependency in detail.evidence_artifact_dependencies:
            if dependency.kind == "analyst":
                payload = self._analyst_evidence_artifact_payload(
                    detail, dependency.competitor, dependency.dimension)
            elif dependency.kind == "comparator":
                payload = self._comparator_evidence_artifact_payload(detail)
            elif dependency.kind == "reflector":
                if not detail.reflections:
                    return False
                payload = detail.reflections[-1].model_dump(mode="json")
            elif dependency.kind == "writer":
                payload = self._writer_evidence_artifact_payload(detail)
            else:
                return False
            if not self._evidence_artifact_valid(record, kind=dependency.kind,
                    payload=payload, competitor=dependency.competitor, dimension=dependency.dimension):
                return False
        kinds = {d.kind for d in detail.evidence_artifact_dependencies}
        return ((not detail.comparison_matrix or "comparator" in kinds)
                and (not detail.reflections or "reflector" in kinds))

    def _reconcile_evidence_artifacts(self, record):
        """Validate actual producer credentials before reusing accepted stage outputs."""
        detail = record.detail
        if not (detail.competitor_kbs or detail.competitor_knowledge
                or detail.evidence_artifact_dependencies or detail.claim_card_bundles
                or detail.comparison_matrix or detail.reflections):
            if detail.report_md or detail.report_artifact:
                detail.evidence_writer_rewrite_required = True
                detail.section_briefs = []
            return
        for product in detail.plan.competitors:
            for dimension in detail.plan.dimensions:
                payload = self._analyst_evidence_artifact_payload(detail, product, dimension)
                if not self._evidence_artifact_valid(
                    record, kind="analyst", payload=payload, competitor=product, dimension=dimension
                ):
                    self._clear_competitor_dimension_output(detail, product, dimension)
                    detail.claim_card_bundles = [item for item in detail.claim_card_bundles
                        if (item.competitor, item.dimension) != (product, dimension)]
        if not self._evidence_artifact_valid(
            record, kind="comparator", payload=self._comparator_evidence_artifact_payload(detail)
        ):
            detail.comparison_matrix = None
            detail.decision_card_bundle = None
            detail.reflections = []
        if not self._evidence_artifact_valid(
            record, kind="writer", payload=self._writer_evidence_artifact_payload(detail)
        ):
            # Without complete per-section producer dependencies, redo the whole report.
            detail.section_briefs = []
            detail.evidence_writer_rewrite_required = True

    @staticmethod
    def _current_evidence_snapshot(
        record: RunRecord, *, require_current_policy: bool = True
    ) -> RunEvidenceSnapshot:
        snapshot = current_snapshot(record.detail)
        if snapshot is None:
            raise ValueError("an explicit evidence snapshot is required before consumption")
        if (
            snapshot.workspace_id != record.detail.workspace_id
            or snapshot.project_id != record.detail.project_id
        ):
            raise EvidenceUseRejectedError("evidence snapshot scope mismatch")
        if (
            require_current_policy
            and snapshot.fact_market_policy_version != FACT_MARKET_POLICY_VERSION
        ):
            raise EvidenceUseRejectedError("evidence market policy requires accepted resealing")
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
        if record.detail.evidence_inputs_dirty:
            raise EvidenceUseRejectedError("evidence inputs require accepted resealing")
        snapshot = self._current_evidence_snapshot(record)
        if agent == "qa":
            snapshot = self._final_qa_snapshot(record)
            if snapshot.fact_market_policy_version != FACT_MARKET_POLICY_VERSION:
                raise EvidenceUseRejectedError("evidence market policy requires accepted resealing")
        budget = _DEPTH_BYTES.get(record.detail.plan.research_depth, 8192)
        if agent in {'analyst', 'writer'} and dimension in {'feature', 'pricing'}:
            budget = min(32768, budget * 2)
        requested_fact_ids = None
        if agent == 'writer' and competitor and dimension:
            from packages.agents.writer.answer_coverage import question_fact_ids
            requested_fact_ids = question_fact_ids(record.detail, snapshot, competitor, dimension)
        analysis_allowance = budget if agent in {'comparator', 'reflector'} else 0
        if agent in {"comparator", "reflector"}:
            # A comparison aggregates independently bounded analyst branches.
            # Reusing one branch's budget retires every otherwise valid producer.
            detail = record.detail
            uses_by_id = {use.id: use for use in detail.evidence_consumptions}
            scopes = set()
            producer_facts = set()
            for dependency in detail.evidence_artifact_dependencies:
                if (dependency.kind != "analyst"
                        or dependency.competitor not in detail.plan.competitors
                        or dependency.dimension not in detail.plan.dimensions):
                    continue
                branch_uses = [uses_by_id.get(key) for key in dependency.consumption_ids]
                if not branch_uses or any(
                    use is None or use.agent != "analyst"
                    or use.status not in {"validated", "reused"}
                    or (use.view_max_bytes or use.max_bytes) > (
                        min(32768, budget * 2) if dependency.dimension in {'feature', 'pricing'} else budget)
                    for use in branch_uses
                ):
                    continue
                if self._evidence_artifact_valid(
                    record, kind="analyst", competitor=dependency.competitor,
                    dimension=dependency.dimension,
                    payload=self._analyst_evidence_artifact_payload(
                        detail, dependency.competitor, dependency.dimension,
                    ),
                ):
                    scopes.add((dependency.competitor, dependency.dimension))
                    producer_facts.update(fact_id for use in branch_uses for fact_id in use.fact_ids)
            budget = min(98304, sum(min(32768, budget * 2) if dimension in {'feature', 'pricing'} else budget
                                   for _, dimension in scopes) or budget)
            if scopes:
                requested_fact_ids = tuple(sorted(producer_facts))
        requested_ids = tuple(sorted(set(source_ids))) if source_ids is not None else None
        if agent in {"qa", "collect_qa", "analyst_qa"} and requested_ids is not None and len(requested_ids) == 1:
            # Checkpoint and final citation audits send no model tokens.
            # Inspect the source's facts in a separate bounded local view rather
            # than retiring a valid source because a generation view was small.
            local_records = [item for item in snapshot.sources if item.id in requested_ids]
            local_records.extend(item for item in snapshot.facts if item.source_id in requested_ids)
            local_records.extend(snapshot.conflicts)
            local_records.extend(snapshot.gaps)
            serialized_bytes = sum(len(canonical_json(item.model_dump(mode="json")).encode("utf-8")) for item in local_records)
            budget = max(budget, 65536, 4 * serialized_bytes + 8192)
        if (self._settings.run_llm_max_tokens and record.detail.execution_mode == 'real'
                and agent in {'analyst', 'comparator', 'reflector'}):
            # Keep whole observations and their omission records within a core
            # stage's conservative envelope; never trim a quote or a condition.
            budget = min(budget, {'analyst': 12000, 'comparator': 20000, 'reflector': 18000}[agent])
        view = select_evidence_view(
            snapshot,
            agent=agent,
            competitor=competitor,
            dimension=dimension,
            source_ids=requested_ids,
            fact_ids=requested_fact_ids,
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
            requested_fact_ids=requested_fact_ids,
            fact_ids=view.fact_ids,
            max_bytes=min(98304, budget + analysis_allowance) if analysis_allowance else budget,
            view_max_bytes=budget if analysis_allowance else None,
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
            if record.detail.evidence_inputs_dirty:
                raise EvidenceUseRejectedError("evidence inputs changed before resealing")
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
            if validated_snapshot.fact_market_policy_version != FACT_MARKET_POLICY_VERSION:
                raise EvidenceUseRejectedError("evidence market policy requires accepted resealing")
            current = select_evidence_view(
                validated_snapshot,
                agent=use.agent,
                competitor=use.competitor,
                dimension=use.dimension,
                source_ids=use.requested_source_ids,
                fact_ids=use.requested_fact_ids,
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
