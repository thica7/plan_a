"""Opt-in public-product acceptance through isolated in-memory production services."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from packages.business_intel.report_sections import build_report_section_index
from packages.config import Settings, get_settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import KBCache, RunJournal
from packages.observability import TraceStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.skills.registry import SkillRegistry
from scripts.export_agent_eval import _redact

ROOT = Path(__file__).resolve().parents[2]


def acceptance_request(case: dict) -> RunCreateRequest:
    return RunCreateRequest(
        **{key: value for key, value in case.items() if key not in {"id", "research_depth"}},
        execution_mode="real",
        research_depth=case.get("research_depth", "quick"),
        collaboration_mode="ai",
        output_language="zh-CN",
        workspace_id="public-product-acceptance",
        auto_redo_warn_enabled=False,
        idempotency_key=f"public-eval-{uuid4().hex}",
    )


@contextmanager
def local_knowledge_environment(profile: Path, storage: Path):
    """Apply a non-secret local profile without shell execution or shared KB writes."""
    storage = storage.expanduser().resolve()
    values = {}
    for line in profile.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not (
            key.startswith("KB_")
            or key
            in {
                "HF_HUB_OFFLINE",
                "TRANSFORMERS_OFFLINE",
                "HF_HUB_DISABLE_TELEMETRY",
                "TOKENIZERS_PARALLELISM",
            }
        ):
            raise ValueError("Unsupported local profile key")
        values[key] = value.strip().strip("\"'")
    if (
        values.get("KB_EMBEDDING_PROVIDER") != "local-e5"
        or values.get("KB_RETRIEVAL_MODE") != "hybrid"
        or values.get("KB_RERANKER_PROVIDER", "none") not in {"none", "local-cross-encoder"}
    ):
        raise ValueError("An explicit local semantic hybrid profile is required")
    storage.mkdir(parents=True, exist_ok=True)
    values.update(
        KB_DB_PATH=str(storage / "knowledge.db"),
        KB_QDRANT_LOCAL_PATH=str(storage / "qdrant"),
        KB_LOCAL_MODEL_STRICT="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false",
    )
    previous = {key: os.environ.get(key) for key in values}
    from packages.tools.rag_retrieve import _get_embedding_provider

    _get_embedding_provider.cache_clear()
    try:
        os.environ.update(values)
        yield {
            "requested_provider": values["KB_EMBEDDING_PROVIDER"],
            "retrieval_mode": values["KB_RETRIEVAL_MODE"],
            "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
            "storage": "temporary SQLite + Qdrant local",
        }
    finally:
        try:
            _get_embedding_provider.cache_clear()
            if (storage / "qdrant").exists():
                from packages.knowledge.vector_store import _local_client

                _local_client(str(storage / "qdrant")).close()
                _local_client.cache_clear()
        finally:
            for key, old in previous.items():
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old


def summarize_acceptance(detail: RunDetail, *, events=(), settings: Settings | None = None) -> dict:
    citations = set(re.findall(r"\[source:([^\]#]+)(?:#chunk:\d+)?\]", detail.report_md))
    source_ids = {source.id for source in detail.raw_sources}
    sections = build_report_section_index(detail.report_md).sections_before_support()
    core = "\n".join(
        section.body
        for section in sections
        if not re.search(r"来源|证据|source|reference|\bevidence\b", section.heading, re.I)
    )
    products = detail.plan.competitors
    analysis_signal = (
        bool(core.strip())
        and bool(products)
        and all(name.casefold() in core.casefold() for name in products)
        and bool(re.search(r"\[source:", core))
    )
    citations_valid = bool(citations) and citations <= source_ids
    usage_fields = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    )
    usage_by_kind = {
        kind: {
            field: (
                sum(values)
                if (
                    values := [
                        span.metadata[field]
                        for span in detail.trace_spans
                        if span.kind == kind
                        and span.metadata.get("token_usage_source") == "provider"
                        and isinstance(span.metadata.get(field), int)
                    ]
                )
                else None
            )
            for field in usage_fields
        }
        for kind in ("llm", "search")
    }
    model_spans = [span for span in detail.trace_spans if span.kind in {"llm", "search"}]
    transported = [
        span for span in model_spans if (span.metadata.get("llm_transport_attempts") or 0) > 0
    ]
    unknown_usage = [
        span
        for span in transported
        if span.metadata.get("token_usage_source") != "provider"
        or span.metadata.get("total_tokens") is None
    ]
    unknown_transport = sum("llm_transport_attempts" not in span.metadata for span in model_spans)
    phases = {}
    for span in model_spans:
        phase = str(span.metadata.get("llm_phase") or "unknown")
        row = phases.setdefault(
            phase,
            {
                "span_count": 0,
                "transport_attempts": 0,
                "unknown_transport_spans": 0,
                "execution_status_counts": {},
            },
        )
        row["span_count"] += 1
        row["transport_attempts"] += span.metadata.get("llm_transport_attempts", 0) or 0
        row["unknown_transport_spans"] += "llm_transport_attempts" not in span.metadata
        status = str(span.metadata.get("llm_execution_status") or "unknown")
        row["execution_status_counts"][status] = row["execution_status_counts"].get(status, 0) + 1
    modules = [
        {
            "agent": event.agent,
            "subagent": event.subagent,
            "module_status": event.payload["module_status"],
            "fallback": event.payload.get("fallback"),
            "reason": event.payload.get("execution_reason") or event.payload.get("fallback_reason"),
            "has_structured_output": any(
                isinstance(event.payload.get(key), dict) and bool(event.payload[key])
                for key in ("analysis", "matrix", "reflection")
            ),
        }
        for event in events
        if event.type == "node_completed" and event.payload.get("module_status")
    ]
    costs = {
        "provider_bill_usd": None,
        "usage_complete": not unknown_usage and not unknown_transport,
        "trace_estimate_range_usd": None,
        "rates_usd_per_million": None,
        "scope": (
            "configured trace token estimates; cache extremes; not a billing bound; "
            "search tool fees unknown"
        ),
    }
    if settings is not None:
        prompt = sum(span.input_tokens_estimate for span in model_spans)
        completion = sum(span.output_tokens_estimate for span in model_spans)
        rates = [settings.llm_cache_usd_per_million, settings.llm_input_usd_per_million]
        costs.update(
            trace_estimate_range_usd=[
                (prompt * rate + completion * settings.llm_output_usd_per_million) / 1_000_000
                for rate in (min(rates), max(rates))
            ],
            rates_usd_per_million={
                "input": settings.llm_input_usd_per_million,
                "cache": settings.llm_cache_usd_per_million,
                "output": settings.llm_output_usd_per_million,
            },
        )
    known_totals = [
        span.metadata["total_tokens"]
        for span in model_spans
        if span.metadata.get("token_usage_source") == "provider"
        and isinstance(span.metadata.get("total_tokens"), int)
    ]
    return {
        "status": detail.status,
        "current_node": detail.current_node,
        "pipeline_terminal": detail.status in {"completed", "completed_with_blockers"},
        "mechanical_pass": detail.status == "completed" and analysis_signal and citations_valid,
        "partial_report_generated": detail.status == "completed_with_blockers"
        and analysis_signal
        and citations_valid
        and bool(citations),
        "semantic_quality": None,
        "has_product_analysis_signal": analysis_signal,
        "citations_valid": citations_valid,
        "unknown_citation_count": len(citations - source_ids),
        "report_chars": len(detail.report_md),
        "core_chars": len(core),
        "competitors": products,
        "source_count": len(detail.raw_sources),
        "source_types": sorted({source.source_type for source in detail.raw_sources}),
        "assessments": detail.comparison_matrix.model_dump(mode="json").get("assessments")
        if detail.comparison_matrix
        else {},
        "native_llm_spans": sum(span.kind == "llm" for span in detail.trace_spans),
        "llm_transport_attempts": sum(
            span.metadata.get("llm_transport_attempts", 0) or 0 for span in model_spans
        ),
        "unknown_transport_spans": unknown_transport,
        "llm_phases": phases,
        "module_executions": modules,
        "module_status_counts": dict(Counter(row["module_status"] for row in modules)),
        "search_spans": sum(span.kind == "search" for span in detail.trace_spans),
        "successful_search_spans": sum(
            span.kind == "search" and span.status == "ok" for span in detail.trace_spans
        ),
        "provider_usage_by_kind": usage_by_kind,
        "provider_total_tokens_last_attempts": sum(known_totals) if known_totals else None,
        "provider_usage_unknown_transport_spans": len(unknown_usage),
        "configured_cost_estimate": costs,
        "provider_usage_scope": "last_attempt_per_span; search usage may be unavailable",
        "budget_checkpoint": detail.llm_budget_checkpoint,
        "qa_issue_count": len(detail.qa_findings),
    }


def failure_messages(events) -> list[str]:
    return [_redact(event.message)[:600] for event in events if event.type == "run_failed"]


def redacted_json(payload: object, *, indent: int | None = None) -> str:
    def redact_values(value):
        if isinstance(value, str):
            return _redact(value)
        if isinstance(value, dict):
            return {key: redact_values(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact_values(item) for item in value]
        return value

    return json.dumps(redact_values(payload), ensure_ascii=False, indent=indent)


def write_redacted_json(path: Path, payload: object) -> None:
    path.write_text(redacted_json(payload, indent=2) + "\n")


async def run_case(
    case: dict, output: Path, timeout_seconds: float, *, local_profile: Path | None = None
) -> dict:
    if local_profile is None:
        return await _run_case(case, output, timeout_seconds)
    # Only the explicitly selected profile affects knowledge configuration. Each case
    # starts with an empty canonical/vector store; cold warm-start misses are reported.
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="acceptance-kb-") as directory:
        with local_knowledge_environment(local_profile, Path(directory)) as config:
            import torch

            from packages.knowledge.embeddings import get_embedding_provider_from_env
            from packages.knowledge.models import KnowledgeScope
            from packages.knowledge.product_benchmark import provider_readiness
            from packages.knowledge.repository import KnowledgeRepository
            from packages.knowledge.reranker import get_reranker_provider_from_env

            torch.set_num_threads(2)
            embedding = get_embedding_provider_from_env()
            reranker = get_reranker_provider_from_env()
            embedding_before = embedding.status().get("inference_calls", 0)
            embedding.embed_query("本地语义检索初始化")
            reranker_before = reranker.status().get("inference_calls", 0) if reranker else 0
            if reranker:
                reranker.rerank("初始化", ["本地精排模型初始化"])
            if not provider_readiness(embedding.status())["semantic_ready"]:
                raise ValueError("Local semantic model did not initialize")
            warmup = {
                "embedding": embedding.status()["inference_calls"] - embedding_before,
                "reranker": reranker.status()["inference_calls"] - reranker_before
                if reranker
                else 0,
            }
            summary = await _run_case(case, output, timeout_seconds)
            scope = KnowledgeScope(**summary["run_scope"], include_workspace_library=False)
            async with KnowledgeRepository() as repo:
                docs = await repo.list_documents(scope=scope, limit=1000)
            summary["knowledge_execution"] = {
                **config,
                "initial_corpus": "empty; no canned product answers seeded",
                "embedding": embedding.status(),
                "reranker": reranker.status() if reranker else None,
                "warmup_inference_calls": warmup,
                "pipeline_inference_calls": {
                    "embedding": embedding.status()["inference_calls"]
                    - embedding_before
                    - warmup["embedding"],
                    "reranker": reranker.status()["inference_calls"]
                    - reranker_before
                    - warmup["reranker"]
                    if reranker
                    else 0,
                },
                "document_count": len(docs),
                "scope": scope.model_dump(mode="json"),
                "indexing_status_counts": dict(Counter(doc.indexing_status for doc in docs)),
                "indexed_model_versions": sorted(
                    {doc.embedding_model for doc in docs if doc.embedding_model}
                ),
                "index_versions": sorted({doc.index_version for doc in docs if doc.index_version}),
                "query_model_version": embedding.model_version,
            }
            write_redacted_json(output / f"{case['id']}-summary.json", summary)
            return summary


async def _run_case(case: dict, output: Path, timeout_seconds: float) -> dict:
    settings = replace(
        get_settings(),
        demo_mode=False,
        run_orchestration_backend="langgraph",
        hitl_enabled=False,
        auto_redo_warn_enabled=False,
        max_iterations=1,
        backup_llm_api_key=None,
        backup_llm_model=None,
        llm_max_retries=0,
        llm_timeout_seconds=45,
        llm_max_output_tokens=4096,
        run_llm_max_calls=60,
        run_llm_max_tokens=200000,
        writer_timeout_seconds=240,
        artifact_storage_root=str(output / "artifacts"),
        langfuse_public_key=None,
        langfuse_secret_key=None,
        otel_export_endpoint=None,
    )
    if not settings.has_primary_llm_credentials or not settings.has_web_search_credentials:
        raise ValueError("Primary model and search credentials are required; none are exported.")
    checkpoint = GraphCheckpointer.in_memory()
    started = time.perf_counter()
    timed_out = False
    error_type = None
    task = None
    try:
        service = RunService(
            SkillRegistry.from_default_path(),
            settings,
            journal=RunJournal.in_memory(),
            kb_cache=KBCache.in_memory(),
            trace_store=TraceStore.in_memory(),
            graph_checkpointer=checkpoint,
            enterprise_store=EnterpriseMemoryStore(),
        )
        detail = await service.create_run(acceptance_request(case))
        task = asyncio.create_task(service.run_pipeline(detail.id))
        async with asyncio.timeout(timeout_seconds):
            while not task.done():
                await asyncio.wait({task}, timeout=15)
                current = service._runs[detail.id].detail
                print(
                    redacted_json(
                        {
                            "case_id": case["id"],
                            "node": current.current_node,
                            "status": current.status,
                            "spans": len(current.trace_spans),
                        },
                    ),
                    flush=True,
                )
            await task
    except TimeoutError:
        if task is None:
            raise
        timed_out = True
    except Exception as exc:
        if task is None:
            raise
        error_type = type(exc).__name__
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await checkpoint.aclose()
    completed = service._runs[detail.id].detail
    events = service.get_trace(detail.id) or []
    rag_spans = [span for span in completed.trace_spans if span.name == "rag_kb_warm_start"]
    summary = {
        "case_id": case["id"],
        "run_scope": {
            "workspace_id": completed.workspace_id,
            "project_id": completed.project_id,
        },
        "timed_out": timed_out,
        "error_type": error_type,
        "duration_seconds": round(time.perf_counter() - started, 2),
        "failure_messages": failure_messages(events),
        **summarize_acceptance(completed, events=events, settings=settings),
        "execution_configuration": {
            "llm_provider": settings.llm_provider_name,
            "model": settings.ark_model,
            "search_provider": settings.web_search_provider,
            "search_model": settings.deepseek_search_model
            if settings.web_search_provider == "deepseek"
            else None,
            "max_tokens": settings.run_llm_max_tokens,
            "max_calls": settings.run_llm_max_calls,
            "max_retries": settings.llm_max_retries,
        },
        "rag_warm_start": {
            "attempts": len(rag_spans),
            "retrieved_hits": sum(span.metadata.get("hit_count", 0) or 0 for span in rag_spans),
            "accepted_sources": sum(
                span.metadata.get("source_count", 0) or 0 for span in rag_spans
            ),
            "degraded_attempts": sum(bool(span.metadata.get("degraded")) for span in rag_spans),
        },
    }
    if timed_out or error_type:
        summary["mechanical_pass"] = False
    write_redacted_json(output / f"{case['id']}-run.json", completed.model_dump(mode="json"))
    write_redacted_json(
        output / f"{case['id']}-events.json", [event.model_dump(mode="json") for event in events]
    )
    (output / f"{case['id']}-report.md").write_text(_redact(completed.report_md) + "\n")
    write_redacted_json(output / f"{case['id']}-summary.json", summary)
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", type=Path, default=ROOT / "eval/live-product-acceptance-v1.jsonl"
    )
    parser.add_argument("--case", help="Run exactly one fixed public task")
    parser.add_argument("--output", type=Path, default=Path("/tmp/plan_a_live_acceptance/runs"))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--local-profile",
        type=Path,
        help="Explicit non-secret local semantic profile; required for --live",
    )
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()]
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
    if not 1 <= len(cases) <= 3:
        parser.error("Select 1-3 fixed public cases.")
    if not args.live:
        print(redacted_json({"mode": "list_only", "cases": [case["id"] for case in cases]}))
        return
    if args.local_profile is None:
        parser.error(
            "--live requires --local-profile for isolated SQLite/Qdrant local semantic retrieval"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    for case in cases:
        print(
            redacted_json(
                await run_case(case, args.output, args.timeout, local_profile=args.local_profile),
            ),
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
