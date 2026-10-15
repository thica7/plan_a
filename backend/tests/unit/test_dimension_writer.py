import asyncio
import json
from types import SimpleNamespace
from pydantic import TypeAdapter, HttpUrl

import pytest
from test_report_claim_audit import price_view
from test_stage_evidence_views import FixedTime, distributed_detail

from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.llm.doubao_client import LLMUsage
from packages.llm.errors import LLMExecutionLimitError
from packages.research.evidence.snapshot import seal_snapshot
from packages.skills.registry import SkillRegistry
from packages.schema.models import DecisionBrief, QCIssue, RedoScope


def test_recorded_docs_price_preserves_maker_unit_and_annual_commitment(monkeypatch):
    from datetime import date
    from packages.agents.writer.dimension_writer import recorded_price_claims
    from packages.research.evidence.answer_guard import evaluate_answer_boundary
    from packages.research.evidence.answer_models import AnswerRequirement
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    view = price_view()
    view = view.model_copy(update={'facts': tuple(f.model_copy(update={
        'qualifiers_json': json.dumps({**f.qualifiers, 'amount_basis': 'doc_maker', 'amount_period': 'monthly', 'billing_interval': 'annual'}),
    }) for f in view.facts)})
    boundary = evaluate_answer_boundary(view, AnswerRequirement(
        competitor='Product A', dimension='pricing', intent='recorded_price', as_of=date(2026, 10, 3)))
    claims = recorded_price_claims(view, [boundary], 'doc-price-use', 'zh-CN')
    assert len(claims) == 1
    assert '每位 Doc Maker 每月' in claims[0].text
    assert '年付' in claims[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["valid", "bad_review", "missing_review", "review_unavailable", "bad_draft"])
