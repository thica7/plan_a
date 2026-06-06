from __future__ import annotations

from packages.business_intel.claim_release import (
    append_claim_release_section,
    apply_claim_release_decisions,
    plan_claim_release_decisions,
    publishable_claim_ids,
)
from packages.business_intel.release_gate import _run_quality_issues
from packages.schema.enterprise import ClaimRecord, EvidenceRecord, ReportVersionRecord


def _evidence(
    evidence_id: str,
    *,
    raw_source_id: str,
    snippet: str,
    reliability: float = 0.95,
    source_type: str = "webpage_verified",
    quality_label: str = "accepted",
) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id,
        workspace_id="workspace-1",
        project_id="project-1",
        run_id="run-1",
        raw_source_id=raw_source_id,
        competitor_id="cursor",
        dimension="feature",
        source_type=source_type,
        title=snippet,
        canonical_url=f"https://example.com/{evidence_id}",
        snippet=snippet,
        content_hash=f"hash-{evidence_id}",
        reliability_score=reliability,
        freshness_score=1.0,
        quality_label=quality_label,  # type: ignore[arg-type]
        first_seen_run_id="run-1",
        last_seen_run_id="run-1",
    )


def _claim(claim_id: str, text: str, evidence_ids: list[str]) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        workspace_id="workspace-1",
        project_id="project-1",
        run_id="run-1",
        competitor_id="cursor",
        claim_type="feature",
        claim_text=text,
        evidence_ids=evidence_ids,
        confidence=0.9,
        created_by_agent="analyst",
    )


def test_claim_release_decisions_scope_publishable_claims() -> None:
    evidence = [
        _evidence(
            "evidence-strong",
            raw_source_id="raw-source-strong",
            snippet="Cursor supports agent mode in editor workflows with project-aware coding.",
        ),
        _evidence(
            "evidence-single",
            raw_source_id="raw-source-single",
            snippet="Cursor offers enterprise agent workflows for coding teams.",
        ),
    ]
    claims = [
        _claim(
            "claim-strong",
            "Cursor supports agent mode in editor workflows.",
            ["evidence-strong"],
        ),
        _claim(
            "claim-single-source",
            "Cursor is the best enterprise-ready coding agent.",
            ["evidence-single"],
        ),
        _claim("claim-missing", "Cursor has an unsupported private feature.", ["missing"]),
    ]

    decisions = plan_claim_release_decisions(
        project_id="project-1",
        claims=claims,
        evidence=evidence,
    )
    by_id = {decision.claim_id: decision for decision in decisions}

    assert by_id["claim-strong"].action == "keep"
    assert by_id["claim-strong"].publishable is True
    assert by_id["claim-single-source"].action == "add_evidence"
    assert by_id["claim-single-source"].publishable is False
    assert by_id["claim-missing"].action == "delete"
    assert by_id["claim-missing"].publishable is False

    updated_claims = apply_claim_release_decisions(claims, decisions)
    assert [claim.id for claim in updated_claims if claim.status == "accepted"] == [
        "claim-strong"
    ]
    assert publishable_claim_ids(updated_claims, decisions) == ["claim-strong"]


def test_claim_release_section_records_withheld_claims() -> None:
    evidence = [
        _evidence(
            "evidence-single",
            raw_source_id="raw-source-single",
            snippet="Cursor offers enterprise agent workflows for coding teams.",
        )
    ]
    claims = [
        _claim(
            "claim-single-source",
            "Cursor is the best enterprise-ready coding agent.",
            ["evidence-single"],
        )
    ]
    decisions = plan_claim_release_decisions(
        project_id="project-1",
        claims=claims,
        evidence=evidence,
    )

    report = append_claim_release_section("# Report\n\nBody.", decisions)

    assert "## Claim Release Controls" in report
    assert "`claim-single-source` action=add_evidence" in report
    assert "[source:evidence-single]" in report


def test_mitigated_run_qa_findings_are_warn_not_blocker() -> None:
    report = ReportVersionRecord(
        id="report-version-1",
        workspace_id="workspace-1",
        project_id="project-1",
        run_id="run-1",
        version_number=1,
        topic_normalized="ai-coding-agent",
        competitor_layer="L1",
        competitor_set_hash="competitor-set",
        report_md="# Report\n\n## Claim Validation & Evidence Risk\n\nHandled.",
        claim_ids=["claim-strong"],
        evidence_ids=["evidence-strong"],
        quality_metadata={
            "run_qa_findings": [
                {
                    "id": "qa-warning-1",
                    "severity": "warn",
                    "problem": "Persona confidence outlier.",
                }
            ],
            "run_qa_findings_resolution": {
                "status": "mitigated_by_release_controls",
                "mitigated_warning_ids": ["qa-warning-1"],
                "withheld_claim_count": 2,
            },
        },
    )

    issues = _run_quality_issues(report)

    assert [issue.rule_id for issue in issues] == ["run_qa_findings_mitigated"]
    assert issues[0].severity == "warn"
