from __future__ import annotations

import json
from pathlib import Path

from packages.agents.planner.logic import PlannerAgentMixin
from packages.research.discovery.planner import build_competitor_queries
from packages.research.extraction.common import extract_page
from packages.research.models import CapturedPage, ResearchBrief
from packages.schema.models import TargetProduct
from packages.search import SearchResult

CASES = Path(__file__).resolve().parents[3] / "eval" / "product-discovery-eval.jsonl"


def test_general_product_discovery_examples_have_source_backed_candidates() -> None:
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    assert {case["category_family"] for case in cases} == {
        "software", "consumer_app", "ecommerce", "hardware", "ai_product",
    }
    planner = PlannerAgentMixin()
    for case in cases:
        target = TargetProduct.model_validate(case["target_product"])
        queries = build_competitor_queries(target, topic=case["topic"])
        assert target.name in " ".join(queries)
        assert target.category in " ".join(queries)
        results = [SearchResult(**result) for result in case["search_results"]]
        for candidate in case["candidates"]:
            matched = planner._candidate_evidence(candidate["name"], results)
            assert [result.url for result in matched] == candidate["expected_evidence_urls"]
        page = CapturedPage(
            candidate_id="candidate-eval", requested_url=case["feature_url"],
            final_url=case["feature_url"], status="ok", title="Product facts",
            text=case["feature_text"], content_hash="feature-eval", quality_score=0.9,
        )
        brief = ResearchBrief(
            run_id="eval", topic=case["topic"], competitor=case["candidates"][0]["name"],
            dimension="feature", product_name=target.name,
            product_category=target.category, product_use_cases=target.use_cases,
        )
        extraction = extract_page(brief, page)
        assert "context_window" not in extraction.fields
        assert case["expected_feature_quote"] in extraction.quotes[0].text
