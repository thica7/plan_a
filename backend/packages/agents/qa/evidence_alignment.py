"""Audit original report citations without retrieving replacement evidence."""

from __future__ import annotations

from packages.identity.source_resolver import normalize_source_token, resolve_source_token
from packages.knowledge.models import KnowledgeScope
from packages.knowledge.repository import KnowledgeRepository
from packages.orchestrator.scoping import build_redo_scope
from packages.research.evidence.snapshot import _document_problem
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.evidence.views import select_evidence_view
from packages.schema.models import QCIssue
from packages.sources import source_tokens


class FinalEvidenceAuditMixin:
    async def _final_qa_evidence(self, record):
        await self._ensure_analysis_evidence(record)
        aliases = self._source_alias_map(record.detail)
        cited_ids = sorted(
            {
                resolve_source_token(token, aliases) or normalize_source_token(token)
                for token in source_tokens(record.detail.report_md)
            }
        )
        snapshot = self._final_qa_snapshot(record)
        producer_verified = self._final_qa_producer_verified(record, snapshot)
        views, uses = [], []
        for source_id in cited_ids:
            view, use = self._begin_evidence_use(record, agent="qa", source_ids=[source_id])
            views.append(view)
            uses.append(use)
            self._trace_local_tool(
                record,
                agent="qa",
                subagent=None,
                name="final_qa_cited_evidence",
                input_text=view.to_prompt_json(),
                output_text=canonical_json({"source_ids": view.source_ids}),
                metadata={
                    "consumption_id": use.id,
                    "snapshot_id": view.snapshot_id,
                    "estimated_bytes": view.estimated_bytes,
                },
            )
        projected, _ = self._project_evidence_detail(record, views)
        projected.report_md = record.detail.report_md
        issues = []
        selected = {source.id: source for source in snapshot.sources if source.id in cited_ids}
        scope = KnowledgeScope(
            workspace_id=record.detail.workspace_id,
            project_id=record.detail.project_id,
            include_workspace_library=True,
        )
        references = [source for source in selected.values() if source.document_id]
        canonical_problems = {}
        if references:
            async with KnowledgeRepository() as repo:
                documents, chunks = {}, {}
                for source in references:
                    if source.document_id not in documents:
                        documents[source.document_id] = await repo.get_document(
                            source.document_id, scope=scope
                        )
                    document = documents[source.document_id]
                    reason = (
                        "canonical_document_unavailable"
                        if document is None
                        else _document_problem(source.to_raw_source(), document, scope)
                    )
                    if not reason and source.chunk_ids:
                        if source.document_id not in chunks:
                            chunks[source.document_id] = {
                                chunk.id: chunk
                                for chunk in await repo.get_chunks_for_document(source.document_id)
                            }
                        known = chunks[source.document_id]
                        if any(chunk_id not in known for chunk_id in source.chunk_ids):
                            reason = "chunk_reference_unavailable"
                        elif any(
                            known[chunk_id].document_id != source.document_id
                            for chunk_id in source.chunk_ids
                        ):
                            reason = "chunk_identity_mismatch"
                    if reason:
                        canonical_problems[source.id] = reason
        # A preserved, unauthenticated report remains readable even without citations,
        # but cannot become a newly published artifact.
        for index, source_id in enumerate(cited_ids or ([] if producer_verified else [None])):
            source = selected.get(source_id)
            reasons = {
                gap.reason for view in views for gap in view.gaps if gap.source_id == source_id
            }
            if not producer_verified:
                reasons.add("writer_producer_unverified")
            if source_id in canonical_problems:
                reasons.add(canonical_problems[source_id])
            if source_id is not None and source is None:
                reasons.add("source_not_in_snapshot")
            if source_id is not None:
                original_view = views[index]
                if any(gap.reason == "context_budget_exceeded" for gap in original_view.gaps):
                    reasons.add("context_budget_exceeded")
                current_view = select_evidence_view(
                    self._current_evidence_snapshot(record),
                    agent="qa",
                    source_ids=[source_id],
                    max_bytes=original_view.max_bytes,
                )
                if current_view.dependency_hash != original_view.dependency_hash:
                    reasons.add("source_dependency_changed")
            for reason in sorted(reasons):
                fact_ids = [fact.id for fact in snapshot.facts if fact.source_id == source_id]
                problem = (
                    f"Referenced evidence {source_id} is invalid: {reason}. "
                    "Original citation must be recollected and reanalysed."
                )
                competitor = source.competitor if source else None
                dimension = source.dimension if source else None
                issue_hash = self._evidence_artifact_hash([snapshot.id, source_id, reason])
                issues.append(
                    QCIssue(
                        id=f"qa-evidence-{issue_hash[:24]}",
                        severity="blocker",
                        detected_by="citation",
                        target_agent="collector",
                        target_competitor=competitor,
                        target_subagent=dimension,
                        field_path=f"report.citations.{source_id}",
                        problem=problem,
                        redo_scope=build_redo_scope(
                            detected_by="citation",
                            target_agent="collector",
                            target_competitor=competitor,
                            target_subagent=dimension,
                            field_path=f"raw_sources.{source_id}",
                            problem=problem,
                        ),
                        metadata={
                            "evidence_reason": reason,
                            "snapshot_id": snapshot.id,
                            "source_ids": [source_id] if source_id else [],
                            "fact_ids": fact_ids,
                            "document_id": source.document_id if source else None,
                            "unpublishable_evidence": True,
                        },
                    )
                )
        return projected, issues, uses
