"""Anonymous real pipeline checks with fixed in-process transports."""

import hashlib
import json

import pytest

from packages.business_intel import official_registry
from packages.research.extraction.semantic import semantic_extraction
from packages.research.models import ResearchBrief, SourceCandidate
from packages.research.pipeline import _repair_brief, run_research_pipeline
from packages.research.question_evidence import question_evidence_gaps
from packages.research.repair import repair_tasks_from_gaps
from packages.search import SearchResult
from packages.tools.evidence_fetch import EvidenceFetchResult

BASE = "Example Suite members can organize their project materials in shared folders."
TARGET = "Assistant Chat is only available on the Summit plan."


@pytest.fixture
def transport(tmp_path, monkeypatch):
    paths = ("intro", "permissions", "assistant", "extra")
    urls = {path: f"https://docs.example-suite.test/{path}" for path in paths}
    registry = tmp_path / "official.json"
    registry.write_text(
        json.dumps(
            [
                {
                    "product": "Example Suite",
                    "documents": [
                        {
                            "title": f"Example Suite {path}",
                            "url": url,
                            "dimension": "feature",
                            "reviewed_by": "test_operator",
                            "reviewed_at": "2026-01-01T00:00:00Z",
                            "review_basis": "Anonymous exact-document authority fixture.",
                        }
                        for path, url in urls.items()
                    ],
                }
            ]
        )
    )
    monkeypatch.setattr(official_registry, "REGISTRY_PATH", registry)
    official_registry.registry_snapshot.cache_clear()
    calls = {"fetch": [], "search": [], "semantic": [], "review": []}
    bodies = {
        urls["intro"]: BASE,
        urls["permissions"]: "Members can edit shared documents on all plans.",
        urls["assistant"]: TARGET,
        urls["extra"]: TARGET,
    }

    async def fetch(url):
        calls["fetch"].append(url)
        body = bodies.get(url, TARGET)
        return EvidenceFetchResult(
            url=url,
            title=f"Example Suite {url.rsplit('/', 1)[-1]}",
            text=body,
            ok=True,
            status_code=200,
            quality_score=0.9,
            source_material_level="full_source",
            content_hash=hashlib.sha256(body.encode()).hexdigest(),
            fetch_method="basic_httpx",
        )

    async def semantic(active, page):
        calls["semantic"].append(
            (page.final_url, tuple(active.metadata.get("active_question_ids", [])))
        )
        return semantic_extraction(active, page, {"facts": [{"quote": page.text}]})

    async def review(active, items):
        calls["review"].append(tuple(item.id for item in items if item.status == "accepted"))
        found = list(dict.fromkeys(
            item.id for item in items if item.status == "accepted" and item.quote == TARGET
        ))
        return {
            "questions": [
                {
                    "question_id": question.question_id,
                    "status": "candidate" if found else "missing",
                    "evidence_ids": found,
                    "missing_fields": [] if found else ["feature availability"],
                    "reason": "Candidate originals exist."
                    if found
                    else "No original for this feature condition.",
                }
                for question in active.questions
            ]
        }

    def candidate(path, rank=0):
        return SourceCandidate(
            title=f"Example Suite {path}",
            url=urls[path],
            origin="manual",
            competitor="Example Suite",
            dimension="feature",
            rank=rank,
            confidence=0.8,
        )

    yield calls, bodies, urls, fetch, semantic, review, candidate
    official_registry.registry_snapshot.cache_clear()


def brief(**changes):
    return ResearchBrief(
        **(
            dict(
                run_id="question-pipeline",
                topic="General feature research",
                competitor="Example Suite",
                dimension="feature",
                product_category="documents",
                target_source_count=1,
                max_fetches=3,
                max_search_queries=1,
                max_candidates=5,
                max_repair_rounds=1,
                include_homepage_candidates=False,
                include_trusted_sources=False,
                questions=[
                    {"question_id": "q1", "question": "Can Basic members use Assistant Chat?"}
                ],
            )
            | changes
        )
    )


def question_gaps(result):
    return [gap for gap in result.gaps if gap.metadata.get("source") == "question_coverage"]


