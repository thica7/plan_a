"""Opt-in downstream diagnostic on fixed official excerpts; never a Collector acceptance."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from packages.business_intel.entity_resolver import resolve_competitor_identity
from packages.config import get_settings
from packages.enterprise import EnterpriseMemoryStore
from packages.identity import compute_raw_source_id
from packages.memory import KBCache, RunJournal
from packages.observability import TraceStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.research.evidence.admission import admit_evidence_items
from packages.research.evidence.snapshot import current_snapshot
from packages.research.extraction.semantic import semantic_page_allowed
from packages.research.models import (
    CapturedPage,
    EvidenceQuote,
    ExtractionResult,
    ResearchBrief,
    SourceCandidate,
)
from packages.schema.api_dto import RunCreateRequest
from packages.schema.models import RawSource
from packages.skills.registry import SkillRegistry
from scripts.eval_live_products import redacted_json, summarize_acceptance, write_redacted_json
from scripts.export_agent_eval import _redact

ROOT = Path(__file__).resolve().parents[2]
SCORED = {f"condition-v1-{n:03}" for n in (1, 2, 4, 5)}
INPUT_MODE = "fixed_official_excerpt"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def allowed_payload(case: dict) -> dict:
    return {"id": case["id"], "product": case["product"], "question": case["question"],
            "sources": [{key: source[key] for key in
                         ("id", "title", "url", "excerpt", "verified_at", "source_role")}
                        for source in case["sources"]]}


def load_cases(path: Path, *, expected_sha256=None, mode="candidate-diagnostic") -> list[dict]:
    data = path.read_bytes()
    if expected_sha256 and digest(data) != expected_sha256:
        raise ValueError("input/source drift: SHA256 differs from frozen input")
    cases = [json.loads(line) for line in data.decode().splitlines() if line.strip()]
    if len(cases) != 8 or len({row["id"] for row in cases}) != 8:
        raise ValueError("exactly eight distinct cases are required")
    if mode == "formal" and any(row.get("review_status") != "reviewed" or
            not row.get("reviewed_by") or not row.get("reviewed_at") for row in cases):
        raise ValueError("formal requires independent human review of all eight cases")
    seen = set()
    for case in cases:
        for source in allowed_payload(case)["sources"]:
            parsed = urlsplit(source["url"])
            if (source["id"] in seen or parsed.scheme != "https" or not parsed.hostname or
                    parsed.username or parsed.password or not source["excerpt"].strip() or
                    source["source_role"] != "source"):
                raise ValueError("invalid source identity or original excerpt")
            datetime.fromisoformat(source["verified_at"].replace("Z", "+00:00"))
            seen.add(source["id"])
    return cases


def map_excerpt(case: dict, source: dict) -> dict:
    """Map bytes only. Numeric quality/confidence are fixture metadata, not model judgments."""
    quote, product = source["excerpt"], case["product"]
    brief = ResearchBrief(run_id="fixed-excerpt-diagnostic", topic="official excerpt",
                          competitor=product, dimension="feature", product_category="software")
    candidate = SourceCandidate(title=source["title"], url=source["url"], origin="manual",
                                competitor=product, dimension="feature", confidence=.5)
    captured = datetime.now(UTC)  # Time this excerpt fixture is materialized, not a web fetch.
    capture = CapturedPage(candidate_id=candidate.id, requested_url=source["url"],
        final_url=source["url"], status="ok", title=source["title"], text=quote,
        content_hash=digest(quote.encode())[:16], quality_score=.5, captured_at=captured,
        fetch_method="curated_input", source_material_level="unknown",
        metadata={"input_mode": INPUT_MODE, "collector_verified": False})
    extraction = ExtractionResult(competitor=product, dimension="feature",
        source_candidate_id=candidate.id, captured_page_id=capture.id,
        fields={"fixed_excerpt": [quote]}, confidence=.5, extractor_name="fixed_excerpt_byte_map",
        quotes=[EvidenceQuote(field="fixed_excerpt", text=quote, source_url=source["url"],
                              start_offset=0, end_offset=len(quote))])
    items = admit_evidence_items([extraction], captured_pages=[capture],
                                 candidates=[candidate], brief=brief)
    row = {"kind": "feature", "competitor": product, "dimension": "feature",
           "evidence_terms": [quote], "evidence_quote": quote,
           "evidence_item_ids": [item.id for item in items], "source_url": source["url"]}
    raw = RawSource(id=compute_raw_source_id(source_type="manual_note", competitor=product,
        dimension="feature", url=source["url"], content_hash=capture.content_hash,
        title=source["title"], snippet=quote, run_id=brief.run_id), competitor=product,
        dimension="feature", source_type="manual_note", url=source["url"], title=source["title"],
        snippet=quote, content_hash=capture.content_hash, confidence=.5, extracted_at=captured,
        candidate_origin="manual", fetch_method="curated_input", metadata={
            "input_mode": INPUT_MODE, "dataset_source_id": source["id"],
            "source_verified_at": source["verified_at"],
            "input_excerpt_sha256": digest(quote.encode()), "source_material_level": "unknown",
            "collector_verified": False, "fixture_metadata": "status/quality/confidence only",
            "normalized_fields": [row] if items and all(
                item.status == "accepted" for item in items) else []})
    mapped = dict(brief=brief, candidate=candidate, capture=capture, extraction=extraction,
                  items=items, raw_source=raw, source=source)
    validate_mapping(mapped)
    return mapped


def validate_mapping(mapped: dict) -> None:
    brief, candidate, page, extraction, raw, source = (mapped[key] for key in
        ("brief", "candidate", "capture", "extraction", "raw_source", "source"))
    quote = extraction.quotes[0]
    expected_row = {"kind": "feature", "competitor": brief.competitor, "dimension": brief.dimension,
        "evidence_terms": [source["excerpt"]], "evidence_quote": source["excerpt"],
        "evidence_item_ids": [item.id for item in mapped["items"]], "source_url": source["url"]}
    expected_rows = [expected_row] if mapped["items"] and all(
        item.status == "accepted" for item in mapped["items"]) else []
    if (not all(item.competitor == brief.competitor and item.dimension == brief.dimension
                for item in (candidate, extraction, raw, *mapped["items"])) or
            page.candidate_id != candidate.id or extraction.source_candidate_id != candidate.id or
            extraction.captured_page_id != page.id or
            any(item.captured_page_id != page.id or item.source_candidate_id != candidate.id
                for item in mapped["items"]) or
            not all(str(url) == source["url"] for url in
                    (candidate.url, page.final_url, page.requested_url,
                     quote.source_url, raw.url)) or
            (quote.start_offset, quote.end_offset) != (0, len(source["excerpt"])) or
            page.text[quote.start_offset:quote.end_offset] != source["excerpt"] or
            quote.text != page.text or raw.snippet != page.text or
            any(item.quote != page.text or item.value != [page.text] or
                item.source_url != source["url"] for item in mapped["items"]) or
            extraction.fields != {"fixed_excerpt": [page.text]} or
            raw.metadata.get("normalized_fields") != expected_rows or
            raw.metadata.get("dataset_source_id") != source["id"] or
            digest(page.text.encode())[:16] != page.content_hash or
            raw.content_hash != page.content_hash):
        raise ValueError("excerpt quote/data identity binding mismatch")


def collector_preflight(mapped: dict) -> dict:
    identity = resolve_competitor_identity(mapped["brief"].competitor)
    allowed = semantic_page_allowed(mapped["brief"], mapped["capture"])
    return {"product": mapped["brief"].competitor, "source_id": mapped["source"]["id"],
            "identity_resolved": identity is not None, "semantic_page_allowed": allowed,
            "collector_status": "skipped", "collector_llm_transport_attempts": 0,
            "blocker": "unknown_product_identity" if identity is None else "collector_not_executed"}


@contextmanager
def isolated_environment(output: Path):
    previous = os.environ.get("KB_DB_PATH")
    os.environ["KB_DB_PATH"] = str(output / "canonical.sqlite")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("KB_DB_PATH", None)
        else:
            os.environ["KB_DB_PATH"] = previous


def live_settings(output: Path):
    settings = get_settings()
    if settings.llm_provider_name != "deepseek" or not settings.has_primary_llm_credentials:
        raise ValueError("inherited primary DeepSeek configuration is required")
    return replace(settings, demo_mode=False, run_orchestration_backend="langgraph",
        hitl_enabled=False, auto_redo_enabled=False, auto_redo_warn_enabled=False,
        analyst_react_enabled=False, max_iterations=1,
        backup_llm_api_key=None, backup_llm_model=None,
        llm_max_retries=0, run_llm_max_repairs=0, llm_max_output_tokens=2048,
        run_llm_max_calls=24, run_llm_max_tokens=80000, llm_timeout_seconds=45,
        artifact_storage_root=str(output / "artifacts"), langfuse_public_key=None,
        langfuse_secret_key=None, otel_export_endpoint=None)


async def run_stages(service: RunService, record) -> None:
    products = record.detail.plan.competitors
    await service._prepare_evidence_snapshot(record, phase="collect")
    await service._prepare_evidence_snapshot(record, phase="analysis")
    snapshot = service._current_evidence_snapshot(record)
    if snapshot.gaps or not snapshot.facts:
        raise ValueError("canonical snapshot admission blocked downstream execution")
    for product in products:
        service._finish_delivery_phase(record, "collector", f"feature::{product}")
    await service._real_analyst_dispatch_step(record, ["feature"], products)
    for product in products:
        await service._real_analyst_branch_step(record, "feature", product)
    await service._real_analyst_join_step(record, ["feature"], products)
    await service._real_comparator_step(record)
    await service._real_reflector_step(record)
    try:
        await service._write_report_draft(record)
    finally:
        await service._real_qa_step(record)


async def run_diagnostic(payloads: list[dict], output: Path, *, timeout=600, manifest=None) -> dict:
    """Execute production downstream stages; never invoke discovery or publish a report."""
    from packages.tools.ingest_document import ingest_document_reference
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    mappings = [map_excerpt(case, source) for case in payloads for source in case["sources"]]
    preflight = [collector_preflight(mapped) for mapped in mappings]
    context = {"input_mode": INPUT_MODE, "collector_status": "skipped", "collector_verified": False,
               "scope": "production downstream stages; curated excerpts; Collector unverified",
               "mechanical_mapping": "verbatim quote/evidence_terms; no semantic labels"}
    write_redacted_json(output / "manifest.json",
                        {**(manifest or {}), **context, "preflight": preflight})
    write_redacted_json(output / "inputs.json", payloads)
    write_redacted_json(output / "extractions.json", {**context, "collector_extractions": [],
        "curated_mappings": [{key: value.model_dump(mode="json") for key, value in mapped.items()
                             if key in {"capture", "candidate", "extraction", "raw_source"}}
                            for mapped in mappings]})
    error_type, error_reason, service, detail = None, None, None, None
    checkpoint = GraphCheckpointer.in_memory()
    with isolated_environment(output):
        settings = live_settings(output)
        try:
            service = RunService(SkillRegistry.from_default_path(), settings,
                journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(),
                trace_store=TraceStore.in_memory(),
                graph_checkpointer=checkpoint, enterprise_store=EnterpriseMemoryStore())
            products = list(dict.fromkeys(case["product"] for case in payloads))
            questions = "\n".join(case["question"] for case in payloads)
            detail = await service.create_run(RunCreateRequest(workspace_id="excerpt-diagnostic",
                project_id=uuid4().hex, topic=" / ".join(products) + " 的权限前提与访问范围研究",
                dimensions=["feature"], competitors=products, execution_mode="real",
                collaboration_mode="ai", output_language="zh-CN", auto_redo_warn_enabled=False,
                decision_brief={"decision_question": questions}))
            for mapped in mappings:
                validate_mapping(mapped)
                raw = mapped["raw_source"]
                reference = await ingest_document_reference(url=str(raw.url),
                    title=raw.title, text=raw.snippet,
                    competitor=raw.competitor, dimension=raw.dimension, source_type=raw.source_type,
                    metadata=raw.metadata, workspace_id=detail.workspace_id,
                    project_id=detail.project_id,
                    source_role="source", index_vectors=False, fetched_at=raw.extracted_at)
                raw.metadata.update(kb_document_id=reference["document_id"],
                    kb_document_version=reference["document_version"],
                    kb_document_content_hash=reference["content_hash"])
                detail.raw_sources.append(raw)
            async with asyncio.timeout(timeout):
                await run_stages(service, service._runs[detail.id])
        except Exception as exc:
            error_type = type(exc).__name__
            error_reason = _redact(str(exc))
        finally:
            await checkpoint.aclose()
        events = service.get_trace(detail.id) if service and detail else []
        summary = summarize_acceptance(detail, events=events, settings=settings) if detail else {}
        mechanical_blockers = bool(error_type or any(item["blocker"] for item in preflight) or
            (detail and any(issue.severity == "blocker" for issue in detail.qa_findings)))
        summary.update(context, status="blocked" if error_type else "diagnostic_complete",
            error_type=error_type, error_reason=error_reason, semantic_quality="pending_human",
            deliverable=False if mechanical_blockers else "pending_human",
            mechanical_pass=False, pipeline_terminal=False, collector_blockers=preflight,
            publication_status="not_attempted", configured_provider=settings.llm_provider_name,
            configured_model=settings.ark_model, provider_bill_usd=None,
            actual_models=sorted({span.model for span in detail.trace_spans
                                  if span.model}) if detail else [])
        if detail:
            snapshot = current_snapshot(detail)
            summary["downstream_observations"] = {
                "qa_blocker_count": sum(i.severity == "blocker" for i in detail.qa_findings),
                "writer_producer_verified": bool(snapshot and any(dep.kind == "writer"
                    for dep in detail.evidence_artifact_dependencies)
                    and service._final_qa_producer_verified(service._runs[detail.id], snapshot)),
                "reviewed_claim_count": sum(item.status == "supported"
                    for audit in detail.report_dimension_audits for item in audit.claims),
                "llm_transport_by_agent": {agent: sum(
                    span.metadata.get("llm_transport_attempts", 0) or 0
                    for span in detail.trace_spans if span.kind == "llm" and span.agent == agent)
                    for agent in "collector analyst comparator reflector writer qa".split()}}
            write_redacted_json(output / "run.json",
                                {**context, "detail": detail.model_dump(mode="json")})
            write_redacted_json(output / "snapshot.json",
                                [s.model_dump(mode="json") for s in detail.evidence_snapshots])
            write_redacted_json(output / "trace.json",
                                [span.model_dump(mode="json") for span in detail.trace_spans])
            if not detail.report_md and detail.report_dimension_audits:
                from packages.agents.writer.dimension_writer import render_dimension_report
                draft = render_dimension_report(detail, detail.report_dimension_audits,
                                                snapshot=snapshot)
                (output / "partial-draft.md").write_text(
                    "<!-- Diagnostic draft; Writer hardening failed; not publishable. -->\n" +
                    _redact(draft))
        write_redacted_json(output / "events.json",
                            [event.model_dump(mode="json") for event in events or []])
        (output / "report.md").write_text(_redact(detail.report_md if detail else "") + "\n")
        write_redacted_json(output / "summary.json", summary)
        return summary


async def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path,
                        default=ROOT / "eval/product-condition-review-v1.jsonl")
    parser.add_argument("--mode", choices=("candidate-diagnostic", "formal"),
                        default="candidate-diagnostic")
    parser.add_argument("--products", nargs="+", default=["Miro", "Airtable"])
    parser.add_argument("--expected-input-sha256")
    parser.add_argument("--output", type=Path, default=Path("/tmp/evidence-binding-" + uuid4().hex))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    locked_hash = args.expected_input_sha256 or digest(args.cases.read_bytes())
    cases = load_cases(args.cases, expected_sha256=locked_hash, mode=args.mode)
    if digest(args.cases.read_bytes()) != locked_hash:
        raise ValueError("input/source drift after loading frozen cases")
    selected = [allowed_payload(row) for row in cases
                if row["product"] in args.products and row["id"] in SCORED]
    if not selected or len(set(args.products)) > 2:
        raise ValueError("select one or two products with answer cases")
    manifest = {"input_sha256": locked_hash,
        "case_ids": [row["id"] for row in selected],
        "not_scored": [row["id"] for row in cases
                       if row["product"] in args.products and row["id"] not in SCORED],
        "runner_sha256": digest(Path(__file__).read_bytes()), "review_mode": args.mode,
        "sources_sha256": digest(json.dumps([row["sources"] for row in selected],
                                            sort_keys=True).encode()),
        "production_code_sha256": digest(b"".join(
            str(path.relative_to(ROOT)).encode() + path.read_bytes()
            for path in sorted((ROOT / "backend/packages").rglob("*.py"))))}
    if not args.live:
        preflight = [collector_preflight(map_excerpt(row, source))
                     for row in selected for source in row["sources"]]
        print(redacted_json({**manifest, "mode": "list_only", "collector_status": "skipped",
                             "llm_transport_attempts": 0, "preflight": preflight}))
        return
    if not args.expected_input_sha256:
        raise ValueError("--live requires --expected-input-sha256 from list_only")
    print(redacted_json(await run_diagnostic(selected, args.output,
                                            timeout=args.timeout, manifest=manifest)))


if __name__ == "__main__":
    asyncio.run(main())
