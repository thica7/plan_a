from datetime import datetime, timedelta

import pytest

from packages.agents import SubagentContext
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.identity import compute_competitor_id, compute_content_hash
from packages.memory import RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.research.models import ResearchBrief
from packages.research.pipeline import run_research_pipeline
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.enterprise import (
    ClaimRecord,
    EnterpriseRunProjection,
    EvidenceRecord,
    ReportVersionRecord,
)
from packages.schema.models import AnalysisPlan, RawSource, TargetProduct
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry
from packages.tools.evidence_fetch import EvidenceFetchResult

NOW = datetime(2026, 10, 2, 12)


def plan(name="Cursor 2.0", market="US", category="AI IDE", topic="AI coding"):
    return AnalysisPlan(
        topic=topic,
        competitors=["Cursor"],
        dimensions=["feature", "pricing"],
        target_product=TargetProduct(name=name, category=category, market=market),
    )


def old_run(
    store,
    *,
    run_id="old",
    project_id="old-project",
    workspace_id="ws",
    old_plan=None,
    mode="real",
    quality="accepted",
    age=2,
    dimension="feature",
    url="https://cursor.com/docs/features",
):
    old_plan = old_plan or plan()
    detail = RunDetail(
        id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        topic=old_plan.topic,
        status="completed",
        execution_mode=mode,
        created_at=NOW,
        updated_at=NOW,
        plan=old_plan,
    )
    context = store.start_run(detail)
    evidence = EvidenceRecord(
        id=f"e-{run_id}",
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        raw_source_id=f"old-source-{run_id}",
        competitor_id=context.competitor_id_map["Cursor"],
        dimension=dimension,
        source_type="webpage_verified",
        title="Cursor original page",
        url=url,
        snippet="Old assertion must never be copied as current evidence.",
        content_hash="old-hash",
        quality_label=quality,
        captured_at=NOW - timedelta(days=age),
        metadata={"source_published_at": "2026-09-01", "source_updated_at": "2026-09-28"},
    )
    claim = ClaimRecord(
        id=f"c-{run_id}",
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        competitor_id=evidence.competitor_id,
        claim_type=dimension,
        claim_text="Historical conclusion [source:old-source]",
        evidence_ids=[evidence.id],
        status="accepted",
    )
    report = ReportVersionRecord(
        id=f"r-{run_id}",
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        version_number=1,
        topic_normalized="ai-coding",
        competitor_set_hash="fixture",
        evidence_ids=[evidence.id],
        claim_ids=[claim.id],
        report_md="DO NOT IMPORT FULL REPORT " * 1000,
        quality_metadata={
            "execution_mode": mode,
            "analysis_plan": old_plan.model_dump(mode="json"),
        },
        created_at=NOW - timedelta(days=1),
    )
    projection = EnterpriseRunProjection(
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        evidence_records=[evidence],
        claim_records=[claim],
        report_version=report,
    )
    store.save_projection(projection)
    detail.enterprise_projection = projection
    return detail


def reuse(store, current_plan=None, runs=()):
    from packages.memory.report_reuse import build_report_reuse_context

    return build_report_reuse_context(
        store,
        workspace_id="ws",
        project_id="new-project",
        plan=current_plan or plan(),
        historical_runs=runs,
        now=NOW,
    )


def test_old_plans_default_to_empty_report_reuse_context():
    current = AnalysisPlan(topic="Old record", competitors=["Cursor"], dimensions=["feature"])
    assert hasattr(current, "report_reuse_context")
    assert current.report_reuse_context.selected == []


def test_related_real_report_preserves_lineage_without_importing_markdown_or_citations():
    store = EnterpriseMemoryStore()
    old_run(store)
    context = reuse(store)
    assert [item.report_id for item in context.selected] == ["r-old"]
    assert len(context.refresh_required) == 1
    link = context.refresh_required[0]
    assert link.url == "https://cursor.com/docs/features"
    assert link.captured_at == NOW - timedelta(days=2)
    assert link.source_published_at == "2026-09-01"
    assert link.source_updated_at == "2026-09-28"
    assert link.requires_refresh is True
    assert context.selected[0].advisory_facts == ["Historical conclusion"]
    assert "DO NOT IMPORT" not in context.model_dump_json()
    assert "[source:" not in context.model_dump_json()


