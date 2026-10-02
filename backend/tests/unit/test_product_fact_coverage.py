from itertools import permutations
from types import SimpleNamespace

import pytest

from packages.identity import compute_content_hash
from packages.research.capture import select_capture_candidates
from packages.research.coverage_contract import evaluate_coverage_contract
from packages.research.models import CapturedPage, EvidenceItem, ResearchBrief, SourceCandidate
from packages.research.pipeline import run_research_pipeline
from packages.search import SearchResult


def _brief(**updates: object) -> ResearchBrief:
    values = {
        "run_id": "product-fact-coverage",
        "topic": "Tablet specifications",
        "competitor": "NovaTab",
        "dimension": "feature",
        "product_name": "NovaTab",
        "product_category": "tablet",
        "target_source_count": 2,
        "max_search_queries": 0,
        "max_candidates": 6,
        "max_fetches": 4,
        "max_repair_rounds": 0,
        "include_trusted_sources": False,
        "include_homepage_candidates": False,
    }
    values.update(updates)
    return ResearchBrief(**values)


@pytest.mark.parametrize(
    "product_scope",
    [{"product_name": "NovaTab", "product_category": ""},
     {"product_name": "", "product_category": "tablet"}],
)
def test_product_nonpricing_coverage_fails_without_accepted_facts(product_scope) -> None:
    coverage = evaluate_coverage_contract(
        _brief(**product_scope), candidates=[], pages=[], evidence_items=[], ledger=[],
    )

    assert coverage.passed is False
    assert coverage.required_intents == ["product_fact_support"]
    assert coverage.missing_intents == ["product_fact_support"]
    assert coverage.blocking_reasons
    assert coverage.repair_hints
    assert "NovaTab" in coverage.repair_hints[0]
    assert "feature" in coverage.repair_hints[0]
    assert coverage.metadata["required_source_count"] == 2
    assert coverage.metadata["usable_source_count"] == 0
    assert coverage.metadata["missing_source_count"] == 2


def _source(index: int) -> tuple[SourceCandidate, CapturedPage, EvidenceItem]:
    candidate = SourceCandidate(
        title="NovaTab specifications",
        url=f"https://reviews.example.com/novatab/specs-{index}",
        origin="web_search", competitor="NovaTab", dimension="feature",
        rank=index, confidence=0.8,
    )
    text = f"NovaTab supports {128 * (index + 1)}GB storage and a 6000mAh battery."
    page = CapturedPage(
        candidate_id=candidate.id, requested_url=candidate.url,
        final_url=candidate.url, status="ok", title=candidate.title,
        text=text, content_hash=compute_content_hash(text), quality_score=1.0,
    )
    item = EvidenceItem(
        competitor="NovaTab", dimension="feature", field="capability_1",
        value={"status": "supported", "evidence_terms": [text]},
        source_candidate_id=candidate.id, captured_page_id=page.id,
        source_url=page.final_url, quote=text, confidence=0.8, status="accepted",
    )
    return candidate, page, item


def _coverage(sources, **brief_updates):
    return evaluate_coverage_contract(
        _brief(**brief_updates), candidates=[source[0] for source in sources],
        pages=[source[1] for source in sources],
        evidence_items=[source[2] for source in sources], ledger=[],
    )


def test_product_coverage_passes_with_target_independent_third_party_sources() -> None:
    coverage = _coverage([_source(0), _source(1)])

    assert coverage.passed is True
    assert coverage.satisfied_intents == ["product_fact_support"]
    assert coverage.missing_intents == []
    assert coverage.blocking_reasons == []
    assert coverage.repair_hints == []
    assert coverage.metadata["usable_source_count"] == 2
    assert coverage.metadata["accepted_evidence_count"] == 2
    assert coverage.metadata["missing_source_count"] == 0


def test_product_coverage_fails_below_target_source_count() -> None:
    coverage = _coverage([_source(0)])

    assert coverage.passed is False
    assert coverage.metadata["usable_source_count"] == 1
    assert coverage.metadata["missing_source_count"] == 1
    assert "1" in coverage.blocking_reasons[0]
    assert "2" in coverage.blocking_reasons[0]
    assert "NovaTab" in coverage.repair_hints[0]


