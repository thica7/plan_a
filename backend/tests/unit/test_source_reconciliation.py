from datetime import datetime

from packages.agents.qa.logic import QualityAgentMixin
from packages.business_intel.source_reconciliation import (
    build_source_reconciliation,
    evidence_by_source_token,
    malformed_source_tokens,
    normalize_report_source_tokens,
    normalize_report_version_sources,
    raw_source_alias_metadata,
    source_token_alias_map,
    source_tokens,
)
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import EnterpriseRunProjection, EvidenceRecord, ReportVersionRecord
from packages.schema.models import AnalysisPlan, QCIssue, RawSource, RedoScope


class _QaHarness(QualityAgentMixin):
    def _extract_cited_source_ids(self, text: str) -> list[str]:
        return source_tokens(text)


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
        "evidence-1": ["evidence-1", "pricing-current"]
    }


def test_source_normalizer_rewrites_source_tokens_to_raw_source_tokens() -> None:
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-raw",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        reliability_score=0.9,
        metadata=raw_source_alias_metadata("pricing-old"),
    )

    normalized = normalize_report_source_tokens(
        "Known [source:pricing-old#chunk:0] and [source:evidence-1].",
        [evidence],
        scoped_evidence_ids=["evidence-1"],
    )

    assert normalized.report_md == "Known [source:pricing-raw] and [source:pricing-raw]."
    assert normalized.evidence_ids == ["evidence-1"]
    assert [item.status for item in normalized.resolutions] == ["alias", "alias"]
    reconciliation = normalized.reconciliation([evidence])
    assert reconciliation["canonical_report_md_changed"] is True
    assert reconciliation["canonical_report_source_tokens"] == ["pricing-raw"]
    assert reconciliation["unresolved_report_source_tokens"] == []


def test_source_reconciliation_without_scope_uses_all_evidence() -> None:
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-raw",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        reliability_score=0.9,
    )

    reconciliation = build_source_reconciliation(
        "Cursor pricing. [source:pricing-raw]",
        [evidence],
    )

    assert reconciliation["scoped_evidence_ids"] == ["evidence-1"]
    assert reconciliation["unresolved_report_source_tokens"] == []


def test_source_normalizer_without_scope_uses_all_evidence() -> None:
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-raw",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        reliability_score=0.9,
    )

    normalized = normalize_report_source_tokens(
        "Cursor pricing. [source:pricing-raw]",
        [evidence],
    )

    assert normalized.report_md == "Cursor pricing. [source:pricing-raw]"
    assert normalized.evidence_ids == ["evidence-1"]
    assert normalized.resolutions[0].status == "resolved"


def test_report_version_normalizer_preserves_empty_explicit_scope() -> None:
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-raw",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        reliability_score=0.9,
    )
    version = ReportVersionRecord(
        id="report-1",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="topic",
        competitor_layer="L1",
        competitor_set_hash="set",
        report_md="No citations yet.",
        evidence_ids=[],
    )

    normalized = normalize_report_version_sources(version, [evidence])

    assert normalized.evidence_ids == []
    assert normalized.report_md == "No citations yet."


def test_source_normalizer_adds_known_out_of_scope_evidence_to_report_scope() -> None:
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-raw",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        reliability_score=0.9,
    )
    version = ReportVersionRecord(
        id="report-1",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="topic",
        competitor_layer="L1",
        competitor_set_hash="set",
        report_md="Cursor pricing. [source:pricing-raw]",
        evidence_ids=[],
    )

    normalized = normalize_report_version_sources(version, [evidence])

    assert normalized.report_md == "Cursor pricing. [source:pricing-raw]"
    assert normalized.evidence_ids == ["evidence-1"]
    reconciliation = normalized.quality_metadata["source_reconciliation"]
    assert reconciliation["unresolved_report_source_tokens"] == []
    assert reconciliation["source_resolutions"][0]["status"] == "alias"


