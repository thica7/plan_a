import json
from datetime import date

import pytest
from test_answer_guard_workflow import fixture_detail
from test_stage_evidence_views import FixedTime

from packages.research.evidence.answer_guard import evaluate_answer_boundary
from packages.research.evidence.answer_models import AnswerRequirement
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.views import select_evidence_view


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)


def price_view():
    detail = fixture_detail()
    row = detail.raw_sources[0].metadata["normalized_fields"][0]
    row["qualifiers"].update(billing_interval="unknown", tax_scope="unknown")
    row["billing_cycle"] = "unknown"
    row["market"] = None
    detail.raw_sources[0].metadata.pop("market", None)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    return select_evidence_view(snapshot, agent="writer", max_bytes=8192)


def test_recorded_price_shows_observation_without_unlocking_current_price():
    view = price_view()
    requirement = AnswerRequirement(competitor="Product A", dimension="pricing", intent="recorded_price", as_of=date(2026, 10, 3))
    boundary = evaluate_answer_boundary(view, requirement)
    assert boundary.status == "partial"
    assert any(f.field == "price" and f.id in boundary.allowed_fact_ids for f in view.facts)
    assert {"market", "billing_interval", "tax_scope"} <= set(boundary.missing_fields)
    current = evaluate_answer_boundary(view, requirement.model_copy(update={"intent": "current_price"}))
    money_ids = {f.id for f in view.facts if f.field == "price"}
    assert not money_ids.intersection(current.allowed_fact_ids)


@pytest.mark.parametrize("mutation", ["stale", "non_original", "unsupported"])
def test_recorded_price_rejects_bad_evidence(mutation):
    view = price_view()
    if mutation == "stale":
        as_of = date(2026, 10, 20)
    elif mutation == "non_original":
        view = view.model_copy(update={"sources": tuple(s.model_copy(update={"material_level": "summary"}) for s in view.sources)})
        as_of = date(2026, 10, 3)
    else:
        view = view.model_copy(update={"facts": tuple(f.model_copy(update={"status": "unknown"}) for f in view.facts)})
        as_of = date(2026, 10, 3)
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor="Product A", dimension="pricing", intent="recorded_price", as_of=as_of))
    assert not {f.id for f in view.facts if f.field == "price"}.intersection(boundary.allowed_fact_ids)


@pytest.mark.parametrize("fault", ["unknown_fact", "wrong_product", "wrong_dimension", "wrong_source", "missing_review", "duplicate_review", "unsupported", "unearned_recommendation"])
def test_claim_audit_rejects_identity_errors_and_incomplete_review(fault):
    from packages.research.evidence.report_claims import ReportClaim, audit_report_claims

    view = price_view()
    fact = next(f for f in view.facts if f.field == "price")
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor="Product A", dimension="pricing", intent="recorded_price", as_of=date(2026, 10, 3)))
    values = dict(id="c1", text="页面采集报价为 3999 CNY。", kind="fact", competitor="Product A", dimension="pricing", fact_ids=[fact.id], source_ids=[fact.source_id])
    if fault == "unknown_fact":
        values["fact_ids"] = ["unseen"]
    if fault == "wrong_product":
        values["competitor"] = "Product B"
    if fault == "wrong_dimension":
        values["dimension"] = "feature"
    if fault == "wrong_source":
        values["source_ids"] = ["other-source"]
    if fault == "unearned_recommendation":
        values["text"] = "该产品适合预算敏感的小团队。"
    reviews = [{"claim_id": "c1", "verdict": "supported", "reason": "Original quote supports the observation."}]
    if fault == "missing_review":
        reviews = []
    if fault == "duplicate_review":
        reviews *= 2
    if fault == "unsupported":
        reviews[0]["verdict"] = "unsupported"
    audited = audit_report_claims([ReportClaim(**values)], reviews, view, [boundary])
    assert audited[0].status != "supported"


def test_claim_audit_accepts_a_cited_recorded_price_with_partial_conditions():
    from packages.research.evidence.report_claims import ReportClaim, audit_report_claims

    view = price_view()
    fact = next(f for f in view.facts if f.field == "price")
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor="Product A", dimension="pricing", intent="recorded_price", as_of=date(2026, 10, 3)))
    claim = ReportClaim(id="c1", text="页面采集报价为 3999 CNY。", kind="fact", competitor="Product A", dimension="pricing", fact_ids=[fact.id], source_ids=[fact.source_id])
    result = audit_report_claims([claim], [{"claim_id": "c1", "verdict": "supported", "reason": "Amount and currency match the dated observation."}], view, [boundary])
    assert result[0].status == "supported"


