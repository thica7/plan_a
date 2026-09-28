from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter

from packages.agents.qa.logic import QualityAgentMixin
from packages.research.evidence.admission import admit_evidence_items
from packages.research.extraction.common import extract_page
from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate
from packages.schema.models import RawSource
from packages.tools.evidence_fetch import _basic_content_problem
from packages.tools.fetch_page import FetchPageResult, _extract_pdf_text

CASES = Path(__file__).resolve().parents[3] / "eval" / "product-evidence-eval.jsonl"


def test_product_evidence_quality_gate_examples() -> None:
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    assert {item["kind"] for item in cases} == {
        "fetch_shell", "freshness", "extraction", "pdf", "price_conflict",
    }
    assert len(cases) >= 7
    for item in cases:
        if item["kind"] == "fetch_shell":
            result = FetchPageResult(
                url="https://example.com/product", ok=True,
                title=item["title"], text=item["text"], content_hash="eval",
            )
            assert _basic_content_problem(result) == item["expected_reason"]
        elif item["kind"] == "freshness":
            metadata = {"source_published_at": item["published_at"]}
            if item.get("verified_now"):
                metadata["last_verified_at"] = datetime.now(UTC).isoformat()
            source = RawSource(
                id=item["id"], competitor="示例产品", dimension="pricing",
                source_type="webpage_verified", title="Product pricing",
                url="https://example.com/pricing", snippet="Synthetic price data",
                content_hash="eval", confidence=.7, metadata=metadata,
            )
            assert (QualityAgentMixin()._source_freshness_problem(source) is not None) == item["expected_stale"]
        elif item["kind"] == "pdf":
            output = BytesIO()
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            writer.write(output)
            assert _extract_pdf_text(output.getvalue()) == item["expected_text"]
        else:
            brief = ResearchBrief(
                run_id="eval", topic="通用产品调研", competitor=item["competitor"],
                dimension=item["dimension"], product_name="目标产品",
                product_category=item["category"],
            )
            candidate = SourceCandidate(
                title=item["competitor"], url="https://example.com/source",
                origin="web_search", competitor=item["competitor"],
                dimension=item["dimension"],
            )
            page = CapturedPage(
                candidate_id=candidate.id, requested_url=candidate.url,
                final_url=candidate.url, status="ok", title=item["competitor"],
                text=item["text"], content_hash="eval", quality_score=.9,
            )
            extraction = extract_page(brief, page)
            if item["kind"] == "price_conflict":
                assert len(extraction.fields["price_points"]) == item["expected_price_count"]
                continue
            evidence = admit_evidence_items([extraction], captured_pages=[page], candidates=[candidate])
            assert any(
                entry.field == item["expected_field"] and entry.status == "accepted"
                and item["expected_quote"] in entry.quote for entry in evidence
            ), item["id"]
