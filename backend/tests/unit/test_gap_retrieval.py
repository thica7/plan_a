import pytest

from packages.enterprise import EnterpriseMemoryStore
from packages.rag import (
    chunk_evidence,
    decorate_evidence_gap_report_with_retrieval,
    fill_evidence_gaps,
    fill_evidence_gaps_online,
    retrieve_gap_candidates,
)
from packages.schema.enterprise import (
    EvidenceGapItem,
    EvidenceGapReport,
    EvidenceRecord,
    ReportVersionRecord,
)
from packages.search import SearchResult
from packages.tools import FetchPageResult


def test_gap_retrieval_decorates_report_with_candidate_evidence() -> None:
    store = EnterpriseMemoryStore()
    store.upsert_evidence(
        EvidenceRecord(
            id="evidence-security-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="security-1",
            competitor_id="cursor",
            dimension="security",
            source_type="webpage_verified",
            title="Cursor security trust center",
            snippet="Cursor security trust center covers SOC 2 and enterprise controls.",
            content_hash="securityhash",
            reliability_score=0.92,
        )
    )
    gap = EvidenceGapItem(
        id="gap-1",
        severity="medium",
        gap_type="missing_verified_source",
        competitor_id="cursor",
        competitor_name="Cursor",
        dimension="security",
        source_type_required="webpage_verified",
        message="Cursor has security evidence, but no verified source.",
        recommended_query="Cursor security trust center official",
        evidence_ids=["weak-evidence"],
    )
    report = EvidenceGapReport(
        project_id="project-1",
        scenario_id="enterprise_risk_review",
        gap_count=1,
        medium_count=1,
        gaps=[gap],
    )

    decorated = decorate_evidence_gap_report_with_retrieval(
        report,
        store=store,
        workspace_id="workspace-1",
        project_id="project-1",
    )
    context = retrieve_gap_candidates(
        store=store,
        workspace_id="workspace-1",
        project_id="project-1",
        gap=gap,
    )

    [decorated_gap] = decorated.gaps
    assert decorated_gap.retrieval_query == (
        "Cursor security trust center official Cursor security webpage_verified"
    )
    assert decorated_gap.retrieval_candidate_ids == ["evidence-security-1"]
    assert decorated_gap.retrieval_candidate_chunk_count >= 1
    assert decorated_gap.retrieval_unique_evidence_count == 1
    assert decorated_gap.retrieval_records[0].evidence_id == "evidence-security-1"
    assert "[source:evidence-security-1#chunk:" in decorated_gap.retrieval_grounded_context
    assert context.candidate_ids == ["evidence-security-1"]
    assert context.records[0].chunk_id.startswith("chunk-")
    assert context.records[0].retrieval_stage == "hybrid_rerank"
    assert context.records[0].bm25_score > 0
    assert "[source:evidence-security-1#chunk:" in context.grounded_context


def test_gap_retrieval_filters_existing_and_wrong_source_type() -> None:
    store = EnterpriseMemoryStore()
    store.upsert_evidence(
        EvidenceRecord(
            id="existing-search",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="search-1",
            competitor_id="cursor",
            dimension="security",
            source_type="web_search_result",
            title="Cursor security search result",
            snippet="Cursor security overview.",
            content_hash="searchhash",
            reliability_score=0.65,
        )
    )
    gap = EvidenceGapItem(
        id="gap-2",
        severity="medium",
        gap_type="missing_verified_source",
        competitor_id="cursor",
        competitor_name="Cursor",
        dimension="security",
        source_type_required="webpage_verified",
        message="Security needs a verified source.",
        recommended_query="Cursor security",
        evidence_ids=["existing-search"],
    )

    context = retrieve_gap_candidates(
        store=store,
        workspace_id="workspace-1",
        project_id="project-1",
        gap=gap,
    )

    assert context.candidate_ids == []
    assert context.grounded_context == ""


