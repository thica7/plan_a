from packages.enterprise import EnterpriseMemoryStore
from packages.rag import decorate_evidence_gap_report_with_retrieval, retrieve_gap_candidates
from packages.schema.enterprise import EvidenceGapItem, EvidenceGapReport, EvidenceRecord


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
    assert context.candidate_ids == ["evidence-security-1"]
    assert "[source:evidence-security-1]" in context.grounded_context


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
