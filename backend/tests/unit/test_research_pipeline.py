import pytest

from packages.research.capture import capture_candidate
from packages.research.discovery import (
    homepage_candidates,
    rank_and_dedupe_candidates,
    trusted_registry_candidates,
)
from packages.research.evaluation import quality_gaps_from_extractions
from packages.research.evidence import raw_source_from_capture, source_quality_problem
from packages.research.extraction import (
    extract_feature_slots,
    extract_page,
    extract_persona_schema,
    extract_pricing_model,
)
from packages.research.models import CapturedPage, ResearchBrief, SourceCandidate
from packages.research.pipeline import run_research_pipeline
from packages.research.repair import repair_tasks_from_gaps
from packages.schema.models import RawSource
from packages.search import SearchResult
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


def test_pricing_extractor_marks_open_weight_pricing_not_applicable() -> None:
    brief = ResearchBrief(
        run_id="run-1",
        topic="Most powerful LLM",
        competitor="Llama",
        dimension="pricing",
    )
    page = CapturedPage(
        candidate_id="candidate-llama-license",
        requested_url="https://www.llama.com/llama-downloads/",
        final_url="https://www.llama.com/llama-downloads/",
        status="ok",
        title="Llama downloads",
        text=(
            "Llama is an open weight model available under a license for "
            "self-hosted deployment. Review the license terms before use."
        ),
        content_hash="hash-llama-license",
        status_code=200,
        fetch_method="webfetch_v2",
        quality_score=0.92,
    )

    extraction = extract_pricing_model(brief, page)
    gaps = quality_gaps_from_extractions(brief, [extraction])

    assert extraction.status == "not_applicable"
    assert extraction.fields["pricing_model_type"] == "open_weight_self_hosted"
    assert extraction.not_applicable_reason
    assert gaps == []


def test_feature_extractor_emits_slot_matrix_and_gap_repair_task() -> None:
    brief = ResearchBrief(
        run_id="run-1",
        topic="AI coding agent",
        competitor="Claude Code",
        dimension="feature",
    )
    page = CapturedPage(
        candidate_id="candidate-claude-code-docs",
        requested_url="https://docs.anthropic.com/en/docs/claude-code/overview",
        final_url="https://docs.anthropic.com/en/docs/claude-code/overview",
        status="ok",
        title="Claude Code overview",
        text=(
            "Claude Code is an agentic coding assistant for developers. It can "
            "work with a repository and codebase, use tools, and run tasks in an IDE."
        ),
        content_hash="hash-claude-code-docs",
        status_code=200,
        fetch_method="webfetch_v2",
        quality_score=0.91,
    )

    extraction = extract_feature_slots(brief, page)
    gaps = quality_gaps_from_extractions(brief, [extraction])
    repair_tasks = repair_tasks_from_gaps(gaps)

    assert extraction.fields["agentic_workflow"]["status"] == "supported"
    assert extraction.fields["repository_context"]["status"] == "supported"
    assert gaps
    assert repair_tasks
    assert repair_tasks[0].strategy == "feature_slot_repair"
    assert repair_tasks[0].query_hints


def test_persona_extractor_gaps_become_structured_repair_task() -> None:
    brief = ResearchBrief(
        run_id="run-1",
        topic="AI assistant market",
        competitor="Gemini",
        dimension="persona",
    )
    page = CapturedPage(
        candidate_id="candidate-gemini-use-cases",
        requested_url="https://workspace.google.com/solutions/ai/",
        final_url="https://workspace.google.com/solutions/ai/",
        status="ok",
        title="Gemini for Workspace",
        text=(
            "Developers use Gemini to automate work, analyze information, and "
            "collaborate in a cloud workspace."
        ),
        content_hash="hash-gemini-persona",
        status_code=200,
        fetch_method="webfetch_v2",
        quality_score=0.86,
    )

    extraction = extract_persona_schema(brief, page)
    gaps = quality_gaps_from_extractions(brief, [extraction])
    repair_tasks = repair_tasks_from_gaps(gaps)

    assert extraction.fields["buyer_or_user_role"]
    assert extraction.fields["primary_use_case"]
    assert any(gap.suggested_action == "persona_schema_repair" for gap in gaps)
    assert repair_tasks[0].target_fields
    assert any("customer" in query.casefold() for query in repair_tasks[0].query_hints)


def test_extract_page_dispatches_by_dimension() -> None:
    pricing_brief = ResearchBrief(
        run_id="run-1",
        topic="LLM APIs",
        competitor="OpenAI",
        dimension="pricing",
    )
    page = CapturedPage(
        candidate_id="candidate-openai-pricing",
        requested_url="https://platform.openai.com/docs/pricing",
        final_url="https://platform.openai.com/docs/pricing",
        status="ok",
        title="OpenAI pricing",
        text="OpenAI API pricing uses input and output token pricing with enterprise options.",
        content_hash="hash-openai-pricing-dispatch",
        status_code=200,
        fetch_method="basic_httpx",
        quality_score=0.9,
    )

    extraction = extract_page(pricing_brief, page)

    assert extraction.extractor_name == "pricing_model"


@pytest.mark.asyncio
async def test_run_research_pipeline_connects_discover_capture_extract_repair() -> None:
    brief = ResearchBrief(
        run_id="run-1",
        topic="AI coding agents",
        competitor="Claude Code",
        dimension="feature",
        homepage_hint="https://www.anthropic.com",
        max_search_queries=1,
        max_candidates=4,
        max_fetches=2,
    )

    async def fake_search(query: str, max_results: int) -> list[SearchResult]:
        assert "Claude Code" in query
        return [
            SearchResult(
                title="Claude Code overview",
                url="https://docs.anthropic.com/en/docs/claude-code/overview",
                snippet="Claude Code coding agent documentation",
            )
        ][:max_results]

    async def fake_fetch(url: str) -> EvidenceFetchResult:
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="Claude Code overview",
            text=(
                "Claude Code is an agentic coding assistant. It supports repository "
                "context, codebase tasks, tool use, and developer workflows."
            ),
            content_hash="hash-claude-code-pipeline",
            status_code=200,
            fetch_method="webfetch_v2",
            quality_score=0.9,
        )

    result = await run_research_pipeline(brief, fetch=fake_fetch, search=fake_search)

    assert result.candidates
    assert result.captured_pages
    assert result.extractions
    assert result.evidence_items
    assert result.metrics["verified_capture_rate"] == 1.0
    assert result.metrics["evidence_item_count"] == len(result.evidence_items)
