import asyncio
import json
import os
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

import scripts.eval_live_products as live_eval
from app.events import RunEvent
from packages.config import Settings
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource, TraceSpan
from scripts.eval_live_products import failure_messages, summarize_acceptance


def detail(status="completed", report="## 产品对比\nNotion 支持文档协作。[source:n]"):
    now = datetime(2026, 10, 7)
    return RunDetail(
        id="public-test",
        topic="文档协作",
        status=status,
        execution_mode="real",
        created_at=now,
        updated_at=now,
        plan=AnalysisPlan(topic="文档协作", competitors=["Notion"], dimensions=["feature"]),
        report_md=report,
        raw_sources=[
            RawSource(
                id="n",
                competitor="Notion",
                dimension="feature",
                title="Notion",
                url="https://www.notion.com/",
                source_type="official",
                confidence=0.9,
                content_hash="public-test",
            )
        ],
    )


@pytest.mark.parametrize("status", ["failed", "running", "completed_with_blockers"])
def test_incomplete_or_blocked_report_never_passes_mechanical_acceptance(status):
    assert not summarize_acceptance(detail(status))["mechanical_pass"]


def test_generated_partial_report_is_separate_from_complete_acceptance():
    summary = summarize_acceptance(detail("completed_with_blockers"))
    assert summary["partial_report_generated"]
    assert not summary["mechanical_pass"]
    assert not summarize_acceptance(detail("completed_with_blockers", report=""))[
        "partial_report_generated"
    ]


@pytest.mark.parametrize("heading", ["来源与证据", "Evidence"])
def test_sources_only_report_does_not_count_as_product_analysis(heading):
    summary = summarize_acceptance(detail(report=f"## {heading}\nNotion [source:n]"))
    assert not summary["has_product_analysis_signal"]
    assert not summary["mechanical_pass"]


def test_invented_citation_fails_acceptance():
    assert not summarize_acceptance(detail(report="## 产品对比\nNotion [source:fake]"))[
        "citations_valid"
    ]


def test_mechanical_pass_does_not_fabricate_semantic_review():
    summary = summarize_acceptance(detail())
    assert summary["mechanical_pass"]
    assert summary["semantic_quality"] is None


def test_usage_separates_search_attempts_and_provider_tokens():
    run = detail()
    for index, (kind, status, tokens) in enumerate(
        [("llm", "ok", 10), ("search", "ok", 100), ("search", "error", 0)]
    ):
        run.trace_spans.append(
            TraceSpan(
                id=str(index),
                kind=kind,
                status=status,
                agent="test",
                name="test",
                duration_ms=1,
                metadata={"total_tokens": tokens, "token_usage_source": "provider"},
            )
        )
    summary = summarize_acceptance(run)
    assert summary["search_spans"] == 2
    assert summary["successful_search_spans"] == 1
    assert summary["provider_usage_by_kind"]["search"]["total_tokens"] == 100
    assert summary["provider_usage_by_kind"]["llm"]["total_tokens"] == 10


def test_stage_summary_uses_transport_and_module_result_instead_of_ok_span():
    run = detail()
    for identifier, agent, attempts, status in [
        ("a", "analyst", 1, "succeeded"),
        ("c", "comparator", 0, "rejected"),
        ("r", "reflector", 1, "error"),
    ]:
        run.trace_spans.append(
            TraceSpan(
                id=identifier,
                kind="llm",
                status="ok",
                agent=agent,
                name="structured",
                duration_ms=1,
                metadata={
                    "llm_transport_attempts": attempts,
                    "llm_phase": f"{agent}:run",
                    "llm_execution_status": status,
                    "token_usage_source": "estimate",
                },
            )
        )
    events = [
        RunEvent(
            id=1,
            run_id=run.id,
            type="node_completed",
            agent="comparator",
            message="fallback",
            payload={"module_status": "fallback", "matrix": {"winner": "tie"}},
        ),
        RunEvent(
            id=2,
            run_id=run.id,
            type="node_completed",
            agent="analyst",
            subagent="feature::B",
            message="skip",
            payload={"module_status": "skipped"},
        ),
        RunEvent(
            id=3,
            run_id=run.id,
            type="node_completed",
            agent="analyst",
            subagent="feature::C",
            message="cache",
            payload={"module_status": "cache"},
        ),
    ]
    summary = summarize_acceptance(run, events=events)
    assert summary["llm_transport_attempts"] == 2
    assert summary["llm_phases"]["comparator:run"]["transport_attempts"] == 0
    assert summary["llm_phases"]["reflector:run"]["execution_status_counts"] == {"error": 1}
    assert [row["module_status"] for row in summary["module_executions"]] == [
        "fallback",
        "skipped",
        "cache",
    ]
    assert summary["provider_usage_by_kind"]["llm"]["total_tokens"] is None
    assert summary["provider_usage_unknown_transport_spans"] == 2
    assert summary["semantic_quality"] is None


