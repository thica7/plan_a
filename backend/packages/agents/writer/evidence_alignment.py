"""Fixed evidence projections and the Writer's guarded artifact commit."""

from __future__ import annotations

import json
from dataclasses import replace

from packages.identity.source_resolver import resolve_source_token, source_tokens
from packages.orchestrator.answer_context import ANSWER_GUARD_INSTRUCTIONS, build_answer_boundaries
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.research.evidence.answer_models import AnswerBoundary
from packages.research.evidence.answer_guard import evaluate_answer_boundary
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.evidence.views import select_evidence_view


class WriterEvidenceAlignmentMixin:
    async def _real_writer_step(self, record):
        snapshot = await self._ensure_analysis_evidence(record)
        previous_dependency = next(
            (
                item
                for item in record.detail.evidence_artifact_dependencies
                if item.kind == "writer"
            ),
            None,
        )
        previous_payload = self._writer_evidence_artifact_payload(record.detail)
        if previous_dependency is not None and not self._evidence_artifact_valid(
            record, kind="writer", payload=previous_payload
        ):
            record.detail.evidence_writer_rewrite_required = True
        start_ids = {item.id for item in record.detail.evidence_consumptions}
        views = []
        for competitor in record.detail.plan.competitors:
            for dimension in record.detail.plan.dimensions:
                from packages.agents.writer.question_retrieval import retrieve_question_facts
                fact_ids, retrieval = await retrieve_question_facts(
                    record.detail, snapshot, competitor, dimension)
                self._trace_local_tool(record, agent='writer', subagent=f'{competitor}/{dimension}',
                    name='question_fact_retrieval', input_text=canonical_json({'snapshot_id': snapshot.id}),
                    output_text=canonical_json(retrieval), metadata={'retrieval_mode': retrieval['mode']})
                view, use = self._begin_evidence_use(
                    record, agent="writer", competitor=competitor, dimension=dimension, fact_ids=fact_ids
                )
                views.append(view)
                self._trace_local_tool(
                    record,
                    agent="writer",
                    subagent=None,
                    name="writer_snapshot_projection",
                    input_text=view.to_prompt_json(),
                    output_text=canonical_json(
                        {"source_ids": view.source_ids, "fact_ids": view.fact_ids}
                    ),
                    metadata={
                        "consumption_id": use.id,
                        "snapshot_id": view.snapshot_id,
                        "estimated_bytes": view.estimated_bytes,
                    },
                )
        projected, gaps = self._project_evidence_detail(record, views)
        from packages.agents.writer.dimension_writer import partial_report_mode
        if partial_report_mode(record.detail, snapshot):
            # Only the audited partial route needs accepted missing-scope context.
            # Its generation/review still use bounded views and live credentials.
            projected.evidence_snapshots = [snapshot]
            projected.evidence_snapshot_id = snapshot.id
        if projected.reflections and not self._evidence_artifact_valid(
            record, kind="reflector", payload=record.detail.reflections[-1].model_dump(mode="json")
        ):
            projected.reflections = []
        baseline = self._analysis_artifacts_hash(record.detail)
        draft = replace(
            record, detail=projected, evidence_origin=record, writer_preserved_report=False
        )
        draft.detail.report_answer_boundaries = []
        draft.detail.report_dimension_audits = list(record.detail.report_dimension_audits) if (
            self._evidence_artifact_valid(record, kind='writer', payload=previous_payload)
        ) else []
        initial_messages = {
            item.id: item.model_dump(mode="json") for item in projected.agent_messages
        }
        try:
            await self._write_report_draft(draft)
        except EvidenceUseRejectedError:
            raise
        except Exception:
            self._validate_writer_commit(record, start_ids, baseline)
            if draft.detail.status == "failed":
                record.detail.status = "failed"
                record.detail.current_node = draft.detail.current_node
                self._persist_run(record.detail.id)
            raise
        uses = self._validate_writer_commit(record, start_ids, baseline)
        if previous_payload != self._writer_evidence_artifact_payload(record.detail):
            raise EvidenceUseRejectedError("Writer report changed before commit")
        if draft.detail.status == "failed":
            record.detail.status = "failed"
            record.detail.current_node = draft.detail.current_node
            self._persist_run(record.detail.id)
            return
        if draft.writer_preserved_report:
            draft.detail.report_answer_boundaries = record.detail.report_answer_boundaries
            draft.detail.report_dimension_audits = record.detail.report_dimension_audits
        # Retained audits keep their original generation credential and review.
        retained_ids = {audit.consumption_id for audit in draft.detail.report_dimension_audits} - {use.id for use in uses}
        for use_id in retained_ids:
            use = next((item for item in record.detail.evidence_consumptions if item.id == use_id), None)
            if use is None:
                raise EvidenceUseRejectedError('Retained dimension audit has no generation credential')
            self._validate_evidence_use(record, use)
            uses.append(use)
        for field in ("report_md", "report_artifact", "section_briefs", "report_answer_boundaries", "report_dimension_audits"):
            setattr(record.detail, field, getattr(draft.detail, field))
        record.structured_report_snapshot = draft.structured_report_snapshot
        record.previous_structured_report_snapshot = draft.previous_structured_report_snapshot
        # Commit only Writer-owned message changes. Messages arriving during awaits survive.
        live_by_id = {item.id: item for item in record.detail.agent_messages}
        for message in draft.detail.agent_messages:
            if message.id not in initial_messages:
                record.detail.agent_messages.append(message)
                message.trace_span_ids = [self._append_agent_message_trace_span(record, message)]
                if self._trace_store is not None:
                    self._trace_store.append_agent_message(message)
            elif message.model_dump(mode="json") != initial_messages[message.id]:
                live = live_by_id.get(message.id)
                if (
                    live is not None
                    and live.status != "consumed"
                    and message.consumed_by == "writer"
                ):
                    self._consume_agent_message(record, live, consumer_agent="writer")
        # Projection normalizes legitimate citation aliases in the final markdown.
        # Record a new producer against that final payload, retaining the same uses.
        projection = (
            None if draft.writer_preserved_report else self._sync_enterprise_projection(record)
        )
        if draft.writer_preserved_report and previous_dependency is not None:
            # Preserve the actual producer even if hardening changed the payload.
            # QA then detects the original hash mismatch; these reads are not generation.
            record.detail.evidence_artifact_dependencies = [
                item
                for item in record.detail.evidence_artifact_dependencies
                if item.kind != "writer"
            ] + [previous_dependency]
            self._persist_run(record.detail.id)
        else:
            self._record_evidence_artifact(
                record,
                kind="writer",
                uses=[] if draft.writer_preserved_report else uses,
                payload=self._writer_evidence_artifact_payload(record.detail),
            )
        if not draft.writer_preserved_report:
            record.detail.evidence_writer_rewrite_required = False
            self._persist_run(record.detail.id)
        await self.emit(
            record.detail.id,
            "report_updated",
            "writer",
            None,
            "Report markdown updated from guarded Writer draft.",
            {
                "report_md": record.detail.report_md,
                "snapshot_id": snapshot.id,
                "analysis_dependency_gaps": gaps,
                **self._enterprise_projection_payload(projection),
            },
        )
        await self.emit(record.detail.id, "node_completed", "writer", None, "Writer completed.")

    def _validate_writer_commit(self, record, start_ids, baseline):
        uses = [
            item
            for item in record.detail.evidence_consumptions
            if item.id not in start_ids and item.agent == "writer"
        ]
        for use in uses:
            self._validate_evidence_use(record, use)
        if baseline != self._analysis_artifacts_hash(record.detail):
            raise EvidenceUseRejectedError("Writer analysis artifacts changed before commit")
        return uses

    def _writer_segment_evidence(self, record, segment):
        """Replace evidence payloads with a bounded selection, retain heading/repair contracts."""
        ids = segment.get("allowed_source_ids")
        if ids is None:
            ids = segment.get("citation_source_ids")
        # An absent citation list is an evidence gap, never broad retrieval.
        ids = ids if isinstance(ids, (list, tuple, set)) else []
        competitor = segment.get("segment_competitor")
        competitor = competitor if competitor in record.detail.plan.competitors else None
        dimension = segment.get("dimension")
        dimension = dimension if dimension in record.detail.plan.dimensions else None
        view, use = self._begin_evidence_use(
            record, agent="writer", competitor=competitor, dimension=dimension, source_ids=ids
        )
        snapshot = self._current_evidence_snapshot(self._evidence_live_record(record))
        candidate_segment = dict(segment)
        lower, upper = 1, view.max_bytes
        best = None
        first_resize = True
        while True:
            selected = self._writer_segment_context(record, candidate_segment, view, use)
            actual_bytes = len(self._writer_evidence_context_json(selected).encode("utf-8"))
            if actual_bytes <= use.max_bytes:
                score = (len({fact.competitor for fact in view.facts}),
                         len({(fact.competitor, fact.dimension) for fact in view.facts}),
                         len(view.facts))
                if best is None or score >= best[0]:
                    best = (score, selected, view, actual_bytes)
                lower = view.max_bytes + 1
            elif selected.get("shard_notes"):
                candidate_segment["shard_notes"] = []
                candidate_segment["shard_notes_gap"] = "shard_notes_context_budget_exceeded"
                continue
            else:
                upper = view.max_bytes - 1
            # Dropping a price observation can also drop large denied-fact
            # controls. Search the freed space locally instead of fixing the
            # first smaller budget and starving another product permanently.
            while lower <= upper:
                selection_budget = ((lower + upper) // 2 if not first_resize else
                                    max(lower, min(upper, use.max_bytes - (actual_bytes - view.estimated_bytes))))
                first_resize = False
                try:
                    view = select_evidence_view(
                        snapshot, agent="writer", competitor=competitor,
                        dimension=dimension, source_ids=use.requested_source_ids,
                        fact_ids=use.requested_fact_ids,
                        max_bytes=selection_budget,
                    )
                except ValueError:
                    lower = selection_budget + 1
                    continue
                break
            else:
                break
        if best is None:
            live = self._evidence_live_record(record)
            rejected = use.model_copy(update={"status": "rejected"})
            live.detail.evidence_consumptions = [
                rejected if item.id == use.id else item for item in live.detail.evidence_consumptions
            ]
            self._persist_run(live.detail.id)
            raise EvidenceUseRejectedError("Writer segment control contract exceeds context budget")
        _, selected, view, actual_bytes = best
        use = use.model_copy(
            update={
                "dependency_hash": view.dependency_hash,
                "source_ids": view.source_ids,
                "fact_ids": view.fact_ids,
                "view_max_bytes": view.max_bytes,
                "estimated_bytes": actual_bytes,
                "estimated_tokens": actual_bytes + 256,
            }
        )
        live = self._evidence_live_record(record)
        live.detail.evidence_consumptions = [
            use if item.id == use.id else item for item in live.detail.evidence_consumptions
        ]
        self._persist_run(live.detail.id)
        boundaries = [AnswerBoundary.model_validate(item) for item in selected["answer_boundaries"]]
        for boundary in boundaries:
            if boundary not in record.detail.report_answer_boundaries:
                record.detail.report_answer_boundaries.append(boundary)
        return selected, use

    @staticmethod
    def _writer_evidence_context_json(segment):
        from packages.agents.writer.logic import _prompt_safe_writer_segment

        payload = _prompt_safe_writer_segment(segment)
        for key in ("source_index", "evidence_claims", "decision_guidance"):
            if payload.get(key) == []:
                payload.pop(key)
        # Persisted boundaries retain their full authenticated view IDs. In a
        # model prompt those same IDs are already in evidence_view; reference it
        # instead of duplicating the entire view once for every requirement.
        if isinstance(payload.get("answer_boundaries"), list):
            payload["answer_boundaries_view_ref"] = "evidence_view"
            payload["answer_boundaries"] = [
                {**{key: value for key, value in boundary.items()
                    if key not in {"view_source_ids", "view_fact_ids", "snapshot_id", "fact_decisions"}},
                 "fact_decisions": [
                     {key: value for key, value in decision.items() if key != "source_id"}
                     for decision in boundary.get("fact_decisions", [])
                     if not decision.get("allowed") or decision.get("reasons")
                 ]}
                for boundary in payload["answer_boundaries"]
            ]
            facts = payload.get("evidence_view", {}).get("facts", [])
            for boundary in payload["answer_boundaries"]:
                requirement = boundary["requirement"]
                scoped_ids = {fact["id"] for fact in facts
                              if fact["competitor"] == requirement["competitor"]
                              and fact["dimension"] == requirement["dimension"]}
                if not scoped_ids and any(
                    gap.get("reason") == "context_budget_exceeded"
                    and gap.get("competitor") == requirement["competitor"]
                    and gap.get("dimension") == requirement["dimension"]
                    for gap in payload.get("evidence_view", {}).get("gaps", [])
                ):
                    boundary["evidence_status"] = "collected_but_omitted"
                if scoped_ids and scoped_ids == set(boundary["allowed_fact_ids"]):
                    boundary.pop("allowed_fact_ids")
                    boundary["allowed_facts_ref"] = "all evidence_view facts for this competitor and dimension"
                for key in ("withheld_fact_ids", "missing_fields", "clarification_fields", "fact_decisions"):
                    if boundary.get(key) == []:
                        boundary.pop(key)
                if requirement.get("context_json") == "{}":
                    requirement.pop("context_json")
                if requirement.get("market") is None:
                    requirement.pop("market", None)
        if not payload.get("analysis") and payload.get("analysis_dependency_gaps"):
            payload.pop("analysis_dependency_gaps")
            payload["analysis_gap"] = "Branch summaries are not reused; use selected original facts. View omissions are not collection failures."
        if payload.get("dimension") == "pricing" and payload.get("answer_boundaries") and all(
            b["requirement"]["intent"] == "recorded_price" for b in payload["answer_boundaries"]
        ):
            # This branch formats original price facts, without branch summaries.
            # Sources and capacity gaps are already bound in evidence_view.
            payload.pop("analysis_gap", None)
            if set(payload.get("citation_source_ids", [])) == {
                source["id"] for source in payload["evidence_view"]["sources"]
            }:
                payload.pop("citation_source_ids", None)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _writer_segment_context(self, record, segment, view, use):
        """Pure local construction; original evidence values and quotes stay complete."""
        contract_fields = {
            "segment_name",
            "segment_kind",
            "section_id",
            "section_key",
            "segment_competitor",
            "dimension",
            "allowed_h2_headings",
            "required_h2_headings",
            "forbidden_h2_headings",
            "repair_targets",
            "publication_issues",
            "required_heading_keys",
            "segment_batch",
            "output_language",
            "repair_sections",
            "repair_part",
            "repair_part_count",
            "segment_count",
            "shard_notes_gap",
        }
        selected = {key: value for key, value in segment.items() if key in contract_fields}
        selected["evidence_consumption_id"] = use.id
        selected["allowed_source_ids"] = list(view.source_ids)
        selected["evidence_view"] = json.loads(view.to_prompt_json())
        selected["answer_boundaries"] = [
            boundary.model_dump(mode="json")
            for boundary in build_answer_boundaries(record.detail, view)
        ]
        if segment.get("answer_intent") == "recorded_price" and view.dimension == "pricing":
            selected["answer_boundaries"] = [
                evaluate_answer_boundary(
                    view, AnswerBoundary.model_validate(boundary).requirement.model_copy(
                        update={"intent": "recorded_price", "market": None, "context_json": "{}"}
                    )
                ).model_dump(mode="json")
                for boundary in selected["answer_boundaries"]
            ]
        selected["answer_guard_instructions"] = ANSWER_GUARD_INSTRUCTIONS
        aliases = self._source_alias_map(self._evidence_live_record(record).detail)
        notes = segment.get("shard_notes", [])
        if isinstance(notes, list):
            selected_notes = []
            for note in notes:
                citations = source_tokens(note) if isinstance(note, str) else []
                source_ids = {resolve_source_token(token, aliases) for token in citations}
                if source_ids and source_ids <= set(view.source_ids):
                    selected_notes.append(note)
            if selected_notes:
                selected["shard_notes"] = selected_notes
            if len(selected_notes) < len(notes):
                selected["shard_notes_gap"] = "shard_note_source_unavailable"
        selected.setdefault("source_index", [])
        selected.setdefault("evidence_claims", [])
        selected.setdefault("decision_guidance", [])
        projected, gaps = self._project_evidence_detail(record, [view])
        selected_competitors = {source.competitor for source in view.sources}
        selected_dimensions = {source.dimension for source in view.sources}
        projected.plan.competitors = [
            item for item in projected.plan.competitors if item in selected_competitors
        ]
        projected.plan.dimensions = [
            item for item in projected.plan.dimensions if item in selected_dimensions
        ]
        projected.competitor_knowledge = {
            key: value
            for key, value in projected.competitor_knowledge.items()
            if key in selected_competitors
        }
        projected.competitor_kbs = {
            key: value
            for key, value in projected.competitor_kbs.items()
            if key in selected_competitors
        }
        if projected.comparison_matrix:
            projected.comparison_matrix.cells = [
                cell
                for cell in projected.comparison_matrix.cells
                if cell.competitor in selected_competitors
                and cell.dimension in selected_dimensions
                and set(cell.source_ids) <= set(view.source_ids)
            ]
            projected.comparison_matrix.summary = []
        from packages.agents.writer.evidence_pack import build_writer_evidence_pack

        brief = json.loads(build_writer_evidence_pack(projected).to_report_brief_prompt_json())
        brief["writer_constraints"] = [
            text.replace("allowed_source_ids", "citation source IDs")
            for text in brief.get("writer_constraints", [])
        ]
        analysis = [
            self._analyst_evidence_artifact_payload(projected, product, dimension)
            for product in projected.plan.competitors
            for dimension in projected.plan.dimensions
            if any(
                source.competitor == product and source.dimension == dimension
                for source in view.sources
            )
        ]
        if gaps:
            selected["analysis_dependency_gaps"] = gaps
        # Include every control, source ID, note and gap in the actual JSON budget.
        candidate = {
            **selected,
            "analysis": analysis,
            "report_brief": brief,
        }
        if len(self._writer_evidence_context_json(candidate).encode("utf-8")) <= use.max_bytes:
            selected["analysis"] = analysis
            selected["report_brief"] = brief
        elif analysis:
            selected["analysis_gap"] = "analysis_context_budget_exceeded; use paired evidence facts"
        return selected
