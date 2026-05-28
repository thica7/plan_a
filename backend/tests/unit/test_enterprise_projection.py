from packages.enterprise import build_enterprise_projection
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    RawSource,
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
    assert len(projection.claim_records) == 1
    assert projection.claim_records[0].evidence_ids == [projection.evidence_records[0].id]
    assert projection.report_version.claim_ids == [projection.claim_records[0].id]
    assert projection.report_version.evidence_ids == [projection.evidence_records[0].id]
    assert projection.report_version.version_number == 2
    assert projection.report_version.competitor_layer == "L1"


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