@pytest.mark.parametrize("mode", ["demo", "simulated", "unknown", None])
def test_non_explicit_real_report_is_not_reused(mode):
    store = EnterpriseMemoryStore()
    detail = old_run(store, mode="demo")
    report = store.report_versions["r-old"]
    report.quality_metadata["execution_mode"] = mode
    report.quality_metadata.pop("analysis_plan")
    context = reuse(store)
    assert context.selected == []
    assert context.refresh_required == []
    assert "not_explicit_real" in [item.reason for item in context.skipped]
    # Only an explicitly real RunDetail can prove a missing report mode.
    if mode is None:
        detail.execution_mode = "real"
        detail.enterprise_projection.report_version.quality_metadata = {
            "analysis_plan": plan().model_dump(mode="json")
        }
        context = reuse(EnterpriseMemoryStore(), runs=[detail])
        assert len(context.selected) == 1


@pytest.mark.parametrize(
    "old_plan,reason",
    [
        (plan(market="China"), "market_conflict"),
        (plan(name="Cursor 1.0"), "version_conflict"),
        (plan(name="Cursor 20"), "version_conflict"),
        (plan(category="CRM"), "category_conflict"),
        (
            AnalysisPlan(topic="AI coding", competitors=["Unrelated"], dimensions=["feature"]),
            "product_identity_missing",
        ),
    ],
)
def test_relevance_rejects_explicit_conflicts_and_generic_topic_match(old_plan, reason):
    store = EnterpriseMemoryStore()
    # Fixture evidence belongs to Cursor; the old report plan is the relevance authority.
    old_run(store)
    store.report_versions["r-old"].quality_metadata["analysis_plan"] = old_plan.model_dump(
        mode="json"
    )
    context = reuse(store)
    assert context.selected == []
    assert reason in [item.reason for item in context.skipped]


def test_scope_checks_projects_reports_evidence_claims_and_persisted_projection():
    store = EnterpriseMemoryStore()
    foreign = old_run(store, workspace_id="foreign", project_id="foreign-project", run_id="foreign")
    valid = old_run(store)
    store.evidence_records["e-old"].workspace_id = "foreign"
    context = reuse(store, runs=[foreign])
    assert context.refresh_required == []
    assert context.selected == []
    assert "scope_mismatch" in [item.reason for item in context.skipped]
    valid.enterprise_projection.workspace_id = "foreign"
    assert reuse(EnterpriseMemoryStore(), runs=[valid]).selected == []


@pytest.mark.parametrize(
    "quality,age,dimension,reason",
    [
        ("unreviewed", 2, "feature", "unreviewed"),
        ("stale", 2, "feature", "stale"),
        ("accepted", 31, "feature", "expired"),
        ("accepted", 8, "pricing", "expired"),
        ("accepted", 8, "version", "expired"),
    ],
)
def test_unreviewed_and_expired_facts_only_offer_original_refresh_url(
    quality, age, dimension, reason
):
    store = EnterpriseMemoryStore()
    old_run(store, quality=quality, age=age, dimension=dimension)
    context = reuse(store)
    assert context.selected[0].advisory_facts == []
    assert context.refresh_required[0].reason == reason
    assert context.refresh_required[0].freshness != "fresh"
    assert reason in [item.reason for item in context.skipped]


@pytest.mark.parametrize(
    "change,reason",
    [
        ("missing_url", "missing_url"),
        ("rejected", "rejected"),
        ("simulated", "simulated_source"),
        ("unsafe", "unsafe_url"),
    ],
)
def test_unsafe_or_rejected_evidence_is_skipped(change, reason):
    store = EnterpriseMemoryStore()
    old_run(store)
    evidence = store.evidence_records["e-old"]
    if change == "missing_url":
        evidence.url = None
    if change == "rejected":
        evidence.quality_label = "rejected"
    if change == "simulated":
        evidence.source_type = "survey_simulated"
    if change == "unsafe":
        evidence.url = "http://192.168.1.2/secret"
    context = reuse(store)
    assert context.refresh_required == []
    assert reason in [item.reason for item in context.skipped]


