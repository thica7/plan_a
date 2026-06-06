import pytest

from packages.research.assembly import (
    assemble_research_report,
    field_matrix_from_evidence_items,
)
from packages.research.capture import CaptureCache, capture_candidate, select_capture_candidates
from packages.research.capture.policy import (
    capture_failure_reason,
    capture_rejection_reason,
    invalid_candidate_reason,
)
from packages.research.discovery import (
    homepage_candidates,
    rank_and_dedupe_candidates,
    search_result_candidates,
    trusted_registry_candidates,
)
from packages.research.evaluation import quality_gaps_from_extractions
from packages.research.evaluation.release_gate import quality_gaps_from_release_gate
from packages.research.evidence import (
    admit_evidence_items,
    citation_refs_from_evidence_items,
    evidence_items_from_extractions,
    raw_source_from_capture,
    snippet_from_evidence_items,
    source_quality_problem,
)
from packages.research.extraction import (
    extract_feature_slots,
    extract_page,
    extract_persona_schema,
    extract_pricing_model,
)
from packages.research.models import (
    CapturedPage,
    EvidenceItem,
    EvidenceQuote,
    ExtractionResult,
    QualityGap,
    ResearchBrief,
    SourceCandidate,
)
from packages.research.pipeline import run_research_pipeline
from packages.research.repair import repair_tasks_from_gaps
from packages.research.repair.redos import repair_tasks_to_redo_scopes
from packages.research.repair.strategies import repair_task_from_gap
from packages.schema.enterprise import (
    BusinessQAEvaluation,
    BusinessQAFinding,
    ProjectReadinessScore,
    ReportReleaseGate,
)
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


def test_search_candidate_confidence_requires_competitor_relevance() -> None:
    brief = ResearchBrief(
        run_id="run-1",
        topic="AI coding agent",
        competitor="Claude Code",
        dimension="feature",
    )

    candidates = search_result_candidates(
        brief,
        [
            SearchResult(
                title="Random automation article",
                url="https://cloud34221.autos/random-post",
                snippet="Unrelated content about automation.",
            )
        ],
        origin="perplexity",
        query="Claude Code official product capabilities",
    )

    assert candidates[0].confidence < 0.5


def test_capture_selection_defers_low_confidence_homepage_candidates() -> None:
    brief = ResearchBrief(
        run_id="run-1",
        topic="AI coding agent",
        competitor="Claude Code",
        dimension="feature",
        target_source_count=2,
        max_fetches=4,
    )
    preferred = [
        SourceCandidate(
            title="Claude Code docs",
            url="https://docs.anthropic.com/en/docs/claude-code/overview",
            origin="trusted_registry",
            competitor="Claude Code",
            dimension="feature",
            confidence=0.98,
        ),
        SourceCandidate(
            title="Claude Code SDK docs",
            url="https://docs.anthropic.com/en/docs/claude-code/sdk",
            origin="perplexity",
            competitor="Claude Code",
            dimension="feature",
            confidence=0.82,
        ),
    ]
    guessed = SourceCandidate(
        title="Claude Code guessed features page",
        url="https://www.anthropic.com/features",
        origin="homepage_derived",
        competitor="Claude Code",
        dimension="feature",
        confidence=0.45,
    )

    selection = select_capture_candidates(brief, [*preferred, guessed])

    assert [candidate.url for candidate in selection.selected] == [
        "https://docs.anthropic.com/en/docs/claude-code/overview",
        "https://docs.anthropic.com/en/docs/claude-code/sdk",
    ]
    assert selection.skipped_reasons[guessed.id] == "deferred_low_confidence_homepage_derived"


def test_clean_research_pipeline_boundary_modules_are_real_contracts() -> None:
    invalid = SourceCandidate(
        title="Local debug page",
        url="http://localhost:5173",
        origin="manual",
        competitor="AcmeAI",
        dimension="feature",
    )
    evidence = EvidenceItem(
        competitor="AcmeAI",
        dimension="feature",
        field="agentic_workflow",
        value={"status": "supported"},
        source_candidate_id="candidate-1",
        captured_page_id="page-1",
        source_url="https://acme.example/docs",
        quote="AcmeAI supports agentic workflow automation for developers.",
        confidence=0.91,
        status="accepted",
    )
    gap = QualityGap(
        severity="warn",
        dimension="feature",
        competitor="AcmeAI",
        field="repository_context",
        reason="Feature slot matrix is missing repository context evidence.",
        suggested_action="feature_slot_repair",
        acceptance_rule="Collect verified docs for repository context.",
    )

    matrix = field_matrix_from_evidence_items([evidence])
    report = assemble_research_report(
        ResearchBrief(
            run_id="run-1",
            topic="AI coding agents",
            competitor="AcmeAI",
            dimension="feature",
        ),
        fields=matrix,
        gaps=[gap],
        repair_tasks=[repair_task_from_gap(gap)],
    )

    assert invalid_candidate_reason(invalid) == "local_url_not_allowed"
    assert capture_failure_reason(None) == "fetch_returned_none"
    assert citation_refs_from_evidence_items([evidence])[0]["ref"] == "S1"
    assert "agentic workflow" in snippet_from_evidence_items([evidence])
    assert matrix[0]["citations"][0]["evidence_item_id"] == evidence.id
    assert report["status"] == "needs_repair"


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