@pytest.mark.parametrize('interval,expected', [('annual', ()), ('monthly', ('unverified_billing_interval',)), ('unknown', ('unverified_billing_interval',))])
def test_price_claim_checks_its_own_billing_condition(interval, expected):
    from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons
    view = price_view()
    boundary = evaluate_answer_boundary(view, AnswerRequirement(
        competitor='Product A', dimension='pricing', intent='recorded_price', as_of=date(2026, 10, 3)))
    fact = next(f for f in view.facts if f.field == 'price')
    fact = fact.model_copy(update={'qualifiers_json': json.dumps({**fact.qualifiers, 'billing_interval': interval})})
    view = view.model_copy(update={'facts': tuple(fact if f.id == fact.id else f for f in view.facts)})
    claim = ReportClaim(id='bound-billing', text='页面采集标价为 3999 CNY，年付。', kind='fact',
        competitor='Product A', dimension='pricing', fact_ids=[fact.id], source_ids=[fact.source_id])
    assert claim_rule_reasons(claim, view, [boundary]) == expected


@pytest.mark.parametrize("text", ["页面采集报价为 4999 CNY。", "采集价为 3999 CNY，支持月付且含税。", "每月完整账单为 3999 CNY。", "当前适用报价为 3999 CNY。", "中国大陆适用报价为 3999 CNY，面向所有席位类型。", "Current applicable quote is 3999 CNY."])
def test_recorded_quote_cannot_be_expanded_even_if_reviewer_says_supported(text):
    from packages.research.evidence.report_claims import ReportClaim, audit_report_claims

    view = price_view()
    fact = next(f for f in view.facts if f.field == "price")
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor="Product A", dimension="pricing", intent="recorded_price", as_of=date(2026, 10, 3)))
    claim = ReportClaim(id="c1", text=text, kind="fact", competitor="Product A", dimension="pricing", fact_ids=[fact.id], source_ids=[fact.source_id])
    result = audit_report_claims([claim], [{"claim_id": "c1", "verdict": "supported", "reason": "Mistaken reviewer verdict."}], view, [boundary])
    assert result[0].status != "supported"


def test_recorded_price_permission_cannot_authorize_an_unmarked_current_price_assertion():
    from types import SimpleNamespace
    from packages.orchestrator.answer_context import _amount_issues, _money_pattern

    view = price_view()
    requirement = AnswerRequirement(competitor="Product A", dimension="pricing", intent="recorded_price", as_of=date(2026, 10, 3))
    boundary = evaluate_answer_boundary(view, requirement)
    facts = {f.id: f for f in view.facts}
    service = SimpleNamespace(_evidence_artifact_hash=lambda value: "hash")
    issues = _amount_issues(service, SimpleNamespace(id=view.snapshot_id), "当前适用报价为 3999 CNY。", "report.line.1", [boundary], facts, set(view.source_ids), _money_pattern(facts))
    assert issues


def test_recorded_price_label_does_not_override_a_conflicting_applicable_price_assertion():
    from types import SimpleNamespace
    from packages.orchestrator.answer_context import _amount_issues, _money_pattern

    view = price_view()
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor="Product A", dimension="pricing", intent="recorded_price", as_of=date(2026, 10, 3)))
    facts = {f.id: f for f in view.facts}
    service = SimpleNamespace(_evidence_artifact_hash=lambda value: "hash")
    text = "页面采集标价（不代表适用报价）：当前适用报价为 3999 CNY。"
    assert _amount_issues(service, SimpleNamespace(id=view.snapshot_id), text, "report.line.1", [boundary], facts, set(view.source_ids), _money_pattern(facts))


def test_feature_claim_cannot_use_support_metadata_in_place_of_full_content():
    from test_stage_evidence_views import distributed_detail
    from packages.research.evidence.report_claims import ReportClaim, audit_report_claims

    view = select_evidence_view(seal_snapshot(distributed_detail(observations=1), phase="analysis", canonical_documents={}), agent="writer", competitor="Notion", dimension="feature", max_bytes=8192)
    fact = next(f for f in view.facts if f.field == "support_level")
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor="Notion", dimension="feature", as_of=date(2026, 10, 3)))
    claim = ReportClaim(id="c1", text="Notion支持评论功能。", kind="fact", competitor="Notion", dimension="feature", fact_ids=[fact.id], source_ids=[fact.source_id])
    audited = audit_report_claims([claim], [{"claim_id":"c1", "verdict":"supported", "reason":"Incorrectly relied on metadata."}], view, [boundary])
    assert audited[0].status != "supported"