def test_only_latest_report_per_run_and_bounded_unique_branch_urls():
    from packages.memory.report_reuse import MAX_CONTEXT_CHARS, report_reuse_candidates

    store = EnterpriseMemoryStore()
    for index in range(5):
        old_run(store, run_id=f"old{index}", url=f"https://cursor.com/docs/features/{index}")
    latest = store.report_versions["r-old0"].model_copy(deep=True)
    latest.id = "latest"
    latest.version_number = 2
    latest.created_at = NOW
    store.report_versions[latest.id] = latest
    context = reuse(store)
    assert len(context.selected) == 3
    assert "latest" in [item.report_id for item in context.selected]
    assert "r-old0" not in [item.report_id for item in context.selected]
    assert sum(len(item.advisory_facts) for item in context.selected) <= 6
    assert len(context.model_dump_json()) <= MAX_CONTEXT_CHARS
    current = plan().model_copy(update={"report_reuse_context": context})
    candidates = report_reuse_candidates(current, "Cursor", "feature")
    assert len(candidates) == 2
    assert all(item.origin == "manual" and not item.snippet for item in candidates)
    assert all(item.date is None and item.last_updated is None for item in candidates)
    assert len({item.url for item in candidates}) == 2


def test_scope_mismatched_claim_never_enters_advisory_facts():
    store = EnterpriseMemoryStore()
    old_run(store)
    store.claim_records["c-old"].project_id = "another-project"
    context = reuse(store)
    assert context.selected[0].advisory_facts == []
    assert "scope_mismatch" in [item.reason for item in context.skipped]


def test_price_claim_on_general_feature_source_uses_the_short_ttl():
    store = EnterpriseMemoryStore()
    old_run(store, dimension="feature", age=8)
    store.claim_records["c-old"].claim_type = "pricing"
    context = reuse(store)
    assert context.selected[0].advisory_facts == []
    assert "expired" in [item.reason for item in context.skipped]


@pytest.mark.parametrize("source_type", ["llm_public_knowledge", "webpage_demo"])
def test_real_report_cannot_turn_non_fetched_material_into_history_facts(source_type):
    store = EnterpriseMemoryStore()
    old_run(store)
    store.evidence_records["e-old"].source_type = source_type
    context = reuse(store)
    assert context.selected == []
    assert context.refresh_required == []
    assert "non_fetched_source" in [item.reason for item in context.skipped]


def test_unknown_capture_provenance_only_offers_the_original_refresh_url():
    store = EnterpriseMemoryStore()
    old_run(store)
    store.evidence_records["e-old"].source_type = "unknown"
    context = reuse(store)
    assert context.selected[0].advisory_facts == []
    assert context.refresh_required[0].freshness == "unreviewed"
    assert context.refresh_required[0].reason == "provenance_unknown"


@pytest.mark.parametrize("mode", ["unknown", "auto", None])
def test_explicit_non_real_evidence_mode_cannot_supply_fresh_history_facts(mode):
    store = EnterpriseMemoryStore()
    old_run(store)
    store.evidence_records["e-old"].metadata["execution_mode"] = mode
    context = reuse(store)
    assert context.selected[0].advisory_facts == []
    assert context.refresh_required[0].freshness == "unreviewed"
    assert context.refresh_required[0].reason == "provenance_unknown"