@pytest.mark.asyncio
async def test_capture_candidate_rejects_soft_404_before_extraction() -> None:
    candidate = SourceCandidate(
        title="Anthropic features",
        url="https://www.anthropic.com/features",
        origin="homepage_derived",
        competitor="Claude",
        dimension="feature",
        confidence=0.45,
    )

    async def fake_fetch(url: str) -> EvidenceFetchResult:
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="404: This page could not be found",
            text="404 not found. This page does not exist.",
            content_hash="hash-soft-404",
            status_code=200,
            fetch_method="webfetch_v2",
            quality_score=0.8,
        )

    captured = await capture_candidate(candidate, fake_fetch)

    assert captured.status == "rejected"
    assert captured.failure_reason == "captured_soft_404"
    assert captured.quality_score == 0.2
    assert (
        capture_rejection_reason(
            ok=True,
            title=captured.title,
            text=captured.text,
            markdown=captured.markdown,
        )
        == "captured_soft_404"
    )


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


def test_field_level_evidence_admission_rejects_low_confidence_fields() -> None:
    brief = ResearchBrief(
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
        text="Pricing page mentions API token pricing.",
        content_hash="hash-low-confidence-pricing",
        status_code=200,
        fetch_method="basic_httpx",
        quality_score=0.1,
    )
    extraction = extract_pricing_model(brief, page).model_copy(update={"confidence": 0.2})

    items = evidence_items_from_extractions([extraction], min_accept_confidence=0.35)

    assert items
    assert {item.status for item in items} == {"rejected"}
    assert all(item.rejection_reason for item in items)


def test_admit_evidence_items_requires_ok_capture_and_field_quote() -> None:
    extraction = ExtractionResult(
        competitor="OpenAI",
        dimension="pricing",
        source_candidate_id="candidate-openai-pricing",
        captured_page_id="page-openai-pricing",
        fields={"pricing_model_type": "api_usage_based"},
        quotes=[],
        confidence=0.9,
        extractor_name="pricing_model",
    )
    page = CapturedPage(
        id="page-openai-pricing",
        candidate_id="candidate-openai-pricing",
        requested_url="https://platform.openai.com/docs/pricing",
        final_url="https://platform.openai.com/docs/pricing",
        status="ok",
        title="OpenAI pricing",
        text="OpenAI API pricing uses token billing.",
        content_hash="hash-openai-admission",
        fetch_method="webfetch_v2",
        quality_score=0.9,
    )
    candidate = SourceCandidate(
        id="candidate-openai-pricing",
        title="OpenAI pricing",
        url=page.final_url,
        origin="trusted_registry",
        competitor="OpenAI",
        dimension="pricing",
    )

    rejected = admit_evidence_items(
        [extraction],
        captured_pages=[page],
        candidates=[candidate],
    )
    accepted = admit_evidence_items(
        [
            extraction.model_copy(
                update={
                    "quotes": [
                        EvidenceQuote(
                            field="pricing_model_type",
                            source_url=page.final_url,
                            text="OpenAI API pricing uses token billing for input and output.",
                        )
                    ]
                }
            )
        ],
        captured_pages=[page],
        candidates=[candidate],
    )

    assert rejected[0].status == "rejected"
    assert "field_quote_missing_or_too_short" in (rejected[0].rejection_reason or "")
    assert accepted[0].status == "accepted"
    assert accepted[0].metadata["candidate_origin"] == "trusted_registry"


@pytest.mark.asyncio
async def test_capture_cache_reuses_page_while_rebinding_candidate_lineage() -> None:
    cache = CaptureCache()
    calls = 0
    first = SourceCandidate(
        title="OpenAI pricing",
        url="https://platform.openai.com/docs/pricing",
        origin="trusted_registry",
        competitor="OpenAI",
        dimension="pricing",
    )
    second = SourceCandidate(
        title="OpenAI API pricing",
        url="https://platform.openai.com/docs/pricing",
        origin="perplexity",
        competitor="OpenAI",
        dimension="pricing",
    )

    async def fake_fetch(url: str) -> EvidenceFetchResult:
        nonlocal calls
        calls += 1
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="OpenAI pricing",
            text="OpenAI API pricing uses token based billing.",
            content_hash="hash-openai-cache",
            status_code=200,
            fetch_method="basic_httpx",
            quality_score=0.9,
        )

    first_page = await capture_candidate(first, fake_fetch)
    cache.put(first, first_page)
    second_page = cache.get(second)

    assert calls == 1
    assert second_page is not None
    assert second_page.candidate_id == second.id
    assert second_page.id != first_page.id


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
    assert result.assembly["branch_key"] == brief.branch_key
    assert result.assembly["accepted_evidence_item_count"] > 0
    assert result.assembly["fields"]
    assert result.metrics["verified_capture_rate"] == 1.0
    assert result.metrics["evidence_item_count"] == len(result.evidence_items)