@pytest.mark.asyncio
async def test_generic_topic_availability_question_uses_originals_without_semantic_model(transport):
    from packages.research.evidence.operations import required_operations

    calls, _, _, fetch, _, review, candidate = transport
    request = brief(max_repair_rounds=0, max_search_queries=0, max_fetches=1)
    assert not required_operations(request.topic, request.product_use_cases)
    result = await run_research_pipeline(
        request, fetch=fetch, seed_candidates=[candidate("assistant")], question_review=review,
    )
    assert any(item.status == "accepted" and item.quote == TARGET for item in result.evidence_items)
    assert any(field.evidence_quote == TARGET for field in result.normalized_fields)
    assert not question_gaps(result)
    assert calls["semantic"] == []


@pytest.mark.asyncio
async def test_third_captured_page_is_prioritized_by_question_before_semantic_page_limit(transport):
    calls, _, urls, fetch, semantic, review, candidate = transport
    result = await run_research_pipeline(
        brief(target_source_count=3, max_repair_rounds=0, max_candidates=3),
        fetch=fetch,
        seed_candidates=[
            candidate("intro", 0),
            candidate("permissions", 1),
            candidate("assistant", 2),
        ],
        semantic_extract=semantic,
        question_review=review,
    )
    assert calls["semantic"][0][0] == urls["assistant"]
    assert len(calls["fetch"]) == 3 and len(calls["review"]) == 1
    assert not question_gaps(result)
    assert any(field.evidence_quote == TARGET for field in result.normalized_fields)
    assert result.metrics["question_stop_reason"] == "candidate_evidence_found"


@pytest.mark.asyncio
async def test_existing_body_missing_question_focus_adds_admitted_fields_without_fetching_again(
    transport,
):
    calls, bodies, urls, fetch, _, _, candidate = transport
    focus_quote = (
        "Assistant Chat answers documentation questions using context "
        "from published workspace pages."
    )
    bodies[urls["intro"]] = BASE + "\n\n" + focus_quote

    async def semantic(active, page):
        focus = tuple(active.metadata.get("active_question_ids", []))
        calls["semantic"].append((page.final_url, focus))
        quote = focus_quote if focus == ("q2",) else BASE
        return semantic_extraction(active, page, {"facts": [{"quote": quote}]})

    async def review(active, items):
        calls["review"].append(tuple(item.id for item in items if item.status == "accepted"))
        rows = []
        for question in active.questions:
            quote = BASE if question.question_id == "q1" else focus_quote
            ids = list(dict.fromkeys(
                item.id for item in items if item.status == "accepted" and item.quote == quote
            ))
            rows.append(
                {
                    "question_id": question.question_id,
                    "status": "candidate" if ids else "missing",
                    "evidence_ids": ids,
                    "missing_fields": [] if ids else ["plan condition"],
                    "reason": "Candidates for review."
                    if ids
                    else "The source observation is missing.",
                }
            )
        return {"questions": rows}

    request = brief(
        max_fetches=1,
        max_search_queries=0,
        questions=[
            {"question_id": "q1", "question": "Can members organize project materials?"},
            {"question_id": "q2", "question": "What does Assistant Chat do?"},
        ],
    )
    result = await run_research_pipeline(
        request,
        fetch=fetch,
        seed_candidates=[candidate("intro")],
        semantic_extract=semantic,
        question_review=review,
    )
    assert calls["fetch"] == [urls["intro"]]
    assert len(calls["semantic"]) == 2 and calls["semantic"][-1][1] == ("q2",)
    assert len(calls["review"]) == 2 and not question_gaps(result), [
        (item.quote, item.status, item.rejection_reason) for item in result.evidence_items
    ]
    assert {BASE, focus_quote} <= {field.evidence_quote for field in result.normalized_fields}
    assert result.metrics["question_repair_round_count"] == 1
    assert result.coverage.metadata["question_remaining_gap_count"] == 0