def test_related_common_product_does_not_import_another_products_old_version_evidence():
    store = EnterpriseMemoryStore()
    old_plan = AnalysisPlan(
        topic="AI coding", competitors=["Cursor", "Cursor 1.0", "Common"], dimensions=["feature"]
    )
    old_run(store, old_plan=old_plan)
    old_evidence = store.evidence_records["e-old"]
    old_evidence.competitor_id = compute_competitor_id("ws", "Cursor 1.0")
    old_claim = store.claim_records["c-old"]
    old_claim.competitor_id = old_evidence.competitor_id
    common = old_evidence.model_copy(deep=True)
    common.id = "common-evidence"
    common.competitor_id = compute_competitor_id("ws", "Common")
    common.url = "https://common.example/docs/features"
    store.evidence_records[common.id] = common
    common_claim = old_claim.model_copy(deep=True)
    common_claim.id = "common-claim"
    common_claim.competitor_id = common.competitor_id
    common_claim.claim_text = "Common historical advisory"
    common_claim.evidence_ids = [common.id]
    store.claim_records[common_claim.id] = common_claim
    store.report_versions["r-old"].evidence_ids.append(common.id)
    store.report_versions["r-old"].claim_ids.append(common_claim.id)
    current = AnalysisPlan(
        topic="AI coding", competitors=["Cursor 2.0", "Common"], dimensions=["feature"]
    )
    context = reuse(store, current_plan=current)
    assert context.selected[0].advisory_facts == ["Common historical advisory"]
    assert [link.competitor for link in context.refresh_required] == ["Common"]
    assert any(
        skip.evidence_id == "e-old" and skip.reason == "version_conflict"
        for skip in context.skipped
    )


def test_explicit_demo_run_cannot_be_overridden_by_report_real_metadata():
    store = EnterpriseMemoryStore()
    detail = old_run(store, mode="demo")
    store.report_versions["r-old"].quality_metadata["execution_mode"] = "real"
    context = reuse(store, runs=[detail])
    assert context.selected == []
    assert "not_explicit_real" in [item.reason for item in context.skipped]


def test_context_character_cap_handles_oversized_original_urls():
    from packages.memory.report_reuse import MAX_CONTEXT_CHARS

    store = EnterpriseMemoryStore()
    old_run(store, url="https://cursor.com/docs/" + "a" * 2000)
    for index in range(6):
        evidence = store.evidence_records["e-old"].model_copy(deep=True)
        evidence.id = f"long-{index}"
        evidence.url = f"https://cursor.com/docs/{index}/" + "a" * 2000
        store.evidence_records[evidence.id] = evidence
        store.report_versions["r-old"].evidence_ids.append(evidence.id)
    context = reuse(store)
    assert len(context.model_dump_json()) <= MAX_CONTEXT_CHARS
    assert context.refresh_required == []
    assert "context_limit" in [item.reason for item in context.skipped]


def service(store, journal=None):
    return RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=False, ark_api_key="fixture-key", ark_model="fixture-model"),
        enterprise_store=store,
        journal=journal,
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )


@pytest.mark.asyncio
async def test_restart_uses_persisted_projection_read_only_after_start_run_resolves_project(
    tmp_path,
):
    store = EnterpriseMemoryStore()
    detail = old_run(store)
    journal = RunJournal(tmp_path / "journal.sqlite")
    journal.save_run(detail)
    restarted_store = EnterpriseMemoryStore()
    restarted = service(restarted_store, RunJournal(tmp_path / "journal.sqlite"))
    try:
        new = await restarted.create_run(
            RunCreateRequest(
                topic="AI coding",
                workspace_id="ws",
                target_product=plan().target_product,
                competitors=["Cursor"],
                dimensions=["feature"],
                execution_mode="real",
            )
        )
        assert new.project_id is not None
        assert new.plan.report_reuse_context.selected[0].report_id == "r-old"
        assert restarted_store.report_versions == {}
        assert restarted_store.evidence_records == {}
        assert journal.load_run(detail.id).model_dump() == detail.model_dump()
        before = new.plan.report_reuse_context.model_dump()

        async def planner_result(*args, **kwargs):
            return {"complexity": "low", "homepage_hints": {}}

        async def target_research(*args, **kwargs):
            return None

        restarted._trace_llm_json = planner_result
        restarted._research_target_product = target_research
        await restarted._real_planner_step(restarted._runs[new.id])
        assert new.plan.report_reuse_context.model_dump() == before
    finally:
        await restarted._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_identity", [False, True])
