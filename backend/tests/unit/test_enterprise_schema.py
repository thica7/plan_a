from pydantic import ValidationError

from packages.identity import compute_competitor_set_hash, compute_evidence_id
from packages.schema.enterprise import (
    ClaimRecord,
    EvidenceRecord,
    ProjectRecord,
    ReportVersionRecord,
)


def test_enterprise_project_schema_carries_phase1_grouping_fields() -> None:
    competitor_set_hash = compute_competitor_set_hash(["cursor", "copilot"])
    project = ProjectRecord(
        id="project-1",
        workspace_id="workspace-1",
        name="AI coding assistants",
        topic="AI coding assistant comparison",
        topic_normalized="ai coding assistant comparison",
        competitor_layer="L1",
        competitor_set_hash=competitor_set_hash,
    )

    assert project.competitor_layer == "L1"
    assert project.competitor_set_hash == competitor_set_hash


def test_evidence_and_claim_records_are_linked_by_stable_ids() -> None:
    evidence_id = compute_evidence_id(
        "https://cursor.sh/pricing",
        "content-hash",
        "cursor",
        "pricing",
    )
    evidence = EvidenceRecord(
        id=evidence_id,
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-1",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://cursor.sh/pricing",
        snippet="Cursor Pro plan pricing.",
        content_hash="content-hash",
        reliability_score=0.9,
    )
    claim = ClaimRecord(
        id="claim-1",
        workspace_id="workspace-1",
        project_id="project-1",
        competitor_id="cursor",
        claim_type="pricing_tier",
        claim_text="Cursor Pro has published pricing.",
        evidence_ids=[evidence.id],
        confidence=0.8,
    )

    assert claim.evidence_ids == [evidence.id]
    assert evidence.canonical_url == ""
    assert evidence.seen_count == 1
    assert evidence.first_seen_run_id is None
    assert evidence.last_seen_run_id is None


def test_claim_record_requires_evidence() -> None:
    try:
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id="cursor",
            claim_type="pricing_tier",
            claim_text="Cursor Pro has published pricing.",
            evidence_ids=[],
        )
    except ValidationError as exc:
        assert "evidence_ids" in str(exc)
    else:
        raise AssertionError("ClaimRecord accepted a claim without evidence.")


def test_report_version_groups_by_topic_layer_and_competitor_set() -> None:
    report = ReportVersionRecord(
        id="report-1",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="ai coding assistant comparison",
        competitor_layer="L1",
        competitor_set_hash=compute_competitor_set_hash(["cursor", "copilot"]),
        report_md="Draft report.",
        claim_ids=["claim-1"],
        evidence_ids=["evidence-1"],
    )

    assert report.version_number == 1
    assert report.status == "draft"
