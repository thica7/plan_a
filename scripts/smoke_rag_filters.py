#!/usr/bin/env python3
"""Smoke-test RAG API filtering against the running backend."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx


DEFAULT_CASES = [
    {
        "name": "openai-codex-docs",
        "query": "OpenAI Codex CLI IDE pricing",
        "competitors": ["OpenAI Codex"],
        "dimensions": ["docs", "pricing"],
    },
    {
        "name": "coda-integrations",
        "query": "Coda API packs webhook integrations",
        "competitors": ["Coda"],
        "dimensions": ["docs", "integrations"],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test RAG result filters.")
    parser.add_argument("--api-base", default="http://localhost:8080")
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--final-top-k", type=int, default=5)
    return parser.parse_args()


def post_json(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


def run_case(client: httpx.Client, case: dict[str, Any], *, top_k: int, final_top_k: int) -> dict[str, Any]:
    payload = {
        "query": case["query"],
        "competitors": case["competitors"],
        "dimensions": case["dimensions"],
        "mode": "hybrid",
        "top_k": top_k,
        "rerank_top_k": top_k,
        "final_top_k": final_top_k,
        "enable_query_rewrite": False,
    }
    response = post_json(client, "/api/knowledge/search", payload)
    hits = response.get("hits", [])
    allowed_competitors = {item.casefold() for item in case["competitors"]}
    allowed_dimensions = {item.casefold() for item in case["dimensions"]}
    violations = [
        {
            "chunk_id": hit.get("chunk_id"),
            "document_id": hit.get("document_id"),
            "title": hit.get("title"),
            "url": hit.get("url"),
            "competitor": hit.get("competitor"),
            "dimension": hit.get("dimension"),
        }
        for hit in hits
        if str(hit.get("competitor") or "").casefold() not in allowed_competitors
        or str(hit.get("dimension") or "").casefold() not in allowed_dimensions
    ]
    return {
        "name": case["name"],
        "query": case["query"],
        "hit_count": len(hits),
        "violations": violations,
        "passed": not violations,
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
        results = [
            run_case(
                client,
                case,
                top_k=args.top_k,
                final_top_k=args.final_top_k,
            )
            for case in DEFAULT_CASES
        ]
    output = {
        "api_base": args.api_base.rstrip("/"),
        "passed": all(result["passed"] for result in results),
        "results": results,
    }
    print_json(output)
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPError as exc:
        print(f"API request failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
