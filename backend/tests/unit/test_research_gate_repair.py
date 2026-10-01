from datetime import datetime
from types import SimpleNamespace

import pytest

from packages.agents.writer.prompt_builder import WriterPromptBuilder
from packages.agents.writer.quality_preflight import run_writer_quality_preflight
from packages.agents.writer.repair import build_writer_repair_plan
from packages.auth import EnterpriseUserContext
from packages.business_intel.manual_revision import validate_manual_revision
from packages.business_intel.release_gate import (
    _release_report_quality_detail,
    evaluate_report_release_gate,
)
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import PreferenceMemoryStore
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evaluation.gaps import quality_gaps_from_extractions
from packages.research.evaluation.release_gate import quality_gaps_from_release_gate
from packages.research.models import QualityGap, ResearchBrief
from packages.research.repair.strategies import query_hints_for_gap
from packages.runtime.service import RuntimeCommandError, RuntimeCommandService
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import (
    ClaimRecord,
    CompetitorRecord,
    EnterpriseRunProjection,
    EvidenceRecord,
    ManualReportRevisionRequest,
    ProjectRecord,
    ReportVersionRecord,
)
from packages.schema.models import AgentMessage, AnalysisPlan, QCIssue, RedoScope, RevisionRecord
from packages.skills.registry import SkillRegistry


def _records():
    project = ProjectRecord(
        id="project-1", workspace_id="workspace-1", name="Phone comparison",
        topic="Phone comparison", topic_normalized="phone", competitor_layer="L1",
        competitor_set_hash="hash", scenario_id="l1_pricing_pack",
    )
    competitor = CompetitorRecord(
        id="phone", workspace_id="workspace-1", name="Phone", normalized_name="phone",
        homepage_url="https://example.com", layer="L1",
    )
    evidence = EvidenceRecord(
        id="evidence-1", workspace_id="workspace-1", project_id=project.id, run_id="run-1",
        competitor_id=competitor.id, raw_source_id="pricing-1", dimension="pricing",
        source_type="webpage_verified", title="Phone price", url="https://example.com/price",
        snippet="Phone costs $499.", content_hash="hash-1",
        reliability_score=0.95, quality_label="accepted",
    )
    claim = ClaimRecord(
        id="claim-1", workspace_id="workspace-1", project_id=project.id, run_id="run-1",
        competitor_id=competitor.id, claim_type="pricing", claim_text="Phone costs $499.",
        evidence_ids=[evidence.id], confidence=0.95,
    )
    report = ReportVersionRecord(
        id="report-1", workspace_id="workspace-1", project_id=project.id,
        run_id="run-1", version_number=1, topic_normalized="phone", competitor_layer="L1",
        competitor_set_hash="hash",
        report_md="## Executive Summary\nPhone costs $499. [source:evidence-1]",
        evidence_ids=[evidence.id], claim_ids=[claim.id],
        quality_metadata={"analysis_plan": {
            "topic": "Phone comparison", "competitors": ["Phone"], "dimensions": ["pricing"],
            "research_depth": "quick", "collaboration_mode": "assisted",
            "decision_brief": {"decision_question": "Which phone?"},
        }},
    )
    return project, competitor, evidence, claim, report


def _gate(report, *, purpose="publication"):
    project, competitor, evidence, claim, _ = _records()
    return evaluate_report_release_gate(
        project=project, report_version=report, competitors=[competitor],
        evidence=[evidence], claims=[claim], purpose=purpose,
    )


def test_internal_quick_draft_warns_about_depth_while_publication_blocks():
    *_, report = _records()
    internal = _gate(report, purpose="internal")
    publication = _gate(report)
    assert internal.allowed is True
    assert internal.warn_count > 0
    assert publication.allowed is False
    assert "report_depth_required" in {issue.rule_id for issue in publication.issues}


