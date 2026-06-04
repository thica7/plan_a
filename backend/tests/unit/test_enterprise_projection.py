from packages.enterprise import build_enterprise_projection
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    QCIssue,
    RawSource,
    RedoScope,
    RunMetrics,
)


def test_build_enterprise_projection_links_evidence_claims_and_report() -> None:
    detail = RunDetail(
        id="run-1",
        topic="AI coding assistant comparison",
        status="completed",
        execution_mode="real",
        created_at="2026-05-28T00:00:00",
        updated_at="2026-05-28T00:05:00",
        plan=AnalysisPlan(
            topic="AI coding assistant comparison",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
        report_md="Cursor has published pricing. [source:pricing-1]",
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                url="https://cursor.sh/pricing?utm_source=test",
                snippet="Cursor has published pricing.",
                content_hash="hash-1",
                confidence=0.9,
            )
        ],
        competitor_knowledge={
            "Cursor": CompetitorKnowledge(
                competitor="Cursor",
                pricing_model=PricingModel(
                    notes=[
                        KnowledgeClaim(
                            claim="Cursor has published pricing.",
                            source_ids=["pricing-1"],
                            confidence=0.9,
                        )
                    ]
                ),
                source_ids=["pricing-1"],
                confidence=0.9,
            )
        },
    )

    projection = build_enterprise_projection(
        detail,
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=2,
        competitor_layer="L1",
    )

    assert len(projection.evidence_records) == 1
    evidence = projection.evidence_records[0]
    assert evidence.canonical_url == "https://cursor.sh/pricing"
    assert evidence.first_seen_run_id == "run-1"
    assert evidence.last_seen_run_id == "run-1"
    assert evidence.seen_count == 1
    assert len(projection.claim_records) == 1
    assert projection.claim_records[0].evidence_ids == [projection.evidence_records[0].id]
    assert projection.report_version.claim_ids == [projection.claim_records[0].id]
    assert projection.report_version.evidence_ids == [projection.evidence_records[0].id]
    assert projection.report_version.version_number == 2
    assert projection.report_version.competitor_layer == "L1"
    assert projection.report_version.quality_metadata["run_id"] == "run-1"
    assert evidence.metadata["raw_source_aliases"] == ["pricing-1"]
    reconciliation = projection.report_version.quality_metadata["source_reconciliation"]
    assert reconciliation["report_source_tokens"] == ["pricing-1"]
    assert reconciliation["unresolved_report_source_tokens"] == []
    assert reconciliation["evidence_source_aliases"][evidence.id] == ["pricing-1"]


def test_projection_carries_run_quality_metadata() -> None:
    detail = RunDetail(
        id="run-1",
        topic="AI coding assistant comparison",
        status="completed",
        execution_mode="real",
        created_at="2026-05-28T00:00:00",
        updated_at="2026-05-28T00:05:00",
        plan=AnalysisPlan(
            topic="AI coding assistant comparison",
            competitors=["Cursor"],
            dimensions=["security"],
        ),
        report_md="Cursor security requires review. [source:security-1]",
        metrics=RunMetrics(schema_pass_rate=0.5),
        raw_sources=[
            RawSource(
                id="security-1",
                competitor="Cursor",
                dimension="security",
                source_type="web_search_result",
                title="Cursor security comparison",
                url="https://example.com/cursor-security",
                snippet="Search-only security summary.",
                content_hash="hash-1",
                confidence=0.68,
            )
        ],
        qa_findings=[
            QCIssue(
                id="qa-1",
                severity="warn",
                detected_by="reflector",
                target_agent="collector",
                target_subagent="security",
                target_competitor="Cursor",
                field_path="raw_sources[security-1]",
                problem="Security source is search-only.",
                redo_scope=RedoScope(
                    kind="collector",
                    target_subagent="security",
                    target_competitor="Cursor",
                    rationale="Recollect official security evidence.",
                ),
            )
        ],
    )

    projection = build_enterprise_projection(detail)

    metadata = projection.report_version.quality_metadata
    assert metadata["run_qa_warning_count"] == 1
    assert metadata["schema_pass_rate"] == 0.5
    assert metadata["search_only_source_ids"] == ["security-1"]
    assert metadata["low_confidence_source_ids"] == ["security-1"]


def test_projection_expands_multi_competitor_sources() -> None:
    detail = RunDetail(
        id="run-1",
        topic="Comparison",
        status="completed",
        execution_mode="real",
        created_at="2026-05-28T00:00:00",
        updated_at="2026-05-28T00:05:00",
        plan=AnalysisPlan(topic="Comparison", competitors=["A", "B"], dimensions=["feature"]),
        raw_sources=[
            RawSource(
                id="feature-1",
                competitor="A",
                covered_competitors=["A", "B"],
                dimension="feature",
                source_type="webpage_verified",
                title="Feature comparison",
                url="https://example.com/features",
                snippet="A and B both support this feature.",
                content_hash="hash-1",
                confidence=0.8,
            )
        ],
    )

    projection = build_enterprise_projection(detail)

    assert len(projection.evidence_records) == 2
    assert {record.competitor_id for record in projection.evidence_records} == {"a", "b"}


def test_projection_uses_competitor_id_map_when_present() -> None:
    detail = RunDetail(
        id="run-1",
        topic="Comparison",
        status="completed",
        execution_mode="real",
        created_at="2026-05-28T00:00:00",
        updated_at="2026-05-28T00:05:00",
        plan=AnalysisPlan(topic="Comparison", competitors=["A"], dimensions=["feature"]),
        raw_sources=[
            RawSource(
                id="feature-1",
                competitor="A",
                dimension="feature",
                source_type="webpage_verified",
                title="Feature comparison",
                url="https://example.com/features",
                snippet="A supports this feature.",
                content_hash="hash-1",
                confidence=0.8,
            )
        ],
    )

    projection = build_enterprise_projection(detail, competitor_id_map={"A": "competitor-a"})

    assert projection.evidence_records[0].competitor_id == "competitor-a"


def test_projection_skips_claims_with_missing_source_ids() -> None:
    detail = RunDetail(
        id="run-1",
        topic="AI coding assistant comparison",
        status="completed",
        execution_mode="real",
        created_at="2026-05-28T00:00:00",
        updated_at="2026-05-28T00:05:00",
        plan=AnalysisPlan(
            topic="AI coding assistant comparison",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
        competitor_knowledge={
            "Cursor": CompetitorKnowledge(
                competitor="Cursor",
                pricing_model=PricingModel(
                    notes=[
                        KnowledgeClaim(
                            claim="Cursor has published pricing.",
                            source_ids=["missing-source"],
                            confidence=0.9,
                        )
                    ]
                ),
            )
        },
    )

    projection = build_enterprise_projection(detail)

    assert projection.evidence_records == []
    assert projection.claim_records == []
    assert projection.report_version.claim_ids == []
