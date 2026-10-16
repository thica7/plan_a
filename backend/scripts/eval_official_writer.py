"""Opt-in real official captures through production Collector and downstream agents."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from packages.agents.context import SubagentContext
from packages.business_intel.official_registry import registered_document, registry_snapshot
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import KBCache, RunJournal
from packages.observability import TraceStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.research.evidence.snapshot import current_snapshot
from packages.research.models import SourceCandidate
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry
from scripts.eval_evidence_binding import ROOT, SCORED, digest, isolated_environment, live_settings, load_cases
from scripts.eval_live_products import redacted_json, summarize_acceptance, write_redacted_json
from scripts.export_agent_eval import _redact


@contextmanager
def diagnostic_environment(output):
    previous = os.environ.get("KB_RETRIEVAL_MODE")
    os.environ["KB_RETRIEVAL_MODE"] = "sparse"
    try:
        with isolated_environment(output):
            yield
    finally:
        if previous is None:
            os.environ.pop("KB_RETRIEVAL_MODE", None)
        else:
            os.environ["KB_RETRIEVAL_MODE"] = previous


def prepare_inputs(path: Path, *, input_hash=None, registry_hash=None):
    # Load/validate a single frozen byte snapshot before reading runtime settings.
    locked = input_hash or digest(path.read_bytes())
    cases = load_cases(path, expected_sha256=locked, mode="formal")
    if digest(path.read_bytes()) != locked:
        raise ValueError("input changed during validation")
    current_registry = registry_snapshot()[1]
    if registry_hash and registry_hash != current_registry:
        raise ValueError("registry changed from frozen SHA256")
    payloads = [{"id": case["id"], "product": case["product"], "question": case["question"],
                 "sources": [{key: source[key] for key in ("id", "title", "url")}
                             for source in case["sources"]]} for case in cases if case["id"] in SCORED]
    for case in payloads:
        for source in case["sources"]:
            if registered_document(case["product"], source["url"]) is None:
                raise ValueError("source is not in reviewed official registry")
    return payloads, {"input_sha256": locked, "registry_sha256": current_registry,
        "reviewed_cases": len(cases), "case_ids": [case["id"] for case in payloads],
        "not_covered": [case["id"] for case in cases if case["id"] not in SCORED],
        "source_urls": [s["url"] for case in payloads for s in case["sources"]],
        "semantic_quality": "pending_human", "input_mode": "live_official_documents",
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "production_code_sha256": digest(b"".join(str(p.relative_to(ROOT)).encode() + p.read_bytes()
            for p in sorted((ROOT / "backend/packages").rglob("*.py"))))}


async def collect_sources(service, record, payloads):
    """Use the real Collector adapter, admission and canonical persistence; no search."""
    products = record.detail.plan.competitors
    for product in products:
        candidates = [SourceCandidate(title=s["title"], url=s["url"], competitor=product,
            dimension="feature", origin="trusted_registry", confidence=.8)
            for case in payloads if case["product"] == product for s in case["sources"]]
        context = SubagentContext(run_id=record.detail.id, agent="collector", subagent=f"feature::{product}")
        sources = await service._collect_competitor_with_research_pipeline(
            record, record.detail, "feature", product, context, batch_sources=[],
            target_source_count=len(candidates), include_official=False, seed_candidates=candidates,
            enable_search=False, enable_repair=False)
        record.detail.raw_sources.extend(sources)
        service._finish_delivery_phase(record, "collector", f"feature::{product}")


async def execute_stages(service, record, payloads):
    """Keep missing scopes visible to production partial-report and evidence gates."""
    try:
        await collect_sources(service, record, payloads)
        if not record.detail.raw_sources:
            raise ValueError("no_accepted_sources: downstream model stages not attempted")
        await service._prepare_evidence_snapshot(record, phase="collect")
        await service._prepare_evidence_snapshot(record, phase="analysis")
        products = record.detail.plan.competitors
        await service._real_analyst_dispatch_step(record, ["feature"], products)
        for product in products:
            await service._real_analyst_branch_step(record, "feature", product)
        await service._real_analyst_join_step(record, ["feature"], products)
        await service._real_comparator_step(record)
        await service._real_reflector_step(record)
        await service._real_writer_step(record)
    finally:
        await service._real_qa_step(record)


def writer_producer_verified(service, record, snapshot):
    return bool(snapshot and any(d.kind == "writer" for d in record.detail.evidence_artifact_dependencies)
                and service._final_qa_producer_verified(record, snapshot))


async def run_live(payloads, manifest, output, *, timeout=600, capture_only=False):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_redacted_json(output / "manifest.json", manifest)
    write_redacted_json(output / "inputs.json", payloads)
    checkpoint = GraphCheckpointer.in_memory()
    service, detail, error_type, error_reason = None, None, None, None
    captures = []
    with diagnostic_environment(output):
        settings = live_settings(output)
        try:
            async with asyncio.timeout(timeout):
                service = RunService(SkillRegistry.from_default_path(), settings,
                    journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(),
                    trace_store=TraceStore.in_memory(), graph_checkpointer=checkpoint,
                    enterprise_store=EnterpriseMemoryStore())
                products = list(dict.fromkeys(case["product"] for case in payloads))
                # Questions select scope; they are never input to evidence fields.
                questions = "\n".join(case["question"] for case in payloads)
                detail = await service.create_run(RunCreateRequest(workspace_id="official-source-acceptance",
                    project_id=uuid4().hex, topic=" / ".join(products) + " 的角色、编辑及访问权限研究",
                    dimensions=["feature"], competitors=products, execution_mode="real",
                    target_product={"name": products[0], "category": "协作软件"},
                    collaboration_mode="ai", output_language="zh-CN", auto_redo_warn_enabled=False,
                    decision_brief={"decision_question": questions}))
                record = service._runs[detail.id]
                if capture_only:
                    # Deliberately omit the optional model selector; capture/admission
                    # and deterministic extraction remain production implementations.
                    from packages.research.capture import capture_candidate
                    from packages.research.capture.official import verify_registered_capture
                    captures = []
                    for case in payloads:
                        context = SubagentContext(run_id=detail.id, agent="collector", subagent=f"feature::{case['product']}")
                        for source in case["sources"]:
                            candidate = SourceCandidate(title=source["title"], url=source["url"],
                                competitor=case["product"], dimension="feature", origin="trusted_registry")
                            async def fetch(url):
                                return await service._trace_fetch(record, "collector", context.subagent,
                                                                  url, context, allow_advanced=True)
                            page = await capture_candidate(candidate, fetch)
                            captures.append({"product": case["product"], "page": page.model_dump(mode="json"),
                                             "verification": verify_registered_capture(case["product"], page)})
                    write_redacted_json(output / "captures.json", captures)
                else:
                    async with asyncio.timeout(timeout):
                        await execute_stages(service, record, payloads)
        except Exception as exc:
            error_type, error_reason = type(exc).__name__, _redact(str(exc))
        finally:
            if capture_only:
                write_redacted_json(output / "captures.json", captures)
            await checkpoint.aclose()
        events = service.get_trace(detail.id) if service and detail else []
        summary = summarize_acceptance(detail, events=events, settings=settings) if detail else {}
        summary.update(manifest, status="blocked" if error_type else "execution_complete",
            error_type=error_type, error_reason=error_reason, capture_only=capture_only,
            semantic_quality="pending_human", deliverable=False,
            publication_status="not_attempted", configured_provider=settings.llm_provider_name,
            configured_model=settings.ark_model, provider_bill_usd=None,
            collector_scope="production research adapter; fixed reviewed URLs; discovery/search not tested")
        summary["semantic_indexing"] = "disabled; diagnostic-only sparse canonical storage"
        if detail:
            snapshot = current_snapshot(detail)
            summary["downstream_observations"] = {
                "snapshot_facts": len(snapshot.facts) if snapshot else 0,
                "raw_source_count": len(detail.raw_sources),
                "qa_blocker_count": sum(i.severity == "blocker" for i in detail.qa_findings),
                "reviewed_claim_count": sum(c.status == "supported" for a in detail.report_dimension_audits for c in a.claims),
                "writer_producer_verified": writer_producer_verified(service, record, snapshot),
                "llm_transport_by_agent": {a: sum(s.metadata.get("llm_transport_attempts", 0) or 0
                    for s in detail.trace_spans if s.kind == "llm" and s.agent == a)
                    for a in "collector analyst comparator reflector writer qa".split()},
                "actual_models": sorted({s.model for s in detail.trace_spans if s.model})}
            write_redacted_json(output / "run.json", detail.model_dump(mode="json"))
            write_redacted_json(output / "snapshot.json", [s.model_dump(mode="json") for s in detail.evidence_snapshots])
            write_redacted_json(output / "trace.json", [s.model_dump(mode="json") for s in detail.trace_spans])
        write_redacted_json(output / "events.json", [e.model_dump(mode="json") for e in events])
        (output / "report.md").write_text(_redact(detail.report_md if detail else "") + "\n")
        write_redacted_json(output / "summary.json", summary)
        return summary


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "eval/product-condition-review-v1.jsonl")
    parser.add_argument("--expected-input-sha256")
    parser.add_argument("--expected-registry-sha256")
    parser.add_argument("--output", type=Path, default=Path("/tmp/official-writer-" + uuid4().hex))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--capture-only", action="store_true")
    args = parser.parse_args(argv)
    payloads, manifest = prepare_inputs(args.cases, input_hash=args.expected_input_sha256,
                                       registry_hash=args.expected_registry_sha256)
    if not args.live:
        print(redacted_json({**manifest, "mode": "list_only", "fetch_attempts": 0, "llm_transport_attempts": 0}))
        return
    if not args.expected_input_sha256 or not args.expected_registry_sha256:
        raise ValueError("live requires frozen input and registry SHA256")
    print(redacted_json(await run_live(payloads, manifest, args.output, timeout=args.timeout,
                                       capture_only=args.capture_only)))


if __name__ == "__main__":
    asyncio.run(main())