def test_internal_gate_still_blocks_out_of_scope_citation():
    *_, report = _records()
    report = report.model_copy(update={"report_md": report.report_md + " [source:unknown]"})
    gate = _gate(report, purpose="internal")
    assert gate.allowed is False
    assert any(
        issue.rule_id == "report_citation_resolves" and issue.severity == "blocker"
        for issue in gate.issues
    )


def test_gate_quality_detail_preserves_real_depth_and_collaboration_mode():
    _, competitor, evidence, _, report = _records()
    detail = _release_report_quality_detail(
        report, competitors=[competitor], evidence=[evidence], dimensions=["pricing"],
    )
    assert detail.plan.research_depth == "quick"
    assert detail.plan.collaboration_mode == "assisted"
    assert detail.plan.decision_brief.decision_question == "Which phone?"


@pytest.mark.parametrize("category", ["手机", "consumer electronics", "general product", ""])
@pytest.mark.parametrize("strategy", [
    "pricing_model_repair", "feature_slot_repair", "persona_schema_repair",
])
def test_repair_queries_do_not_assume_api_software(category, strategy):
    gap = QualityGap(
        severity="warn", dimension="pricing", competitor="Phone", reason="missing",
        suggested_action=strategy, acceptance_rule="source required",
        metadata={"product_category": category},
    )
    queries = " ".join(query_hints_for_gap(gap, [])).casefold()
    assert "api" not in queries
    assert "token" not in queries
    assert "developer" not in queries


def test_explicit_api_category_keeps_api_repair_queries():
    gap = QualityGap(
        severity="warn", dimension="pricing", competitor="API", reason="missing",
        suggested_action="pricing_model_repair", acceptance_rule="source required",
        metadata={"product_category": "LLM API software"},
    )
    assert any("token" in query for query in query_hints_for_gap(gap, []))


def test_quick_writer_prompt_uses_core_summary_product_comparison_and_limits():
    now = datetime.utcnow()
    detail = RunDetail(id="quick", topic="Phone", status="running", execution_mode="demo",
                       created_at=now, updated_at=now,
                       plan=AnalysisPlan(topic="Phone", competitors=["Phone"],
                                         dimensions=["pricing"], research_depth="quick"))
    prompt = WriterPromptBuilder().first_draft_prompt(
        detail, language_guidance="", user_research_policy="", memory_context="", layer_context="",
        grounding_prompt="", community_policy_text="", writer_context_json="{}",
        required_sections="## Summary",
    )
    assert "SWOT" not in prompt.user
    assert "product" in prompt.user.casefold()
    assert "limitations" in prompt.user.casefold()


def test_quick_writer_preflight_and_backfill_do_not_require_swot():
    now = datetime.utcnow()
    detail = RunDetail(id="quick", topic="Phone", status="running", execution_mode="demo",
                       created_at=now, updated_at=now,
                       plan=AnalysisPlan(topic="Phone", competitors=["Phone"],
                                         dimensions=["pricing"], research_depth="quick"))
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=Settings())
    markdown = (
        "## Executive Summary\nCore finding.\n## Competitive Findings\nProduct comparison.\n"
        "## Confidence Notes\nLimitations."
    )
    assert run_writer_quality_preflight(detail, markdown).passed is True
    assert service._ensure_report_required_sections(detail, markdown) == markdown
    assert "SWOT" not in service._writer_required_sections(detail)


def test_quick_line_repair_preserves_compact_report():
    service, record, _ = _repair_service()
    record.detail.plan.decision_brief = None
    record.detail.report_md = (
        "## Executive Summary\nSummary.\n## Competitive Findings\n"
        "Phone costs $499. [source:evidence-1]\n## Confidence Notes\nLimitations."
    )
    issue = _redo_issue("line")
    plan = build_writer_repair_plan(record.detail, [issue])
    assert plan.mode == "line"