@pytest.mark.asyncio
async def test_unfetched_seed_is_reused_before_search_and_enters_normal_evidence(transport):
    calls, _, urls, fetch, semantic, review, candidate = transport

    async def search(query, limit):
        pytest.fail("An available seed must be used before spending discovery budget.")

    result = await run_research_pipeline(
        brief(max_fetches=2),
        fetch=fetch,
        search=search,
        seed_candidates=[candidate("intro", 0), candidate("assistant", 1)],
        semantic_extract=semantic,
        question_review=review,
    )
    assert calls["fetch"] == [urls["intro"], urls["assistant"]]
    assert len(calls["review"]) == 2 and not question_gaps(result)
    assert any(field.evidence_quote == TARGET for field in result.normalized_fields)
    assert result.metrics["operation_repair_round_count"] == 0


@pytest.mark.asyncio
async def test_no_depth_search_and_fetch_repair_stays_within_original_budgets(transport):
    calls, _, urls, fetch, semantic, review, candidate = transport

    async def search(query, limit):
        calls["search"].append(query)
        assert "official" in query and "Assistant Chat" in query
        return [
            SearchResult(title="Example Suite assistant", url=urls["assistant"], snippet=TARGET)
        ]

    request = brief(max_fetches=2, max_search_queries=1, max_candidates=2)
    result = await run_research_pipeline(
        request,
        fetch=fetch,
        search=search,
        seed_candidates=[candidate("intro")],
        semantic_extract=semantic,
        question_review=review,
    )
    assert len(calls["fetch"]) == 2 and len(calls["search"]) == 1
    assert len(result.candidates) <= 2 and not question_gaps(result)
    assert result.metrics["question_review_count"] == 2


@pytest.mark.asyncio
async def test_same_focus_without_new_evidence_stops_and_keeps_explicit_question_gap(transport):
    calls, _, urls, fetch, semantic, review, candidate = transport

    async def search(query, limit):
        calls["search"].append(query)
        return []

    result = await run_research_pipeline(
        brief(),
        fetch=fetch,
        search=search,
        seed_candidates=[candidate("intro")],
        semantic_extract=semantic,
        question_review=review,
    )
    assert len(calls["semantic"]) == 1
    assert len(calls["review"]) == 1 and len(calls["search"]) == 1
    assert len(question_gaps(result)) == 1
    assert result.metrics["question_stop_reason"] == "no_progress"
    assert result.metrics["question_repair_round_count"] == 1


@pytest.mark.asyncio
async def test_missing_review_callback_is_unverified_and_does_not_spend_repair_budget(transport):
    calls, _, _, fetch, semantic, _, candidate = transport
    result = await run_research_pipeline(
        brief(), fetch=fetch, seed_candidates=[candidate("intro")], semantic_extract=semantic
    )
    assert len(question_gaps(result)) == 1
    assert result.metrics["question_review_count"] == 0
    assert result.metrics["question_stop_reason"] == "unverified"
    assert len(calls["semantic"]) == 1


