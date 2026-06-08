#!/usr/bin/env python3
"""Audit KB coverage and data-quality signals through the local REST API."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_COMPETITORS = [
    "Anytype",
    "Coda",
    "Codeium",
    "Cursor",
    "Figma",
    "GitHub Copilot",
    "Obsidian",
    "OpenAI Codex",
    "Penpot",
    "Shortcut",
    "Windsurf",
]

KNOWN_DIMENSIONS = {
    "changelog",
    "docs",
    "integrations",
    "overview",
    "pricing",
    "release_notes",
    "security",
    "updates",
}

EXPECTED_COMPETITOR_DOMAINS = {
    "Anytype": {"anytype.io", "doc.anytype.io", "developers.anytype.io"},
    "Claude Code": {"anthropic.com", "docs.anthropic.com", "code.claude.com"},
    "Cloudflare Pages": {"cloudflare.com", "pages.cloudflare.com", "developers.cloudflare.com"},
    "Coda": {"coda.io"},
    "Codeium": {
        "cognition.ai",
        "codeium.com",
        "devin.ai",
        "docs.devin.ai",
        "docs.windsurf.com",
        "windsurf.com",
    },
    "Cursor": {"cursor.com", "docs.cursor.com"},
    "Figma": {"figma.com", "help.figma.com"},
    "Fly.io": {"fly.io"},
    "GitHub Copilot": {"github.com", "docs.github.com", "github.blog"},
    "Jira": {"atlassian.com", "support.atlassian.com"},
    "Linear": {"linear.app"},
    "Netlify": {"netlify.com", "docs.netlify.com"},
    "Notion": {"notion.com", "notion.so"},
    "Obsidian": {"obsidian.md", "help.obsidian.md", "docs.obsidian.md"},
    "OpenAI Codex": {"developers.openai.com", "platform.openai.com"},
    "Penpot": {"penpot.app", "help.penpot.app", "community.penpot.app"},
    "Qodo": {"qodo.ai", "docs.qodo.ai"},
    "Railway": {"railway.com"},
    "Render": {"render.com"},
    "Replit": {"replit.com", "docs.replit.com"},
    "Shortcut": {"shortcut.com", "developer.shortcut.com", "help.shortcut.com"},
    "Sketch": {"sketch.com"},
    "Supabase": {"supabase.com"},
    "Vercel": {"vercel.com"},
    "Windsurf": {
        "cognition.ai",
        "devin.ai",
        "docs.devin.ai",
        "windsurf.com",
        "docs.windsurf.com",
    },
}

MOJIBAKE_MARKERS = ("\u00e2", "\u00c2", "\u00c3", "\ufffd")
TERMINAL_FAILURE_STATUSES = {"failed", "cancelled"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit KB quality via REST API.")
    parser.add_argument("--api-base", default="http://localhost:8080")
    parser.add_argument("--min-docs-per-competitor", type=int, default=8)
    parser.add_argument("--stale-days", type=int, default=30)
    parser.add_argument("--recent-failed-jobs", type=int, default=50)
    parser.add_argument("--max-suspicious-dimensions", type=int, default=0)
    parser.add_argument("--max-missing-metadata", type=int, default=0)
    parser.add_argument("--max-mojibake-documents", type=int, default=0)
    parser.add_argument("--max-non-http-documents", type=int, default=0)
    parser.add_argument("--max-suspicious-source-domains", type=int, default=0)
    parser.add_argument("--fail-on-gate", action="store_true")
    parser.add_argument("--competitor", action="append", default=[])
    return parser.parse_args()


def get_json(client: httpx.Client, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()


def paged_documents(client: httpx.Client, *, page_size: int = 200) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = get_json(client, "/api/knowledge/documents", limit=page_size, offset=offset)
        if not isinstance(page, list):
            raise ValueError("unexpected documents response")
        documents.extend(page)
        if len(page) < page_size:
            return documents
        offset += page_size


def failed_jobs(client: httpx.Client, *, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    if limit <= 0:
        return [], []
    params = {"status": "failed", "limit": min(limit, 200), "offset": 0}
    warnings: list[str] = []
    try:
        jobs = get_json(client, "/api/crawl/jobs", **params)
    except httpx.HTTPStatusError as exc:
        warnings.append(
            f"/api/crawl/jobs failed with HTTP {exc.response.status_code}; "
            "falling back to /api/knowledge/crawl-jobs"
        )
        jobs = get_json(client, "/api/knowledge/crawl-jobs", **params)
    if not isinstance(jobs, list):
        raise ValueError("unexpected crawl jobs response")
    return jobs, warnings


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def document_url(document: dict[str, Any]) -> str:
    return str(document.get("canonical_url") or document.get("url") or "")


def has_mojibake(document: dict[str, Any]) -> bool:
    title = str(document.get("title") or "")
    text = str(document.get("text") or "")
    return any(marker in title or marker in text[:4000] for marker in MOJIBAKE_MARKERS)


def audit_documents(
    documents: list[dict[str, Any]],
    *,
    competitors: list[str],
    min_docs_per_competitor: int,
    stale_days: int,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=max(0, stale_days))
    by_competitor: Counter[str] = Counter()
    by_dimension: Counter[str] = Counter()
    by_source_type: Counter[str] = Counter()
    suspicious_dimensions: list[dict[str, str]] = []
    missing_metadata: list[dict[str, str]] = []
    stale_documents: list[dict[str, str]] = []
    mojibake_documents: list[dict[str, str]] = []
    non_http_documents: list[dict[str, str]] = []
    suspicious_source_domains: list[dict[str, str]] = []
    duplicate_urls: dict[str, list[str]] = defaultdict(list)

    for document in documents:
        competitor = str(document.get("competitor") or "")
        dimension = str(document.get("dimension") or "")
        source_type = str(document.get("source_type") or "")
        url = document_url(document)
        title = str(document.get("title") or "")
        document_id = str(document.get("id") or "")

        by_competitor[competitor or "<missing>"] += 1
        by_dimension[dimension or "<missing>"] += 1
        by_source_type[source_type or "<missing>"] += 1

        if url:
            duplicate_urls[url].append(document_id)
            scheme = urlsplit(url).scheme
            if scheme not in {"http", "https"}:
                non_http_documents.append(_doc_ref(document, reason=f"scheme={scheme or '<empty>'}"))
            if competitor and not _source_domain_matches_competitor(competitor, url):
                host = urlsplit(url).hostname or "<missing>"
                suspicious_source_domains.append(_doc_ref(
                    document,
                    reason=f"competitor={competitor}, host={host}",
                ))
        else:
            non_http_documents.append(_doc_ref(document, reason="missing_url"))

        if not competitor or not dimension or not source_type:
            missing_metadata.append(_doc_ref(document, reason="missing required metadata"))
        if dimension and dimension not in KNOWN_DIMENSIONS:
            suspicious_dimensions.append(_doc_ref(document, reason=f"dimension={dimension}"))
        if has_mojibake(document):
            mojibake_documents.append(_doc_ref(document, reason="mojibake marker"))

        seen_at = parse_datetime(str(document.get("last_seen_at") or document.get("fetched_at") or ""))
        if seen_at is not None and seen_at < stale_cutoff:
            stale_documents.append(_doc_ref(document, reason=f"last_seen_at={seen_at.isoformat()}"))
        if not title.strip():
            missing_metadata.append(_doc_ref(document, reason="missing title"))

    low_coverage = [
        {"competitor": competitor, "count": by_competitor.get(competitor, 0)}
        for competitor in competitors
        if by_competitor.get(competitor, 0) < min_docs_per_competitor
    ]
    duplicate_active_urls = [
        {"url": url, "document_ids": ids}
        for url, ids in sorted(duplicate_urls.items())
        if len(ids) > 1
    ]

    return {
        "document_count": len(documents),
        "competitor_counts": dict(sorted(by_competitor.items())),
        "dimension_counts": dict(sorted(by_dimension.items())),
        "source_type_counts": dict(sorted(by_source_type.items())),
        "low_coverage": sorted(low_coverage, key=lambda item: (item["count"], item["competitor"])),
        "suspicious_dimensions": suspicious_dimensions[:50],
        "suspicious_dimensions_count": len(suspicious_dimensions),
        "missing_metadata": missing_metadata[:50],
        "missing_metadata_count": len(missing_metadata),
        "mojibake_documents": mojibake_documents[:50],
        "mojibake_documents_count": len(mojibake_documents),
        "stale_documents": stale_documents[:50],
        "stale_documents_count": len(stale_documents),
        "non_http_documents": non_http_documents[:50],
        "non_http_documents_count": len(non_http_documents),
        "suspicious_source_domains": suspicious_source_domains[:50],
        "suspicious_source_domains_count": len(suspicious_source_domains),
        "duplicate_active_urls": duplicate_active_urls[:50],
        "duplicate_active_urls_count": len(duplicate_active_urls),
    }


def _source_domain_matches_competitor(competitor: str, url: str) -> bool:
    allowed_domains = EXPECTED_COMPETITOR_DOMAINS.get(competitor)
    if not allowed_domains:
        return True
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for allowed in allowed_domains:
        normalized = allowed.lower().removeprefix("www.")
        if host == normalized or host.endswith(f".{normalized}"):
            return True
    return False


def audit_failed_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    error_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    samples: list[dict[str, str]] = []
    for job in jobs:
        status = str(job.get("status") or "")
        error = str(job.get("error") or "<empty>")
        status_counts[status or "<missing>"] += 1
        if status in TERMINAL_FAILURE_STATUSES or status == "failed":
            error_counts[error] += 1
            samples.append({
                "url": str(job.get("url") or ""),
                "competitor": str(job.get("competitor") or ""),
                "dimension": str(job.get("dimension") or ""),
                "error": error,
            })
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "error_counts": dict(error_counts.most_common()),
        "samples": samples[:20],
    }


def quality_gate(
    quality: dict[str, Any],
    *,
    max_suspicious_dimensions: int,
    max_missing_metadata: int,
    max_mojibake_documents: int,
    max_non_http_documents: int,
    max_suspicious_source_domains: int = 0,
) -> dict[str, Any]:
    blockers: list[str] = []
    if quality["low_coverage"]:
        labels = [
            f"{item['competitor']}={item['count']}"
            for item in quality["low_coverage"]
        ]
        blockers.append(f"low_coverage: {', '.join(labels)}")
    _append_threshold_blocker(
        blockers,
        "suspicious_dimensions",
        quality["suspicious_dimensions_count"],
        max_suspicious_dimensions,
    )
    _append_threshold_blocker(
        blockers,
        "missing_metadata",
        quality["missing_metadata_count"],
        max_missing_metadata,
    )
    _append_threshold_blocker(
        blockers,
        "mojibake_documents",
        quality["mojibake_documents_count"],
        max_mojibake_documents,
    )
    _append_threshold_blocker(
        blockers,
        "non_http_documents",
        quality["non_http_documents_count"],
        max_non_http_documents,
    )
    _append_threshold_blocker(
        blockers,
        "suspicious_source_domains",
        quality["suspicious_source_domains_count"],
        max_suspicious_source_domains,
    )
    return {
        "passed": not blockers,
        "blockers": blockers,
        "thresholds": {
            "max_suspicious_dimensions": max_suspicious_dimensions,
            "max_missing_metadata": max_missing_metadata,
            "max_mojibake_documents": max_mojibake_documents,
            "max_non_http_documents": max_non_http_documents,
            "max_suspicious_source_domains": max_suspicious_source_domains,
        },
    }


def _append_threshold_blocker(
    blockers: list[str],
    name: str,
    actual: int,
    maximum: int,
) -> None:
    if actual > maximum:
        blockers.append(f"{name}: {actual} > {maximum}")


def _doc_ref(document: dict[str, Any], *, reason: str) -> dict[str, str]:
    return {
        "id": str(document.get("id") or ""),
        "title": str(document.get("title") or ""),
        "url": document_url(document),
        "competitor": str(document.get("competitor") or ""),
        "dimension": str(document.get("dimension") or ""),
        "reason": reason,
    }


def print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        print(json.dumps(payload, ensure_ascii=True, indent=2))


def main() -> int:
    args = parse_args()
    competitors = args.competitor or DEFAULT_COMPETITORS
    with httpx.Client(
        base_url=args.api_base.rstrip("/"),
        timeout=60.0,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        health = get_json(client, "/api/health")
        stats = get_json(client, "/api/knowledge/stats")
        documents = paged_documents(client)
        failures, audit_warnings = failed_jobs(client, limit=args.recent_failed_jobs)

    quality = audit_documents(
        documents,
        competitors=competitors,
        min_docs_per_competitor=args.min_docs_per_competitor,
        stale_days=args.stale_days,
    )
    gate = quality_gate(
        quality,
        max_suspicious_dimensions=args.max_suspicious_dimensions,
        max_missing_metadata=args.max_missing_metadata,
        max_mojibake_documents=args.max_mojibake_documents,
        max_non_http_documents=args.max_non_http_documents,
        max_suspicious_source_domains=args.max_suspicious_source_domains,
    )
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "api_base": args.api_base.rstrip("/"),
        "health": health,
        "stats": stats,
        "quality": quality,
        "quality_gate": gate,
        "recent_failed_jobs": audit_failed_jobs(failures),
        "warnings": audit_warnings,
    }
    print_json(output)
    if health.get("status") == "error":
        return 2
    if args.fail_on_gate and not gate["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPError as exc:
        print(f"API request failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