@pytest.mark.parametrize('text,expected', [
    ('最多29名团队成员可同时编辑。', False),
    ('最多29人可以编辑同一页面。', False),
    ('最多29人可进行协作编辑。', False),
    ('你和最多29名队友可同时编辑页面，总共最多29人。', False),
    ('你和最多29名队友可同时编辑页面，总共29名成员。', False),
    ('你和最多29名队友可同时编辑页面，最多29位编辑者。', False),
    ('You and up to 29 teammates can edit together, a total of 29 people.', False),
    ('Confluence supports simultaneous editing with a maximum of 29 editors.', False),
    ('支持多人同时编辑页面。', False),
    ('你和最多29名队友可同时编辑页面。', True),
    ('包括你在内，最多30人可同时编辑页面。', True),
    ('You and up to 29 teammates can edit a page together in real time.', True),
])
def test_additive_teammate_limit_survives_a_mistaken_supported_review(text, expected):
    from test_stage_evidence_views import distributed_detail
    from packages.research.evidence.report_claims import ReportClaim, audit_report_claims
    view = select_evidence_view(seal_snapshot(distributed_detail(observations=1), phase='analysis', canonical_documents={}),
        agent='writer', competitor='Notion', dimension='feature', max_bytes=8192)
    fact = next(f for f in view.facts if f.field == 'evidence_terms')
    quote = 'You and up to 29 teammates can edit a page together in real time.'
    fact = fact.model_copy(update={'quote': quote, 'value_json': json.dumps([quote])})
    view = view.model_copy(update={'facts': tuple(fact if f.id == fact.id else f for f in view.facts)})
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor='Notion', dimension='feature', as_of=date(2026, 10, 3)))
    claim = ReportClaim(id='count', text=text, kind='fact', competitor='Notion', dimension='feature', fact_ids=[fact.id], source_ids=[fact.source_id])
    audited = audit_report_claims([claim], [{'claim_id': 'count', 'verdict': 'supported', 'reason': 'Mistaken reviewer verdict.'}], view, [boundary])
    assert (audited[0].status == 'supported') == expected


def test_feature_claim_cannot_merge_multiple_content_observations():
    from test_stage_evidence_views import distributed_detail
    from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons
    view = select_evidence_view(seal_snapshot(distributed_detail(observations=2), phase='analysis', canonical_documents={}),
        agent='writer', competitor='Notion', dimension='feature', max_bytes=16384)
    facts = [f for f in view.facts if f.field == 'evidence_terms'][:2]
    assert len(facts) == 2
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor='Notion', dimension='feature', as_of=date(2026, 10, 3)))
    claim = ReportClaim(id='combined', text='支持评论和编辑功能。', kind='fact', competitor='Notion', dimension='feature',
        fact_ids=[f.id for f in facts], source_ids=list({f.source_id for f in facts}))
    assert 'feature_claim_multiple_observations' in claim_rule_reasons(claim, view, [boundary])


def test_feature_claim_cannot_borrow_another_observation_through_support_metadata():
    from test_stage_evidence_views import distributed_detail
    from packages.research.evidence.report_claims import ReportClaim, audit_report_claims
    view = select_evidence_view(seal_snapshot(distributed_detail(observations=2), phase='analysis', canonical_documents={}),
        agent='writer', competitor='Notion', dimension='feature', max_bytes=16384)
    content = next(f for f in view.facts if f.field == 'evidence_terms')
    other = next(f for f in view.facts if f.field == 'support_level' and f.evidence_item_ids != content.evidence_item_ids)
    quote = 'You and up to 29 teammates can edit a page together in real time.'
    other = other.model_copy(update={'quote': quote})
    view = view.model_copy(update={'facts': tuple(other if f.id == other.id else f for f in view.facts)})
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor='Notion', dimension='feature', as_of=date(2026, 10, 3)))
    claim = ReportClaim(id='borrowed', text='支持评论与最多29人实时协作编辑。', kind='fact', competitor='Notion', dimension='feature',
        fact_ids=[content.id, other.id], source_ids=list({content.source_id, other.source_id}))
    result = audit_report_claims([claim], [{'claim_id': 'borrowed', 'verdict': 'supported', 'reason': 'Mistaken verdict.'}], view, [boundary])
    assert result[0].status != 'supported'
    assert 'feature_claim_multiple_observations' in result[0].rule_reasons


