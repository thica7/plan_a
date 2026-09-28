from __future__ import annotations

from packages.research.coverage_contract import evaluate_coverage_contract
from packages.research.discovery.planner import build_search_queries
from packages.research.evidence.admission import admit_evidence_items
from packages.research.extraction.common import extract_page
from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate


def _page() -> CapturedPage:
    return CapturedPage(
        candidate_id="candidate-home",
        requested_url="https://example.com/vacuum",
        final_url="https://example.com/vacuum",
        status="ok",
        title="示例吸尘器",
        text="这款无线吸尘器具备可更换电池，并支持吸拖一体清洁。",
        content_hash="example",
        quality_score=0.9,
    )


def test_generic_product_uses_cited_capability_phrases() -> None:
    brief = ResearchBrief(
        run_id="run-generic", topic="家电调研", competitor="示例吸尘器",
        dimension="feature", product_category="家用清洁电器",
    )
    extracted = extract_page(brief, _page())
    assert "context_window" not in extracted.fields
    assert "agentic_workflow" not in extracted.fields
    assert extracted.fields["capability_1"]["status"] == "supported"
    assert "可更换电池" in extracted.quotes[0].text
    assert extracted.quotes[0].source_url == "https://example.com/vacuum"
    candidate = SourceCandidate(
        title="示例吸尘器", url="https://example.com/vacuum",
        origin="web_search", competitor="示例吸尘器", dimension="feature",
    )
    page = _page().model_copy(update={"candidate_id": candidate.id})
    supported = extract_page(brief, page)
    items = admit_evidence_items([supported], captured_pages=[page], candidates=[candidate])
    assert any(item.status == "accepted" and item.field == "capability_1" for item in items)


def test_legacy_feature_run_keeps_existing_slots() -> None:
    brief = ResearchBrief(
        run_id="legacy", topic="AI assistant", competitor="Example",
        dimension="feature",
    )
    assert "context_window" in extract_page(brief, _page()).fields


def test_generic_product_search_avoids_ai_specific_queries() -> None:
    brief = ResearchBrief(
        run_id="run-generic", topic="家电调研", competitor="示例吸尘器",
        dimension="pricing", product_category="家用清洁电器",
        product_use_cases=["清理宠物毛发"], product_market="中国",
    )
    queries = build_search_queries(brief)
    assert any("家用清洁电器" in query for query in queries)
    assert any("中国" in query for query in queries)
    assert all("token cost" not in query and "model documentation" not in query for query in queries)


def test_hardware_price_is_cited_without_saas_tiers() -> None:
    brief = ResearchBrief(
        run_id="hardware", topic="家电价格调研", competitor="洁净家",
        dimension="pricing", product_name="示例吸尘器", product_category="家用清洁电器",
    )
    candidate = SourceCandidate(
        title="洁净家售价", url="https://cleanhome.example/price",
        origin="web_search", competitor="洁净家", dimension="pricing",
    )
    page = CapturedPage(
        candidate_id=candidate.id, requested_url=candidate.url, final_url=candidate.url,
        status="ok", title="洁净家产品价格",
        text="洁净家无线吸尘器官网售价 ¥1,299，一次性购买，含两年保修。",
        content_hash="hardware-price", quality_score=0.9,
    )
    extracted = extract_page(brief, page)
    assert extracted.fields["pricing_model_type"] == "one_time_purchase"
    assert "¥1,299" in extracted.fields["price_points"]
    assert any("¥1,299" in quote.text for quote in extracted.quotes)
    items = admit_evidence_items([extracted], captured_pages=[page], candidates=[candidate])
    coverage = evaluate_coverage_contract(
        brief, candidates=[candidate], pages=[page], evidence_items=items, ledger=[],
    )
    assert coverage.passed is True
    assert coverage.metadata["contract"] == "product_pricing_v1"
