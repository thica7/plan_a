import pytest

from packages.research.capture import capture_candidate
from packages.research.discovery import (
    homepage_candidates,
    rank_and_dedupe_candidates,
    trusted_registry_candidates,
)
from packages.research.evidence import raw_source_from_capture, source_quality_problem
from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate
from packages.schema.models import RawSource
from packages.tools.evidence_fetch import EvidenceFetchResult


def test_research_discovery_separates_trusted_and_homepage_candidates() -> None:
    brief = ResearchBrief(
        run_id="run-1",
        topic="AI coding agent",
        competitor="Claude Code",
        dimension="feature",
        homepage_hint="https://www.anthropic.com",
    )

    trusted = trusted_registry_candidates(brief)
    homepage = homepage_candidates(brief)

    assert trusted
    assert all(candidate.origin == "trusted_registry" for candidate in trusted)
    assert not any(
        candidate.url.rstrip("/") == "https://www.anthropic.com/features"
        for candidate in trusted
    )
    assert any(
        candidate.url.rstrip("/") == "https://www.anthropic.com/features"
        for candidate in homepage
    )


def test_research_candidate_ranking_prefers_trusted_origin() -> None:
    weak = SourceCandidate(
        title="Derived features",
        url="https://www.anthropic.com/features",
        origin="homepage_derived",
        competitor="Claude Code",
        dimension="feature",
        confidence=0.45,
    )
    trusted = SourceCandidate(
        title="Claude Code docs",
        url="https://docs.anthropic.com/en/docs/claude-code/overview",
        origin="trusted_registry",
        competitor="Claude Code",
        dimension="feature",
        confidence=0.98,
    )

    ranked = rank_and_dedupe_candidates(
        [weak, trusted],
        competitor="Claude Code",
        dimension="feature",
        homepage_hint="https://www.anthropic.com",
    )

    assert ranked[0].url == "https://docs.anthropic.com/en/docs/claude-code/overview"


@pytest.mark.asyncio
async def test_capture_candidate_returns_typed_page() -> None:
    candidate = SourceCandidate(
        title="OpenAI pricing",
        url="https://developers.openai.com/api/docs/pricing",
        origin="trusted_registry",
        competitor="GPT-5.5",
        dimension="pricing",
    )

    async def fake_fetch(url: str) -> EvidenceFetchResult:
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="Pricing | OpenAI API",
            text="OpenAI API pricing includes free, plan, token, and enterprise billing details.",
            content_hash="hash-openai-pricing",
            status_code=200,
            fetch_method="basic_httpx",
            quality_score=1.0,
            text_length=78,
        )

    captured = await capture_candidate(candidate, fake_fetch)

    assert captured.status == "ok"
    assert captured.candidate_id == candidate.id
    assert captured.final_url == candidate.url
    assert captured.fetch_method == "basic_httpx"


def test_raw_source_from_capture_preserves_candidate_and_fetch_lineage() -> None:
    brief = ResearchBrief(
        run_id="run-1",
        topic="Powerful LLM",
        competitor="Claude",
        dimension="pricing",
    )
    candidate = SourceCandidate(
        title="Claude pricing",
        url="https://claude.com/pricing",
        origin="trusted_registry",
        competitor="Claude",
        dimension="pricing",
        rank=0,
        confidence=0.98,
    )
    captured = CapturedPage(
        candidate_id=candidate.id,
        requested_url=candidate.url,
        final_url=candidate.url,
        status="ok",
        title="Plans & Pricing | Claude",
        text="Claude pricing includes Free, Pro, Max, Team, and Enterprise plans.",
        content_hash="hash-claude-pricing",
        status_code=200,
        fetch_method="basic_httpx",
        quality_score=1.0,
        text_length=68,
    )

    source = raw_source_from_capture(brief, candidate, captured, confidence=0.96)

    assert source.source_type == "webpage_verified"
    assert source.candidate_origin == "trusted_registry"
    assert source.fetch_method == "basic_httpx"
    assert source_quality_problem(source) is None


def test_source_quality_problem_rejects_soft_404() -> None:
    source = RawSource(
        id="raw-source-1",
        competitor="Llama",
        dimension="feature",
        source_type="webpage_verified",
        title="404: This page could not be found",
        url="https://www.llama.com/404/",
        snippet="404 not found. This page does not exist.",
        content_hash="hash-404",
        confidence=0.96,
    )

    assert "soft 404" in (source_quality_problem(source) or "")