@pytest.mark.parametrize('url,expected', [
    ('https://superhuman.com/docs/use-cases/collaborative-docs', True),
    ('https://superhuman.com/plans/mail', False),
    ('https://untrusted.example/docs', False),
])
def test_review_identity_context_is_bound_to_a_curated_docs_source(url, expected):
    from test_stage_evidence_views import distributed_detail
    from packages.research.evidence.report_claims import ReportClaim
    from packages.agents.writer.dimension_writer import review_payload
    view = select_evidence_view(seal_snapshot(distributed_detail(observations=1), phase='analysis', canonical_documents={}),
        agent='writer', competitor='Coda', dimension='feature', max_bytes=8192)
    view = view.model_copy(update={'sources': tuple(s.model_copy(update={'url': url}) for s in view.sources)})
    fact = next(f for f in view.facts if f.field == 'evidence_terms')
    claim = ReportClaim(id='docs', text='支持评论功能。', kind='fact', competitor='Coda', dimension='feature',
        fact_ids=[fact.id], source_ids=[fact.source_id])
    payload = review_payload([claim], view)
    assert bool(payload.get('document_product_bindings')) == expected
    if expected:
        assert payload['document_product_bindings'] == [{'source_id': fact.source_id, 'competitor': 'Coda',
            'document_product': 'Superhuman Docs'}]


@pytest.mark.parametrize("text", ["Free 计划包含推动团队前进的功能。", "Standard includes more features to empower growing teams."])
def test_feature_marketing_is_not_a_concrete_observation_even_with_a_supported_review(text):
    from test_stage_evidence_views import distributed_detail
    from packages.research.evidence.report_claims import ReportClaim, audit_report_claims

    view = select_evidence_view(seal_snapshot(distributed_detail(observations=1), phase="analysis", canonical_documents={}), agent="writer", competitor="Notion", dimension="feature", max_bytes=8192)
    fact = next(f for f in view.facts if f.field == "evidence_terms")
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor="Notion", dimension="feature", as_of=date(2026, 10, 3)))
    claim = ReportClaim(id="c1", text=text, kind="fact", competitor="Notion", dimension="feature", fact_ids=[fact.id], source_ids=[fact.source_id])
    audited = audit_report_claims([claim], [{"claim_id":"c1", "verdict":"supported", "reason":"Slogan was directly quoted."}], view, [boundary])
    assert audited[0].status != "supported"
    assert "promotional_claim_not_concrete" in audited[0].rule_reasons


def test_price_review_retains_bound_price_and_all_conditions_without_repeating_unbound_metadata():
    from packages.research.evidence.report_claims import ReportClaim
    from packages.agents.writer.dimension_writer import review_payload
    view = price_view()
    fact = next(f for f in view.facts if f.field == 'price')
    claim = ReportClaim(id='price-context', text='页面采集报价为 3999 CNY。', kind='fact', competitor='Product A',
        dimension='pricing', fact_ids=[fact.id], source_ids=[fact.source_id])
    payload = review_payload([claim], view)
    assert [f['id'] for f in payload['facts']] == [fact.id]
    assert payload['facts'][0]['qualifiers'] == fact.qualifiers
    assert payload['quotes'][0]['text'] == fact.quote


def test_review_payload_contains_complete_observation_conditions():
    from test_stage_evidence_views import distributed_detail
    from packages.research.evidence.report_claims import ReportClaim
    from packages.agents.writer.dimension_writer import review_payload

    view = select_evidence_view(seal_snapshot(distributed_detail(observations=1), phase="analysis", canonical_documents={}), agent="writer", competitor="Notion", dimension="feature", max_bytes=8192)
    fact = next(f for f in view.facts if f.field == "support_level")
    terms = next(f for f in view.facts if f.field == "evidence_terms" and f.evidence_item_ids == fact.evidence_item_ids)
    changed = terms.model_copy(update={"value_json": '["Comments are unavailable in this workspace."]'})
    view = view.model_copy(update={"facts": tuple(changed if f.id == terms.id else f for f in view.facts)})
    claim = ReportClaim(id="c1", text="支持评论功能。", kind="fact", competitor="Notion", dimension="feature", fact_ids=[fact.id], source_ids=[fact.source_id])
    payload = review_payload([claim], view)
    assert any(f["id"] == terms.id for f in payload["facts"])
    assert "unavailable" in str(payload)


