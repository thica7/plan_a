from datetime import datetime
from types import SimpleNamespace

import pytest

from packages.config import Settings
from packages.skills import SkillRegistry
from packages.orchestrator.service import RunService, RunRecord
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource


def fixture():
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=Settings(demo_mode=True))
    now = datetime.utcnow()
    detail = RunDetail(id="partial", topic="协作", status="running", execution_mode="real", created_at=now, updated_at=now, plan=AnalysisPlan(topic="协作", competitors=["Notion", "Coda"], dimensions=["feature", "pricing"], complexity="low"), max_iterations=1)
    detail.raw_sources = [RawSource(id="verified", competitor="Notion", covered_competitors=["Notion"], dimension="feature", source_type="webpage_verified", title="Notion collaboration", url="https://www.notion.com/help/collaborate-with-people", snippet="Multiple people edit a page at the same time with live changes.", content_hash="body", confidence=.9, metadata={"evidence_items": [{"status": "accepted", "field": "capability_1", "quote": "Multiple people edit a page at the same time with live changes."}]})]
    detail.raw_sources[0].metadata["normalized_fields"] = [{"kind": "feature", "evidence_quote": detail.raw_sources[0].snippet}]
    service._runs[detail.id] = RunRecord(detail=detail)
    return service, detail


def test_missing_branch_continues_with_blockers_after_retry_budget():
    service, detail = fixture()
    detail.qa_findings = service._build_collect_qa_issues(detail)
    route = service._route_phase_qa({"run_id": detail.id, "collect_qa_attempts": 1}, "collect")
    assert route == "pass"
    assert detail.status != "failed"
    assert any(issue.severity == "blocker" and issue.metadata.get("partial_report_gap") for issue in detail.collect_qa_findings)
    assert detail.raw_sources[0].id == "verified"


def test_all_missing_still_fails():
    service, detail = fixture()
    detail.raw_sources = []
    detail.qa_findings = service._build_collect_qa_issues(detail)
    assert service._route_phase_qa({"run_id": detail.id, "collect_qa_attempts": 1}, "collect") == "fail"


def test_analyst_pass_preserves_collector_gaps_for_comparator_and_writer():
    service, detail = fixture()
    detail.qa_findings = service._build_collect_qa_issues(detail)
    assert service._route_phase_qa({"run_id": detail.id}, "analyst") == "pass"
    assert detail.qa_findings
    assert all(issue.target_agent == "collector" and issue.severity == "blocker" for issue in detail.qa_findings)


def test_invalid_identity_still_fails():
    service, detail = fixture()
    detail.raw_sources[0].covered_competitors = ["Figma"]
    detail.qa_findings = service._build_collect_qa_issues(detail)
    assert service._route_phase_qa({"run_id": detail.id, "collect_qa_attempts": 1}, "collect") == "fail"


@pytest.mark.asyncio
@pytest.mark.parametrize("scoped", [False, True])
async def test_partial_analysis_uses_original_scope(scoped, monkeypatch):
    from packages.orchestrator.graph import _add_real_nodes
    from packages.schema.api_dto import PendingGraphRedo
    from packages.schema.models import RedoScope
    service, detail = fixture()
    record = service._runs[detail.id]
    detail.qa_findings = service._build_collect_qa_issues(detail)
    if scoped:
        record.active_graph_kind = "scoped_redo"
        scope = RedoScope(kind="collector", target_subagent="pricing", target_competitor="Coda", rationale="补证")
        record.pending_graph_redo = PendingGraphRedo(iteration=1, stage="collector", redo_scope=scope, redo_scopes=[scope], before_md="old", issue_ids=[], qa_issue_ids_before=[], issue_count_before=0)
    async def prepare(*args, **kwargs): return SimpleNamespace(id="snapshot")
    async def qa(*args, **kwargs): pass
    monkeypatch.setattr(service, "_prepare_evidence_snapshot", prepare)
    monkeypatch.setattr(service, "_real_phase_qa_step", qa)
    class Graph:
        def __init__(self): self.nodes = {}
        def add_node(self, name, node): self.nodes[name] = node
    graph = Graph(); _add_real_nodes(graph, service)
    state = await graph.nodes["collect_qa"]({"run_id": detail.id, "dimensions": ["pricing"], "target_competitors": ["Coda"], "collect_qa_attempts": 0})
    assert state["dimensions"] == (["pricing"] if scoped else ["feature", "pricing"])
    assert state["target_competitors"] == (["Coda"] if scoped else [])