@pytest.mark.parametrize("duplicate", ["page", "url", "hash"])
def test_product_coverage_counts_duplicate_sources_once(duplicate: str) -> None:
    first = _source(0)
    candidate, page, item = _source(1)
    if duplicate == "page":
        candidate = first[0]
        page = first[1]
        item = first[2].model_copy(update={"field": "capability_2"})
    elif duplicate == "url":
        page = page.model_copy(update={
            "final_url": "https://REVIEWS.EXAMPLE.COM/novatab/specs-0/?ref=partner#specs",
        })
    else:
        page = page.model_copy(update={"content_hash": first[1].content_hash})

    coverage = _coverage([first, (candidate, page, item)])

    assert coverage.passed is False
    assert coverage.metadata["usable_source_count"] == 1


@pytest.mark.parametrize("order", list(permutations(range(3))))
@pytest.mark.parametrize("include_independent_source", [False, True])
def test_product_coverage_merges_linked_duplicates_independently_of_fact_order(
    order: tuple[int, ...], include_independent_source: bool,
) -> None:
    first = _source(0)
    candidate, page, item = _source(1)
    page = page.model_copy(update={"final_url": first[1].final_url + "?ref=partner"})
    item = item.model_copy(update={"source_url": page.final_url})
    bridge = (candidate, page, item)
    candidate, page, item = _source(2)
    page = page.model_copy(update={
        "text": bridge[1].text, "content_hash": bridge[1].content_hash,
    })
    item = item.model_copy(update={"quote": bridge[2].quote, "value": bridge[2].value})
    linked = [first, bridge, (candidate, page, item)]
    sources = [linked[index] for index in order]
    if include_independent_source:
        sources.append(_source(3))

    coverage = _coverage(sources)

    assert coverage.passed is include_independent_source
    assert coverage.metadata["usable_source_count"] == 1 + int(include_independent_source)
    assert coverage.metadata["accepted_evidence_count"] == 3 + int(include_independent_source)
    assert coverage.metadata["missing_source_count"] == int(not include_independent_source)


@pytest.mark.parametrize(
    "invalid_support",
    ["wrong_competitor", "wrong_dimension", "wrong_candidate", "wrong_page",
     "failed_page", "rejected_page", "rejected_fact", "unreviewed_fact", "missing_page"],
)
def test_product_coverage_ignores_invalid_fact_support(invalid_support: str) -> None:
    candidate, page, item = _source(0)
    if invalid_support == "wrong_competitor":
        item = item.model_copy(update={"competitor": "OtherTab"})
    elif invalid_support == "wrong_dimension":
        item = item.model_copy(update={"dimension": "persona"})
    elif invalid_support == "wrong_candidate":
        item = item.model_copy(update={"source_candidate_id": "other-candidate"})
    elif invalid_support == "wrong_page":
        item = item.model_copy(update={"captured_page_id": "other-page"})
    elif invalid_support in {"failed_page", "rejected_page"}:
        page = page.model_copy(update={"status": invalid_support.removesuffix("_page")})
    elif invalid_support in {"rejected_fact", "unreviewed_fact"}:
        item = item.model_copy(update={"status": invalid_support.removesuffix("_fact")})
    coverage = evaluate_coverage_contract(
        _brief(target_source_count=1), candidates=[candidate],
        pages=[] if invalid_support == "missing_page" else [page],
        evidence_items=[item], ledger=[],
    )

    assert coverage.passed is False
    assert coverage.metadata["usable_source_count"] == 0


def test_legacy_nonproduct_nonpricing_coverage_keeps_empty_contract() -> None:
    coverage = evaluate_coverage_contract(
        _brief(product_name="", product_category=""),
        candidates=[], pages=[], evidence_items=[], ledger=[],
    )

    assert coverage.passed is True
    assert coverage.required_intents == []


