#!/usr/bin/env python3
"""Validate the running backend after rebuild and real-source collection."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx


def _load_script(name: str):
    script_path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate runtime health, KB quality, and RAG filters.")
    parser.add_argument("--api-base", default="http://localhost:8080")
    parser.add_argument("--min-docs-per-competitor", type=int, default=8)
    parser.add_argument("--recent-failed-jobs", type=int, default=50)
    return parser.parse_args()


def get_json(client: httpx.Client, path: str) -> Any:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def post_json(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


def smoke_fetch(client: httpx.Client) -> dict[str, Any]:
    payload = {"url": "https://developers.openai.com/codex"}
    response = post_json(client, "/api/smoke/fetch", payload)
    return {
        "passed": bool(response.get("ok")) and response.get("details", {}).get("text_chars", 0) > 500,
        "result": response,
    }


def audit_quality(client: httpx.Client, *, min_docs_per_competitor: int, recent_failed_jobs: int) -> dict[str, Any]:
    audit = _load_script("audit_kb_quality")
    health = get_json(client, "/api/health")
    stats = get_json(client, "/api/knowledge/stats")
    documents = audit.paged_documents(client)
    failures, warnings = audit.failed_jobs(client, limit=recent_failed_jobs)
    quality = audit.audit_documents(
        documents,
        competitors=audit.DEFAULT_COMPETITORS,
        min_docs_per_competitor=min_docs_per_competitor,
        stale_days=30,
    )
    gate = audit.quality_gate(
        quality,
        max_suspicious_dimensions=0,
        max_missing_metadata=0,
        max_mojibake_documents=0,
        max_non_http_documents=0,
        max_suspicious_source_domains=0,
    )
    return {
        "passed": health.get("status") != "error" and gate["passed"],
        "health": health,
        "stats": stats,
        "quality_gate": gate,
        "low_coverage": quality["low_coverage"],
        "warnings": warnings,
        "failed_job_errors": audit.audit_failed_jobs(failures)["error_counts"],
    }


def smoke_rag_filters(client: httpx.Client) -> dict[str, Any]:
    smoke = _load_script("smoke_rag_filters")
    results = [
        smoke.run_case(client, case, top_k=12, final_top_k=5)
        for case in smoke.DEFAULT_CASES
    ]
    return {
        "passed": all(result["passed"] for result in results),
        "results": results,
    }


def print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        print(json.dumps(payload, ensure_ascii=True, indent=2))


def main() -> int:
    args = parse_args()
    with httpx.Client(
        base_url=args.api_base.rstrip("/"),
        timeout=60.0,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        checks = {
            "fetch": smoke_fetch(client),
            "rag_filters": smoke_rag_filters(client),
            "kb_quality": audit_quality(
                client,
                min_docs_per_competitor=args.min_docs_per_competitor,
                recent_failed_jobs=args.recent_failed_jobs,
            ),
        }
    output = {
        "api_base": args.api_base.rstrip("/"),
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
    }
    print_json(output)
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPError as exc:
        print(f"API request failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