def test_directed_redo_resets_only_selected_branch_allowance():
    from packages.schema.api_dto import CollectorResearchUsage
    from packages.schema.models import RedoScope
    service, detail = fixture(); record = service._runs[detail.id]
    branch = service._analyst_branch_id("pricing", "Coda")
    untouched = service._analyst_branch_id("feature", "Notion")
    detail.collector_research_usage = {branch: CollectorResearchUsage(search_calls=2, fetch_calls=4), untouched: CollectorResearchUsage(search_calls=2)}
    record.semantic_extraction_cache = {("Coda", "pricing", "a"): None, ("Notion", "feature", "b"): None}
    scope = RedoScope(kind="collector", target_subagent="pricing", target_competitor="Coda", rationale="缺价")
    service._reset_collector_redo_allowance(record, scope)
    assert branch not in detail.collector_research_usage
    assert detail.collector_research_usage[untouched].search_calls == 2
    assert list(record.semantic_extraction_cache) == [("Notion", "feature", "b")]


def test_repair_query_comes_from_matching_gap_only():
    from packages.research.discovery import build_search_queries
    service, detail = fixture()
    detail.qa_findings = service._build_collect_qa_issues(detail)
    tasks = service._collector_targeted_repairs(detail, "Coda", "pricing")
    assert tasks and all(task.competitor == "Coda" and task.dimension == "pricing" for task in tasks)
    brief = service._research_brief(detail, "Coda", "pricing")
    assert "current plan prices currency billing interval seat type" in build_search_queries(brief, repair_tasks=tasks)[0]
    assert not service._collector_targeted_repairs(detail, "Notion", "feature")


@pytest.mark.parametrize("agent", ["qa", "collect_qa", "analyst_qa"])
def test_local_audits_can_inspect_large_source_without_false_retirement(agent):
    from packages.research.evidence.snapshot import seal_snapshot
    service, detail = fixture(); record = service._runs[detail.id]
    detail.plan.research_depth = "quick"
    source = detail.raw_sources[0]
    source.metadata["last_verified_at"] = datetime.utcnow().isoformat()
    source.metadata["normalized_fields"] = [
        {"kind": "feature", "competitor": "Notion", "dimension": "feature", "slot": f"capability_{i}",
         "support_level": "documented", "evidence_terms": [f"Notion supports shared document workflow number {i}."],
         "evidence_quote": f"Notion supports shared document workflow number {i}.", "confidence": .8}
        for i in range(12)
    ]
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    generation, _ = service._begin_evidence_use(record, agent="writer", source_ids=[source.id])
    audit, _ = service._begin_evidence_use(record, agent=agent, source_ids=[source.id])
    assert len(generation.facts) < len(snapshot.facts)
    assert len(audit.facts) == len(snapshot.facts)
    assert audit.estimated_bytes <= audit.max_bytes and audit.max_bytes >= 65536
    assert not any(gap.reason == "context_budget_exceeded" for gap in audit.gaps)


