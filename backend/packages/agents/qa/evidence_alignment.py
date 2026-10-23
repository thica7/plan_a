"""Audit original report citations without retrieving replacement evidence."""

from __future__ import annotations

from packages.identity.source_resolver import normalize_source_token, resolve_source_token
from packages.knowledge.models import KnowledgeScope
from packages.knowledge.repository import KnowledgeRepository
from packages.orchestrator.answer_context import audit_answer_boundaries, report_answer_claim_cards
from packages.orchestrator.scoping import build_redo_scope
from packages.research.evidence.snapshot import _document_problem
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.evidence.views import select_evidence_view
from packages.research.evidence.report_claims import audit_report_claims
from packages.schema.decision_brief import safe_decision_brief_text
from packages.schema.models import QCIssue
from packages.sources import source_tokens


def audit_dimension_claims(service, record, snapshot, *, producer_verified):
    """Replay the original generation view; do not borrow uncited snapshot facts."""
    issues = []
    dependency = next((d for d in record.detail.evidence_artifact_dependencies if d.kind == "writer"), None)
    uses = {u.id: u for u in record.detail.evidence_consumptions}
    for index, audit in enumerate(record.detail.report_dimension_audits):
        reasons = set()
        use = uses.get(audit.consumption_id)
        if not producer_verified or dependency is None or audit.consumption_id not in dependency.consumption_ids:
            reasons.add("claim_producer_unverified")
        if use is None or use.agent != "writer" or use.snapshot_id != snapshot.id:
            reasons.add("claim_generation_view_missing")
        elif use.competitor != audit.competitor or use.dimension != audit.dimension:
            reasons.add("claim_generation_scope_mismatch")
        if not reasons:
            view = select_evidence_view(snapshot, agent="writer", competitor=use.competitor, dimension=use.dimension,
                source_ids=use.requested_source_ids, fact_ids=use.requested_fact_ids,
                max_bytes=use.view_max_bytes or use.max_bytes)
            boundaries = [b for b in record.detail.report_answer_boundaries
                          if b.requirement.competitor == audit.competitor and b.requirement.dimension == audit.dimension
                          and set(b.view_fact_ids) == set(use.fact_ids) and set(b.view_source_ids) == set(use.source_ids)]
            published = [c for c in audit.claims if c.status == "supported"]
            from packages.agents.writer.question_retrieval import _eligible_facts
            discovery = _eligible_facts(snapshot, audit.competitor, audit.dimension) if audit.dimension == 'feature' else view.facts
            replayed = audit_report_claims([c.claim for c in published], [c.review for c in published if c.review],
                view, boundaries, available_facts=discovery, review_version=audit.claim_review_version)
            if any(c.status != "supported" for c in replayed):
                reasons.add("claim_review_replay_failed")
            from packages.agents.writer.answer_presentation import (
                observation_claims, question_coverage_matches,
            )
            for item in observation_claims(record.detail, audit):
                clause = safe_decision_brief_text(item.claim.text) + " " + "".join(f"[source:{sid}]" for sid in item.claim.source_ids)
                if clause not in record.detail.report_md:
                    reasons.add("published_claim_missing_or_changed")
            if any(size > use.max_bytes for size in audit.review_context_bytes):
                reasons.add("claim_review_context_exceeded")
            from packages.agents.writer.answer_coverage import (
                coverage_resolution_reasons, is_qualified_partial_clarification, research_questions,
            )
            questions = research_questions(record.detail, audit.competitor, audit.dimension)
            expected = {item['question_id']: item['question'] for item in questions}
            actual = {item.question_id: item.question for item in audit.answer_coverage}
            if actual != expected or len(actual) != len(audit.answer_coverage):
                reasons.add('answer_coverage_scope_changed')
            published_ids = {item.claim.id for item in published}
            published_claims = [item.claim.model_dump(mode='json') for item in published]
            from packages.agents.writer.price_answers import server_missing_price_answers
            from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
            price_answers = server_missing_price_answers(
                record.detail, snapshot, questions, audit.competitor,
                claims=tuple(item.claim for item in published))
            from packages.agents.writer.request_clarification import server_clarification_answer
            clarification_answers = {q['question_id']: server_clarification_answer(q) for q in questions}
            if audit.answer_binding_version == 3 and audit.claim_review_version != 3:
                reasons.add('claim_review_version_required')
            def answer_invalid(item, *, required_version=audit.answer_binding_version,
                               answer_facts=view.facts):
                if item.resolution == 'insufficient':
                    original = price_answers.get(item.question_id)
                    return (item.status != 'partial' or original is None
                            or item != ReportAnswerCoverage(**original))
                if item.binding_version in (2, 3) and item.binding_version != required_version:
                    return True
                if item.binding_version == 3 and item.resolution == 'clarification' and not item.claim_ids:
                    original = clarification_answers.get(item.question_id)
                    return (required_version != 3 or original is None or item != original
                            or not is_qualified_partial_clarification(item, published_claims,
                                facts=answer_facts, report_md=record.detail.report_md))
                qualified_clarification = required_version in (2, 3) and is_qualified_partial_clarification(
                    item, published_claims, facts=answer_facts, report_md=record.detail.report_md)
                return ((item.status != 'answered' and not qualified_clarification) or not item.claim_ids
                        or not set(item.claim_ids) <= published_ids
                        or bool(coverage_resolution_reasons(item, published_claims,
                            required_binding_version=required_version, facts=answer_facts,
                            require_subquestions=audit.answer_review_contract is not None)))
            from packages.agents.qa.question_context import question_context_blocks
            request_only_ids = {item.question_id for item in audit.answer_coverage
                if audit.answer_binding_version == 3 and item == clarification_answers.get(item.question_id)
                and not answer_invalid(item)}
            if (question_context_blocks(service, record.detail, snapshot, use, view, audit.gaps, request_only_ids)
                    or any(answer_invalid(item) for item in audit.answer_coverage)
                    or questions and not audit.answer_coverage):
                reasons.add('answer_coverage_incomplete')
            if not question_coverage_matches(record.detail.report_md, audit, record.detail.output_language,
                                             audits=record.detail.report_dimension_audits):
                reasons.add('published_answer_missing_or_changed')
        for reason in sorted(reasons):
            problem = f"主张引用审核失败：{reason}。请重新生成该产品和维度的报告内容。"
            issues.append(QCIssue(id=f"qa-claim-{service._evidence_artifact_hash([snapshot.id, index, reason])[:20]}",
                severity="blocker", detected_by="citation", target_agent="writer", target_competitor=audit.competitor,
                target_subagent=audit.dimension, field_path=f"report.dimension_audits.{index}", problem=problem,
                redo_scope=build_redo_scope(detected_by="citation", target_agent="writer", target_competitor=audit.competitor,
                    target_subagent=audit.dimension, field_path=f"report.dimension_audits.{index}", problem=problem),
                metadata={"claim_audit_reason": reason, "snapshot_id": snapshot.id, "unpublishable_evidence": True}))
    return issues