@pytest.mark.asyncio
async def test_run_research_pipeline_executes_gap_driven_repair_round() -> None:
    brief = ResearchBrief(
        run_id="run-1",
        topic="LLM APIs",
        competitor="AcmeAI",
        dimension="pricing",
        max_search_queries=1,
        max_candidates=2,
        max_fetches=1,
        max_repair_rounds=1,
    )
    search_queries: list[str] = []

    async def fake_search(query: str, max_results: int) -> list[SearchResult]:
        search_queries.append(query)
        if "official pricing plans billing" in query.casefold():
            return [
                SearchResult(
                    title="AcmeAI API pricing",
                    url="https://acme.example/docs/pricing",
                    snippet="AcmeAI API pricing has token costs and enterprise options.",
                )
            ][:max_results]
        return [
            SearchResult(
                title="AcmeAI product overview",
                url="https://acme.example/business/",
                snippet="AcmeAI helps teams build with AI.",
            )
        ][:max_results]

    async def fake_fetch(url: str) -> EvidenceFetchResult:
        if "docs/pricing" in url:
            return EvidenceFetchResult(
                url=url,
                ok=True,
                title="AcmeAI API pricing",
                text=(
                    "AcmeAI API pricing uses input and output token pricing. "
                    "Free, Pro, Team, and Enterprise plans are available. "
                    "GPT models include prices such as $1.25 per 1M input tokens "
                    "and $10 per 1M output tokens, with 100000 tokens included "
                    "per token billing examples. Enterprise customers can contact sales."
                ),
                content_hash="hash-acme-pricing-repair",
                status_code=200,
                fetch_method="webfetch_v2",
                quality_score=0.94,
            )
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="AcmeAI business overview",
            text="AcmeAI helps organizations adopt AI products and business workflows.",
            content_hash="hash-acme-overview",
            status_code=200,
            fetch_method="basic_httpx",
            quality_score=0.76,
        )

    result = await run_research_pipeline(brief, fetch=fake_fetch, search=fake_search)

    assert result.metrics["initial_gap_count"] > result.metrics["remaining_gap_count"]
    assert result.metrics["repair_round_count"] == 1
    assert result.metrics["gap_resolution_rate"] > 0
    assert any("official pricing plans billing" in query.casefold() for query in search_queries)
    assert any(
        item.field == "price_points" and item.status == "accepted"
        for item in result.evidence_items
    )


def test_release_gate_issues_become_repair_tasks_and_redo_scopes() -> None:
    gate = ReportReleaseGate(
        report_version_id="report-version-1",
        workspace_id="workspace-1",
        project_id="project-1",
        allowed=False,
        status="blocked",
        readiness=ProjectReadinessScore(
            project_id="project-1",
            score=72,
            risk_level="blocked",
            evidence_score=60,
            claim_score=70,
            coverage_score=70,
            qa_score=60,
            summary="Blocked by evidence quality.",
        ),
        qa_evaluation=BusinessQAEvaluation(
            project_id="project-1",
            scenario_id="l1_pricing_pack",
            competitor_layer="L1",
        ),
        issue_count=2,
        blocker_count=2,
        warn_count=0,
        issues=[
            BusinessQAFinding(
                id="release-issue-1",
                rule_id="claim_uses_low_confidence_evidence",
                rule_name="Claim evidence confidence",
                severity="blocker",
                competitor_name="Claude",
                dimension="pricing",
                message="Pricing claim depends on weak evidence.",
                evidence_ids=["evidence-1"],
                claim_ids=["claim-1"],
                recommendation="Collect verified pricing evidence.",
            ),
            BusinessQAFinding(
                id="release-issue-2",
                rule_id="report_citation_resolves",
                rule_name="Report citations resolve",
                severity="blocker",
                message="Report has unresolved source token.",
                recommendation="Replace unresolved source token.",
            ),
        ],
    )

    gaps = quality_gaps_from_release_gate(gate)
    tasks = repair_tasks_from_gaps(gaps)
    scopes = repair_tasks_to_redo_scopes(tasks)

    assert [gap.suggested_action for gap in gaps] == [
        "pricing_model_repair",
        "human_review",
    ]
    assert tasks[0].competitor == "Claude"
    assert tasks[0].dimension == "pricing"
    assert [scope.kind for scope in scopes] == ["collector", "writer_only"]
    assert scopes[0].target_subagent == "pricing"
    assert scopes[0].target_competitor == "Claude"