@pytest.mark.asyncio
async def test_dimension_level_issue_keeps_scoped_cleanup_and_dispatch_local(monkeypatch):
    from packages.orchestrator.graph import _add_real_nodes
    from packages.schema.api_dto import PendingGraphRedo
    from packages.schema.models import QCIssue, RedoScope
    service, detail = fixture(); record = service._runs[detail.id]
    detail.max_iterations = 3
    detail.raw_sources = [detail.raw_sources[0].model_copy(update={"id": product, "competitor": product, "covered_competitors": [product], "dimension": "pricing"}) for product in ["Notion", "Coda"]]
    scope = RedoScope(kind="collector", target_subagent="pricing", target_competitor="Coda", rationale="补证")
    detail.qa_findings = [QCIssue(id="invalid-pricing", field_path="raw_sources.pricing", redo_scope=scope, severity="blocker", detected_by="coverage", target_agent="collector", target_subagent="pricing", problem="Pricing sources are invalid.")]
    record.active_graph_kind = "scoped_redo"
    record.pending_graph_redo = PendingGraphRedo(iteration=1, stage="collector", redo_scope=scope, redo_scopes=[scope], before_md="old", issue_ids=[], qa_issue_ids_before=[], issue_count_before=0)
    async def prepare(*args, **kwargs): return SimpleNamespace(id="snapshot")
    async def qa(*args, **kwargs): pass
    monkeypatch.setattr(service, "_prepare_evidence_snapshot", prepare)
    monkeypatch.setattr(service, "_real_phase_qa_step", qa)
    class Graph:
        def __init__(self): self.nodes = {}
        def add_node(self, name, node): self.nodes[name] = node
    graph = Graph(); _add_real_nodes(graph, service)
    state = await graph.nodes["collect_qa"]({"run_id": detail.id, "dimensions": ["pricing"], "target_competitors": ["Coda"], "collect_qa_attempts": 0})
    assert state["target_competitors"] == ["Coda"]
    assert state["dimensions"] == ["pricing"]
    assert service._route_phase_qa({"run_id": detail.id, **state}, "collect") == "retry"
    assert [source.id for source in detail.raw_sources] == ["Notion"]


@pytest.mark.asyncio
async def test_audit_capacity_gap_does_not_retire_a_reliable_source(monkeypatch):
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.research.evidence.views import select_evidence_view
    service, detail = fixture(); record = service._runs[detail.id]
    detail.raw_sources[0].metadata["last_verified_at"] = datetime.utcnow().isoformat()
    # Keep a genuinely oversized original after prompt metadata deduplication.
    detail.raw_sources[0].snippet += " Full original description." * 100
    detail.raw_sources[0].metadata["normalized_fields"][0]["evidence_quote"] = detail.raw_sources[0].snippet
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    source_id = detail.raw_sources[0].id
    detail.report_md = f"Documented capability [source:{source_id}]"
    original_begin = service._begin_evidence_use
    def limited(*args, **kwargs):
        view, use = original_begin(*args, **kwargs)
        return select_evidence_view(snapshot, agent="qa", source_ids=[source_id], max_bytes=1200), use
    monkeypatch.setattr(service, "_begin_evidence_use", limited)
    monkeypatch.setattr(service, "_final_qa_producer_verified", lambda *args: True)
    _, issues, _ = await service._final_qa_evidence(record)
    capacity = [issue for issue in issues if issue.metadata.get("evidence_reason") == "context_budget_exceeded"]
    assert capacity and all(issue.target_agent == "writer" for issue in capacity)
    assert all(issue.redo_scope.kind == "writer_only" for issue in capacity)
    assert not any(issue.target_agent == "collector" for issue in issues)


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_writer", [False, True])
async def test_final_qa_coverage_includes_frozen_uncited_sources(monkeypatch, historical_writer):
    from packages.research.evidence.snapshot import seal_snapshot
    service, detail = fixture(); record = service._runs[detail.id]
    detail.raw_sources[0].metadata["last_verified_at"] = datetime.utcnow().isoformat()
    detail.report_md = "Documented capability [source:verified]"
    if historical_writer:
        original = seal_snapshot(detail, phase="analysis", canonical_documents={})
        _, writer_use = service._begin_evidence_use(record, agent="writer", source_ids=["verified"])
        service._validate_evidence_use(record, writer_use)
        service._record_evidence_artifact(record, kind="writer", uses=[writer_use], payload=service._writer_evidence_artifact_payload(detail))
    other = detail.raw_sources[0].model_copy(deep=True)
    other.id = "uncited-coda"; other.competitor = "Coda"; other.covered_competitors = ["Coda"]
    detail.raw_sources.append(other)
    current = seal_snapshot(detail, phase="analysis", canonical_documents={})
    if historical_writer:
        assert service._final_qa_snapshot(record).id == original.id != current.id
    monkeypatch.setattr(service, "_build_qa_issues", service._build_collect_qa_issues)
    await service._real_qa_step(record)
    assert not any(issue.target_subagent == "feature" and issue.metadata.get("issue_kind") == "missing_evidence" for issue in detail.qa_findings)
    assert any(use.agent == "collect_qa" and "uncited-coda" in use.requested_source_ids and use.snapshot_id == current.id for use in detail.evidence_consumptions)
