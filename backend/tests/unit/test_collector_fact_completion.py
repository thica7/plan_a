import json

import pytest
from test_run_evidence_snapshot import make_detail

from packages.agents import SubagentContext
from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.coverage_contract import evaluate_coverage_contract
from packages.research.models import CapturedPage, EvidenceItem, ResearchBrief, SourceCandidate
from packages.skills.registry import SkillRegistry
from packages.tools.evidence_fetch import EvidenceFetchResult
from packages.schema.api_dto import CollectorResearchUsage


def pricing_fixture(field="price_points", value=None, wrong_candidate=False):
    brief = ResearchBrief(
        run_id="offline",
        topic="Billing",
        competitor="A",
        dimension="pricing",
        homepage_hint="https://a.example",
    )
    candidate = SourceCandidate(
        title="A Pricing",
        url="https://a.example/pricing",
        origin="homepage_derived",
        competitor="A",
        dimension="pricing",
    )
    page = CapturedPage(
        candidate_id=candidate.id,
        requested_url=candidate.url,
        final_url=candidate.url,
        status="ok",
        content_hash="fixed",
        title="A Pricing",
        text="A Pro $20 per seat monthly.",
        quality_score=1,
    )
    item = EvidenceItem(
        competitor="A",
        dimension="pricing",
        field=field,
        value=value if value is not None else ["$20"],
        source_candidate_id="wrong" if wrong_candidate else candidate.id,
        captured_page_id=page.id,
        source_url=page.final_url,
        quote=page.text,
        status="accepted",
        confidence=0.9,
    )
    return brief, candidate, page, item


@pytest.mark.parametrize(
    "field,value,wrong_candidate",
    [
        ("billing_cycle", "monthly", False),
        ("price_points", [], False),
        ("price_points", ["$20"], True),
    ],
)
def test_non_price_or_unbound_evidence_cannot_complete_pricing(field, value, wrong_candidate):
    brief, candidate, page, item = pricing_fixture(field, value, wrong_candidate)
    coverage = evaluate_coverage_contract(
        brief, candidates=[candidate], pages=[page], evidence_items=[item], ledger=[]
    )
    assert not coverage.passed
    assert "current_plan_price_support" in coverage.missing_intents


def test_valid_price_evidence_still_completes_collection():
    brief, candidate, page, item = pricing_fixture()
    assert evaluate_coverage_contract(
        brief, candidates=[candidate], pages=[page], evidence_items=[item], ledger=[]
    ).passed