def test_configured_estimate_range_is_not_reported_as_provider_bill():
    run = detail()
    run.trace_spans = [
        TraceSpan(
            id="x",
            kind="search",
            status="ok",
            agent="collector",
            name="native search",
            duration_ms=1,
            input_tokens_estimate=100,
            output_tokens_estimate=20,
            metadata={"llm_transport_attempts": 1},
        )
    ]
    settings = Settings(
        llm_input_usd_per_million=2, llm_cache_usd_per_million=0.5, llm_output_usd_per_million=4
    )
    summary = summarize_acceptance(run, settings=settings)
    costs = summary["configured_cost_estimate"]
    assert costs["trace_estimate_range_usd"] == pytest.approx([0.00013, 0.00028])
    assert costs["provider_bill_usd"] is None
    assert costs["usage_complete"] is False


def test_explicit_local_profile_uses_temporary_storage_and_restores_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KB_DB_PATH", "existing.db")
    profile = tmp_path / "local.env.example"
    profile.write_text(
        "KB_RETRIEVAL_MODE=hybrid\nKB_EMBEDDING_PROVIDER=local-e5\n"
        "KB_RERANKER_PROVIDER=none\nKB_QDRANT_LOCAL_PATH=do-not-use\n"
    )
    with live_eval.local_knowledge_environment(profile, tmp_path / "isolated") as config:
        import os

        assert os.environ["KB_DB_PATH"] == str(tmp_path / "isolated" / "knowledge.db")
        assert os.environ["KB_QDRANT_LOCAL_PATH"] == str(tmp_path / "isolated" / "qdrant")
        assert config["requested_provider"] == "local-e5"
    import os

    assert os.environ["KB_DB_PATH"] == "existing.db"


def test_local_profile_rejects_hash_and_non_profile_settings(tmp_path):
    profile = tmp_path / "profile"
    profile.write_text("KB_EMBEDDING_PROVIDER=hash\nKB_RETRIEVAL_MODE=hybrid\n")
    with pytest.raises(ValueError, match="local semantic"):
        with live_eval.local_knowledge_environment(profile, tmp_path / "storage"):
            pass
    profile.write_text("ARK_API_KEY=synthetic-not-a-credential\n")
    with pytest.raises(ValueError, match="profile key"):
        with live_eval.local_knowledge_environment(profile, tmp_path / "storage"):
            pass


@pytest.mark.asyncio
async def test_local_profile_cleanup_releases_real_qdrant_through_storage_alias(tmp_path):
    from qdrant_client import QdrantClient

    from packages.knowledge.vector_store import VectorStore, _local_client

    storage = tmp_path / "real"
    storage.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(storage, target_is_directory=True)
    profile = tmp_path / "profile"
    profile.write_text("KB_EMBEDDING_PROVIDER=local-e5\nKB_RETRIEVAL_MODE=hybrid\n")
    client = None
    try:
        with live_eval.local_knowledge_environment(profile, alias):
            store = VectorStore()
            await store.initialise()
            client = store._client
        reopened = QdrantClient(path=str(storage.resolve() / "qdrant"))
        try:
            assert reopened.get_collections().collections
        finally:
            reopened.close()
    finally:
        if client is not None:
            client.close()
        _local_client.cache_clear()


@pytest.mark.asyncio
async def test_local_profile_restores_environment_when_real_client_cleanup_raises(
    tmp_path, monkeypatch
):
    from packages.knowledge.vector_store import VectorStore, _local_client

    monkeypatch.setenv("KB_DB_PATH", "existing.db")
    monkeypatch.setenv("KB_QDRANT_LOCAL_PATH", "existing-qdrant")
    monkeypatch.delenv("TOKENIZERS_PARALLELISM", raising=False)
    profile = tmp_path / "profile"
    profile.write_text("KB_EMBEDDING_PROVIDER=local-e5\nKB_RETRIEVAL_MODE=hybrid\n")
    try:
        with pytest.raises(RuntimeError, match="cleanup control"):
            with live_eval.local_knowledge_environment(profile, tmp_path / "isolated"):
                store = VectorStore()
                await store.initialise()
                close = store._client.close

                def close_then_raise():
                    close()
                    raise RuntimeError("cleanup control")

                monkeypatch.setattr(store._client, "close", close_then_raise)
        assert os.environ["KB_DB_PATH"] == "existing.db"
        assert os.environ["KB_QDRANT_LOCAL_PATH"] == "existing-qdrant"
        assert "TOKENIZERS_PARALLELISM" not in os.environ
    finally:
        _local_client.cache_clear()