async def test_history_candidate_is_currently_fetched_and_admitted_before_raw_source(
    wrong_identity,
):
    store = EnterpriseMemoryStore()
    old_run(store)
    runner = service(store)
    calls = []
    try:
        detail = await runner.create_run(
            RunCreateRequest(
                topic="AI coding",
                workspace_id="ws",
                project_id="new-project",
                target_product=plan().target_product,
                competitors=["Cursor"],
                dimensions=["feature"],
                execution_mode="real",
            )
        )
        record = runner._runs[detail.id]

        async def fetch(record, agent, subagent, url, context=None):
            calls.append(url)
            product = "Salesforce CRM" if wrong_identity else "Cursor"
            text = (
                f"{product} supports code completion, repository indexing, "
                "multi-file editing and agent workflows. " * 3
            )
            return EvidenceFetchResult(
                url=url,
                ok=True,
                title=f"{product} features",
                text=text,
                content_hash="current-hash",
                status_code=200,
                fetch_method="fixture_fetch",
                quality_score=0.95,
                text_length=len(text),
                capture_metadata={
                    "source_published_at": "2026-10-01",
                    "source_updated_at": "2026-10-02",
                },
            )

        runner._trace_fetch = fetch
        sources = await runner._collect_competitor_with_research_pipeline(
            record,
            detail,
            "feature",
            "Cursor",
            SubagentContext(run_id=detail.id, agent="collector", subagent="feature::Cursor"),
            batch_sources=[],
            target_source_count=1,
            include_official=False,
            enable_search=False,
            enable_repair=False,
        )
        assert calls == ["https://cursor.com/docs/features"]
        if wrong_identity:
            assert sources == []
        else:
            assert len(sources) == 1
            assert sources[0].content_hash == "current-hash"
            assert sources[0].candidate_origin == "manual"
            assert sources[0].metadata["history_report_id"] == "r-old"
            assert sources[0].metadata["history_evidence_id"] == "e-old"
            assert sources[0].metadata["source_published_at"] == "2026-10-01"
            assert sources[0].metadata["source_updated_at"] == "2026-10-02"
            assert sources[0].metadata["history_source_published_at"] == "2026-09-01"
            assert sources[0].metadata["history_source_updated_at"] == "2026-09-28"
            assert "Old assertion" not in sources[0].snippet
            assert "old-source" not in sources[0].id
    finally:
        await runner._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_reviewer_refresh_keeps_its_current_urls_ahead_of_history():
    store = EnterpriseMemoryStore()
    old_run(store)
    runner = service(store)
    calls = []
    try:
        detail = await runner.create_run(
            RunCreateRequest(
                topic="AI coding",
                workspace_id="ws",
                project_id="new-project",
                target_product=plan().target_product,
                competitors=["Cursor"],
                dimensions=["feature"],
                execution_mode="real",
            )
        )
        detail.evidence_refresh_active = True
        detail.raw_sources = [
            RawSource(
                id="current-source",
                competitor="Cursor",
                dimension="feature",
                source_type="webpage_verified",
                title="Current source",
                url="https://cursor.com/docs/agent",
                snippet="Cursor agent workflows",
                content_hash="old-current",
                confidence=0.9,
            )
        ]

        async def fetch(record, agent, subagent, url, context=None):
            calls.append(url)
            text = (
                "Cursor supports multi-file editing, code completion, "
                "agent workflows and repository indexing. " * 3
            )
            return EvidenceFetchResult(
                url=url,
                ok=True,
                title="Cursor features",
                text=text,
                content_hash="refreshed",
                status_code=200,
                fetch_method="fixture_fetch",
                quality_score=0.95,
                text_length=len(text),
            )

        runner._trace_fetch = fetch
        await runner._collect_competitor_with_research_pipeline(
            runner._runs[detail.id],
            detail,
            "feature",
            "Cursor",
            SubagentContext(run_id=detail.id, agent="collector", subagent="feature::Cursor"),
            batch_sources=[],
            target_source_count=1,
            include_official=False,
            enable_search=False,
            enable_repair=False,
        )
        assert calls == ["https://cursor.com/docs/agent"]
    finally:
        await runner._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("history_status", ["valid", "failed", "wrong_identity"])
