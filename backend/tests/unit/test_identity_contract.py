from pathlib import Path

from packages.identity import (
    compute_artifact_id,
    compute_competitor_id,
    compute_graph_thread_id,
    compute_project_id,
    compute_raw_source_id,
    compute_red_team_finding_id,
    compute_report_version_id,
    compute_run_id_for_idempotency_key,
    compute_source_registry_id,
    compute_survey_respondent_id,
    compute_workflow_id,
    new_run_id,
)

ROOT = Path(__file__).resolve().parents[3]


def test_identity_contract_generates_stable_typed_ids() -> None:
    raw_source_id = compute_raw_source_id(
        source_type="webpage_verified",
        competitor="Cursor",
        dimension="pricing",
        url="https://cursor.com/pricing?utm_source=test",
        content_hash="hash-1",
        title="Cursor pricing",
    )

    assert raw_source_id == compute_raw_source_id(
        source_type="webpage_verified",
        competitor="Cursor",
        dimension="pricing",
        url="https://cursor.com/pricing",
        content_hash="hash-1",
        title="Cursor pricing",
    )
    assert raw_source_id.startswith("raw-source-")
    assert compute_run_id_for_idempotency_key("abc").startswith("run-")
    assert new_run_id().startswith("run-")
    assert compute_workflow_id("competitive-intel", "abc").startswith("competitive-intel-")
    assert compute_graph_thread_id("run-1", "redo", 1).startswith("graph-thread-")
    assert compute_report_version_id(run_id="run-1", version_number=1).startswith("report-version-")
    assert compute_project_id("workspace-1", "Topic", ["competitor-1"]).startswith("project-")
    assert compute_competitor_id("workspace-1", "Cursor").startswith("competitor-")
    assert compute_source_registry_id("workspace-1", "cursor.com", "webpage_verified").startswith(
        "source-registry-"
    )
    assert compute_survey_respondent_id("run-1", "Cursor", "Pricing", 1).startswith(
        "survey-respondent-"
    )
    assert compute_red_team_finding_id(
        "missing-counterevidence",
        "competitor-1",
        "Pricing",
        "Needs more source diversity.",
        severity="major",
        evidence_ids=["evidence-1"],
        claim_ids=["claim-1"],
    ).startswith("red-team-")
    assert compute_artifact_id(
        workspace_id="workspace-1",
        project_id="project-1",
        evidence_id="evidence-1",
        artifact_type="web_snapshot",
        filename="Snapshot.txt",
        content_hash="hash-1",
    ).startswith("artifact-")


def test_core_modules_delegate_resource_ids_to_identity_contract() -> None:
    checked_files = {
        "backend/packages/enterprise/projection.py": [
            'id=f"report-',
        ],
        "backend/packages/rag/gap_fill.py": [
            "online-gap-",
            "report-version-gap-fill-{",
        ],
        "backend/packages/business_intel/evidence_gaps.py": [
            "evidence-gap-{hashlib",
            "schema-suggestion-{hashlib",
        ],
        "backend/packages/business_intel/evaluator.py": [
            "business-qa-{hashlib",
        ],
        "backend/packages/business_intel/release_gate.py": [
            "release-gate-{hashlib",
        ],
        "backend/packages/business_intel/red_team.py": [
            "red-team-{hashlib",
        ],
        "backend/packages/business_intel/scorer.py": [
            "recommendation-{hashlib",
        ],
        "backend/packages/artifacts/store.py": [
            "artifact-{hashlib",
        ],
        "backend/packages/workflows/service.py": [
            "report-approval-{",
            "scheduled-scan-{",
        ],
        "backend/packages/orchestrator/service.py": [
            'thread_id=f"',
        ],
        "backend/packages/agents/survey/logic.py": [
            'respondent_id=f"',
        ],
        "backend/packages/workflows/client.py": [
            "competitive-intel-{hashlib",
        ],
        "backend/packages/observability/tracing.py": [
            "hashlib.sha256",
        ],
    }
    for relative_path, forbidden_snippets in checked_files.items():
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            assert snippet not in text, f"{relative_path} still hand-rolls ID snippet {snippet!r}"
