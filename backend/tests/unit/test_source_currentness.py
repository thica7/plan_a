from __future__ import annotations

from datetime import UTC, datetime

from packages.agents.qa.logic import QualityAgentMixin
from packages.research.evidence.admission import raw_source_from_capture
from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate


def test_old_publication_remains_old_when_page_is_fetched_today() -> None:
    brief = ResearchBrief(
        run_id="freshness-run", topic="价格调研", competitor="示例产品",
        dimension="pricing", product_name="目标产品",
    )
    candidate = SourceCandidate(
        title="示例产品历史价格", url="https://example.com/pricing",
        origin="web_search", competitor="示例产品", dimension="pricing",
        date="2020-01-01", last_updated="2020-02-01",
    )
    page = CapturedPage(
        candidate_id=candidate.id, requested_url=candidate.url,
        final_url=candidate.url, status="ok", title=candidate.title,
        text="示例产品的历史价格曾为每月 10 元。", content_hash="old-price",
        quality_score=0.9, captured_at=datetime.now(UTC),
    )
    source = raw_source_from_capture(brief, candidate, page, confidence=0.7)
    assert source.metadata["source_published_at"] == "2020-01-01"
    assert source.metadata["source_updated_at"] == "2020-02-01"
    assert source.metadata["fetched_at"]
    assert "old" in QualityAgentMixin()._source_freshness_problem(source).casefold() or (
        "days old" in QualityAgentMixin()._source_freshness_problem(source).casefold()
    )


def test_recent_explicit_verification_overrides_old_publication_date() -> None:
    source = raw_source_from_capture(
        ResearchBrief(run_id="current", topic="价格", competitor="示例产品", dimension="pricing"),
        SourceCandidate(title="官方价格", url="https://example.com/current", origin="web_search",
                        date="2020-01-01", last_updated="2020-01-01"),
        CapturedPage(candidate_id="candidate", requested_url="https://example.com/current",
                     final_url="https://example.com/current", status="ok", title="官方价格",
                     text="经核验的当前价格信息。", content_hash="verified", quality_score=.9),
        confidence=.8,
    )
    source.metadata["last_verified_at"] = datetime.now(UTC).isoformat()
    assert QualityAgentMixin()._source_freshness_problem(source) is None