@pytest.mark.parametrize('depth', ['quick', 'standard', 'deep'])
async def test_real_quick_report_writes_dimensions_and_audits_every_published_claim(monkeypatch, mode, depth):
    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    detail = distributed_detail(observations=2)
    detail.topic = '权限和评论操作比较'
    detail.plan.research_depth = depth
    for s in detail.raw_sources:
        s.url = TypeAdapter(HttpUrl).validate_python(s.url)
    detail.plan.dimensions = ["feature", "pricing"]
    detail.plan.decision_brief = DecisionBrief(primary_job="共同维护团队知识", success_metric="能说明证据与缺口")
    source = price_view().sources[0].to_raw_source()
    source.competitor = "Notion"
    source.covered_competitors = ["Notion"]
    for row in source.metadata["normalized_fields"]:
        row["competitor"] = "Notion"
    detail.raw_sources.append(source)
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True), journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    calls = []
    async def model(record, **kwargs):
        calls.append(kwargs)
        payload = json.loads(kwargs["user"].split("\nJSON:\n", 1)[1])
        if kwargs["name"] == "dimension_claim_review":
            if mode == "review_unavailable" and kwargs["subagent"].startswith("Confluence/"):
                raise RuntimeError("Reviewer transport unavailable")
            if mode == "bad_review":
                return "not JSON"
            if mode == "missing_review":
                return json.dumps({"reviews": []})
            return json.dumps({"reviews": [{"claim_id": c["id"], "verdict": "supported", "reason": "The quoted source directly supports this observation."} for c in payload["claims"]]})
        facts = payload["evidence_view"]["facts"]
        if mode == "bad_draft":
            return "not JSON"
        product, dimension = payload["segment_competitor"], payload["dimension"]
        fact = next(f for f in facts if f["field"] == ("price" if dimension == "pricing" else "evidence_terms"))
        text = "页面采集报价为 3999 CNY。" if dimension == "pricing" else "支持对共享页面进行评论，需成为工作区成员。"
        return json.dumps({"claims": [{"text": text, "kind": "fact", "competitor": product, "dimension": dimension, "fact_ids": [fact["id"]], "source_ids": [fact["source_id"]], "operation_binding": fact.get("operation_observations", [None])[0]}]})
    monkeypatch.setattr(service, "_trace_llm_text", model)
    report = await service._writer_markdown_report_from_evidence_pack(record, SimpleNamespace(metrics=SimpleNamespace(segmented_writer_required=False)), 20)
    assert "## 价格" in report
    assert ("3999 CNY" in report) == (mode in {"valid", "review_unavailable", "bad_draft"})
    assert all(product in report for product in detail.plan.competitors)
    assert "付款周期" in report and "税费" in report
    from packages.agents.writer.quality_preflight import run_writer_quality_preflight
    assert run_writer_quality_preflight(detail, report).passed == (mode not in {"bad_review", "missing_review"})
    writes = [c for c in calls if c["name"] == "dimension_claim_writer"]
    assert all(c['max_output_tokens'] == 1600 for c in calls)
    assert len(writes) == 3  # Admitted prices use deterministic drafts; empty branches make no call.
    assert len(calls) == (4 if mode == "bad_draft" else 7)
    assert len(detail.report_dimension_audits) == 6
    assert all(use.estimated_bytes <= use.max_bytes for use in detail.evidence_consumptions)
    assert all(len(c["user"].split("\nJSON:\n", 1)[1].encode()) <= 8192 for c in calls)
    if mode in {"bad_review", "missing_review"}:
        assert all(c.status != "supported" for a in detail.report_dimension_audits for c in a.claims)
    if mode == "bad_draft":
        assert all(c.status != "supported" for a in detail.report_dimension_audits if a.dimension == "feature" for c in a.claims)
    if mode == "review_unavailable":
        assert any(c.status == "supported" for a in detail.report_dimension_audits if a.competitor == "Coda" for c in a.claims)
        assert all(c.status != "supported" for a in detail.report_dimension_audits if a.competitor == "Confluence" for c in a.claims)
    detail.report_md = report
    service._record_evidence_artifact(record, kind="writer", uses=detail.evidence_consumptions, payload=service._writer_evidence_artifact_payload(detail))
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    assert not audit_dimension_claims(service, record, service._current_evidence_snapshot(record), producer_verified=True)
    original = service._writer_evidence_artifact_payload(detail)
    detail.report_md += "\nNew unreviewed sentence."
    assert not service._evidence_artifact_valid(record, kind="writer", payload=service._writer_evidence_artifact_payload(detail))
    detail.report_md = report
    if mode == "valid":
        detail.report_md = report.replace("3999 CNY", "4999 CNY")
        issues = audit_dimension_claims(service, record, service._current_evidence_snapshot(record), producer_verified=True)
        assert any(issue.metadata.get("claim_audit_reason") == "published_claim_missing_or_changed" for issue in issues)
    assert original["dimension_audits"]
    if mode == "valid":
        detail.report_md = report
        await service._real_writer_step(record)
        assert detail.report_dimension_audits
        assert '## 竞品深挖' not in detail.report_md
        assert '## 横向决策矩阵' not in detail.report_md
        before = len(calls)
        issue = QCIssue(id="thin-section", severity="warn", detected_by="text_quality", target_agent="writer",
            field_path="report_quality.core_section_depth_score", problem="Competitive Findings section is too thin.",
            redo_scope=RedoScope(kind="writer_only", rationale="Improve the findings section."))
        service._append_agent_message(record, from_agent="qa", to_agent="writer", message_type="redo_request",
            payload_schema="RedoRequestPayload", payload={"issues":[issue.model_dump(mode="json")], "issue_ids":[issue.id], "redo_scope":issue.redo_scope.model_dump(mode="json")})
        await service._real_writer_step(record)
        assert detail.report_dimension_audits
        assert all(c["name"] in {"dimension_claim_writer", "dimension_claim_review"} for c in calls[before:])
        _, issues, _ = await service._final_qa_evidence(record)
        assert not issues