def test_gap_retrieval_uses_chunk_level_reranking_and_dedupes_evidence() -> None:
    store = EnterpriseMemoryStore()
    long_text = " ".join(
        [
            "Cursor pricing overview mentions monthly seats and trial limits.",
            "Enterprise security details include SOC 2, SSO, audit logs, and data controls.",
        ]
        * 20
    )
    evidence = EvidenceRecord(
        id="evidence-enterprise-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="enterprise-1",
        competitor_id="cursor",
        dimension="security",
        source_type="webpage_verified",
        title="Cursor enterprise security",
        snippet="Cursor enterprise security and pricing summary.",
        content_hash="enterprisehash",
        reliability_score=0.95,
        freshness_score=0.8,
        metadata={"full_text": long_text},
    )
    store.upsert_evidence(evidence)
    chunks = chunk_evidence(evidence, max_chars=260, overlap_chars=40)
    assert len(chunks) > 1

    gap = EvidenceGapItem(
        id="gap-3",
        severity="high",
        gap_type="missing_verified_source",
        competitor_id="cursor",
        competitor_name="Cursor",
        dimension="security",
        source_type_required="webpage_verified",
        message="Security needs specific enterprise controls evidence.",
        recommended_query="Cursor enterprise SSO audit logs SOC 2",
    )

    context = retrieve_gap_candidates(
        store=store,
        workspace_id="workspace-1",
        project_id="project-1",
        gap=gap,
        limit=3,
    )

    assert context.rewritten_queries[0] == (
        "Cursor enterprise SSO audit logs SOC 2 Cursor security webpage_verified"
    )
    assert context.candidate_ids == ["evidence-enterprise-1"]
    assert len(context.records) == 1
    assert context.candidate_chunk_count > context.unique_evidence_candidate_count
    assert context.unique_evidence_candidate_count == 1
    assert context.dedupe_drop_count > 0
    assert context.records[0].chunk_index >= 0
    assert "audit logs" in context.records[0].snippet.casefold()


def test_gap_fill_writes_candidates_back_to_report_version() -> None:
    store = EnterpriseMemoryStore()
    store.upsert_evidence(
        EvidenceRecord(
            id="evidence-trust-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="trust-1",
            competitor_id="cursor",
            dimension="security",
            source_type="webpage_verified",
            title="Cursor trust center",
            snippet="Cursor trust center describes SOC 2, SSO, audit logs, and security controls.",
            content_hash="trusthash",
            reliability_score=0.96,
        )
    )
    source_version = store.upsert_report_version(
        ReportVersionRecord(
            id="report-v1",
            workspace_id="workspace-1",
            project_id="project-1",
            version_number=1,
            topic_normalized="cursor-security",
            competitor_layer="L1",
            competitor_set_hash="competitors-hash",
            report_md="# Report\n\nCursor security needs more evidence.",
            evidence_ids=[],
        )
    )
    report = EvidenceGapReport(
        project_id="project-1",
        scenario_id="enterprise_risk_review",
        gap_count=1,
        medium_count=1,
        gaps=[
            EvidenceGapItem(
                id="gap-security",
                severity="medium",
                gap_type="missing_verified_source",
                competitor_id="cursor",
                competitor_name="Cursor",
                dimension="security",
                source_type_required="webpage_verified",
                message="Security needs a verified source.",
                recommended_query="Cursor SOC 2 SSO audit logs trust center",
            )
        ],
    )

    result = fill_evidence_gaps(
        report,
        store=store,
        workspace_id="workspace-1",
        project_id="project-1",
        source_report_version=source_version,
    )

    assert result.filled_gap_count == 1
    assert result.added_evidence_count == 1
    assert result.before_gap_count == 1
    assert result.after_gap_count == 0
    assert result.gap_closure_rate == 1.0
    assert result.gap_fill_chain_closed is True
    assert result.candidate_evidence_ids == ["evidence-trust-1"]
    assert result.gap_evidence_links == {"gap-security": ["evidence-trust-1"]}
    assert [event.event_type for event in result.decision_events] == [
        "rag.retrieved",
        "report.ready",
    ]
    rag_payload = result.decision_events[0].payload
    assert rag_payload["gap_closure_rate"] == 1.0
    assert rag_payload["retrieval_record_count"] == 1
    assert rag_payload["retrieval_queries"] == [
        "Cursor SOC 2 SSO audit logs trust center Cursor security webpage_verified"
    ]
    assert rag_payload["gap_evidence_links"] == {"gap-security": ["evidence-trust-1"]}
    assert len(rag_payload["retrieval_contexts"]) == 1
    assert rag_payload["retrieval_contexts"][0]["gap_id"] == "gap-security"
    assert rag_payload["retrieval_contexts"][0]["query"] == rag_payload["retrieval_queries"][0]
    assert rag_payload["chunk_ids"][0].startswith("chunk-")
    assert set(rag_payload["rerank_scores"]) == set(rag_payload["chunk_ids"])
    assert result.decision_events[1].payload["source_report_version_id"] == "report-v1"
    assert result.updated_report_version is not None
    assert (
        result.decision_events[1].payload["updated_report_version_id"]
        == result.updated_report_version.id
    )
    assert result.updated_report_version.parent_version_id == "report-v1"
    assert result.updated_report_version.version_number == 2
    assert result.updated_report_version.evidence_ids == ["evidence-trust-1"]
    assert result.updated_report_version.quality_metadata["rag_gap_fill"][
        "filled_gap_ids"
    ] == ["gap-security"]
    assert result.updated_report_version.quality_metadata["rag_gap_fill"][
        "gap_evidence_links"
    ] == {"gap-security": ["evidence-trust-1"]}
    assert result.updated_report_version.quality_metadata["rag_gap_fill"][
        "decision_events"
    ][0]["event_type"] == "rag.retrieved"
    assert result.updated_report_version.quality_metadata["rag_gap_fill"][
        "decision_events"
    ][1]["payload"]["gap_evidence_links"] == {"gap-security": ["evidence-trust-1"]}
    assert "## RAG Gap Fill" in result.updated_report_version.report_md
    assert "[source:evidence-trust-1]" in result.updated_report_version.report_md
    assert store.get_report_version(result.updated_report_version.id) is not None