@pytest.mark.asyncio
async def test_invalid_candidate_ids_cannot_close_gap_or_trigger_unbounded_review(transport):
    calls, _, _, fetch, semantic, _, candidate = transport

    async def invalid(active, items):
        calls["review"].append(1)
        return {
            "questions": [
                {
                    "question_id": "q1",
                    "status": "candidate",
                    "evidence_ids": ["foreign"],
                    "missing_fields": [],
                    "reason": "An invented identity cannot support this request.",
                }
            ]
        }

    result = await run_research_pipeline(
        brief(max_fetches=1),
        fetch=fetch,
        seed_candidates=[candidate("intro")],
        semantic_extract=semantic,
        question_review=invalid,
    )
    assert len(question_gaps(result)) == 1 and len(calls["review"]) == 1
    assert result.coverage.metadata["question_remaining_gap_count"] == 1
    assert result.metrics["question_stop_reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_callback_capacity_failure_stops_without_claiming_evidence_absent(transport):
    _, _, _, fetch, semantic, _, candidate = transport

    async def capacity(active, items):
        return {"_question_stop_reason": "capacity_exceeded",
                "_question_review_metadata": {"eligible_evidence_count": 3,
                    "omitted_evidence_count": 2, "max_bytes": 12000}}

    result = await run_research_pipeline(
        brief(),
        fetch=fetch,
        seed_candidates=[candidate("intro")],
        semantic_extract=semantic,
        question_review=capacity,
    )
    assert question_gaps(result) and result.metrics["question_stop_reason"] == "capacity_exceeded"
    assert result.metrics["question_review_count"] == 1
    assert result.metrics["question_review_metadata"]["omitted_evidence_count"] == 2
    assert result.coverage.metadata["question_review_metadata"]["eligible_evidence_count"] == 3


@pytest.mark.asyncio
async def test_evidence_authorization_errors_from_review_propagate(transport):
    _, _, _, fetch, semantic, _, candidate = transport

    async def unauthorized(active, items):
        raise RuntimeError("Evidence authorization was rejected.")

    with pytest.raises(RuntimeError, match="authorization"):
        await run_research_pipeline(
            brief(),
            fetch=fetch,
            seed_candidates=[candidate("intro")],
            semantic_extract=semantic,
            question_review=unauthorized,
        )


@pytest.mark.asyncio
async def test_evidence_guard_value_error_is_never_mistaken_for_a_capacity_stop(transport):
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError

    _, _, _, fetch, semantic, _, candidate = transport

    async def unauthorized(active, items):
        raise EvidenceUseRejectedError("Evidence capacity cannot override authorization.")

    with pytest.raises(EvidenceUseRejectedError):
        await run_research_pipeline(
            brief(), fetch=fetch, seed_candidates=[candidate("intro")],
            semantic_extract=semantic, question_review=unauthorized,
        )


@pytest.mark.asyncio
async def test_unregistered_discovery_stays_rejected_with_explicit_authority_stop(transport):
    calls, _, _, fetch, semantic, review, candidate = transport

    async def search(query, limit):
        calls["search"].append(query)
        return [
            SearchResult(
                title="Example Suite unknown",
                url="https://docs.example-suite.test/unknown",
                snippet=TARGET,
            )
        ]

    result = await run_research_pipeline(
        brief(max_fetches=2),
        fetch=fetch,
        search=search,
        seed_candidates=[candidate("intro")],
        semantic_extract=semantic,
        question_review=review,
    )
    assert result.metrics["question_stop_reason"] == "authority_unverified"
    assert result.captured_pages[-1].status == "rejected" and question_gaps(result)
    assert len(calls["review"]) == 1


@pytest.mark.asyncio
async def test_new_unrelated_observations_get_only_one_final_review_and_no_second_repair(transport):
    calls, _, urls, fetch, semantic, _, candidate = transport

    async def search(query, limit):
        calls["search"].append(query)
        return [
            SearchResult(title="Example Suite permissions", url=urls["permissions"], snippet=BASE)
        ]

    async def missing(active, items):
        calls["review"].append(1)
        return {
            "questions": [
                {
                    "question_id": "q1",
                    "status": "missing",
                    "evidence_ids": [],
                    "missing_fields": ["feature availability"],
                    "reason": "These originals cover another capability.",
                }
            ]
        }

    result = await run_research_pipeline(
        brief(max_fetches=3, max_search_queries=2, max_repair_rounds=3),
        fetch=fetch,
        search=search,
        seed_candidates=[candidate("intro")],
        semantic_extract=semantic,
        question_review=missing,
    )
    assert len(calls["review"]) == 2 and len(calls["search"]) == 1
    assert result.metrics["question_repair_round_count"] == 1 and question_gaps(result)
    assert result.metrics["question_stop_reason"] == "no_progress"


@pytest.mark.asyncio
async def test_unhashable_internal_stop_marker_fails_closed_without_a_parser_crash(transport):
    _, _, _, fetch, semantic, _, candidate = transport

    async def invalid(active, items):
        return {"questions": [], "_question_stop_reason": []}

    result = await run_research_pipeline(
        brief(max_repair_rounds=0),
        fetch=fetch,
        seed_candidates=[candidate("intro")],
        semantic_extract=semantic,
        question_review=invalid,
    )
    assert question_gaps(result)


def test_question_repair_brief_never_expands_undeclared_depth_budgets():
    request = brief(max_fetches=1, max_search_queries=1, max_candidates=2)
    tasks = repair_tasks_from_gaps(question_evidence_gaps(request, []))
    repaired = _repair_brief(request, tasks, round_index=1)
    assert repaired.max_fetches == request.max_fetches
    assert repaired.max_search_queries == request.max_search_queries
    assert repaired.max_candidates == request.max_candidates