@pytest.mark.parametrize("depth", [None, "quick"])
async def test_history_fetch_precedes_search_with_fallback_even_when_repairs_disabled(
    history_status, depth
):
    from packages.memory.report_reuse import report_reuse_candidates

    store = EnterpriseMemoryStore()
    old_run(store)
    current = plan().model_copy(update={"report_reuse_context": reuse(store)})
    events = []
    history_url = "https://cursor.com/docs/features"
    fallback_url = "https://cursor.com/docs/agent"

    async def fetch(url):
        events.append(("fetch", url))
        wrong = url == history_url and history_status == "wrong_identity"
        failed = url == history_url and history_status == "failed"
        product = "Salesforce CRM" if wrong else "Cursor"
        text = (
            f"{product} supports code completion, repository indexing, "
            "multi-file editing and agent workflows. " * 3
        )
        return EvidenceFetchResult(
            url=url,
            ok=not failed,
            title=f"{product} features",
            text=text,
            content_hash="current-hash",
            status_code=500 if failed else 200,
            fetch_method="fixture_fetch",
            quality_score=0.95,
            text_length=len(text),
        )

    async def search(query, max_results):
        events.append(("search", query))
        return [
            SearchResult(
                title="Cursor agent features", url=fallback_url, snippet="Cursor agent workflows"
            )
        ]

    result = await run_research_pipeline(
        ResearchBrief(
            run_id="new",
            topic="AI coding",
            competitor="Cursor",
            dimension="feature",
            product_name="Cursor 2.0",
            product_category="AI IDE",
            research_depth=depth,
            target_source_count=1,
            max_fetches=2,
            max_search_queries=1,
            max_repair_rounds=0,
            include_trusted_sources=False,
            include_homepage_candidates=False,
        ),
        fetch=fetch,
        search=search,
        seed_candidates=report_reuse_candidates(current, "Cursor", "feature"),
    )
    assert events[0] == ("fetch", history_url)
    searches = [event for event in events if event[0] == "search"]
    if history_status == "valid":
        assert searches == []
    else:
        assert searches
        assert any(
            page.requested_url == fallback_url and page.status == "ok"
            for page in result.captured_pages
        )
    assert len([event for event in events if event[0] == "fetch"]) <= 2
    assert len(searches) <= 1