def test_source_normalizer_removes_malformed_report_tokens() -> None:
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-raw",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        reliability_score=0.9,
    )

    normalized = normalize_report_source_tokens(
        "Valid [source:pricing-raw]. Invalid [source: all persona cells].",
        [evidence],
    )

    assert normalized.report_md == "Valid [source:pricing-raw]. Invalid ."
    assert malformed_source_tokens("Invalid [source: all persona cells].") == [
        "all persona cells"
    ]
    reconciliation = normalized.reconciliation([evidence])
    assert reconciliation["unresolved_report_source_tokens"] == ["all persona cells"]
    assert reconciliation["source_resolutions"][-1]["status"] == "malformed"


def test_source_token_alias_map_unifies_raw_and_evidence_tokens() -> None:
    raw_source = RawSource(
        id="pricing-raw",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://cursor.com/pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        confidence=0.9,
    )
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-raw",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        reliability_score=0.9,
        metadata=raw_source_alias_metadata("pricing-old"),
    )

    aliases = source_token_alias_map(raw_sources=[raw_source], evidence=[evidence])

    assert aliases["evidence-1"] == "pricing-raw"
    assert aliases["pricing-raw"] == "pricing-raw"
    assert aliases["pricing-old"] == "pricing-raw"


def test_run_qa_resolves_enterprise_evidence_tokens() -> None:
    detail = _run_detail_with_enterprise_report()

    issues = _QaHarness()._build_phantom_citation_issues(detail)

    assert [issue.problem for issue in issues] == [
        "Report contains malformed source token all persona cells."
    ]


def test_run_qa_refresh_replaces_stale_writer_source_findings() -> None:
    detail = _run_detail_with_enterprise_report()
    retained_issue = QCIssue(
        id="qc-retained",
        severity="warn",
        detected_by="coverage",
        target_agent="collector",
        field_path="raw_sources",
        problem="Coverage still needs review.",
        redo_scope=RedoScope(kind="collector", rationale="coverage review"),
        self_found=False,
    )
    detail.qa_findings = [
        QCIssue(
            id="qc-stale-evidence",
            severity="blocker",
            detected_by="citation",
            target_agent="writer",
            field_path="report_md",
            problem="Report cites unknown source id evidence-1.",
            redo_scope=RedoScope(kind="writer_only", rationale="stale citation"),
            self_found=False,
        ),
        retained_issue,
    ]

    changed = _QaHarness()._refresh_report_source_qa_findings(detail)

    assert changed is True
    assert [issue.problem for issue in detail.qa_findings] == [
        "Coverage still needs review.",
        "Report contains malformed source token all persona cells.",
    ]


def _run_detail_with_enterprise_report() -> RunDetail:
    raw_source = RawSource(
        id="pricing-raw",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://cursor.com/pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        confidence=0.9,
    )
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        run_id="run-1",
        raw_source_id="pricing-raw",
        competitor_id="cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor publishes pricing.",
        content_hash="hash-1",
        reliability_score=0.9,
    )
    return RunDetail(
        id="run-1",
        workspace_id="workspace-1",
        topic="Cursor pricing",
        status="completed",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="Cursor pricing",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
        report_md=(
            "Cursor publishes pricing. [source:evidence-1] "
            "Bad aggregate marker. [source: all persona cells]"
        ),
        raw_sources=[raw_source],
        enterprise_projection=EnterpriseRunProjection(
            workspace_id="workspace-1",
            project_id="project-1",
            run_id="run-1",
            evidence_records=[evidence],
            claim_records=[],
            report_version=ReportVersionRecord(
                id="report-1",
                workspace_id="workspace-1",
                project_id="project-1",
                run_id="run-1",
                version_number=1,
                topic_normalized="cursor-pricing",
                competitor_layer="L1",
                competitor_set_hash="set",
                report_md="Cursor publishes pricing. [source:evidence-1]",
                evidence_ids=["evidence-1"],
            ),
        ),
    )