@pytest.mark.parametrize("product_scope", [True, False])
def test_pricing_contracts_keep_existing_source_requirements(product_scope: bool) -> None:
    candidate, page, item = _source(0)
    price_quote = "NovaTab costs $299 for the 128GB storage model."
    candidate = candidate.model_copy(update={"dimension": "pricing"})
    page = page.model_copy(update={
        "title": "NovaTab pricing", "text": price_quote,
        "content_hash": compute_content_hash(price_quote),
    })
    brief = _brief(
        dimension="pricing", product_name="NovaTab" if product_scope else "",
        product_category="tablet" if product_scope else "",
    )
    item = item.model_copy(update={
        "dimension": "pricing", "field": "price_rows", "quote": price_quote,
        "value": [{"price": "$299", "source_quote": price_quote}],
    })
    coverage = evaluate_coverage_contract(
        brief, candidates=[candidate], pages=[page], evidence_items=[item], ledger=[],
    )

    if product_scope:
        assert coverage.passed is True
        assert coverage.required_intents == ["current_plan_price_support"]
        assert coverage.metadata["contract"] == "product_pricing_v1"
    else:
        assert coverage.passed is False
        assert "official_pricing_page" in coverage.missing_intents
        assert coverage.metadata["contract"] == "pricing_v1"
    assert "product_fact_support" not in coverage.required_intents


def test_product_nonpricing_selection_keeps_overflow_for_runtime_fetch_budget() -> None:
    preferred = [_source(index)[0] for index in range(3)]
    fallback = _source(3)[0].model_copy(update={"confidence": 0.4})
    last_fallback = _source(4)[0].model_copy(update={"confidence": 0.3})
    selection = select_capture_candidates(
        _brief(), [fallback, *preferred, last_fallback],
    )

    assert selection.selected == preferred[:2]
    assert selection.overflow_queue == [preferred[2], fallback, last_fallback]
    assert fallback.id not in selection.skipped_reasons
    assert last_fallback.id not in selection.skipped_reasons


def test_product_selection_limits_initial_batch_to_fetch_budget() -> None:
    selection = select_capture_candidates(
        _brief(target_source_count=3, max_fetches=1), [_source(index)[0] for index in range(3)],
    )

    assert len(selection.selected) == 1
    assert selection.overflow_queue == [_source(index)[0] for index in (1, 2)]


def test_legacy_nonproduct_selection_keeps_existing_fetch_batch() -> None:
    candidates = [_source(index)[0] for index in range(4)]
    selection = select_capture_candidates(
        _brief(product_name="", product_category=""), candidates,
    )

    assert selection.selected == candidates
    assert selection.overflow_queue == []


class _FakeFetch:
    def __init__(
        self, fact_indices: set[int], duplicate_indices: dict[int, int] | None = None,
    ) -> None:
        self.fact_indices = fact_indices
        self.duplicate_indices = duplicate_indices or {}
        self.calls: list[str] = []

    async def __call__(self, url: str) -> SimpleNamespace:
        self.calls.append(url)
        index = int(url.rsplit("-", 1)[1])
        fact_index = self.duplicate_indices.get(index, index)
        text = (
            f"NovaTab supports {128 * (fact_index + 1)}GB storage and a 6000mAh battery."
            if index in self.fact_indices else
            "NovaTab appears in this tablet catalog with general company history "
            "and contact information."
        )
        return SimpleNamespace(
            url=url, title="NovaTab specifications", text=text, markdown=text,
            ok=True, quality_score=1.0, status_code=200, fetch_method="test_fetch",
        )


@pytest.mark.asyncio
async def test_pipeline_backfills_product_facts_until_independent_target_is_met() -> None:
    fetch = _FakeFetch({2, 3, 4})
    candidates = [_source(index)[0] for index in range(5)]
    result = await run_research_pipeline(_brief(), fetch=fetch, seed_candidates=candidates)

    assert fetch.calls == [candidate.url for candidate in candidates[:4]]
    assert result.coverage.passed is True
    assert result.coverage.metadata["usable_source_count"] == 2
    assert result.metrics["adaptive_backfill_fetch_count"] == 2
    assert len({
        item.captured_page_id for item in result.evidence_items if item.status == "accepted"
    }) == 2


@pytest.mark.asyncio
async def test_pipeline_stops_after_sufficient_initial_product_facts() -> None:
    fetch = _FakeFetch({0, 1, 2, 3})
    candidates = [_source(index)[0] for index in range(4)]
    result = await run_research_pipeline(_brief(), fetch=fetch, seed_candidates=candidates)

    assert fetch.calls == [candidate.url for candidate in candidates[:2]]
    assert result.coverage.passed is True
    assert result.metrics["adaptive_backfill_fetch_count"] == 0
    assert result.metrics["accepted_evidence_item_count"] >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fact_indices, usable_sources", [({3}, 0), ({2, 3}, 1)])