@pytest.mark.asyncio
async def test_history_pass_respects_a_one_candidate_budget():
    from packages.memory.report_reuse import report_reuse_candidates

    store = EnterpriseMemoryStore()
    old_run(store)
    old_run(store, run_id="second", url="https://cursor.com/docs/second")
    current = plan().model_copy(update={"report_reuse_context": reuse(store)})
    calls = []

    async def fetch(url):
        calls.append(url)
        text = "Cursor supports multi-file editing, code completion and agent workflows. " * 3
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="Cursor features",
            text=text,
            content_hash="current",
            status_code=200,
            fetch_method="fixture",
            quality_score=0.95,
            text_length=len(text),
        )

    result = await run_research_pipeline(
        ResearchBrief(
            run_id="new",
            topic="AI coding",
            competitor="Cursor",
            dimension="feature",
            target_source_count=1,
            max_candidates=1,
            max_fetches=2,
            max_repair_rounds=0,
            include_trusted_sources=False,
            include_homepage_candidates=False,
        ),
        fetch=fetch,
        seed_candidates=report_reuse_candidates(current, "Cursor", "feature"),
    )
    assert len(calls) == 1
    assert len(result.candidates) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "depth,has_history,dimension,skip_optional",
    [
        ("quick", True, "feature", True),
        ("quick", False, "feature", False),
        ("standard", True, "feature", False),
        ("deep", True, "feature", False),
        ("quick", True, "persona", False),
    ],
)
async def test_complete_collector_branch_only_skips_optional_community_for_sufficient_quick_history(
    depth,
    has_history,
    dimension,
    skip_optional,
):
    store = EnterpriseMemoryStore()
    if has_history:
        old_run(
            store,
            old_plan=plan().model_copy(update={"dimensions": [dimension]}),
            dimension=dimension,
            url="https://cursor.com/customers"
            if dimension == "persona"
            else "https://cursor.com/docs/features",
        )
    runner = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="fixture-key",
            ark_model="fixture-model",
            pplx_api_key="fixture-key",
            web_search_provider="perplexity",
            collector_react_enabled=False,
            collector_target_verified_sources_per_branch=1,
        ),
        enterprise_store=store,
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    searches = []

    async def unexpected_llm(*args, **kwargs):
        raise AssertionError("This fixture must never call a model")

    runner._trace_llm_json = unexpected_llm
    runner._trace_llm_text = unexpected_llm
    runner._llm.complete_json = unexpected_llm
    runner._llm.complete_text = unexpected_llm
    try:
        detail = await runner.create_run(
            RunCreateRequest(
                topic="AI coding",
                workspace_id="ws",
                project_id="new-project",
                target_product=None if dimension == "persona" else plan().target_product,
                research_depth=depth,
                competitors=["Cursor"],
                dimensions=[dimension],
                execution_mode="real",
            )
        )

        async def fetch(record, agent, subagent, url, context=None, **kwargs):
            text = (
                "Cursor supports code completion, repository indexing, "
                "multi-file editing and agent workflows. "
                "Cursor customers are developers and enterprise engineering teams. "
                "Customer case studies show "
                "workflow fit, onboarding effort, adoption benefits and switching costs. "
                "Cursor面向企业开发者，适合代码编写。"
            ) * 3
            return EvidenceFetchResult(
                url=url,
                ok=True,
                title="Cursor features and customers",
                text=text,
                content_hash="current-hash",
                status_code=200,
                fetch_method="fixture_fetch",
                quality_score=0.95,
                text_length=len(text),
            )

        async def search(record, agent, subagent, query, max_results, context=None, **kwargs):
            searches.append(query)
            return []

        runner._trace_fetch = fetch
        runner._trace_search = search
        await runner._real_collector_branch_step(runner._runs[detail.id], dimension, "Cursor")
        assert detail.raw_sources
        community_searches = [
            query
            for query in searches
            if any(word in query for word in ("reddit", "forum", "review"))
        ]
        if skip_optional:
            assert searches == []
            event = next(
                event
                for event in runner._runs[detail.id].events
                if event.type == "node_completed" and event.agent == "collector"
            )
            assert (
                event.payload["collect"]["community_skip_reason"]
                == "quick_history_current_coverage_complete"
            )
        else:
            assert community_searches
    finally:
        await runner._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("same_content", [False, True])
