from packages.business_intel.source_reconciliation import (
    build_source_reconciliation,
    evidence_by_source_token,
    raw_source_alias_metadata,
)
from packages.schema.enterprise import EvidenceRecord


def test_source_reconciliation_resolves_ids_raw_sources_aliases_and_chunks() -> None:
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-old",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        reliability_score=0.9,
        metadata=raw_source_alias_metadata("pricing-current"),
    )

    by_token = evidence_by_source_token([evidence])
    assert by_token["evidence-1"] == evidence
    assert by_token["pricing-old"] == evidence
    assert by_token["pricing-current"] == evidence

    reconciliation = build_source_reconciliation(
        "Known [source:pricing-current#chunk:0]. Missing [source:ghost].",
        [evidence],
        scoped_evidence_ids=["evidence-1"],
    )

    assert reconciliation["report_source_tokens"] == ["pricing-current", "ghost"]
    assert reconciliation["unresolved_report_source_tokens"] == ["ghost"]
    assert reconciliation["evidence_source_aliases"] == {
        "evidence-1": ["pricing-current", "pricing-old"]
    }