def test_gap_fill_chain_stays_open_until_all_gaps_are_filled() -> None:
    store = EnterpriseMemoryStore()
    store.upsert_evidence(
        EvidenceRecord(
            id="evidence-trust-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="trust-1",
            competitor_id="cursor",
            dimension="security",
            source_type="webpage_verified",
            title="Cursor trust center",
            snippet="Cursor trust center describes SOC 2, SSO, and audit logs.",
            content_hash="trusthash",
            reliability_score=0.96,
        )
    )
    source_version = store.upsert_report_version(
        ReportVersionRecord(
            id="report-partial-v1",
            workspace_id="workspace-1",
            project_id="project-1",
            version_number=1,
            topic_normalized="cursor-security",
            competitor_layer="L1",
            competitor_set_hash="competitors-hash",
            report_md="# Report\n\nCursor security and pricing need evidence.",
            evidence_ids=[],
        )
    )
    report = EvidenceGapReport(
        project_id="project-1",
        scenario_id="enterprise_risk_review",
        gap_count=2,
        medium_count=2,
        gaps=[
            EvidenceGapItem(
                id="gap-security",
                severity="medium",
                gap_type="missing_verified_source",
                competitor_id="cursor",
                competitor_name="Cursor",
                dimension="security",
                source_type_required="webpage_verified",
                message="Security needs a verified source.",
                recommended_query="Cursor SOC 2 SSO audit logs trust center",
            ),
            EvidenceGapItem(
                id="gap-pricing",
                severity="medium",
                gap_type="missing_verified_source",
                competitor_id="cursor",
                competitor_name="Cursor",
                dimension="pricing",
                source_type_required="official_pricing",
                message="Pricing needs an official pricing source.",
                recommended_query="Cursor enterprise pricing official page",
            ),
        ],
    )

    result = fill_evidence_gaps(
        report,
        store=store,
        workspace_id="workspace-1",
        project_id="project-1",
        source_report_version=source_version,
    )

    assert result.filled_gap_count == 1
    assert result.before_gap_count == 2
    assert result.after_gap_count == 1
    assert result.remaining_gap_ids == ["gap-pricing"]
    assert result.gap_fill_chain_closed is False
    assert result.decision_events[-1].payload["gap_fill_chain_closed"] is False
    assert result.updated_report_version is not None
    metadata = result.updated_report_version.quality_metadata["rag_gap_fill"]
    assert metadata["gap_fill_chain_closed"] is False
    assert metadata["remaining_gap_ids"] == ["gap-pricing"]