@pytest.mark.asyncio
async def test_actual_quick_writer_avoids_segmented_full_report_prompt():
    service, record, _ = _repair_service()
    record.detail.plan.competitor_layer = "L1"
    captured = []
    async def text_call(*args, **kwargs):
        captured.append(kwargs)
        return "quick draft"
    async def grounding(*args):
        return "Grounded evidence"
    service._trace_llm_text = text_call
    service._writer_grounding_prompt = grounding
    pack = SimpleNamespace(
        metrics=SimpleNamespace(segmented_writer_required=True), to_prompt_json=lambda: "{}",
    )
    result = await service._writer_markdown_report_from_evidence_pack(record, pack, 1)
    assert result == "quick draft"
    assert "SWOT" not in captured[0]["user"]
    assert "1,200-2,000" in captured[0]["user"]
    assert "limitations" in captured[0]["user"]
    assert "battlecard" not in captured[0]["system"].casefold()
    assert "battlecard" not in captured[0]["user"].casefold()


def test_extraction_gap_carries_product_category_into_repair():
    brief = ResearchBrief(
        run_id="run", topic="Phone", competitor="Phone", dimension="pricing",
        product_category="手机",
    )
    gaps = quality_gaps_from_extractions(brief, [])
    assert gaps[0].metadata["product_category"] == "手机"


@pytest.mark.parametrize("body", [
    "Phone costs $499.", "Phone is the best phone. [source:evidence-1]",
])
def test_manual_revision_revalidates_current_claims_instead_of_inheriting_old_qa(body):
    store = EnterpriseMemoryStore()
    project, competitor, evidence, claim, source = _records()
    store.upsert_project(project)
    store.competitors[competitor.id] = competitor
    store.save_projection(EnterpriseRunProjection(
        workspace_id=source.workspace_id, project_id=source.project_id, run_id=source.run_id,
        evidence_records=[evidence], claim_records=[claim], report_version=source,
    ))
    source = store.upsert_report_version(source.model_copy(update={"quality_metadata": {
        "run_qa_findings": [], "release_gate": {"allowed": True},
    }}))
    service = RuntimeCommandService(
        settings=Settings(), run_service=object(), workflow_service=object(),
        enterprise_store=store, preference_memory=PreferenceMemoryStore.in_memory(),
    )
    revision, _ = service._create_manual_report_revision(
        source, ManualReportRevisionRequest(
            report_md="## Executive Summary\n" + body, note="Changed facts",
        ),
        EnterpriseUserContext(user_id="reviewer", role="owner", workspace_id="workspace-1"),
    )
    assert revision.claim_ids != source.claim_ids
    assert revision.quality_metadata["release_gate"]["allowed"] is False
    assert revision.quality_metadata["manual_revision"]["validation_status"] == "blocked"
    assert any(
        item["severity"] == "blocker" for item in revision.quality_metadata["run_qa_findings"]
    )


def _repair_service():
    project, competitor, evidence, claim, report = _records()
    store = EnterpriseMemoryStore()
    store.upsert_project(project)
    store.competitors[competitor.id] = competitor
    projection = EnterpriseRunProjection(
        workspace_id=report.workspace_id, project_id=report.project_id, run_id=report.run_id,
        evidence_records=[evidence], claim_records=[claim], report_version=report,
    )
    store.save_projection(projection)
    now = datetime.utcnow()
    detail = RunDetail(
        id=report.run_id, topic=project.topic, status="completed", execution_mode="real",
        created_at=now, updated_at=now,
        plan=AnalysisPlan.model_validate(report.quality_metadata["analysis_plan"]),
        report_md=report.report_md, enterprise_projection=projection)
    detail.hitl_enabled = False
    detail.max_iterations = 5
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(), settings=Settings(),
        enterprise_store=store,
    )
    service._runs[detail.id] = RunRecord(detail=detail)
    return service, service._runs[detail.id], projection