@pytest.mark.asyncio
async def test_react_receives_failed_coverage_and_does_not_finish_on_http_200(
    monkeypatch, tmp_path
):
    service = RunService(
        SkillRegistry.from_default_path(),
        Settings(demo_mode=True, collector_react_max_turns=3),
        journal=RunJournal(tmp_path / "journal.db"),
        kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = make_detail()
    detail.plan.research_depth = "deep"
    detail.plan.competitors = ["A"]
    detail.plan.dimensions = ["pricing"]
    detail.plan.homepage_hints = {"A": "https://a.example"}
    record = RunRecord(detail=detail)
    service._runs[detail.id] = record
    context = SubagentContext(run_id=detail.id, agent="collector", subagent="pricing_A")
    service._record_collector_coverage(
        detail.id,
        context.subagent,
        "A",
        "pricing",
        {
            "passed": False,
            "missing_intents": ["current_plan_price_support"],
            "repair_hints": ["Find the actual current plan amount."],
        },
    )
    captured = []
    actions = [
        {"action": "fetch_page", "url": "https://a.example/pricing"},
        {"action": "finish", "sources": []},
        {"action": "finish", "sources": []},
    ]

    async def complete(_record, **kwargs):
        captured.append(kwargs)
        return actions.pop(0)

    async def fetch(*args, **kwargs):
        return EvidenceFetchResult(
            url="https://a.example/pricing",
            ok=True,
            title="A Pricing",
            text="A annual billing costs less. No captured plan amounts.",
            content_hash="policy-only",
            status_code=200,
            quality_score=0.95,
        )

    monkeypatch.setattr(service, "_trace_llm_json", complete)
    monkeypatch.setattr(service, "_trace_fetch", fetch)
    await service._run_collector_competitor_react(record, "pricing", "A", context)
    assert "Find the actual current plan amount." in captured[0]["user"]
    assert len(captured) == 3
    assert "remaining_turns=1" in captured[-1]["user"]
    obs = json.loads(captured[-1]["user"].split("Observations JSON: ", 1)[1].split("\n\n", 1)[0])
    assert any(row.get("error") == "fact_coverage_incomplete" for row in obs)


@pytest.mark.asyncio
@pytest.mark.parametrize("fetch_calls,expected_calls", [(4, 0), (3, 1)])
async def test_react_uses_remaining_tool_budget(monkeypatch, tmp_path, fetch_calls, expected_calls):
    service = RunService(
        SkillRegistry.from_default_path(), Settings(demo_mode=True),
        journal=RunJournal(tmp_path / "budget-journal.db"), kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = make_detail()
    detail.plan.research_depth = "quick"
    record = RunRecord(detail=detail)
    context = SubagentContext(run_id=detail.id, agent="collector", subagent="feature::A")
    detail.collector_research_usage[context.subagent] = CollectorResearchUsage(
        search_calls=1, fetch_calls=fetch_calls,
    )
    captured = []

    async def complete(_record, **kwargs):
        captured.append(kwargs)
        return {"action": "finish", "sources": []}

    monkeypatch.setattr(service, "_trace_llm_json", complete)
    await service._run_collector_competitor_react(record, "feature", "A", context)
    assert len(captured) == expected_calls
    if captured:
        assert '"remaining_search_calls": 0' in captured[0]["user"]
        assert '"remaining_fetch_calls": 1' in captured[0]["user"]
        assert "Allowed actions are fetch_page, find_official_docs, finish." in captured[0]["system"]


@pytest.mark.asyncio
async def test_empty_filtered_search_does_not_retry_exhausted_budget(monkeypatch, tmp_path):
    from packages.schema.models import TargetProduct

    service = RunService(
        SkillRegistry.from_default_path(), Settings(demo_mode=True),
        journal=RunJournal(tmp_path / "search-journal.db"), kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = make_detail()
    detail.plan.research_depth = "quick"
    detail.plan.target_product = TargetProduct(name="Acme", category="团队软件")
    record = RunRecord(detail=detail)
    context = SubagentContext(run_id=detail.id, agent="collector", subagent="feature::A")
    calls = []

    async def search(_record, **kwargs):
        calls.append(kwargs)
        detail.collector_research_usage[context.subagent] = CollectorResearchUsage(search_calls=1)
        return []

    monkeypatch.setattr(service, "_trace_search", search)
    for _ in range(2):
        assert await service._search_research_candidates(record, detail, "feature", context, "A docs", 3) == []
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_search_budget_is_tracked_by_dimension_without_context(monkeypatch, tmp_path):
    service = RunService(
        SkillRegistry.from_default_path(), Settings(demo_mode=True),
        journal=RunJournal(tmp_path / "dimension-journal.db"), kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = make_detail()
    detail.plan.research_depth = "quick"
    detail.collector_research_usage["feature"] = CollectorResearchUsage(search_calls=1)
    record = RunRecord(detail=detail)

    async def unexpected_search(*args, **kwargs):
        pytest.fail("An exhausted dimension must not attempt another search")

    monkeypatch.setattr(service, "_trace_search", unexpected_search)
    assert await service._search_research_candidates(record, detail, "feature", None, "A docs", 3) == []


@pytest.mark.parametrize(
    "text",
    [
        "A monthly billing has a minimum invoice threshold of $5. "
        "Balances below that threshold roll into the next invoice.",
        "A shipping costs $5. Monthly billing is available.",
    ],
)
@pytest.mark.parametrize("product_scope", [False, True])
def test_policy_or_shipping_amount_is_not_current_plan_price(text, product_scope):
    from packages.research.evidence import admit_evidence_items
    from packages.research.extraction import extract_page

    brief, candidate, page, _ = pricing_fixture()
    if product_scope:
        brief.product_name = "A"
        brief.product_category = "subscription product"
    page.text = page.markdown = page.snippet = text
    items = admit_evidence_items(
        [extract_page(brief, page)], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    assert not evaluate_coverage_contract(
        brief, candidates=[candidate], pages=[page], evidence_items=items, ledger=[]
    ).passed


@pytest.mark.parametrize(
    "text",
    [
        "A Pro monthly billing has a minimum invoice threshold of $5. "
        "Balances roll into the next invoice.",
        "A Pro monthly shipping costs $5.",
    ],
)
@pytest.mark.parametrize("product_scope", [False, True])
def test_plan_name_does_not_turn_policy_amount_into_plan_price(text, product_scope):
    from packages.research.evidence import admit_evidence_items
    from packages.research.extraction import extract_page

    brief, candidate, page, _ = pricing_fixture()
    if product_scope:
        brief.product_name = "A"
        brief.product_category = "subscription product"
    page.text = page.markdown = page.snippet = text
    items = admit_evidence_items(
        [extract_page(brief, page)], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    assert not evaluate_coverage_contract(
        brief, candidates=[candidate], pages=[page], evidence_items=items, ledger=[]
    ).passed


@pytest.mark.parametrize("product_scope", [False, True])
def test_plan_price_survives_adjacent_shipping_and_invoice_threshold(product_scope):
    from packages.research.evidence import admit_evidence_items
    from packages.research.extraction import extract_page

    brief, candidate, page, _ = pricing_fixture()
    if product_scope:
        brief.product_name = "A"
        brief.product_category = "subscription product"
    page.text = page.markdown = page.snippet = (
        "A Pro price is $20 per month; shipping costs $5. Minimum invoice threshold is $2."
    )
    extraction = extract_page(brief, page)
    assert [row["price"] for row in extraction.fields["price_rows"]] == (
        ["$20"] if product_scope else ["$20 per month"]
    )
    items = admit_evidence_items(
        [extraction], brief=brief, captured_pages=[page], candidates=[candidate]
    )
    assert evaluate_coverage_contract(
        brief, candidates=[candidate], pages=[page], evidence_items=items, ledger=[]
    ).passed