def test_failure_event_is_redacted_before_preview_truncation():
    messages = failure_messages(
        [
            RunEvent(
                id=1, run_id="test", type="run_failed", message="Run failed: secret=private-value"
            )
        ]
    )
    assert "private-value" not in str(messages)
    assert "redacted" in messages[0]


def test_json_diagnostics_remain_parseable_after_redacting_string_values(tmp_path):
    path = tmp_path / "diagnostics.json"
    live_eval.write_redacted_json(
        path,
        {
            "topic": "Diagnostic secret=synthetic-placeholder",
            "status": "failed",
            "nested": [{"url": "https://example.com/?token=synthetic-query-value"}],
        },
    )
    result = json.loads(path.read_text())
    assert result["status"] == "failed"
    assert len(result["nested"]) == 1
    assert "synthetic-placeholder" not in path.read_text()
    assert "synthetic-query-value" not in path.read_text()


@pytest.mark.asyncio
async def test_live_cli_stdout_and_saved_summary_share_recursive_redaction(
    tmp_path, monkeypatch, capsys
):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({"id": "fallback-case"}) + "\n")
    payload = {
        "status": "completed_with_blockers",
        "llm_transport_attempts": 1,
        "semantic_quality": None,
        "module_executions": [
            {
                "module_status": "fallback",
                "fallback": {
                    "used": True,
                    "reason": "provider timeout",
                    "error": "secret=synthetic-cli-value",
                },
                "nested": [{"url": "https://example.com/?token=synthetic-cli-query"}],
            }
        ],
    }

    async def fake_run_case(case, output, timeout, **kwargs):
        live_eval.write_redacted_json(output / "summary.json", payload)
        return payload

    monkeypatch.setattr(live_eval, "run_case", fake_run_case)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_live_products",
            "--cases",
            str(cases),
            "--output",
            str(tmp_path),
            "--live",
            "--local-profile",
            str(tmp_path / "unused-local-profile"),
        ],
    )
    await live_eval.main()
    stdout = capsys.readouterr().out
    assert "synthetic-cli-value" not in stdout
    assert "synthetic-cli-query" not in stdout
    printed = json.loads(stdout)
    assert printed == json.loads((tmp_path / "summary.json").read_text())
    assert printed["llm_transport_attempts"] == 1
    assert printed["semantic_quality"] is None
    module = printed["module_executions"][0]
    assert module["module_status"] == "fallback"
    assert module["fallback"]["used"] is True
    assert module["fallback"]["reason"] == "provider timeout"


@pytest.mark.asyncio
async def test_list_only_cli_uses_same_redaction_for_case_identifiers(
    tmp_path, monkeypatch, capsys
):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({"id": "case secret=synthetic-cli-id"}) + "\n")
    monkeypatch.setattr(sys, "argv", ["eval_live_products", "--cases", str(cases)])
    await live_eval.main()
    stdout = capsys.readouterr().out
    assert "synthetic-cli-id" not in stdout
    assert json.loads(stdout)["mode"] == "list_only"


@pytest.mark.asyncio
@pytest.mark.parametrize("project_id", ["completed-project", None])
async def test_run_summary_records_completed_run_scope(tmp_path, monkeypatch, project_id):
    created = detail("running")
    created.workspace_id = "public-product-acceptance"
    created.project_id = "requested-project"
    completed = detail()
    completed.workspace_id = "completed-workspace"
    completed.project_id = project_id

    class FakeCheckpoint:
        @staticmethod
        def in_memory():
            return FakeCheckpoint()

        async def aclose(self):
            pass

    class FakeService:
        def __init__(self, *args, **kwargs):
            self._runs = {created.id: SimpleNamespace(detail=created)}

        async def create_run(self, request):
            return created

        async def run_pipeline(self, run_id):
            self._runs[run_id].detail = completed

        def get_trace(self, run_id):
            return []

    monkeypatch.setattr(live_eval, "RunService", FakeService)
    monkeypatch.setattr(live_eval, "GraphCheckpointer", FakeCheckpoint)
    monkeypatch.setattr(
        live_eval,
        "get_settings",
        lambda: Settings(
            ark_api_key="offline-test", ark_model="offline-test", pplx_api_key="offline-test"
        ),
    )
    summary = await live_eval._run_case(
        {"id": "scope", "topic": "public", "competitors": ["A"], "dimensions": ["pricing"]},
        tmp_path,
        30,
    )
    assert summary["run_scope"] == {
        "workspace_id": completed.workspace_id,
        "project_id": project_id,
    }
    assert json.loads((tmp_path / "scope-summary.json").read_text())["run_scope"] == summary[
        "run_scope"
    ]