@pytest.mark.parametrize("long_quotes", [False, True])
def test_price_segment_preserves_three_observations_with_shared_exact_qualifiers(monkeypatch, long_quotes):
    from copy import deepcopy
    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ["Notion"]
    detail.plan.dimensions = ["feature", "pricing"]
    detail.raw_sources = [s for s in detail.raw_sources if s.competitor == "Notion"]
    source = price_view().sources[0].to_raw_source()
    source.competitor = "Notion"
    source.covered_competitors = ["Notion"]
    template = source.metadata["normalized_fields"][0]
    rows = []
    for plan, amount in (("Free", 0), ("Plus", 10), ("Business", 20)):
        row = deepcopy(template)
        row.update(competitor="Notion", tier_name=plan, price=amount, unit="USD", source_quote=f"{plan} ${amount} per member / month", evidence_item_ids=[f"price-{plan}"])
        if long_quotes:
            row["source_quote"] = "Original page context. " * (8 + len(rows) * 14) + row["source_quote"]
        row["qualifiers"].update(amount=amount, currency="USD", plan=plan, price_basis="subscription", price_type="official_current", price_scope="listed_unit", amount_basis="member", amount_period="monthly", source_note="Confirmed original page observation. " * 4)
        rows.append(row)
    source.metadata["normalized_fields"] = rows
    detail.raw_sources.append(source)
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True), journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    selected, use = service._writer_segment_evidence(record, dict(segment_name="price", segment_competitor="Notion", dimension="pricing", answer_intent="recorded_price", allowed_source_ids=[source.id]))
    prices = [f for f in selected["evidence_view"]["facts"] if f["field"] == "price"]
    assert {f["value"] for f in prices} == {0, 10, 20}
    assert len(service._writer_evidence_context_json(selected).encode()) <= use.max_bytes


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [EvidenceUseRejectedError, asyncio.CancelledError])
async def test_dimension_writer_does_not_turn_integrity_budget_or_cancel_errors_into_gaps(monkeypatch, failure):
    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    detail = distributed_detail(observations=1)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    detail.plan.dimensions = ["feature", "pricing"]
    detail.report_md = "Previous report remains available."
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True), journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    async def unavailable(*args, **kwargs):
        raise failure("Stop publication")
    monkeypatch.setattr(service, "_trace_llm_text", unavailable)
    with pytest.raises(failure):
        await service._writer_dimension_report(record, 20)
    assert detail.report_md == "Previous report remains available."
    assert not detail.report_dimension_audits


@pytest.mark.asyncio
@pytest.mark.parametrize("changed,budget", [(False, 60), (True, 60), (False, 1)])
async def test_dimension_writer_actual_transport_keeps_usage_and_rejects_stale_or_over_budget_drafts(monkeypatch, changed, budget):
    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    detail = distributed_detail(observations=1)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    detail.plan.dimensions = ["feature", "pricing"]
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True, run_llm_max_calls=budget, run_llm_max_tokens=200000), journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    calls = []
    async def complete_text(*, system, user):
        payload = json.loads(user.split("\nJSON:\n", 1)[1])
        calls.append(payload)
        if changed:
            detail.raw_sources[0].content_hash = "changed-during-transport"
            seal_snapshot(detail, phase="analysis", canonical_documents={})
        if "claims" in payload:
            return json.dumps({"reviews": [{"claim_id": c["id"], "verdict": "supported", "reason": "Quoted content supports this observation."} for c in payload["claims"]]})
        fact = next(f for f in payload["evidence_view"]["facts"] if f["field"] == "evidence_terms")
        return json.dumps({"claims": [{"text": "支持对共享页面进行评论，需成为工作区成员。", "kind": "fact", "competitor": payload["segment_competitor"], "dimension": payload["dimension"], "fact_ids": [fact["id"]], "source_ids": [fact["source_id"]], "operation_binding": fact.get("operation_observations", [None])[0]}]})
    monkeypatch.setattr(service._llm, "complete_text", complete_text)
    monkeypatch.setattr(service._llm, "consume_last_usage", lambda: LLMUsage(prompt_tokens=117, completion_tokens=23, total_tokens=140))
    if changed:
        with pytest.raises(EvidenceUseRejectedError):
            await service._writer_dimension_report(record, 20)
        assert not detail.report_md and not detail.report_dimension_audits
    elif budget == 1:
        with pytest.raises(RuntimeError, match='compact_report_contract'):
            await service._real_writer_step(record)
        assert not detail.report_md  # An entirely unaudited report has no publishable sources.
    else:
        await service._real_writer_step(record)
        assert detail.report_md and detail.report_dimension_audits
    assert len(calls) == (0 if budget == 1 else 1 if changed else 6)
    assert detail.llm_budget_checkpoint["calls"] == len(calls)
    assert detail.llm_budget_checkpoint["tokens_charged"] == 140 * len(calls)
    assert len([s for s in detail.trace_spans if s.kind == "llm" and s.status == "ok"]) == len(calls)


