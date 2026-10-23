"""Real Writer/QA replay with fixed model transport, not a semantic accuracy test."""

import json
from claim_review_fixture import answer_response
from claim_review_fixture import expand_prompt_payload, question_plan_response, supported_review

import pytest
from unittest.mock import patch
from pydantic import HttpUrl, TypeAdapter
from test_stage_evidence_views import distributed_detail, FixedTime
from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService, RunRecord
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.views import select_evidence_view
from packages.schema.models import DecisionBrief
from packages.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_final_qa_replays_question_filtered_generation_view():
    with patch("packages.research.evidence.views.datetime", FixedTime):
        picked = None
        for size in (800,):
            d = distributed_detail(observations=1)
            d.plan.competitors = ["Notion"]
            d.plan.dimensions = ["feature"]
            d.plan.research_depth = "quick"
            d.topic = "协作工具调研"
            d.execution_mode = "real"
            d.plan.decision_brief = DecisionBrief(decision_question="Notion: Must Guests sign in?")
            d.raw_sources = [s for s in d.raw_sources if s.competitor == "Notion"]
            s = d.raw_sources[0]
            s.url = TypeAdapter(HttpUrl).validate_python(s.url)
            common = {
                "kind": "feature",
                "competitor": "Notion",
                "dimension": "feature",
                "support_level": "documented",
                "confidence": 0.9,
            }
            login = "Guests must sign in before starting a session."
            edit = "Editors can edit documents shared with them."
            s.metadata["normalized_fields"] = [
                dict(
                    common,
                    slot="edit",
                    evidence_item_ids=["edit"],
                    evidence_quote=edit,
                    evidence_terms=[edit, "Verified context " + ("context " * size)],
                ),
                dict(
                    common,
                    slot="login",
                    evidence_item_ids=["login"],
                    evidence_quote=login,
                    evidence_terms=[login, "Verified context " + ("context " * (size + 200))],
                ),
            ]
            snap = seal_snapshot(d, phase="analysis", canonical_documents={})
            loginfact = next(
                f for f in snap.facts if f.field == "evidence_terms" and f.quote == login
            )
            generic = select_evidence_view(
                snap,
                agent="writer",
                competitor="Notion",
                dimension="feature",
                source_ids=[s.id],
                max_bytes=16384,
            )
            filtered = select_evidence_view(
                snap,
                agent="writer",
                competitor="Notion",
                dimension="feature",
                source_ids=[s.id],
                fact_ids=[loginfact.id],
                max_bytes=16384,
            )
            if loginfact.id not in generic.fact_ids and loginfact.id in filtered.fact_ids:
                picked = d, snap, generic, filtered, loginfact, size
                break
        assert picked, "could not locate bounded divergent selection"
        d, snap, generic, filtered, loginfact, size = picked
        service = RunService(
            SkillRegistry.from_default_path(),
            Settings(demo_mode=True, writer_task_execution_enabled=False),
            journal=RunJournal.in_memory(),
            kb_cache=KBCache.in_memory(),
            graph_checkpointer=GraphCheckpointer.in_memory(),
        )
        record = RunRecord(d)
        service._runs[d.id] = record

        async def response(record, **kw):
            payload = expand_prompt_payload(json.loads(kw["user"].split("\nJSON:\n", 1)[1]))
            if kw["name"] == "dimension_claim_writer":
                rows = payload["evidence_view"]["facts"]
                row = next(r for r in rows if r["id"] == loginfact.id)
                return question_plan_response(payload, [
                            dict(
                                text=login,
                                kind="fact",
                                competitor="Notion",
                                dimension="feature",
                                fact_ids=[row["id"]],
                                source_ids=[row["source_id"]],
                            )
                        ])
            if kw["name"] == "dimension_claim_review":
                return json.dumps(
                    {
                        "reviews": [
                            supported_review(c)
                            for c in payload["claims"]
                        ]
                    }
                )
            if kw["name"] in {"dimension_answer_coverage", "dimension_answer_review"}:
                return answer_response(payload,
                    {
                        "version": 3,
                        "answers": [
                            dict(
                                question_id=q["question_id"],
                                status="answered",
                                claim_ids=[c["id"] for c in payload["claims"]],
                                reason="The login requirement is answered.",
                                resolution="direct", conclusion="yes",
                                missing_fields=[],
                            )
                            for q in payload["questions"]
                        ]
                    }
                )
            raise AssertionError(kw["name"])

        with patch.object(service, "_trace_llm_text", response):
            await service._real_writer_step(record)
        producer = service._final_qa_producer_verified(record, snap)
        issues = audit_dimension_claims(service, record, snap, producer_verified=producer)
        assert producer
        assert any(c.status == "supported" for a in d.report_dimension_audits for c in a.claims)
        assert not issues, "final QA reconstructed a different generation view"
        from packages.orchestrator.answer_context import audit_answer_boundaries

        boundary_issues = audit_answer_boundaries(
            service, record, snap, producer_verified=producer, aliases={s.id: s.id}
        )
        assert not boundary_issues, "answer boundaries must replay the same selected facts"