async def test_pipeline_stops_with_failed_coverage_when_product_budget_is_exhausted(
    fact_indices: set[int], usable_sources: int,
) -> None:
    fetch = _FakeFetch(fact_indices)
    candidates = [_source(index)[0] for index in range(5)]
    result = await run_research_pipeline(
        _brief(max_fetches=3), fetch=fetch, seed_candidates=candidates,
    )

    assert fetch.calls == [candidate.url for candidate in candidates[:3]]
    assert result.coverage.passed is False
    assert result.coverage.metadata["usable_source_count"] == usable_sources
    assert result.metrics["adaptive_backfill_fetch_count"] == 1
    assert result.metrics["accepted_evidence_item_count"] == usable_sources


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_first_repair", [False, True])
async def test_product_repair_stops_when_accumulated_independent_sources_meet_target(
    duplicate_first_repair: bool,
) -> None:
    fetch = _FakeFetch({0, 1, 3, 4, 5}, {3: 0} if duplicate_first_repair else {})
    candidate_count = 6 if duplicate_first_repair else 5
    candidates = [_source(index)[0] for index in range(candidate_count)]
    result = await run_research_pipeline(
        _brief(
            research_depth="standard", target_source_count=3,
            max_fetches=candidate_count, max_repair_rounds=1,
        ),
        fetch=fetch, seed_candidates=candidates,
    )

    expected_fetches = 5 if duplicate_first_repair else 4
    assert fetch.calls == [candidate.url for candidate in candidates[:expected_fetches]]
    assert result.coverage.passed is True
    assert result.coverage.metadata["usable_source_count"] == 3
    assert len(result.captured_pages) == expected_fetches
    assert result.metrics["capture_fetch_count"] == expected_fetches
    assert result.metrics["repair_round_count"] == 1
    assert result.metrics["repair_capture_count"] == expected_fetches - 3
    assert result.metrics["adaptive_backfill_fetch_count"] == int(duplicate_first_repair)


@pytest.mark.asyncio
async def test_product_repair_exhausts_budget_when_new_pages_repeat_prior_facts() -> None:
    fetch = _FakeFetch({0, 1, 3, 4, 5}, {3: 0, 4: 1})
    candidates = [_source(index)[0] for index in range(6)]
    result = await run_research_pipeline(
        _brief(
            research_depth="standard", target_source_count=3,
            max_fetches=5, max_repair_rounds=1,
        ),
        fetch=fetch, seed_candidates=candidates,
    )

    assert fetch.calls == [candidate.url for candidate in candidates[:5]]
    assert result.coverage.passed is False
    assert result.coverage.metadata["usable_source_count"] == 2
    assert result.metrics["capture_fetch_count"] == 5
    assert result.metrics["repair_capture_count"] == 2


@pytest.mark.asyncio
async def test_product_repair_cached_url_does_not_consume_remaining_fetch_slot() -> None:
    search_calls = 0
    fetch = _FakeFetch({0, 1, 3, 4}, {3: 0})

    async def search(query: str, max_results: int) -> list[SearchResult]:
        nonlocal search_calls
        search_calls += 1
        if search_calls <= 2:
            return []
        return [SearchResult(
            title="NovaTab specifications", url=_source(index)[0].url,
            snippet="NovaTab supports storage and battery specifications.",
            provider="perplexity",
        ) for index in (3, 0, 4)]

    candidates = [_source(index)[0] for index in (0, 1, 2)]
    candidates.append(_source(5)[0].model_copy(update={
        "url": "ftp://reviews.example.com/novatab/specs-5",
    }))
    result = await run_research_pipeline(
        _brief(
            research_depth="standard", target_source_count=3, max_fetches=5,
            max_repair_rounds=1, max_candidates=10, max_search_queries=4,
        ),
        fetch=fetch, search=search, seed_candidates=candidates,
    )

    assert fetch.calls == [_source(index)[0].url for index in (0, 1, 2, 3, 4)]
    assert result.metrics["capture_fetch_count"] == len(fetch.calls) == 5
    assert result.metrics["capture_cache_hits"] == 1
    assert result.coverage.passed is True
    assert result.coverage.metadata["usable_source_count"] == 3
