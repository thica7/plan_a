#!/usr/bin/env python3
"""Collect verified public pages into the KB without synthetic fallback text."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlsplit

import httpx

TERMINAL = {"success", "failed", "cancelled", "completed"}
CRAWL_JOB_API_PATHS = {
    "crawl": "/api/crawl/jobs",
    "knowledge": "/api/knowledge/crawl-jobs",
}

SOURCES: list[dict[str, str]] = [
    # Agentic AI IDEs
    {"competitor": "Cursor", "dimension": "pricing", "url": "https://cursor.com/pricing"},
    {"competitor": "Cursor", "dimension": "docs", "url": "https://docs.cursor.com"},
    {"competitor": "Cursor", "dimension": "changelog", "url": "https://cursor.com/changelog"},
    {"competitor": "Cursor", "dimension": "security", "url": "https://cursor.com/security"},
    {"competitor": "Windsurf", "dimension": "pricing", "url": "https://windsurf.com/pricing"},
    {"competitor": "Windsurf", "dimension": "docs", "url": "https://docs.windsurf.com"},
    {"competitor": "Windsurf", "dimension": "changelog", "url": "https://windsurf.com/changelog"},
    {"competitor": "Codeium", "dimension": "overview", "url": "https://docs.windsurf.com/plugins"},
    {
        "competitor": "Codeium",
        "dimension": "docs",
        "url": "https://docs.windsurf.com/plugins/getting-started",
    },
    {
        "competitor": "Codeium",
        "dimension": "integrations",
        "url": "https://docs.windsurf.com/command/plugins-overview",
    },
    {"competitor": "Codeium", "dimension": "pricing", "url": "https://codeium.com/pricing"},
    {"competitor": "Codeium", "dimension": "changelog", "url": "https://codeium.com/changelog"},
    {"competitor": "GitHub Copilot", "dimension": "pricing", "url": "https://github.com/features/copilot#pricing"},
    {"competitor": "GitHub Copilot", "dimension": "docs", "url": "https://docs.github.com/en/copilot"},
    {"competitor": "GitHub Copilot", "dimension": "changelog", "url": "https://github.blog/changelog/label/copilot"},
    {"competitor": "Qodo", "dimension": "pricing", "url": "https://www.qodo.ai/pricing"},
    {"competitor": "Qodo", "dimension": "docs", "url": "https://docs.qodo.ai"},
    # Collaboration and knowledge tools
    {"competitor": "Notion", "dimension": "pricing", "url": "https://www.notion.com/pricing"},
    {"competitor": "Notion", "dimension": "docs", "url": "https://www.notion.com/help"},
    {"competitor": "Notion", "dimension": "integrations", "url": "https://www.notion.com/integrations"},
    {"competitor": "Notion", "dimension": "security", "url": "https://www.notion.com/security"},
    {"competitor": "Coda", "dimension": "pricing", "url": "https://coda.io/pricing"},
    {"competitor": "Coda", "dimension": "docs", "url": "https://coda.io/developers/apis/v1"},
    {"competitor": "Coda", "dimension": "docs", "url": "https://coda.io/api-migration-guide"},
    {"competitor": "Coda", "dimension": "integrations", "url": "https://coda.io/packs"},
    {"competitor": "Coda", "dimension": "integrations", "url": "https://coda.io/product/packs"},
    {"competitor": "Coda", "dimension": "integrations", "url": "https://coda.io/packs/build/latest/"},
    {"competitor": "Coda", "dimension": "changelog", "url": "https://coda.io/packs/build/latest/support/changes/"},
    {"competitor": "Obsidian", "dimension": "pricing", "url": "https://obsidian.md/pricing"},
    {"competitor": "Obsidian", "dimension": "docs", "url": "https://help.obsidian.md"},
    {"competitor": "Obsidian", "dimension": "docs", "url": "https://docs.obsidian.md"},
    {"competitor": "Obsidian", "dimension": "changelog", "url": "https://obsidian.md/changelog"},
    {"competitor": "Obsidian", "dimension": "security", "url": "https://obsidian.md/security"},
    {"competitor": "Anytype", "dimension": "pricing", "url": "https://anytype.io/pricing"},
    {"competitor": "Anytype", "dimension": "docs", "url": "https://doc.anytype.io/anytype-docs"},
    {"competitor": "Anytype", "dimension": "integrations", "url": "https://developers.anytype.io/docs/reference/2025-04-22/anytype-api"},
    {"competitor": "Anytype", "dimension": "security", "url": "https://doc.anytype.io/anytype-docs/advanced/data-and-security/self-hosting/self-hosted"},
    # Design tools
    {"competitor": "Figma", "dimension": "pricing", "url": "https://www.figma.com/pricing"},
    {"competitor": "Figma", "dimension": "docs", "url": "https://help.figma.com"},
    {"competitor": "Figma", "dimension": "release_notes", "url": "https://www.figma.com/release-notes"},
    {"competitor": "Figma", "dimension": "security", "url": "https://www.figma.com/security"},
    {"competitor": "Penpot", "dimension": "pricing", "url": "https://penpot.app/pricing"},
    {"competitor": "Penpot", "dimension": "docs", "url": "https://help.penpot.app"},
    {"competitor": "Penpot", "dimension": "changelog", "url": "https://community.penpot.app/c/announcements/product-updates/16"},
    {"competitor": "Penpot", "dimension": "integrations", "url": "https://help.penpot.app/plugins/beta-changelog/"},
    {"competitor": "Penpot", "dimension": "security", "url": "https://penpot.app/security-whitepaper"},
    {"competitor": "Sketch", "dimension": "pricing", "url": "https://www.sketch.com/pricing"},
    {"competitor": "Sketch", "dimension": "docs", "url": "https://www.sketch.com/docs"},
    {"competitor": "Sketch", "dimension": "updates", "url": "https://www.sketch.com/updates"},
    {"competitor": "Canva", "dimension": "pricing", "url": "https://www.canva.com/pricing"},
    {"competitor": "Canva", "dimension": "docs", "url": "https://www.canva.com/help"},
    # Product management
    {"competitor": "Linear", "dimension": "pricing", "url": "https://linear.app/pricing"},
    {"competitor": "Linear", "dimension": "docs", "url": "https://linear.app/docs"},
    {"competitor": "Linear", "dimension": "changelog", "url": "https://linear.app/changelog"},
    {"competitor": "Linear", "dimension": "security", "url": "https://linear.app/security"},
    {"competitor": "Jira", "dimension": "pricing", "url": "https://www.atlassian.com/software/jira/pricing"},
    {"competitor": "Jira", "dimension": "docs", "url": "https://support.atlassian.com/jira-software-cloud"},
    {"competitor": "Jira", "dimension": "changelog", "url": "https://www.atlassian.com/software/jira/whats-new"},
    {"competitor": "Shortcut", "dimension": "pricing", "url": "https://www.shortcut.com/pricing"},
    {"competitor": "Shortcut", "dimension": "overview", "url": "https://www.shortcut.com/"},
    {"competitor": "Shortcut", "dimension": "docs", "url": "https://www.shortcut.com/faq"},
    {"competitor": "Shortcut", "dimension": "integrations", "url": "https://developer.shortcut.com/"},
    {"competitor": "Shortcut", "dimension": "integrations", "url": "https://www.shortcut.com/agents"},
    {"competitor": "Shortcut", "dimension": "security", "url": "https://www.shortcut.com/security"},
    {"competitor": "Shortcut", "dimension": "changelog", "url": "https://www.shortcut.com/release-notes/"},
    {"competitor": "Shortcut", "dimension": "changelog", "url": "https://www.shortcut.com/blog-categories/shortcut-news-and-updates"},
    {"competitor": "Height", "dimension": "pricing", "url": "https://height.app/pricing"},
    {"competitor": "Height", "dimension": "docs", "url": "https://height.app/help"},
    {"competitor": "Height", "dimension": "changelog", "url": "https://height.app/changelog"},
    # Deployment platforms
    {"competitor": "Vercel", "dimension": "pricing", "url": "https://vercel.com/pricing"},
    {"competitor": "Vercel", "dimension": "docs", "url": "https://vercel.com/docs"},
    {"competitor": "Vercel", "dimension": "changelog", "url": "https://vercel.com/changelog"},
    {"competitor": "Vercel", "dimension": "security", "url": "https://vercel.com/security"},
    {"competitor": "Netlify", "dimension": "pricing", "url": "https://www.netlify.com/pricing"},
    {"competitor": "Netlify", "dimension": "docs", "url": "https://docs.netlify.com"},
    {"competitor": "Netlify", "dimension": "changelog", "url": "https://www.netlify.com/changelog"},
    {"competitor": "Cloudflare Pages", "dimension": "pricing", "url": "https://pages.cloudflare.com"},
    {"competitor": "Cloudflare Pages", "dimension": "docs", "url": "https://developers.cloudflare.com/pages"},
    {"competitor": "Cloudflare Pages", "dimension": "changelog", "url": "https://developers.cloudflare.com/pages/changelog"},
    # OpenAI Codex has no static seed source above; keep several high-signal pages for targeted fills.
    {"competitor": "OpenAI Codex", "dimension": "overview", "url": "https://developers.openai.com/codex"},
    {"competitor": "OpenAI Codex", "dimension": "docs", "url": "https://developers.openai.com/codex/cli"},
    {"competitor": "OpenAI Codex", "dimension": "docs", "url": "https://developers.openai.com/codex/ide"},
    {"competitor": "OpenAI Codex", "dimension": "docs", "url": "https://developers.openai.com/codex/cloud"},
    {"competitor": "OpenAI Codex", "dimension": "pricing", "url": "https://developers.openai.com/api/docs/models/gpt-5.3-codex"},
]

SITEMAPS: list[dict[str, str]] = [
    {"competitor": "Cursor", "url": "https://cursor.com/sitemap.xml"},
    {"competitor": "Cursor", "url": "https://docs.cursor.com/sitemap.xml"},
    {"competitor": "Windsurf", "url": "https://windsurf.com/sitemap.xml"},
    {"competitor": "Windsurf", "url": "https://docs.windsurf.com/sitemap.xml"},
    {"competitor": "Codeium", "url": "https://docs.windsurf.com/llms.txt"},
    {"competitor": "GitHub Copilot", "url": "https://docs.github.com/sitemap.xml"},
    {"competitor": "Qodo", "url": "https://docs.qodo.ai/sitemap.xml"},
    {"competitor": "Notion", "url": "https://www.notion.com/sitemap.xml"},
    {"competitor": "Coda", "url": "https://coda.io/sitemap.xml"},
    {"competitor": "Obsidian", "url": "https://help.obsidian.md/sitemap.xml"},
    {"competitor": "Anytype", "url": "https://doc.anytype.io/sitemap.xml"},
    {"competitor": "Figma", "url": "https://help.figma.com/sitemap.xml"},
    {"competitor": "Penpot", "url": "https://help.penpot.app/sitemap.xml"},
    {"competitor": "Sketch", "url": "https://www.sketch.com/sitemap.xml"},
    {"competitor": "Linear", "url": "https://linear.app/sitemap.xml"},
    {"competitor": "Jira", "url": "https://support.atlassian.com/sitemap.xml"},
    {"competitor": "Vercel", "url": "https://vercel.com/sitemap.xml"},
    {"competitor": "Netlify", "url": "https://docs.netlify.com/sitemap.xml"},
    {"competitor": "Cloudflare Pages", "url": "https://developers.cloudflare.com/sitemap.xml"},
    {"competitor": "Supabase", "url": "https://supabase.com/sitemap.xml"},
    {"competitor": "Supabase", "url": "https://supabase.com/docs/sitemap.xml"},
    {"competitor": "Railway", "url": "https://railway.com/sitemap.xml"},
    {"competitor": "Render", "url": "https://render.com/sitemap.xml"},
    {"competitor": "Fly.io", "url": "https://fly.io/sitemap.xml"},
    {"competitor": "Replit", "url": "https://docs.replit.com/sitemap.xml"},
    {"competitor": "Claude Code", "url": "https://docs.anthropic.com/sitemap.xml"},
    {"competitor": "OpenAI Codex", "url": "https://developers.openai.com/sitemap.xml"},
    {"competitor": "OpenAI Codex", "url": "https://platform.openai.com/sitemap.xml"},
]

SITEMAP_PATH_PREFIXES = {
    "Codeium": (
        "/command/plugins",
        "/plugins/",
        "/troubleshooting/plugins",
    ),
}

DISCOVERY_KEYWORDS = [
    "pricing",
    "plans",
    "docs",
    "documentation",
    "api",
    "security",
    "sso",
    "saml",
    "audit",
    "webhook",
    "integration",
    "changelog",
    "release",
    "releases",
    "blog",
    "whats-new",
    "what-s-new",
    "what's-new",
    "news",
    "updates",
    "guide",
    "reference",
    "enterprise",
    "admin",
    "billing",
    "limits",
    "copilot",
    "pages",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect verified public URLs into KB.")
    parser.add_argument("--api-base", default="http://localhost:8000")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum built-in seed sources to include; 0 means all built-in sources.",
    )
    parser.add_argument("--window", type=int, default=2)
    parser.add_argument("--wait-seconds", type=int, default=90)
    parser.add_argument("--verify-timeout", type=float, default=20.0)
    parser.add_argument(
        "--verify-mode",
        choices=["local", "backend", "none"],
        default="local",
        help="Use local HTTP checks, backend /api/smoke/fetch checks, or skip preflight checks.",
    )
    parser.add_argument("--discover-sitemaps", action="store_true")
    parser.add_argument("--discovered-limit", type=int, default=80)
    parser.add_argument("--per-competitor-limit", type=int, default=40)
    parser.add_argument("--include-competitor", action="append", default=[])
    parser.add_argument("--exclude-competitor", action="append", default=[])
    parser.add_argument("--allow-existing", action="store_true")
    parser.add_argument(
        "--job-api",
        choices=["auto", "crawl", "knowledge"],
        default="auto",
        help="Crawl-job API to use; auto falls back to /api/knowledge/crawl-jobs.",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def verify_url(client: httpx.Client, url: str, timeout: float) -> tuple[bool, str]:
    try:
        response = client.get(url, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:180]}"
    content_type = response.headers.get("content-type", "")
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code}"
    text_content_types = ("text/html", "text/plain", "text/markdown", "text/x-markdown")
    if not any(content_type.startswith(kind) for kind in text_content_types):
        return False, f"unsupported content-type {content_type[:80]}"
    return True, f"HTTP {response.status_code}, {len(response.text)} chars"


def verify_url_via_backend(client: httpx.Client, url: str) -> tuple[bool, str]:
    try:
        response = client.post("/api/smoke/fetch", json={"url": url})
    except httpx.HTTPError as exc:
        return False, f"backend fetch request failed: {type(exc).__name__}: {str(exc)[:180]}"
    if response.status_code >= 400:
        return False, f"backend fetch HTTP {response.status_code}: {response.text[:180]}"
    payload = response.json()
    details = payload.get("details") if isinstance(payload, dict) else {}
    if not payload.get("ok"):
        error = details.get("error") if isinstance(details, dict) else None
        status_code = details.get("status_code") if isinstance(details, dict) else None
        return False, f"backend fetch failed: status={status_code}, error={error or '<empty>'}"
    text_chars = int(details.get("text_chars") or 0) if isinstance(details, dict) else 0
    status_code = details.get("status_code") if isinstance(details, dict) else None
    title = str(details.get("title") or "")[:80] if isinstance(details, dict) else ""
    if text_chars < 80:
        return False, f"backend fetch returned too little text: {text_chars} chars"
    return True, f"backend fetch HTTP {status_code}, {text_chars} chars, title={title}"


def verify_source(
    client: httpx.Client,
    source: dict[str, str],
    *,
    mode: str,
    timeout: float,
) -> tuple[bool, str]:
    if mode == "none":
        return True, "verification skipped"
    if mode == "backend":
        return verify_url_via_backend(client, source["url"])
    return verify_url(client, source["url"], timeout)


def discover_sitemap_sources(
    client: httpx.Client,
    limit: int,
    *,
    per_competitor_limit: int,
) -> list[dict[str, str]]:
    discovered: list[dict[str, str]] = []
    seen: set[str] = {source["url"] for source in SOURCES}
    for sitemap in SITEMAPS:
        for entry in sitemap_entries(client, sitemap["url"], max_nested=2):
            url = entry["url"]
            if url in seen or not _is_relevant_url(url):
                continue
            if not _sitemap_entry_matches_competitor(sitemap["competitor"], url):
                continue
            seen.add(url)
            discovered.append({
                "competitor": sitemap["competitor"],
                "dimension": _dimension_for_url(url),
                "url": url,
                "lastmod": entry.get("lastmod", ""),
            })
    discovered.sort(key=lambda item: (item.get("lastmod", ""), item["url"]), reverse=True)
    if per_competitor_limit <= 0:
        return discovered[:limit]

    balanced: list[dict[str, str]] = []
    counts: dict[str, int] = {}
    for item in discovered:
        competitor = item["competitor"]
        if counts.get(competitor, 0) >= per_competitor_limit:
            continue
        balanced.append(item)
        counts[competitor] = counts.get(competitor, 0) + 1
        if len(balanced) >= limit:
            break
    return balanced


def sitemap_urls(client: httpx.Client, sitemap_url: str, *, max_nested: int) -> list[str]:
    return [entry["url"] for entry in sitemap_entries(client, sitemap_url, max_nested=max_nested)]


def sitemap_entries(
    client: httpx.Client,
    sitemap_url: str,
    *,
    max_nested: int,
) -> list[dict[str, str]]:
    try:
        response = client.get(sitemap_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log(f"skip sitemap {sitemap_url}: {type(exc).__name__}: {str(exc)[:120]}")
        return []
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        entries = _text_index_entries(response.text)
        if entries:
            return entries
        log(f"skip sitemap {sitemap_url}: XML parse error {exc}")
        return []

    entries: list[dict[str, str]] = []
    nested: list[str] = []
    for node in root:
        loc = _child_text(node, "loc")
        if not loc:
            continue
        if loc.endswith(".xml"):
            nested.append(loc)
            continue
        entries.append({"url": loc, "lastmod": _child_text(node, "lastmod")})

    if max_nested <= 0:
        return entries
    for nested_url in nested[:8]:
        entries.extend(sitemap_entries(client, nested_url, max_nested=max_nested - 1))
    return entries


def _child_text(node: ET.Element, suffix: str) -> str:
    for child in node:
        if child.tag.endswith(suffix) and child.text:
            return child.text.strip()
    return ""


def _text_index_entries(text: str) -> list[dict[str, str]]:
    urls = re.findall(r"https?://[^\s<>\]\)\"']+", text)
    seen: set[str] = set()
    entries: list[dict[str, str]] = []
    for url in urls:
        cleaned = url.rstrip(".,;:")
        if cleaned in seen:
            continue
        seen.add(cleaned)
        entries.append({"url": cleaned, "lastmod": ""})
    return entries


def _is_relevant_url(url: str) -> bool:
    parsed = urlsplit(url)
    lowered = f"{parsed.path}?{parsed.query}".lower()
    return any(keyword in lowered for keyword in DISCOVERY_KEYWORDS)


def _sitemap_entry_matches_competitor(competitor: str, url: str) -> bool:
    prefixes = SITEMAP_PATH_PREFIXES.get(competitor)
    if not prefixes:
        return True
    path = urlsplit(url).path.lower()
    return any(path.startswith(prefix) for prefix in prefixes)


def _dimension_for_url(url: str) -> str:
    lowered = url.lower()
    if any(token in lowered for token in ["pricing", "plans"]):
        return "pricing"
    if any(token in lowered for token in ["changelog", "release", "updates", "whats-new"]):
        return "changelog"
    if any(token in lowered for token in ["security", "sso", "saml", "audit"]):
        return "security"
    if any(token in lowered for token in ["integration", "webhook", "api", "reference"]):
        return "integrations"
    if any(token in lowered for token in ["billing", "limits", "admin", "enterprise"]):
        return "pricing"
    return "docs"


def post_json(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


def get_json(client: httpx.Client, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()


def _job_api_paths(mode: str) -> list[str]:
    if mode == "auto":
        return [CRAWL_JOB_API_PATHS["crawl"], CRAWL_JOB_API_PATHS["knowledge"]]
    return [CRAWL_JOB_API_PATHS[mode]]


def create_crawl_job(
    client: httpx.Client,
    payload: dict[str, Any],
    *,
    job_api: str,
) -> tuple[dict[str, Any], str]:
    last_error: httpx.HTTPStatusError | None = None
    for path in _job_api_paths(job_api):
        try:
            return post_json(client, path, payload), path
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if job_api != "auto":
                raise
            log(f"{path} failed with HTTP {exc.response.status_code}; trying fallback")
    if last_error is not None:
        raise last_error
    raise RuntimeError("no crawl-job API paths configured")


def list_crawl_jobs(client: httpx.Client, *, job_api: str) -> list[dict[str, Any]]:
    last_error: httpx.HTTPStatusError | None = None
    for path in _job_api_paths(job_api):
        try:
            jobs = get_json(client, path, limit=200, offset=0)
            if isinstance(jobs, dict) and "value" in jobs:
                jobs = jobs["value"]
            if not isinstance(jobs, list):
                raise ValueError(f"unexpected crawl-job response from {path}")
            return jobs
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if job_api != "auto":
                raise
            log(f"{path} failed with HTTP {exc.response.status_code}; trying fallback")
    if last_error is not None:
        raise last_error
    raise RuntimeError("no crawl-job API paths configured")


def existing_document_urls(client: httpx.Client) -> set[str]:
    urls: set[str] = set()
    offset = 0
    limit = 200
    while True:
        documents = get_json(
            client,
            "/api/knowledge/documents",
            source_type="webpage_verified",
            limit=limit,
            offset=offset,
        )
        for document in documents:
            url = document.get("canonical_url") or document.get("url")
            if url:
                urls.add(str(url))
        if len(documents) < limit:
            return urls
        offset += limit


def filter_sources(
    sources: list[dict[str, str]],
    *,
    include_competitors: list[str],
    exclude_competitors: list[str],
    existing_urls: set[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    include = {item.casefold() for item in include_competitors}
    exclude = {item.casefold() for item in exclude_competitors}
    selected: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for source in sources:
        competitor = source["competitor"].casefold()
        if include and competitor not in include:
            skipped.append({**source, "reason": "not in include filter"})
            continue
        if competitor in exclude:
            skipped.append({**source, "reason": "excluded competitor"})
            continue
        if source["url"] in existing_urls:
            skipped.append({**source, "reason": "already ingested"})
            continue
        selected.append(source)
    return selected, skipped


def limit_seed_sources(sources: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    if limit <= 0:
        return list(sources)
    return sources[: min(limit, len(sources))]


def wait_for_jobs(
    client: httpx.Client,
    job_ids: list[str],
    *,
    wait_seconds: int,
    job_api: str,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + wait_seconds
    latest: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        jobs = list_crawl_jobs(client, job_api=job_api)
        latest = [job for job in jobs if job.get("id") in job_ids]
        terminal_count = sum(1 for job in latest if job.get("status") in TERMINAL)
        if terminal_count == len(job_ids):
            return latest
        time.sleep(3)
    return latest


def main() -> int:
    args = parse_args()
    api_base = args.api_base.rstrip("/")
    created_jobs: list[str] = []
    verified: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    terminal_jobs: list[dict[str, Any]] = []
    pre_skipped: list[dict[str, str]] = []

    with httpx.Client(
        base_url=api_base,
        timeout=300.0,
        follow_redirects=True,
        trust_env=False,
    ) as api_client:
        selected = limit_seed_sources(SOURCES, args.limit)
        if args.discover_sitemaps:
            selected.extend(
                discover_sitemap_sources(
                    api_client,
                    args.discovered_limit,
                    per_competitor_limit=args.per_competitor_limit,
                )
            )
        existing_urls = set() if args.allow_existing else existing_document_urls(api_client)
        selected, pre_skipped = filter_sources(
            selected,
            include_competitors=args.include_competitor,
            exclude_competitors=args.exclude_competitor,
            existing_urls=existing_urls,
        )
        before_stats = get_json(api_client, "/api/knowledge/stats")
        for source in selected:
            ok, reason = verify_source(
                api_client,
                source,
                mode=args.verify_mode,
                timeout=args.verify_timeout,
            )
            if not ok:
                log(f"skip {source['url']}: {reason}")
                skipped.append({**source, "reason": reason})
                continue
            log(f"collect {source['competitor']} {source['dimension']}: {source['url']} ({reason})")
            job_payload = {
                "url": source["url"],
                "run_id": f"real-collect:{source['competitor']}:{source['dimension']}",
                "competitor": source["competitor"],
                "dimension": source["dimension"],
            }
            job, job_api_path = create_crawl_job(
                api_client,
                job_payload,
                job_api=args.job_api,
            )
            created_jobs.append(str(job["id"]))
            verified.append({
                **source,
                "verify": reason,
                "job_id": str(job["id"]),
                "job_api": job_api_path,
            })
            if len(created_jobs) % max(1, args.window) == 0:
                terminal_jobs.extend(
                    wait_for_jobs(
                        api_client,
                        created_jobs[-args.window :],
                        wait_seconds=args.wait_seconds,
                        job_api=args.job_api,
                    )
                )
        remaining = created_jobs[len(terminal_jobs) :]
        if remaining:
            terminal_jobs.extend(
                wait_for_jobs(
                    api_client,
                    remaining,
                    wait_seconds=args.wait_seconds,
                    job_api=args.job_api,
                )
            )
        after_stats = get_json(api_client, "/api/knowledge/stats")

    success_jobs = [job for job in terminal_jobs if job.get("status") == "success"]
    output = {
        "requested": len(selected),
        "verified": len(verified),
        "pre_skipped_count": len(pre_skipped),
        "pre_skipped_sample": pre_skipped[:20],
        "skipped": skipped,
        "jobs_created": len(created_jobs),
        "jobs_success": len(success_jobs),
        "jobs_failed": [
            {
                "url": job.get("url"),
                "competitor": job.get("competitor"),
                "dimension": job.get("dimension"),
                "error": job.get("error"),
            }
            for job in terminal_jobs
            if job.get("status") != "success"
        ],
        "before_stats": before_stats,
        "after_stats": after_stats,
        "docs_added": int(after_stats.get("doc_count") or 0)
        - int(before_stats.get("doc_count") or 0),
        "chunks_added": int(after_stats.get("chunk_count") or 0)
        - int(before_stats.get("chunk_count") or 0),
    }
    print_json(output)
    return 0 if success_jobs else 1


def print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        print(json.dumps(payload, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
