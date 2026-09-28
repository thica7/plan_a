from __future__ import annotations

from packages.research.coverage_contract import evaluate_coverage_contract
from packages.research.discovery.planner import build_search_queries
from packages.research.evaluation import quality_gaps_from_extractions
from packages.research.evidence.admission import admit_evidence_items
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.extraction.common import extract_page
from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate


def _page() -> CapturedPage:
    return CapturedPage(
        candidate_id="candidate-home",
        requested_url="https://example.com/vacuum",
        final_url="https://example.com/vacuum",
        status="ok",
        title="示例吸尘器",
        text="示例吸尘器具备可更换电池设计，并支持吸拖一体清洁，适合日常家庭地面整理。",
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
    assert quality_gaps_from_extractions(brief, [supported]) == []


def test_legacy_feature_run_keeps_existing_slots() -> None:
    brief = ResearchBrief(
        run_id="legacy", topic="AI assistant", competitor="Example",
        dimension="feature",
    )
    assert "context_window" in extract_page(brief, _page()).fields


def test_generic_feature_gap_uses_product_discovery_when_no_capability_is_cited() -> None:
    brief = ResearchBrief(
        run_id="generic-empty", topic="家电调研", competitor="示例吸尘器",
        dimension="feature", product_category="家用清洁电器",
    )
    page = _page().model_copy(update={"text": "欢迎访问我们的主页。"})
    gaps = quality_gaps_from_extractions(brief, [extract_page(brief, page)])
    assert len(gaps) == 1
    assert gaps[0].suggested_action == "targeted_discovery"
    assert "context_window" not in (gaps[0].field or "")


def test_generic_price_gap_avoids_ai_billing_repair_queries() -> None:
    brief = ResearchBrief(
        run_id="generic-no-price", topic="家电价格", competitor="洁净家",
        dimension="pricing", product_category="家用清洁电器",
    )
    page = _page().model_copy(update={"text": "洁净家介绍产品外观和颜色。"})
    gaps = quality_gaps_from_extractions(brief, [extract_page(brief, page)])
    assert len(gaps) == 1
    assert gaps[0].severity == "blocker"
    assert gaps[0].suggested_action == "targeted_discovery"


def test_generic_persona_gap_avoids_developer_persona_repair() -> None:
    brief = ResearchBrief(
        run_id="generic-no-persona", topic="家电用户", competitor="洁净家",
        dimension="persona", product_category="家用清洁电器",
    )
    page = _page().model_copy(update={"text": "洁净家介绍产品外观和颜色。"})
    gaps = quality_gaps_from_extractions(brief, [extract_page(brief, page)])
    assert len(gaps) == 1
    assert gaps[0].suggested_action == "targeted_discovery"


def test_generic_feature_does_not_turn_explicit_absence_into_capability() -> None:
    brief = ResearchBrief(
        run_id="generic-negation", topic="家电调研", competitor="洁净家",
        dimension="feature", product_category="家用清洁电器",
    )
    page = _page().model_copy(update={
        "text": "洁净家不具备可更换电池设计。",
    })
    assert extract_page(brief, page).fields == {}


def test_generic_feature_requires_current_product_in_cited_clause() -> None:
    brief = ResearchBrief(
        run_id="feature-comparison", topic="家电功能", competitor="飞跃牌",
        dimension="feature", product_name="洁净家", product_category="家用清洁电器",
    )
    page = _page().model_copy(update={
        "title": "洁净家与飞跃牌功能对比",
        "text": "洁净家无线吸尘器支持可更换电池。飞跃牌无线吸尘器外观为蓝色。",
    })
    assert extract_page(brief, page).fields == {}


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


def test_hardware_audience_and_use_case_need_page_quotes() -> None:
    brief = ResearchBrief(
        run_id="hardware-persona", topic="家电用户调研", competitor="洁净家",
        dimension="persona", product_name="示例吸尘器",
        product_category="家用清洁电器", product_audience="养宠家庭",
        product_use_cases=["清理宠物毛发"],
    )
    candidate = SourceCandidate(
        title="洁净家适用人群", url="https://cleanhome.example/users",
        origin="web_search", competitor="洁净家", dimension="persona",
    )
    page = CapturedPage(
        candidate_id=candidate.id, requested_url=candidate.url, final_url=candidate.url,
        status="ok", title="洁净家用户场景",
        text="洁净家吸尘器面向养宠家庭，适合清理宠物毛发和地毯上的灰尘。",
        content_hash="audience", quality_score=.9,
    )
    extraction = extract_page(brief, page)
    assert extraction.fields["target_segment"] == "养宠家庭"
    assert extraction.fields["primary_use_case"] == "清理宠物毛发和地毯上的灰尘"
    items = admit_evidence_items([extraction], captured_pages=[page], candidates=[candidate])
    assert {item.field for item in items if item.status == "accepted"} >= {
        "target_segment", "primary_use_case",
    }


def test_generic_persona_does_not_copy_target_audience_to_rival() -> None:
    brief = ResearchBrief(
        run_id="persona-comparison", topic="吸尘器用户", competitor="飞跃牌",
        dimension="persona", product_name="洁净家", product_category="家用清洁电器",
        product_audience="养宠家庭", product_use_cases=["清理宠物毛发"],
    )
    page = CapturedPage(
        candidate_id="persona-comparison", requested_url="https://example.com/compare",
        final_url="https://example.com/compare", status="ok", title="洁净家与飞跃牌对比",
        text=("洁净家无线吸尘器面向养宠家庭，适合清理宠物毛发和地毯。"
              "飞跃牌无线吸尘器面向专业保洁公司，适合清洁办公楼和大型场馆。"),
        content_hash="persona-comparison", quality_score=.9,
    )
    extraction = extract_page(brief, page)
    assert extraction.fields["target_segment"] == "专业保洁公司"
    assert extraction.fields["primary_use_case"] == "清洁办公楼和大型场馆"
    assert all("养宠家庭" not in quote.text and "清理宠物毛发" not in quote.text for quote in extraction.quotes)
    third_brand = page.model_copy(update={
        "text": "飞跃牌和清洁王产品对比，清洁王面向专业保洁公司，适合清理大型商场的公共区域。",
    })
    assert extract_page(brief, third_brand).fields == {}


def test_generic_saas_price_keeps_tier_and_monthly_cycle() -> None:
    brief = ResearchBrief(
        run_id="software-price", topic="团队协作产品", competitor="DevMate",
        dimension="pricing", product_name="NoteHarbor", product_category="team software",
    )
    page = CapturedPage(
        candidate_id="software-price", requested_url="https://devmate.example/pricing",
        final_url="https://devmate.example/pricing", status="ok",
        title="DevMate pricing",
        text="The DevMate Pro plan costs $20 per user per month for small teams.",
        content_hash="software-price", quality_score=.9,
    )
    extraction = extract_page(brief, page)
    assert extraction.fields["pricing_model_type"] == "subscription_saas"
    assert extraction.fields["price_rows"][0]["tier_name"] == "Pro"
    assert extraction.fields["price_rows"][0]["billing_cycle"] == "monthly"


def test_generic_price_does_not_assign_rival_price_to_competitor() -> None:
    brief = ResearchBrief(
        run_id="comparison-price", topic="吸尘器价格", competitor="洁净家",
        dimension="pricing", product_name="目标吸尘器", product_category="家电",
    )
    candidate = SourceCandidate(
        title="洁净家与飞跃牌价格对比", url="https://example.com/comparison",
        origin="web_search", competitor="洁净家", dimension="pricing",
    )
    page = CapturedPage(
        candidate_id=candidate.id, requested_url=candidate.url, final_url=candidate.url,
        status="ok", title=candidate.title,
        text="洁净家无线吸尘器标准套装售价 ¥1,299，包含两年保修服务。飞跃牌无线吸尘器标准套装售价 ¥999，包含一年保修服务。",
        content_hash="comparison-price", quality_score=.9,
    )
    extraction = extract_page(brief, page)
    assert extraction.fields["price_points"] == ["¥1,299"]
    assert [row["price"] for row in extraction.fields["price_rows"]] == ["¥1,299"]
    items = admit_evidence_items([extraction], captured_pages=[page], candidates=[candidate])
    normalized = normalized_fields_from_evidence_items(items)
    assert [(field.price, field.source_quote) for field in normalized] == [
        ("¥1,299", "洁净家无线吸尘器标准套装售价 ¥1,299，包含两年保修服务。"),
    ]
    assert evaluate_coverage_contract(
        brief, candidates=[candidate], pages=[page], evidence_items=items, ledger=[],
    ).passed


def test_generic_price_rows_keep_independent_source_quotes() -> None:
    brief = ResearchBrief(
        run_id="two-price", topic="家电价格", competitor="洁净家",
        dimension="pricing", product_name="目标吸尘器", product_category="家电",
    )
    candidate = SourceCandidate(
        title="洁净家价格", url="https://example.com/prices", origin="web_search",
        competitor="洁净家", dimension="pricing",
    )
    page = CapturedPage(
        candidate_id=candidate.id, requested_url=candidate.url, final_url=candidate.url,
        status="ok", title=candidate.title,
        text="洁净家基础款无线吸尘器售价 ¥1,299，包含两年保修服务。洁净家旗舰款无线吸尘器售价 ¥1,899，包含三年保修服务。",
        content_hash="two-price", quality_score=.9,
    )
    extraction = extract_page(brief, page)
    items = admit_evidence_items([extraction], captured_pages=[page], candidates=[candidate])
    normalized = normalized_fields_from_evidence_items(items)
    assert [(field.price, field.source_quote) for field in normalized] == [
        ("¥1,299", "洁净家基础款无线吸尘器售价 ¥1,299，包含两年保修服务。"),
        ("¥1,899", "洁净家旗舰款无线吸尘器售价 ¥1,899，包含三年保修服务。"),
    ]


def test_generic_price_rejects_ambiguous_respective_prices() -> None:
    brief = ResearchBrief(
        run_id="ambiguous-price", topic="吸尘器价格", competitor="洁净家",
        dimension="pricing", product_name="目标吸尘器", product_category="家电",
    )
    page = CapturedPage(
        candidate_id="ambiguous-price", requested_url="https://example.com/compare",
        final_url="https://example.com/compare", status="ok", title="两款吸尘器价格对比",
        text="飞跃牌和洁净家两款无线吸尘器的官方售价分别为 ¥999 和 ¥1,299。",
        content_hash="ambiguous-price", quality_score=.9,
    )
    assert extract_page(brief, page).fields["price_points"] == []
    page = page.model_copy(update={
        "text": "飞跃牌与洁净家无线吸尘器官方售价为 ¥999、¥1,299。",
    })
    assert extract_page(brief, page).fields["price_points"] == []
    page = page.model_copy(update={
        "text": "飞跃牌、洁净家无线吸尘器售价 ¥999、¥1,299，均含两年保修。",
    })
    assert extract_page(brief, page).fields["price_points"] == []
    page = page.model_copy(update={
        "text": "飞跃牌和洁净家标准版无线吸尘器售价为 ¥999、¥1,299，均含保修。",
    })
    assert extract_page(brief, page).fields["price_points"] == []


def test_generic_price_keeps_named_tiers_after_product_header() -> None:
    brief = ResearchBrief(
        run_id="tier-price", topic="吸尘器价格", competitor="洁净家",
        dimension="pricing", product_name="目标吸尘器", product_category="家电",
    )
    page = CapturedPage(
        candidate_id="tier-price", requested_url="https://example.com/cleanhome",
        final_url="https://example.com/cleanhome", status="ok", title="洁净家套餐价格",
        text="洁净家官方套餐价格：标准版售价 ¥1,299，高级版售价 ¥1,999。",
        content_hash="tier-price", quality_score=.9,
    )
    assert extract_page(brief, page).fields["price_points"] == ["¥1,299", "¥1,999"]
    multiline = page.model_copy(update={
        "text": "洁净家官方价格\n标准版售价 ¥1,299，包含一年保修。\n高级版售价 ¥1,999，包含三年保修。",
    })
    assert extract_page(brief, multiline).fields["price_points"] == ["¥1,299", "¥1,999"]