async def test_history_sources_that_redirect_or_repeat_content_do_not_skip_discovery(same_content):
    from packages.memory.report_reuse import report_reuse_candidates

    store = EnterpriseMemoryStore()
    old_run(store, url="https://cursor.com/docs/first")
    old_run(store, run_id="second", url="https://cursor.com/docs/second")
    current = plan().model_copy(update={"report_reuse_context": reuse(store)})
    calls = []
    searches = []
    fallback_url = "https://cursor.com/docs/new-evidence"

    async def fetch(url):
        calls.append(url)
        history = url != fallback_url
        final_url = url if same_content or not history else "https://cursor.com/docs/canonical"
        text = (
            f"Cursor supports code {'completion' if history else 'editing'}, "
            "repository indexing and multi-file agent workflows. "
            * 3
        )
        return EvidenceFetchResult(
            url=final_url,
            ok=True,
            title="Cursor features",
            text=text,
            content_hash=compute_content_hash(text),
            status_code=200,
            fetch_method="fixture_fetch",
            quality_score=0.95,
            text_length=len(text),
            capture_metadata={
                "source_published_at": "2026-10-01",
                "source_updated_at": "2026-10-02",
            },
        )

    async def search(query, max_results):
        searches.append(query)
        return [
            SearchResult(
                title="Cursor current evidence", url=fallback_url, snippet="Cursor agent workflows"
            )
        ]

    result = await run_research_pipeline(
        ResearchBrief(
            run_id="new",
            topic="AI coding",
            competitor="Cursor",
            dimension="feature",
            target_source_count=2,
            max_fetches=3,
            max_search_queries=1,
            max_repair_rounds=0,
            include_trusted_sources=False,
            include_homepage_candidates=False,
        ),
        fetch=fetch,
        search=search,
        seed_candidates=report_reuse_candidates(current, "Cursor", "feature"),
    )
    assert len(searches) == 1
    assert fallback_url in calls
    assert len(calls) == 3
    fallback_page = next(
        page for page in result.captured_pages if page.requested_url == fallback_url
    )
    runner = service(store)
    detail = RunDetail(
        id="new",
        topic=current.topic,
        status="running",
        execution_mode="real",
        created_at=NOW,
        updated_at=NOW,
        plan=current,
    )
    try:
        fallback_sources = runner._raw_sources_from_research_result(
            detail,
            result.brief,
            result.model_copy(update={"captured_pages": [fallback_page]}),
            batch_sources=[],
            target_source_count=2,
        )
        assert [str(source.url) for source in fallback_sources] == [fallback_url]

        sources = runner._raw_sources_from_research_result(
            detail,
            result.brief,
            result,
            batch_sources=[],
            target_source_count=2,
        )
        assert fallback_url in [str(source.url) for source in sources]
        assert len(sources) == 2
        assert len({source.content_hash for source in sources}) >= 2
        for source in sources:
            page = next(
                page for page in result.captured_pages
                if page.requested_url == source.metadata["requested_url"]
            )
            assert source.metadata["fetched_at"] == page.captured_at.isoformat()
            assert source.metadata["source_published_at"] == "2026-10-01"
            assert source.metadata["source_updated_at"] == "2026-10-02"
        history_source = next(source for source in sources if source.candidate_origin == "manual")
        assert history_source.metadata["history_report_id"] in {"r-old", "r-second"}
        assert history_source.metadata["history_evidence_id"] in {"e-old", "e-second"}
        assert history_source.metadata["history_captured_at"] == (
            NOW - timedelta(days=2)
        ).isoformat()
        assert history_source.metadata["history_source_published_at"] == "2026-09-01"
        assert history_source.metadata["history_source_updated_at"] == "2026-09-28"
        fallback_source = next(source for source in sources if str(source.url) == fallback_url)
        assert fallback_source.candidate_origin == "perplexity"
        assert not any(key.startswith("history_") for key in fallback_source.metadata)
    finally:
        await runner._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_read", ["get_project", "list_projects", "list_report_versions"])
async def test_optional_history_read_failure_preserves_journal_fallback_and_new_run(
    tmp_path, failed_read
):
    store = EnterpriseMemoryStore()
    persisted = old_run(store)
    journal = RunJournal(tmp_path / "fallback.sqlite")
    journal.save_run(persisted)
    runner = service(store, journal)

    async def unexpected_llm(*args, **kwargs):
        raise AssertionError("This fixture must never call a model")

    runner._trace_llm_json = unexpected_llm
    runner._trace_llm_text = unexpected_llm
    runner._llm.complete_json = unexpected_llm
    runner._llm.complete_text = unexpected_llm

    def broken_read(*args, **kwargs):
        raise RuntimeError("history read fixture failure")

    setattr(store, failed_read, broken_read)
    try:
        created = await runner.create_run(
            RunCreateRequest(
                topic="AI coding",
                workspace_id="ws",
                project_id="new-project",
                target_product=plan().target_product,
                competitors=["Cursor"],
                dimensions=["feature"],
                execution_mode="real",
            )
        )
        assert created.plan.report_reuse_context.selected[0].report_id == "r-old"
        assert any(
            "history_store" in item.reason for item in created.plan.report_reuse_context.skipped
        )
        assert journal.load_run(created.id) is not None
        assert journal.load_run(persisted.id).model_dump() == persisted.model_dump()
    finally:
        await runner._graph_checkpointer.aclose()
