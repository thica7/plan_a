#!/usr/bin/env python3
"""Plan or apply conservative KB cleanup actions through the local REST API."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_kb_quality import KNOWN_DIMENSIONS, document_url, has_mojibake, paged_documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan conservative KB cleanup actions.")
    parser.add_argument("--api-base", default="http://localhost:8080")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--remove-missing-metadata", action="store_true")
    parser.add_argument("--remove-suspicious-dimensions", action="store_true")
    parser.add_argument("--remove-404-like", action="store_true")
    parser.add_argument("--remove-mojibake", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Maximum actions to apply; 0 means no cap.")
    return parser.parse_args()


def classify_document(document: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    competitor = str(document.get("competitor") or "")
    dimension = str(document.get("dimension") or "")
    source_type = str(document.get("source_type") or "")
    title = str(document.get("title") or "")
    text = str(document.get("text") or "")

    if not competitor or not dimension or not source_type or not document_url(document):
        reasons.append("missing_metadata")
    if dimension and dimension not in KNOWN_DIMENSIONS:
        reasons.append("suspicious_dimension")
    if _is_404_like(title, text):
        reasons.append("404_like")
    if has_mojibake(document):
        reasons.append("mojibake")
    return reasons


def cleanup_plan(
    documents: list[dict[str, Any]],
    *,
    remove_missing_metadata: bool,
    remove_suspicious_dimensions: bool,
    remove_404_like: bool,
    remove_mojibake: bool,
) -> list[dict[str, Any]]:
    enabled = {
        "missing_metadata": remove_missing_metadata,
        "suspicious_dimension": remove_suspicious_dimensions,
        "404_like": remove_404_like,
        "mojibake": remove_mojibake,
    }
    actions: list[dict[str, Any]] = []
    for document in documents:
        reasons = classify_document(document)
        selected = [reason for reason in reasons if enabled.get(reason)]
        if not selected:
            continue
        actions.append({
            "action": "delete_document",
            "document_id": str(document.get("id") or ""),
            "title": str(document.get("title") or ""),
            "url": document_url(document),
            "competitor": str(document.get("competitor") or ""),
            "dimension": str(document.get("dimension") or ""),
            "reasons": selected,
        })
    return actions


def apply_cleanup(client: httpx.Client, actions: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    selected = actions[:limit] if limit > 0 else actions
    results: list[dict[str, Any]] = []
    for action in selected:
        document_id = str(action["document_id"])
        response = client.delete(f"/api/knowledge/documents/{document_id}")
        results.append({
            "document_id": document_id,
            "status_code": response.status_code,
            "ok": response.status_code == 204,
            "reasons": action["reasons"],
        })
        response.raise_for_status()
    return results


def _is_404_like(title: str, text: str) -> bool:
    lowered_title = title.lower()
    lowered_text = text[:2000].lower()
    return (
        "404" in lowered_title
        or "page could not be found" in lowered_title
        or "page could not be found" in lowered_text
        or "not found" == lowered_title.strip()
    )


def main() -> int:
    args = parse_args()
    with httpx.Client(
        base_url=args.api_base.rstrip("/"),
        timeout=60.0,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        documents = paged_documents(client)
        actions = cleanup_plan(
            documents,
            remove_missing_metadata=args.remove_missing_metadata,
            remove_suspicious_dimensions=args.remove_suspicious_dimensions,
            remove_404_like=args.remove_404_like,
            remove_mojibake=args.remove_mojibake,
        )
        applied = apply_cleanup(client, actions, limit=args.limit) if args.apply else []

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "api_base": args.api_base.rstrip("/"),
        "apply": args.apply,
        "candidate_count": len(actions),
        "applied_count": len(applied),
        "actions": actions[:100],
        "applied": applied,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPError as exc:
        print(f"API request failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