def test_orchestrator_internal_gate_persists_analysis_contract():
    service, record, projection = _repair_service()
    projection.report_version.quality_metadata.pop("analysis_plan")
    gate = service._evaluate_report_release_gate(projection)
    assert gate.allowed is True
    service._attach_release_gate_quality_metadata(projection, gate)
    assert projection.report_version.quality_metadata["analysis_plan"]["research_depth"] == "quick"
    assert projection.report_version.quality_metadata["release_gate"]["purpose"] == "internal"


def _redo_issue(issue_id):
    return QCIssue(
        id=issue_id, severity="blocker", detected_by="citation", target_agent="writer",
        field_path="report_md.line[2]", problem="unsupported",
        redo_scope=RedoScope(kind="writer_only", rationale="fix line"),
    )


def test_repair_acceptance_metadata_records_versions_targets_and_resolution():
    service, record, projection = _repair_service()
    record.detail.qa_findings = [_redo_issue("remaining")]
    record.detail.revisions = [RevisionRecord(id="revision-1", iteration=1, stage="writer_only",
        before_md="Old body", after_md=record.detail.report_md, issue_ids=["fixed", "remaining"],
        qa_issue_ids_before=["fixed", "remaining"], issue_count_before=2, issue_count_after=1,
        metadata={"before_report_version_id": "old-version", "writer_repair_mode": "line",
                  "writer_repair_sections": ["competitive_findings"]})]
    gate = _gate(projection.report_version, purpose="internal").model_copy(update={
        "issues": [], "issue_count": 0, "blocker_count": 0, "warn_count": 0,
    })
    service._attach_release_gate_quality_metadata(projection, gate)
    acceptance = projection.report_version.quality_metadata["repair_acceptance"][-1]
    assert acceptance["mode"] == "line"
    assert acceptance["sections"] == ["competitive_findings"]
    assert acceptance["before_report_version_id"] == "old-version"
    assert acceptance["after_report_version_id"] == projection.report_version.id
    assert acceptance["resolved_issue_ids"] == ["fixed"]
    assert acceptance["remaining_issue_ids"] == ["remaining"]
    assert acceptance["improved"] is True
    assert acceptance["no_progress"] is False


@pytest.mark.asyncio
async def test_auto_redo_stops_after_repeated_attempts_without_issue_improvement():
    service, record, _ = _repair_service()
    record.detail.qa_findings = [_redo_issue("stuck")]
    record.detail.revisions = [RevisionRecord(
        id=f"rev-{iteration}", iteration=iteration, stage="writer_only",
        issue_ids=["stuck"], qa_issue_ids_before=["stuck"],
        issue_count_before=1, issue_count_after=1,
        redo_scopes=[record.detail.qa_findings[0].redo_scope],
        metadata={"qa_issue_ids_after": ["stuck"]})
        for iteration in (1, 2)]
    called = []
    async def redo(*args, **kwargs):
        called.append(args)
    service.run_scoped_redo = redo
    assert await service._maybe_run_auto_redo(record) is False
    assert called == []
    assert any(event.payload.get("reason") == "no_progress" for event in record.events)


@pytest.mark.asyncio
async def test_each_revision_records_acceptance_before_next_auto_retry():
    service, record, projection = _repair_service()
    record.detail.qa_findings = []
    record.detail.agent_messages = [AgentMessage(id="writer-ready", run_id=record.detail.id,
        from_agent="writer", to_agent="qa", message_type="report_ready",
        payload_schema="MarkdownReport", payload={"writer_repair_mode": "section",
        "writer_repair_sections": ["competitive_findings"]})]
    await service._record_revision(record, iteration=1, stage="writer_only",
        redo_scope=RedoScope(kind="writer_only", rationale="fix"), redo_scopes=[],
        before_md="Old body", issue_ids=["fixed"], qa_issue_ids_before=["fixed"],
        issue_count_before=1,
        metadata={"before_report_version_id": "old-version"})
    acceptance = record.detail.revisions[-1].metadata["repair_acceptance"]
    assert acceptance["mode"] == "section"
    assert acceptance["resolved_issue_ids"] == ["fixed"]
    assert acceptance["after_report_version_id"] == projection.report_version.id