class FinalEvidenceAuditMixin:
    async def _final_qa_evidence(self, record):
        await self._ensure_analysis_evidence(record)
        aliases = self._source_alias_map(record.detail)
        cited_ids = {
            resolve_source_token(token, aliases) or normalize_source_token(token)
            for token in source_tokens(record.detail.report_md)
        }
        if record.detail.report_answer_boundaries:
            cited_ids.update(
                resolve_source_token(source_id, aliases) or normalize_source_token(source_id)
                for card in report_answer_claim_cards(record.detail)
                for source_id in card.source_ids
            )
        cited_ids = sorted(cited_ids)
        snapshot = self._final_qa_snapshot(record)
        producer_verified = self._final_qa_producer_verified(record, snapshot)
        claim_issues = audit_dimension_claims(self, record, snapshot, producer_verified=producer_verified)
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
        issues = list(claim_issues)
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
                reviewed_claim_sources = {sid for a in record.detail.report_dimension_audits
                    for c in a.claims if c.status == "supported" for sid in c.claim.source_ids}
                if any(gap.reason == "context_budget_exceeded" for gap in original_view.gaps) and not (
                    producer_verified and not claim_issues and source_id in reviewed_claim_sources
                ):
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
                if (
                    reason == "writer_producer_unverified"
                    and record.detail.report_answer_boundaries
                ):
                    # The answer audit returns a Writer repair for a changed report
                    # contract. Source/dependency failures retain collection repairs.
                    continue
                fact_ids = [fact.id for fact in snapshot.facts if fact.source_id == source_id]
                capacity_problem = reason == "context_budget_exceeded"
                target_agent = "writer" if capacity_problem else "collector"
                problem = ("Local citation audit could not inspect all facts within its context capacity. "
                           "Reduce the cited claim set and rerun the audit; the source remains valid."
                           if capacity_problem else
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
                        target_agent=target_agent,
                        target_competitor=competitor,
                        target_subagent=dimension,
                        field_path=f"report.citations.{source_id}",
                        problem=problem,
                        redo_scope=build_redo_scope(
                            detected_by="citation",
                            target_agent=target_agent,
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
        issues.extend(audit_answer_boundaries(
            self, record, snapshot, producer_verified=producer_verified, aliases=aliases
        ))
        return projected, issues, uses