@pytest.mark.asyncio
async def test_online_gap_fill_collects_evidence_then_links_report_version() -> None:
    store = EnterpriseMemoryStore()
    source_version = store.upsert_report_version(
        ReportVersionRecord(
            id="report-online-v1",
            workspace_id="workspace-1",
            project_id="project-1",
            version_number=1,
            topic_normalized="cursor-security",
            competitor_layer="L1",
            competitor_set_hash="competitors-hash",
            report_md="# Report\n\nCursor security has an evidence gap.",
            evidence_ids=[],
        )
    )
    report = EvidenceGapReport(
        project_id="project-1",
        scenario_id="enterprise_risk_review",
        gap_count=1,
        high_count=1,
        gaps=[
            EvidenceGapItem(
                id="gap-online-security",
                severity="high",
                gap_type="missing_verified_source",
                competitor_id="cursor",
                competitor_name="Cursor",
                dimension="security",
                source_type_required="webpage_verified",
                message="Security needs a verified source.",
                recommended_query="Cursor SOC 2 SSO audit logs trust center",
            )
        ],
    )

    async def fake_search(query: str, max_results: int) -> list[SearchResult]:
        assert "Cursor SOC 2" in query
        assert max_results == 3
        return [
            SearchResult(
                title="Cursor trust center",
                url="https://cursor.example/trust",
                snippet="Cursor trust center covers SOC 2, SSO, audit logs, and security controls.",
            )
        ]

    async def fake_fetch(url: str) -> FetchPageResult:
        assert url == "https://cursor.example/trust"
        return FetchPageResult(
            url=url,
            ok=True,
            title="Cursor trust center",
            text=(
                "Cursor trust center covers SOC 2, enterprise SSO, audit logs, "
                "data controls, and security controls for enterprise customers."
            ),
            content_hash="onlinehash",
            status_code=200,
        )

    result = await fill_evidence_gaps_online(
        report,
        store=store,
        workspace_id="workspace-1",
        project_id="project-1",
        source_report_version=source_version,
        search=fake_search,
        fetch=fake_fetch,
    )

    evidence_items = store.list_evidence(project_id="project-1")
    assert len(evidence_items) == 1
    [evidence] = evidence_items
    assert evidence.source_type == "webpage_verified"
    assert evidence.metadata["online_gap_fill"] is True
    assert evidence.metadata["gap_id"] == "gap-online-security"
    assert "SOC 2" in evidence.metadata["full_text"]
    assert result.filled_gap_count == 1
    assert result.added_evidence_count == 1
    assert result.online_collected_evidence_count == 1
    assert result.online_failure_count == 0
    assert [event.event_type for event in result.decision_events] == [
        "rag.retrieved",
        "tool.called",
        "report.ready",
    ]
    assert result.decision_events[1].payload["tool"] == "online_gap_fill"
    assert result.decision_events[1].payload["online_collected_evidence_ids"] == [evidence.id]
    assert result.gap_closure_rate == 1.0
    assert result.gap_fill_chain_closed is True
    assert result.candidate_evidence_ids == [evidence.id]
    assert result.gap_evidence_links == {"gap-online-security": [evidence.id]}
    assert result.updated_report_version is not None
    metadata = result.updated_report_version.quality_metadata["rag_gap_fill"]
    assert metadata["before_gap_count"] == 1
    assert metadata["after_gap_count"] == 0
    assert metadata["gap_closure_rate"] == 1.0
    assert metadata["gap_fill_chain_closed"] is True
    assert metadata["online_collected_evidence_ids"] == [evidence.id]
    assert metadata["gap_evidence_links"] == {"gap-online-security": [evidence.id]}
    assert metadata["online_failures"] == []
    assert [event["event_type"] for event in metadata["decision_events"]] == [
        "rag.retrieved",
        "tool.called",
        "report.ready",
    ]
    rag_payload = metadata["decision_events"][0]["payload"]
    assert rag_payload["retrieval_contexts"][0]["gap_id"] == "gap-online-security"
    assert rag_payload["gap_evidence_links"] == {"gap-online-security": [evidence.id]}
    assert rag_payload["chunk_ids"][0].startswith("chunk-")
    assert set(rag_payload["rerank_scores"]) == set(rag_payload["chunk_ids"])
    assert result.updated_report_version.evidence_ids == [evidence.id]
    assert f"[source:{evidence.id}]" in result.updated_report_version.report_md


@pytest.mark.asyncio
async def test_online_gap_fill_does_not_store_robots_blocked_search_fallback() -> None:
    store = EnterpriseMemoryStore()
    source_version = store.upsert_report_version(
        ReportVersionRecord(
            id="report-robots-v1",
            workspace_id="workspace-1",
            project_id="project-1",
            version_number=1,
            topic_normalized="cursor-robots",
            competitor_layer="L1",
            competitor_set_hash="competitors-hash",
            report_md="# Report\n\nCursor onboarding has an evidence gap.",
            evidence_ids=[],
        )
    )
    report = EvidenceGapReport(
        project_id="project-1",
        scenario_id="l1_pricing_pack",
        gap_count=1,
        medium_count=1,
        gaps=[
            EvidenceGapItem(
                id="gap-robots-onboarding",
                severity="medium",
                gap_type="missing_dimension_coverage",
                competitor_id="cursor",
                competitor_name="Cursor",
                dimension="onboarding",
                source_type_required="any usable source",
                message="Onboarding needs any usable evidence.",
                recommended_query="Cursor onboarding enterprise evidence",
            )
        ],
    )

    async def fake_search(query: str, max_results: int) -> list[SearchResult]:
        return [
            SearchResult(
                title="Cursor onboarding",
                url="https://cursor.example/onboarding",
                snippet="Cursor onboarding overview.",
            )
        ]

    async def fake_fetch(url: str) -> FetchPageResult:
        return FetchPageResult(
            url=url,
            ok=False,
            title="",
            text="",
            content_hash="robotshash",
            error="Blocked by robots.txt at https://cursor.example/robots.txt",
        )

    result = await fill_evidence_gaps_online(
        report,
        store=store,
        workspace_id="workspace-1",
        project_id="project-1",
        source_report_version=source_version,
        search=fake_search,
        fetch=fake_fetch,
    )

    assert store.list_evidence(project_id="project-1") == []
    assert result.filled_gap_count == 0
    assert result.added_evidence_count == 0
    assert result.online_collected_evidence_count == 0
    assert result.online_failure_count == 1
    assert result.gap_fill_chain_closed is False
    assert result.decision_events[1].event_type == "tool.called"
    assert result.decision_events[1].payload["online_failures"][0]["stage"] == "robots"