@pytest.mark.asyncio
async def test_local_profile_document_counts_use_actual_run_scope(tmp_path, monkeypatch):
    from packages.knowledge import embeddings, reranker
    from packages.knowledge.models import DocumentCreate
    from packages.knowledge.repository import KnowledgeRepository

    class OfflineEmbedding:
        model_version = "offline-semantic-test"
        inference_calls = 0

        def embed_query(self, query):
            self.inference_calls += 1
            return [1.0, 0.0]

        def status(self):
            return {
                "requested_provider": "local-sentence-transformer",
                "effective_provider": "local-sentence-transformer",
                "model_version": self.model_version,
                "dimensions": 2,
                "inference_calls": self.inference_calls,
            }

    embedding = OfflineEmbedding()
    monkeypatch.setattr(embeddings, "get_embedding_provider_from_env", lambda: embedding)
    monkeypatch.setattr(reranker, "get_reranker_provider_from_env", lambda: None)
    actual_scope = {"workspace_id": "completed-workspace", "project_id": "completed-project"}

    async def offline_run_case(case, output, timeout):
        rows = [
            (actual_scope, "ready", embedding.model_version, "actual-index"),
            (actual_scope, "failed", None, None),
            ({**actual_scope, "project_id": None}, "ready", "library-model", "library-index"),
            (
                {**actual_scope, "project_id": "other-project"},
                "ready", "other-model", "other-index",
            ),
            (
                {**actual_scope, "workspace_id": "other-workspace"},
                "ready", "other-model", "other-index",
            ),
            (
                {"workspace_id": "public-product-acceptance", "project_id": None},
                "ready", "public-model", "public-index",
            ),
            (
                {"workspace_id": "public-product-acceptance", "project_id": "requested-project"},
                "ready", "request-model", "request-index",
            ),
        ]
        async with KnowledgeRepository() as repo:
            for index, (scope, status, model, version) in enumerate(rows):
                doc = await repo.upsert_document(
                    DocumentCreate(
                        title=f"document-{index}",
                        text=f"scoped material {index}",
                        source_type="official",
                        **scope,
                    ),
                    content_hash=f"scoped-content-{index}",
                )
                await repo.set_indexing_state(
                    doc.id, status, embedding_model=model, index_version=version
                )
        return {"run_scope": actual_scope}

    monkeypatch.setattr(live_eval, "_run_case", offline_run_case)
    profile = tmp_path / "profile"
    profile.write_text("KB_EMBEDDING_PROVIDER=local-e5\nKB_RETRIEVAL_MODE=hybrid\n")
    summary = await live_eval.run_case(
        {"id": "scope", "project_id": "requested-project"},
        tmp_path,
        30,
        local_profile=profile,
    )
    execution = summary["knowledge_execution"]
    assert execution["document_count"] == 2
    assert execution["scope"] == {**actual_scope, "include_workspace_library": False}
    assert execution["indexing_status_counts"] == {"ready": 1, "failed": 1}
    assert execution["indexed_model_versions"] == [embedding.model_version]
    assert execution["index_versions"] == ["actual-index"]
    saved = json.loads((tmp_path / "scope-summary.json").read_text())
    assert saved["knowledge_execution"] == execution


@pytest.mark.asyncio
async def test_cancelling_acceptance_stops_pipeline_before_closing_checkpoint(
    monkeypatch, tmp_path
):
    started, cancelled, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    children = []

    class FakeCheckpoint:
        @staticmethod
        def in_memory():
            return FakeCheckpoint()

        async def aclose(self):
            assert cancelled.is_set()
            closed.set()

    class FakeService:
        def __init__(self, *args, **kwargs):
            self._runs = {"public-test": SimpleNamespace(detail=detail("running"))}

        async def create_run(self, request):
            return self._runs["public-test"].detail

        async def run_pipeline(self, run_id):
            children.append(asyncio.current_task())
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    monkeypatch.setattr(live_eval, "RunService", FakeService)
    monkeypatch.setattr(live_eval, "GraphCheckpointer", FakeCheckpoint)
    monkeypatch.setattr(
        live_eval,
        "get_settings",
        lambda: Settings(
            ark_api_key="offline-test", ark_model="offline-test", pplx_api_key="offline-test"
        ),
    )
    task = asyncio.create_task(
        live_eval.run_case(
            {"id": "cancel", "topic": "public", "competitors": ["A"], "dimensions": ["pricing"]},
            tmp_path,
            30,
        )
    )
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assert closed.is_set()
        assert all(child.done() for child in children)
    finally:
        for child in children:
            child.cancel()
        await asyncio.gather(*children, return_exceptions=True)