@pytest.mark.asyncio
async def test_budget_exhaustion_keeps_previously_reviewed_segments_unreviewed_prices_stay_private(monkeypatch):
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.dimensions = ['feature', 'pricing']
    source = price_view().sources[0].to_raw_source()
    source.competitor = 'Notion'
    source.covered_competitors = ['Notion']
    for row in source.metadata['normalized_fields']:
        row['competitor'] = 'Notion'
    detail.raw_sources.append(source)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True),
        journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase='analysis', canonical_documents={})

    async def model(record, **kwargs):
        payload = json.loads(kwargs['user'].split('\nJSON:\n', 1)[1])
        if kwargs['subagent'] != 'Notion/feature':
            raise LLMExecutionLimitError('run_llm_token_budget_exceeded')
        if kwargs['name'] == 'dimension_claim_review':
            return json.dumps({'reviews': [{'claim_id': c['id'], 'verdict': 'supported',
                'reason': 'The quote supports the observation.'} for c in payload['claims']]})
        fact = next(f for f in payload['evidence_view']['facts'] if f['field'] == 'evidence_terms')
        return json.dumps({'claims': [{'text': '支持对共享页面进行评论，需成为工作区成员。', 'kind': 'fact',
            'competitor': 'Notion', 'dimension': 'feature', 'fact_ids': [fact['id']], 'source_ids': [fact['source_id']], 'operation_binding': fact.get('operation_observations', [None])[0]}]})

    monkeypatch.setattr(service, '_trace_llm_text', model)
    await service._real_writer_step(record)
    assert '支持对共享页面进行评论' in detail.report_md
    assert '3999 CNY' not in detail.report_md
    assert '模型额度不足，本段未完成审核' in detail.report_md
    assert len(detail.report_dimension_audits) == 6
    assert any(c.status == 'supported' for a in detail.report_dimension_audits for c in a.claims)
    assert all(c.status != 'supported' for a in detail.report_dimension_audits if a.dimension == 'pricing' for c in a.claims)


def test_one_malformed_review_does_not_discard_other_valid_claim_reviews():
    from packages.agents.writer.dimension_writer import parse_claim_reviews
    reviews, invalid = parse_claim_reviews(json.dumps({'reviews': [
        {'claim_id': 'good', 'verdict': 'supported', 'reason': 'Directly supported.'},
        {'claim_id': 'bad', 'text': 'Unexpected rewrite', 'verdict': 'supported', 'reason': 'Invalid schema.'},
    ]}))
    assert invalid and [r.claim_id for r in reviews] == ['good']
    reviews, invalid = parse_claim_reviews(json.dumps({'reviews': [
        {'claim_id': 'bad', 'verdict': 'supported', 'reason': 'Apparently valid.'},
        {'claim_id': 'bad', 'text': 'Unexpected rewrite', 'verdict': 'unsupported', 'reason': 'Collision.'},
    ]}))
    assert invalid and reviews == []


def test_review_ids_are_bound_to_this_batch_not_another_product_or_batch():
    from packages.agents.writer.dimension_writer import parse_claim_reviews
    reviews, invalid = parse_claim_reviews(json.dumps({'reviews': [
        {'claim_id': 'earlier-batch', 'verdict': 'supported', 'reason': 'Not reviewed in this payload.'},
        {'claim_id': 'current-batch', 'verdict': 'supported', 'reason': 'Reviewed in this payload.'},
    ]}), {'current-batch'})
    assert invalid and [r.claim_id for r in reviews] == ['current-batch']