def test_review_payload_does_not_merge_distinct_quotes_from_one_evidence_item():
    from packages.research.evidence.report_claims import ReportClaim
    from packages.agents.writer.dimension_writer import review_payload

    view = price_view()
    fact = next(f for f in view.facts if f.field == "price")
    other = fact.model_copy(update={"id": "other-observation", "quote": "Unrelated plan costs $20."})
    view = view.model_copy(update={"facts": (*view.facts, other)})
    claim = ReportClaim(id="c1", text="页面采集报价为 3999 CNY。", kind="fact", competitor=fact.competitor,
                        dimension="pricing", fact_ids=[fact.id], source_ids=[fact.source_id])
    payload = review_payload([claim], view)
    assert any(f["id"] == fact.id for f in payload["facts"])
    assert all(f["id"] != other.id for f in payload["facts"])


def test_recorded_price_claims_preserve_all_selected_amounts_without_model_rewriting():
    from packages.agents.writer.dimension_writer import recorded_price_claims

    view = price_view()
    fact = next(f for f in view.facts if f.field == "price")
    prices = tuple(fact.model_copy(update={"id": f"price-{plan}", "value_json": json.dumps({"amount": amount, "currency": "USD"}), "qualifiers_json": json.dumps(
        dict(fact.qualifiers, plan=plan, amount=amount, currency="USD", amount_basis="member", amount_period="monthly")),
        "quote": f"{plan} ${amount} per member / month"}) for plan, amount in (("Free", 0), ("Plus", 10), ("Business", 20)))
    view = view.model_copy(update={"facts": prices, "fact_ids": tuple(f.id for f in prices)})
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor="Product A", dimension="pricing", intent="recorded_price", as_of=date(2026, 10, 3)))
    claims = recorded_price_claims(view, [boundary], "use-price", "zh-CN")
    assert len(claims) == 3
    assert all(c.kind == "fact" and len(c.fact_ids) == 1 for c in claims)
    assert "Free" in claims[0].text and "0 USD" in claims[0].text
    assert "Plus" in claims[1].text and "10 USD" in claims[1].text
    assert "Business" in claims[2].text and "20 USD" in claims[2].text
    assert all("每位成员每月" in c.text and "月付" not in c.text and "billing_" not in c.text for c in claims)


def test_row_only_comment_rule_cannot_be_published_as_all_product_comments():
    from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons
    from types import SimpleNamespace
    from test_capability_alignment import fact
    from packages.research.evidence.operations import structured_operations
    from packages.research.evidence.snapshot_models import canonical_json
    quote = 'You can only leave comments on an entire row.'
    original = fact('Coda', quote, slot='row-comments')
    original = original.model_copy(update={'qualifiers_json': canonical_json({'operations': structured_operations(quote, [quote], 'Coda')})})
    view = SimpleNamespace(facts=(original,))
    boundaries = [SimpleNamespace(allowed_fact_ids=(original.id,))]
    base = dict(id='row-claim', kind='fact', competitor='Coda', dimension='feature', fact_ids=[original.id], source_ids=[original.source_id])
    broad = ReportClaim(text='在 Coda 中，评论只能针对整行进行。', **base)
    scoped = ReportClaim(text='在 Coda 的表格中，行评论只能针对整行进行。', **base)
    assert 'operation_object_scope_omitted' in claim_rule_reasons(broad, view, boundaries)
    assert 'operation_object_scope_omitted' not in claim_rule_reasons(scoped, view, boundaries)


@pytest.mark.parametrize('text', [
    '在 Coda 中，所有评论（包括表格评论）都只能针对整行进行。',
    'All comments in Coda, including table comments, can only target an entire row.',
])
def test_table_mention_does_not_exempt_global_comment_generalization(text):
    from types import SimpleNamespace
    from test_capability_alignment import fact
    from packages.research.evidence.report_claims import ReportClaim, ClaimReview, audit_report_claims
    from packages.research.evidence.operations import structured_operations
    from packages.research.evidence.snapshot_models import canonical_json
    quote = 'You can only leave comments on an entire row.'
    original = fact('Coda', quote, slot='row-comments')
    original = original.model_copy(update={'qualifiers_json': canonical_json({'operations': structured_operations(quote, [quote], 'Coda')})})
    claim = ReportClaim(id='universal-row', text=text, kind='fact', competitor='Coda', dimension='feature',
                       fact_ids=[original.id], source_ids=[original.source_id])
    review = ClaimReview(claim_id=claim.id, verdict='supported', reason='Mock semantic reviewer accepts it.')
    result = audit_report_claims([claim], [review], SimpleNamespace(facts=(original,)),
                               [SimpleNamespace(allowed_fact_ids=(original.id,))])[0]
    assert result.status == 'rejected' and 'operation_object_scope_omitted' in result.rule_reasons