def test_manual_new_sentence_does_not_inherit_previous_sentence_citation():
    _, _, evidence, _, report = _records()
    report = report.model_copy(update={
        "report_md": "Phone costs $499. [source:evidence-1] Phone lasts forever.",
    })
    _, metadata = validate_manual_revision(report, [evidence])
    assert metadata["run_qa_blocker_count"] == 1
    assert metadata["unresolved_manual_claims"][0]["claim_text"] == "Phone lasts forever."


def test_manual_markdown_table_headers_are_not_treated_as_unsupported_facts():
    _, _, evidence, _, report = _records()
    report = report.model_copy(update={"report_md": (
        "| Claim | Evidence |\n| --- | --- |\n| Phone costs $499. | [source:evidence-1] |"
    )})
    claims, metadata = validate_manual_revision(report, [evidence])
    assert len(claims) == 1
    assert metadata["run_qa_blocker_count"] == 0


@pytest.mark.asyncio
async def test_auto_redo_compares_same_problem_even_when_issue_ids_change():
    service, record, _ = _repair_service()
    record.detail.qa_findings = [_redo_issue("new-id")]
    record.detail.revisions = [RevisionRecord(
        id=f"rev-{iteration}", iteration=iteration, stage="writer_only",
        issue_ids=[f"old-{iteration}"], issue_count_before=1, issue_count_after=1,
        metadata={"qa_issue_ids_after": [f"new-{iteration}"],
                  "repair_issue_keys": ["report_md.line[2]|writer_only"]})
        for iteration in (1, 2)]
    async def unexpected_redo(*args, **kwargs):
        raise AssertionError("repeated unchanged problem must stop")
    service.run_scoped_redo = unexpected_redo
    assert await service._maybe_run_auto_redo(record) is False


def test_internal_deep_requires_more_analysis_than_standard_as_warning():
    *_, report = _records()
    body = report.report_md + "\n" + ("Analysis detail. " * 75)
    standard = report.model_copy(update={"report_md": body, "quality_metadata": {"analysis_plan": {
        **report.quality_metadata["analysis_plan"], "research_depth": "standard",
    }}})
    deep = standard.model_copy(update={"quality_metadata": {"analysis_plan": {
        **standard.quality_metadata["analysis_plan"], "research_depth": "deep",
    }}})
    assert not any(
        issue.rule_id == "report_depth_required"
        for issue in _gate(standard, purpose="internal").issues
    )
    assert any(issue.rule_id == "report_depth_required" and issue.severity == "warn"
               for issue in _gate(deep, purpose="internal").issues)


def test_publication_command_rechecks_quick_draft_with_strict_gate():
    service, _, projection = _repair_service()
    assert service._evaluate_report_release_gate(projection).allowed is True
    runtime = RuntimeCommandService(
        settings=Settings(), run_service=service, workflow_service=object(),
        enterprise_store=service._enterprise_store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )
    with pytest.raises(RuntimeCommandError) as blocked:
        runtime._enforce_report_release_gate(
            projection.report_version,
            EnterpriseUserContext(user_id="reviewer", role="owner", workspace_id="workspace-1"),
        )
    assert blocked.value.status_code == 409
    assert any(issue["rule_id"] == "report_depth_required" and issue["severity"] == "blocker"
               for issue in blocked.value.detail["issues"])


def test_release_gate_repair_gap_preserves_known_product_category():
    *_, report = _records()
    report.quality_metadata["analysis_plan"]["target_product"] = {
        "name": "Phone", "category": "手机",
    }
    gaps = quality_gaps_from_release_gate(_gate(report, purpose="internal"))
    assert gaps
    assert all(gap.metadata["product_category"] == "手机" for gap in gaps)
