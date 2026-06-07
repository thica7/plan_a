#!/usr/bin/env python3
"""Seed demo crawl sources and knowledge data through the local REST API.

The script is idempotent for crawl sources: before creating a source, it lists
existing sources and skips one with the same topic dimension and source type.
Direct crawl jobs are also skipped when the same source run_id and URL already
exist. It assumes the backend is already running.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

TOPICS: list[dict[str, Any]] = [
    {"topic": "Notion", "competitors": ["Notion", "Coda", "Obsidian", "Anytype"]},
    {"topic": "Figma", "competitors": ["Figma", "Penpot", "Sketch", "Canva"]},
    {"topic": "Linear", "competitors": ["Linear", "Jira", "Shortcut", "Height"]},
    {
        "topic": "Vercel",
        "competitors": ["Vercel", "Netlify", "Cloudflare Pages", "Vercel competitors"],
    },
    {"topic": "Cursor", "competitors": ["Cursor", "Windsurf", "GitHub Copilot", "Codeium"]},
]

SOURCE_TYPES = [
    "web_search",
    "sitemap",
    "rss",
    "pricing",
    "official_docs",
    "changelog",
]

COMPETITOR_DOMAINS = {
    "Anytype": "anytype.io",
    "Canva": "canva.com",
    "Cloudflare Pages": "pages.cloudflare.com",
    "Coda": "coda.io",
    "Codeium": "codeium.com",
    "Cursor": "cursor.com",
    "Figma": "figma.com",
    "GitHub Copilot": "github.com",
    "Height": "height.app",
    "Jira": "atlassian.com",
    "Linear": "linear.app",
    "Netlify": "netlify.com",
    "Notion": "notion.com",
    "Obsidian": "obsidian.md",
    "Penpot": "penpot.app",
    "Shortcut": "shortcut.com",
    "Sketch": "sketch.com",
    "Vercel": "vercel.com",
    "Vercel competitors": "vercel.com",
    "Windsurf": "windsurf.com",
}

DOC_URLS = {
    "Anytype": "https://doc.anytype.io",
    "Cloudflare Pages": "https://developers.cloudflare.com/pages",
    "Cursor": "https://docs.cursor.com",
    "GitHub Copilot": "https://docs.github.com/en/copilot",
    "Linear": "https://linear.app/docs",
    "Netlify": "https://docs.netlify.com",
    "Notion": "https://www.notion.com/help",
    "Vercel": "https://vercel.com/docs",
    "Windsurf": "https://docs.windsurf.com",
}

PRICING_URLS = {
    "Cloudflare Pages": "https://pages.cloudflare.com",
    "GitHub Copilot": "https://github.com/features/copilot#pricing",
    "Jira": "https://www.atlassian.com/software/jira/pricing",
    "Notion": "https://www.notion.com/pricing",
}

CHANGELOG_URLS = {
    "Figma": "https://www.figma.com/release-notes",
    "GitHub Copilot": "https://github.blog/changelog/label/copilot",
    "Linear": "https://linear.app/changelog",
    "Vercel": "https://vercel.com/changelog",
}

EVAL_PATH = Path("eval/competitor-analysis-eval.jsonl")
TERMINAL_STATUSES = {"success", "completed", "failed", "cancelled"}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed demo KB data through the REST API.")
    parser.add_argument("--topics", type=int, default=5)
    parser.add_argument("--per-topic-sources", type=int, default=6)
    parser.add_argument("--wait-seconds", type=int, default=60)
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument("--api-base", default="http://localhost:8000")
    parser.add_argument("--ingest-mode", choices=["web", "api"], default="api")
    return parser.parse_args()


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[Any | None, bool]:
    for attempt in range(2):
        try:
            response = client.request(method, path, json=json_payload, params=params)
        except httpx.HTTPError as exc:
            log(f"{method} {path} failed: {exc}")
            if attempt == 0:
                time.sleep(2)
                continue
            time.sleep(1)
            return None, False

        if response.status_code >= 500 and attempt == 0:
            log(f"{method} {path} returned {response.status_code}; retrying once")
            time.sleep(2)
            continue

        if response.status_code >= 400:
            log(f"{method} {path} returned {response.status_code}: {response.text[:500]}")
            time.sleep(1)
            return None, False

        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        time.sleep(1)
        return data, True

    time.sleep(1)
    return None, False


def selected_topics(count: int) -> list[dict[str, Any]]:
    return TOPICS[: max(0, min(count, len(TOPICS)))]


def selected_source_types(count: int) -> list[str]:
    return SOURCE_TYPES[: max(0, min(count, len(SOURCE_TYPES)))]


def host_for(competitor: str) -> str:
    return COMPETITOR_DOMAINS.get(competitor, f"{competitor.lower().replace(' ', '')}.com")


def homepage_url(competitor: str) -> str:
    return f"https://{host_for(competitor)}"


def seed_url_for(competitor: str, source_type: str) -> str:
    home = homepage_url(competitor)
    if source_type == "pricing":
        return PRICING_URLS.get(competitor, f"{home}/pricing")
    if source_type == "official_docs":
        return DOC_URLS.get(competitor, f"{home}/docs")
    if source_type == "changelog":
        return CHANGELOG_URLS.get(competitor, f"{home}/changelog")
    if source_type == "rss":
        return f"{home}/blog"
    return home


def source_payload(topic_entry: dict[str, Any], source_type: str, competitor: str) -> dict[str, Any]:
    topic = str(topic_entry["topic"])
    host = host_for(competitor)
    domains = [host_for(item) for item in topic_entry["competitors"]]
    base_config: dict[str, Any] = {
        "competitor": competitor,
        "seed_topic": topic,
        "seed_competitors": topic_entry["competitors"],
        "max_urls": 8,
    }

    if source_type == "web_search":
        config = {
            **base_config,
            "query": f"{competitor} {topic} pricing plans features 2026",
        }
    elif source_type == "sitemap":
        config = {**base_config, "url": f"https://{host}/sitemap.xml"}
    elif source_type == "rss":
        config = {**base_config, "url": f"https://{host}/blog/rss.xml"}
    elif source_type == "pricing":
        config = {
            **base_config,
            "query": f"{competitor} pricing tiers",
            "url_patterns": ["/pricing", "/plans"],
            "include_domains": domains,
        }
    elif source_type == "official_docs":
        config = {
            **base_config,
            "query": f"{competitor} documentation API",
            "include_domains": domains,
        }
    elif source_type == "changelog":
        config = {
            **base_config,
            "query": f"{competitor} changelog release notes",
            "include_domains": domains,
        }
    else:
        config = base_config

    return {
        "type": source_type,
        "competitor": competitor,
        "dimension": topic,
        "priority": 100,
        "config": config,
    }


def list_sources(client: httpx.Client) -> tuple[list[dict[str, Any]], bool]:
    data, ok = request_json(client, "GET", "/api/crawl/sources")
    return (data if isinstance(data, list) else []), ok


def find_existing_source(
    sources: list[dict[str, Any]],
    *,
    topic: str,
    source_type: str,
) -> dict[str, Any] | None:
    for source in sources:
        if source.get("dimension") == topic and source.get("type") == source_type:
            return source
    return None


def create_or_reuse_source(
    client: httpx.Client,
    sources: list[dict[str, Any]],
    topic_entry: dict[str, Any],
    source_type: str,
    competitor: str,
) -> tuple[dict[str, Any] | None, bool, bool]:
    topic = str(topic_entry["topic"])
    existing = find_existing_source(sources, topic=topic, source_type=source_type)
    if existing:
        log(f"[{topic}] reuse source {source_type}: {existing.get('id')}")
        return existing, True, True

    payload = source_payload(topic_entry, source_type, competitor)
    log(f"[{topic}] create source {source_type} for {competitor}")
    data, ok = request_json(client, "POST", "/api/crawl/sources", json_payload=payload)
    if not ok or not isinstance(data, dict):
        return None, False, False
    source = data.get("source")
    if not isinstance(source, dict):
        log(f"[{topic}] source response missing source object for {source_type}")
        return None, False, False
    sources.append(source)
    return source, True, False


def list_all_jobs(client: httpx.Client) -> tuple[list[dict[str, Any]], bool]:
    jobs: list[dict[str, Any]] = []
    ok_all = True
    offset = 0
    limit = 200
    while True:
        data, ok = request_json(
            client,
            "GET",
            "/api/crawl/jobs",
            params={"limit": limit, "offset": offset},
        )
        ok_all = ok_all and ok
        if not ok or not isinstance(data, list):
            break
        jobs.extend(data)
        if len(data) < limit:
            break
        offset += limit
    return jobs, ok_all


def find_existing_job(
    jobs: list[dict[str, Any]],
    *,
    run_id: str,
    url: str,
) -> dict[str, Any] | None:
    for job in jobs:
        if (
            job.get("run_id") == run_id
            and job.get("url") == url
            and job.get("status") not in {"failed", "cancelled"}
        ):
            return job
    return None


def create_or_reuse_job(
    client: httpx.Client,
    jobs: list[dict[str, Any]],
    *,
    source: dict[str, Any],
    topic: str,
    competitor: str,
    source_type: str,
) -> tuple[dict[str, Any] | None, bool, bool]:
    source_id = str(source["id"])
    url = seed_url_for(competitor, source_type)
    existing = find_existing_job(jobs, run_id=source_id, url=url)
    if existing:
        log(f"[{topic}] reuse crawl job {source_type}: {existing.get('id')}")
        return existing, True, True

    payload = {
        "url": url,
        "run_id": source_id,
        "competitor": competitor,
        "dimension": topic,
    }
    log(f"[{topic}] create crawl job {source_type}: {url}")
    data, ok = request_json(client, "POST", "/api/crawl/jobs", json_payload=payload)
    if ok and isinstance(data, dict):
        jobs.append(data)
        return data, True, False
    return None, False, False


def wait_for_jobs(
    client: httpx.Client,
    *,
    job_ids: set[str],
    wait_seconds: int,
    topic: str,
) -> tuple[list[dict[str, Any]], bool]:
    if not job_ids:
        return [], True

    deadline = time.monotonic() + max(0, wait_seconds)
    latest: list[dict[str, Any]] = []
    ok_all = True
    while True:
        jobs, ok = list_all_jobs(client)
        ok_all = ok_all and ok
        latest = [job for job in jobs if job.get("id") in job_ids]
        terminal = [job for job in latest if str(job.get("status")) in TERMINAL_STATUSES]
        log(f"[{topic}] crawl jobs terminal {len(terminal)}/{len(job_ids)}")
        if len(terminal) == len(job_ids) or time.monotonic() >= deadline:
            return latest, ok_all
        time.sleep(min(5, max(0, deadline - time.monotonic())))


def batch_ingest_from_jobs(
    client: httpx.Client,
    *,
    jobs: list[dict[str, Any]],
    topic: str,
) -> tuple[dict[str, Any], bool]:
    items: list[dict[str, Any]] = []
    for job in jobs:
        metadata = job.get("result_metadata")
        if not isinstance(metadata, dict):
            continue
        page = metadata.get("page") or metadata.get("parsed_page") or {}
        if not isinstance(page, dict):
            page = {}
        text = page.get("text") or metadata.get("text")
        if not isinstance(text, str) or not text.strip():
            text = fallback_text_for_job(job, topic=topic)
        if not isinstance(text, str) or not text.strip():
            continue
        title = page.get("title") or job.get("url") or f"{topic} crawl result"
        items.append({
            "source": "text",
            "text": text,
            "title": str(title),
            "crawl_run_id": job.get("run_id"),
        })

    if not items:
        return {"accepted": 0, "job_id": None, "status": "skipped_no_parsed_text"}, True

    log(f"[{topic}] batch ingest {len(items)} parsed crawl pages")
    data, ok = request_json(
        client,
        "POST",
        "/api/knowledge/batch",
        json_payload={
            "items": items,
            "options": {"max_concurrent": 4, "fail_fast": False},
        },
    )
    if not ok or not isinstance(data, dict):
        return {"accepted": 0, "job_id": None, "status": "failed"}, False

    ingest_job_id = data.get("job_id")
    if not ingest_job_id:
        return data, True

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        detail, detail_ok = request_json(
            client,
            "GET",
            f"/api/knowledge/ingest-jobs/{ingest_job_id}",
        )
        if not detail_ok or not isinstance(detail, dict):
            return data, False
        if detail.get("status") in {"success", "failed"}:
            data["ingest_detail"] = detail
            return data, detail.get("status") == "success"
        time.sleep(2)
    data["status"] = "timeout"
    return data, False


def fallback_text_for_job(job: dict[str, Any], *, topic: str) -> str:
    """Generate deterministic demo KB text when live crawling cannot return content."""
    competitor = str(job.get("competitor") or "Unknown competitor")
    url = str(job.get("url") or "")
    dimension = str(job.get("dimension") or topic)
    status = str(job.get("status") or "unknown")
    error = str(job.get("error") or "no parsed page text")
    return "\n\n".join([
        f"{competitor} competitive intelligence seed for {dimension}.",
        (
            f"Source URL: {url}. Crawl status: {status}. "
            f"Fallback reason: {error[:160]}."
        ),
        (
            f"Pricing signals for {competitor}: entry-level plan, free trial, "
            "annual discount, per-seat billing, enterprise tier, usage limits, "
            "overage fees, and add-on packaging should be checked during analysis."
        ),
        (
            f"Feature signals for {competitor}: SSO/SAML, audit log, API access, "
            "webhooks, AI automation, integrations, RBAC, reporting, and data "
            "residency are relevant comparison dimensions."
        ),
        (
            f"User review signals for {competitor}: onboarding quality, support "
            "responsiveness, ease of use, reliability, migration effort, pricing "
            "fairness, missing integrations, and roadmap sentiment are useful "
            "for competitive positioning."
        ),
    ])


def get_stats(client: httpx.Client) -> tuple[dict[str, Any], bool]:
    data, ok = request_json(client, "GET", "/api/knowledge/stats")
    return (data if isinstance(data, dict) else {}), ok


def load_eval_labels() -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    if not EVAL_PATH.exists():
        log(f"eval file not found: {EVAL_PATH}")
        return labels

    with EVAL_PATH.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                log(f"skip invalid eval line {line_no}: {exc}")
                continue
            labels.append({
                "query": raw.get("query", ""),
                "relevant_doc_ids": raw.get("relevant_doc_ids", []),
                "relevant_chunk_ids": raw.get("relevant_chunk_ids", []),
            })
    return [label for label in labels if label["query"]]


def run_eval(client: httpx.Client, *, skip_eval: bool) -> tuple[dict[str, Any] | None, bool]:
    if skip_eval:
        return None, True
    labels = load_eval_labels()
    if not labels:
        return None, False
    log(f"running eval with {len(labels)} labels")
    data, ok = request_json(
        client,
        "POST",
        "/api/knowledge/eval",
        json_payload={"labels": labels, "top_k": 10},
    )
    return (data if isinstance(data, dict) else None), ok


def process_topic(
    client: httpx.Client,
    topic_entry: dict[str, Any],
    *,
    source_types: list[str],
    wait_seconds: int,
) -> tuple[dict[str, Any], bool]:
    topic = str(topic_entry["topic"])
    competitors = list(topic_entry["competitors"])
    topic_summary: dict[str, Any] = {
        "topic": topic,
        "sources_created": 0,
        "sources_reused": 0,
        "source_failures": 0,
        "jobs_created": 0,
        "jobs_reused": 0,
        "job_failures": 0,
        "job_ids": [],
    }
    partial_failure = False

    sources, ok = list_sources(client)
    partial_failure = partial_failure or not ok
    jobs, ok = list_all_jobs(client)
    partial_failure = partial_failure or not ok

    for index, source_type in enumerate(source_types):
        competitor = competitors[index % len(competitors)]
        source, ok, reused = create_or_reuse_source(
            client,
            sources,
            topic_entry,
            source_type,
            competitor,
        )
        if not ok or source is None:
            topic_summary["source_failures"] += 1
            partial_failure = True
            continue
        topic_summary["sources_reused" if reused else "sources_created"] += 1

        job, ok, reused = create_or_reuse_job(
            client,
            jobs,
            source=source,
            topic=topic,
            competitor=competitor,
            source_type=source_type,
        )
        if not ok or job is None:
            topic_summary["job_failures"] += 1
            partial_failure = True
            continue
        topic_summary["jobs_reused" if reused else "jobs_created"] += 1
        topic_summary["job_ids"].append(job.get("id"))

    final_jobs, ok = wait_for_jobs(
        client,
        job_ids={str(job_id) for job_id in topic_summary["job_ids"] if job_id},
        wait_seconds=wait_seconds,
        topic=topic,
    )
    partial_failure = partial_failure or not ok
    topic_summary["job_statuses"] = {
        str(job.get("id")): job.get("status") for job in final_jobs if job.get("id")
    }
    batch_summary, ok = batch_ingest_from_jobs(client, jobs=final_jobs, topic=topic)
    topic_summary["batch_ingest"] = batch_summary
    partial_failure = partial_failure or not ok
    topic_summary["ingested_document_ids"] = [
        job.get("result_metadata", {}).get("document_id")
        for job in final_jobs
        if isinstance(job.get("result_metadata"), dict)
        and job.get("result_metadata", {}).get("document_id")
    ]
    return topic_summary, partial_failure


def main() -> int:
    args = parse_args()
    api_base = args.api_base.rstrip("/")
    if args.ingest_mode == "web":
        log("web ingest mode requested; current REST API has no render flag, using API mode")

    source_types = selected_source_types(args.per_topic_sources)
    topics = selected_topics(args.topics)
    partial_failure = False
    topic_summaries: list[dict[str, Any]] = []

    with httpx.Client(base_url=api_base, timeout=300.0, follow_redirects=True) as client:
        before_stats, ok = get_stats(client)
        partial_failure = partial_failure or not ok

        for topic_entry in topics:
            log(f"seeding topic {topic_entry['topic']}")
            summary, failed = process_topic(
                client,
                topic_entry,
                source_types=source_types,
                wait_seconds=args.wait_seconds,
            )
            topic_summaries.append(summary)
            partial_failure = partial_failure or failed

        after_stats, ok = get_stats(client)
        partial_failure = partial_failure or not ok
        eval_result, ok = run_eval(client, skip_eval=args.skip_eval)
        partial_failure = partial_failure or not ok

    before_docs = int(before_stats.get("doc_count") or 0)
    before_chunks = int(before_stats.get("chunk_count") or 0)
    after_docs = int(after_stats.get("doc_count") or 0)
    after_chunks = int(after_stats.get("chunk_count") or 0)
    metrics = (eval_result or {}).get("metrics") or {}
    summary_text = (
        f"Seeded {max(0, after_docs - before_docs)} docs, "
        f"{max(0, after_chunks - before_chunks)} chunks across {len(topics)} topics. "
        f"Eval score: recall@10={metrics.get('recall@10')}, MRR={metrics.get('mrr')}"
    )
    output = {
        "summary": summary_text,
        "api_base": api_base,
        "topics_requested": len(topics),
        "source_types": source_types,
        "seeded_docs": max(0, after_docs - before_docs),
        "seeded_chunks": max(0, after_chunks - before_chunks),
        "before_stats": before_stats,
        "after_stats": after_stats,
        "eval": eval_result,
        "topics": topic_summaries,
        "partial_failure": partial_failure,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if partial_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
