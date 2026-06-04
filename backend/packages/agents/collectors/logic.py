from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from packages.agents import SubagentContext
from packages.agents.collectors.skill_tools import collect_competitor_with_skill_tools
from packages.identity import compute_raw_source_id
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    RawSource,
)
from packages.search import SearchResult
from packages.tools import (
    extract_facts,
    fetch_page,
    find_official_docs,
    search_review_site_queries,
    survey_simulator,
)

CORE_SCHEMA_DIMENSIONS = ("pricing", "feature", "persona")

KNOWN_OFFICIAL_SOURCE_HINTS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "cursor": {
        "pricing": [("Cursor official pricing", "https://cursor.com/pricing")],
        "feature": [("Cursor official features", "https://www.cursor.com/features")],
        "persona": [("Cursor official product page", "https://cursor.com")],
        "security": [("Cursor official security", "https://cursor.com/security")],
    },
    "githubcopilot": {
        "feature": [
            (
                "GitHub Copilot official feature docs",
                "https://docs.github.com/en/copilot/get-started/features",
            ),
            (
                "GitHub Copilot official product page",
                "https://github.com/features/copilot",
            ),
        ],
        "pricing": [
            (
                "GitHub Copilot official plans and pricing",
                "https://github.com/features/copilot/plans",
            )
        ],
        "persona": [
            (
                "GitHub Copilot official product page",
                "https://github.com/features/copilot",
            )
        ],
        "security": [
            (
                "GitHub Copilot enterprise approval resources",
                "https://docs.github.com/en/enterprise-cloud@latest/copilot/tutorials/roll-out-at-scale/govern-at-scale/resources-for-approval",
            ),
            (
                "GitHub Copilot compliance changelog",
                "https://github.blog/changelog/2024-06-03-github-copilot-compliance-soc-2-type-1-report-and-iso-iec-270012013-certification-scope/",
            ),
        ],
    },
    "windsurf": {
        "pricing": [
            (
                "Windsurf official plans and usage",
                "https://docs.windsurf.com/windsurf/accounts/usage",
            )
        ],
        "feature": [
            (
                "Windsurf official Cascade docs",
                "https://docs.windsurf.com/plugins/cascade/cascade-overview",
            ),
            (
                "Windsurf official plugin docs",
                "https://docs.windsurf.com/plugins",
            ),
        ],
        "persona": [
            (
                "Windsurf official getting started docs",
                "https://docs.windsurf.com/windsurf/getting-started",
            ),
        ],
        "security": [
            ("Windsurf official trust page", "https://windsurf.com/trust"),
            ("Windsurf official compliance page", "https://windsurf.com/compliance"),
        ],
    },
    "claudecode": {
        "feature": [
            (
                "Claude Code official product page",
                "https://www.anthropic.com/product/claude-code",
            ),
            (
                "Claude Code official overview docs",
                "https://docs.anthropic.com/en/docs/claude-code/overview",
            ),
        ],
        "pricing": [
            (
                "Claude Code cost management docs",
                "https://code.claude.com/docs/en/costs",
            ),
            ("Claude official pricing", "https://claude.com/pricing"),
        ],
        "persona": [
            (
                "Claude Code official product page",
                "https://www.anthropic.com/product/claude-code",
            )
        ],
        "security": [
            (
                "Claude Code official security docs",
                "https://docs.claude.com/en/docs/claude-code/security",
            )
        ],
    },
}

PRODUCT_IDENTITY_HINTS: dict[str, tuple[str, ...]] = {
    "cursor": (
        "cursor.com",
        "cursor ai",
        "ai code editor",
        "code editor",
        "coding agent",
        "composer",
    ),
    "githubcopilot": (
        "github.com/features/copilot",
        "docs.github.com/en/copilot",
        "github copilot",
        "copilot",
    ),
    "windsurf": (
        "windsurf.com",
        "docs.windsurf.com",
        "docs.devin.ai/desktop",
        "windsurf",
        "codeium",
        "ai code editor",
    ),
    "claudecode": (
        "claude-code",
        "claude code",
        "code.claude.com",
        "anthropic.com/product/claude-code",
    ),
}

PRODUCT_CONFUSION_TERMS: dict[str, tuple[str, ...]] = {
    "cursor": (
        "cursor extractor",
        "database cursor",
        "pagination cursor",
        "sql cursor",
        "css cursor",
        "mouse cursor",
    ),
    "windsurf": (
        "devin.ai",
        "devin desktop",
        "cognition devin",
    ),
    "claudecode": ("generic claude",),
}

USER_RESEARCH_SOURCE_TYPES = {
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
}

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


class CollectorAgentMixin:
    async def _run_collector_react(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
    ) -> int:
        detail = record.detail
        skill = self._skill_registry.get(dimension)
        observations: list[dict[str, object]] = []
        fetched_by_url: dict[str, Any] = {}
        added = 0
        max_turns = self._collector_task_max_turns(detail.plan, dimension)
        for turn in range(1, max_turns + 1):
            payload = await self._trace_llm_json(
                record,
                agent="collector",
                subagent=dimension,
                name=f"{dimension}_react_turn_{turn}",
                system=(
                    "You are a bounded collector ReAct runner. Decide exactly one next action. "
                    "Allowed actions are web_search, fetch_page, finish. "
                    "Use web_search to find evidence, fetch_page to inspect promising URLs, "
                    "and finish only when you can output structured sources."
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Dimension: {dimension}\n"
                    f"Dimension description: {skill.description if skill else dimension}\n"
                    f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Observations JSON: {json.dumps(observations, ensure_ascii=False)}\n\n"
                    "Return one action. For finish, include sources with competitor, "
                    "title, url, summary, confidence."
                ),
                schema_hint=(
                    '{"action":"web_search|fetch_page|finish","query":"query or null",'
                    '"url":"https://... or null","rationale":"short reason",'
                    '"sources":[{"competitor":"name","title":"title","url":"https://... or null",'
                    '"summary":"summary","confidence":0.0}]}'
                ),
                context=context,
            )
            action = str(payload.get("action") or "").strip().lower()
            if action == "web_search":
                query = str(
                    payload.get("query")
                    or self._web_search_query(detail, detail.plan.competitors[0], dimension)
                )
                results = await self._trace_search(
                    record,
                    agent="collector",
                    subagent=dimension,
                    query=query,
                    max_results=3,
                    context=context,
                )
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "query": query,
                        "results": [result.__dict__ for result in results[:3]],
                    }
                )
                continue
            if action == "fetch_page":
                url = str(payload.get("url") or "")
                if not url.startswith(("http://", "https://")):
                    observations.append(
                        {"turn": turn, "action": action, "error": "invalid_url", "url": url}
                    )
                    continue
                fetched = await self._trace_fetch(record, "collector", dimension, url, context)
                fetched_by_url[fetched.url] = fetched
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "url": fetched.url,
                        "ok": fetched.ok,
                        "title": fetched.title,
                        "snippet": fetched.snippet,
                        "content_hash": fetched.content_hash,
                    }
                )
                continue
            if action == "finish":
                sources = await self._sources_from_react_finish(
                    record,
                    detail,
                    dimension,
                    payload,
                    context,
                    fetched_by_url,
                )
                detail.raw_sources.extend(sources)
                added += len(sources)
                break
            observations.append(
                {"turn": turn, "action": action or "unknown", "error": "unsupported_action"}
            )
        return added

    async def _run_collector_competitor_react(
        self,
        record: RunRecord,
        dimension: str,
        competitor: str,
        context: SubagentContext,
    ) -> list[RawSource]:
        detail = record.detail
        skill = self._skill_registry.get(dimension)
        observations: list[dict[str, object]] = []
        fetched_by_url: dict[str, Any] = {}
        qa_feedback = self._qa_feedback_for_branch(detail, "collector", dimension, competitor)
        max_turns = self._collector_task_max_turns(detail.plan, dimension, competitor)
        for turn in range(1, max_turns + 1):
            payload = await self._trace_llm_json(
                record,
                agent="collector",
                subagent=context.subagent,
                name=f"{dimension}_{self._issue_id_fragment(competitor)}_collector_react_turn_{turn}",
                system=(
                    "You are a bounded collector ReAct runner for exactly one competitor "
                    "and one dimension. "
                    "Allowed actions are web_search, robots_check, fetch_page, find_official_docs, "
                    "search_review_site, survey_simulator, finish. "
                    "Use search/fetch evidence before finish. Return only sources for "
                    "the assigned competitor."
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Competitor: {competitor}\n"
                    f"Dimension: {dimension}\n"
                    f"Dimension description: {skill.description if skill else dimension}\n"
                    f"Homepage hint: {detail.plan.homepage_hints.get(competitor, '')}\n"
                    f"QA feedback for redo: {json.dumps(qa_feedback, ensure_ascii=False)}\n"
                    f"Observations JSON: {json.dumps(observations, ensure_ascii=False)}\n\n"
                    "Return one action. For finish, include sources with title, url, "
                    "summary, confidence."
                ),
                schema_hint=(
                    '{"action":"web_search|robots_check|fetch_page|find_official_docs|'
                    'search_review_site|survey_simulator|finish","query":"query or null",'
                    '"url":"https://... or null","rationale":"short reason",'
                    '"sources":[{"title":"title","url":"https://... or null",'
                    '"summary":"summary","confidence":0.0}]}'
                ),
                context=context,
            )
            action = str(payload.get("action") or "").strip().lower()
            if action == "web_search":
                query = str(
                    payload.get("query") or self._web_search_query(detail, competitor, dimension)
                )
                results = await self._trace_search(
                    record,
                    agent="collector",
                    subagent=context.subagent,
                    query=query,
                    max_results=3,
                    context=context,
                )
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "query": query,
                        "results": [result.__dict__ for result in results[:3]],
                    }
                )
                continue
            if action == "robots_check":
                url = str(payload.get("url") or detail.plan.homepage_hints.get(competitor) or "")
                if not url.startswith(("http://", "https://")):
                    observations.append(
                        {"turn": turn, "action": action, "error": "invalid_url", "url": url}
                    )
                    continue
                check = await self._trace_robots(
                    record, "collector", context.subagent, url, context
                )
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "url": url,
                        "allowed": check.allowed,
                        "checked": check.checked,
                        "robots_url": check.robots_url,
                    }
                )
                continue
            if action == "fetch_page":
                url = str(payload.get("url") or "")
                if not url.startswith(("http://", "https://")):
                    observations.append(
                        {"turn": turn, "action": action, "error": "invalid_url", "url": url}
                    )
                    continue
                fetched = await self._trace_fetch(
                    record, "collector", context.subagent, url, context
                )
                fetched_by_url[fetched.url] = fetched
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "url": fetched.url,
                        "ok": fetched.ok,
                        "title": fetched.title,
                        "snippet": fetched.snippet,
                        "content_hash": fetched.content_hash,
                    }
                )
                continue
            if action == "find_official_docs":
                candidates = find_official_docs(
                    competitor=competitor,
                    dimension=dimension,
                    homepage_hint=detail.plan.homepage_hints.get(competitor),
                )
                self._trace_local_tool(
                    record,
                    agent="collector",
                    subagent=context.subagent,
                    name="find_official_docs",
                    input_text=json.dumps(
                        {
                            "competitor": competitor,
                            "dimension": dimension,
                            "homepage_hint": detail.plan.homepage_hints.get(competitor),
                        },
                        ensure_ascii=False,
                    ),
                    output_text=json.dumps(
                        [candidate.__dict__ for candidate in candidates], ensure_ascii=False
                    ),
                    context=context,
                    metadata={"candidate_count": len(candidates)},
                )
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "candidates": [candidate.__dict__ for candidate in candidates[:4]],
                    }
                )
                continue
            if action == "search_review_site":
                plan = search_review_site_queries(competitor=competitor, topic=detail.topic)
                self._trace_local_tool(
                    record,
                    agent="collector",
                    subagent=context.subagent,
                    name="search_review_site",
                    input_text=json.dumps(
                        {"competitor": competitor, "topic": detail.topic}, ensure_ascii=False
                    ),
                    output_text=json.dumps(plan.__dict__, ensure_ascii=False),
                    context=context,
                    metadata={"query_count": len(plan.queries)},
                )
                observations.append({"turn": turn, "action": action, "queries": plan.queries})
                continue
            if action == "survey_simulator":
                records = survey_simulator(
                    topic=detail.topic,
                    competitor=competitor,
                    dimension=dimension,
                    qa_feedback=qa_feedback,
                )
                self._trace_local_tool(
                    record,
                    agent="collector",
                    subagent=context.subagent,
                    name="survey_simulator",
                    input_text=json.dumps(
                        {"topic": detail.topic, "competitor": competitor, "dimension": dimension},
                        ensure_ascii=False,
                    ),
                    output_text=json.dumps([item.__dict__ for item in records], ensure_ascii=False),
                    context=context,
                    metadata={"record_count": len(records)},
                )
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "records": [item.__dict__ for item in records],
                    }
                )
                continue
            if action == "finish":
                return await self._sources_from_react_finish(
                    record,
                    detail,
                    dimension,
                    {
                        **payload,
                        "sources": self._force_source_competitor(
                            payload.get("sources"), competitor
                        ),
                    },
                    context,
                    fetched_by_url,
                )
            observations.append(
                {"turn": turn, "action": action or "unknown", "error": "unsupported_action"}
            )
        return []

    def _force_source_competitor(
        self, raw_sources: object, competitor: str
    ) -> list[dict[str, object]]:
        if not isinstance(raw_sources, list):
            return []
        sources: list[dict[str, object]] = []
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized["competitor"] = competitor
            sources.append(normalized)
        return sources

    async def _sources_from_react_finish(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        payload: dict[str, Any],
        context: SubagentContext,
        fetched_by_url: dict[str, Any],
    ) -> list[RawSource]:
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list):
            return []
        sources: list[RawSource] = []
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            competitor = str(item.get("competitor") or detail.plan.competitors[0])
            title = str(item.get("title") or f"{competitor} {dimension} evidence")
            summary = str(item.get("summary") or title)
            url_value = item.get("url")
            if not isinstance(url_value, str) or not url_value.startswith(("http://", "https://")):
                url_value = None
            content_basis = f"{competitor}:{dimension}:{title}:{url_value or ''}:{summary}"
            fetched = None
            if url_value:
                fetched = fetched_by_url.get(url_value)
                if fetched is None:
                    fetched = await self._trace_fetch(
                        record, "collector", context.subagent, url_value, context
                    )
                    fetched_by_url[fetched.url] = fetched
            verified = fetched is not None and fetched.ok
            extracted_facts = []
            if verified:
                extracted_facts = extract_facts(
                    fetched.text,
                    dimension=dimension,
                    source_id=None,
                    max_facts=3,
                )
                self._trace_local_tool(
                    record,
                    agent="collector",
                    subagent=context.subagent,
                    name="extract_facts",
                    input_text=json.dumps(
                        {"dimension": dimension, "url": fetched.url, "text": fetched.snippet},
                        ensure_ascii=False,
                    ),
                    output_text=json.dumps(
                        [fact.__dict__ for fact in extracted_facts], ensure_ascii=False
                    ),
                    context=context,
                    metadata={"fact_count": len(extracted_facts), "url": fetched.url},
                )
            source_type = (
                "webpage_verified"
                if verified
                else "web_search_result"
                if url_value
                else "llm_public_knowledge"
            )
            source_title = fetched.title if verified and fetched.title else title
            source_url = fetched.url if fetched is not None else url_value
            snippet = (
                (
                    " ".join(fact.fact for fact in extracted_facts[:2])
                    if extracted_facts
                    else fetched.snippet
                )
                if verified
                else summary
            )
            content_hash = (
                fetched.content_hash
                if fetched is not None
                else hashlib.sha256(content_basis.encode()).hexdigest()[:16]
            )
            sources.append(
                source := RawSource(
                    id=compute_raw_source_id(
                        source_type=source_type,
                        competitor=competitor,
                        dimension=dimension,
                        url=source_url,
                        content_hash=content_hash,
                        title=source_title,
                        snippet=snippet,
                        run_id=detail.id,
                    ),
                    competitor=competitor,
                    dimension=dimension,
                    source_type=source_type,
                    title=source_title,
                    url=source_url,
                    snippet=snippet,
                    content_hash=content_hash,
                    confidence=(
                        min(
                            1.0, self._coerce_confidence(item.get("confidence"), default=0.7) + 0.03
                        )
                        if verified
                        else self._coerce_confidence(item.get("confidence"), default=0.7)
                    ),
                )
            )
            if not self._source_is_usable(source):
                sources.pop()
        return sources

    async def _collect_with_web_search(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
    ) -> int:
        detail = record.detail
        skill = self._skill_registry.get(dimension)
        added = 0
        for competitor in detail.plan.competitors:
            query = self._web_search_query(detail, competitor, dimension)
            competitor_added = 0
            results = await self._trace_search(
                record,
                agent="collector",
                subagent=dimension,
                query=query,
                max_results=3,
                context=context,
            )
            for result in self._rank_search_results(detail, competitor, dimension, results):
                source = await self._source_from_search_result(
                    detail,
                    competitor,
                    dimension,
                    result,
                    record,
                    context,
                )
                if source is None:
                    continue
                detail.raw_sources.append(source)
                added += 1
                competitor_added += 1
                break
            if competitor_added == 0 and skill is not None:
                fallback_query = f"{competitor} {skill.description}"
                results = await self._trace_search(
                    record,
                    agent="collector",
                    subagent=dimension,
                    query=fallback_query,
                    max_results=3,
                    context=context,
                )
                for result in self._rank_search_results(detail, competitor, dimension, results):
                    source = await self._source_from_search_result(
                        detail,
                        competitor,
                        dimension,
                        result,
                        record,
                        context,
                    )
                    if source is None:
                        continue
                    detail.raw_sources.append(source)
                    added += 1
                    competitor_added += 1
                    break
        return added

    async def _collect_competitor_with_web_search(
        self,
        record: RunRecord,
        dimension: str,
        competitor: str,
        context: SubagentContext,
    ) -> list[RawSource]:
        detail = record.detail
        skill = self._skill_registry.get(dimension)
        if self._should_collect_official_first(dimension):
            official_sources = await self._collect_official_sources(
                record,
                detail,
                dimension,
                competitor,
                context,
            )
            if official_sources:
                return official_sources
        queries = [self._web_search_query(detail, competitor, dimension)]
        if skill is not None:
            queries.append(f"{competitor} {skill.description}")
        for query in queries:
            results = await self._trace_search(
                record,
                agent="collector",
                subagent=context.subagent,
                query=query,
                max_results=3,
                context=context,
            )
            for result in self._rank_search_results(detail, competitor, dimension, results):
                source = await self._source_from_search_result(
                    detail,
                    competitor,
                    dimension,
                    result,
                    record,
                    context,
                )
                if source is not None:
                    return [source]
        return []

    async def _collect_official_sources(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
    ) -> list[RawSource]:
        sources: list[RawSource] = []
        for candidate in self._official_source_candidates(detail, competitor, dimension):
            source = await self._source_from_search_result(
                detail,
                competitor,
                dimension,
                candidate,
                record,
                context,
            )
            if source is None:
                continue
            sources.append(source)
            break
        if sources:
            self._trace_local_tool(
                record,
                agent="collector",
                subagent=context.subagent,
                name="official_source_registry",
                input_text=json.dumps(
                    {
                        "competitor": competitor,
                        "dimension": dimension,
                        "homepage_hint": detail.plan.homepage_hints.get(competitor),
                    },
                    ensure_ascii=False,
                ),
                output_text=json.dumps(
                    [source.model_dump(mode="json") for source in sources],
                    ensure_ascii=False,
                ),
                context=context,
                metadata={"source_count": len(sources)},
            )
        return sources

    def _official_source_candidates(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> list[SearchResult]:
        normalized_competitor = self._official_registry_key(competitor)
        normalized_dimension = self._official_dimension_key(dimension)
        raw_candidates: list[tuple[str, str, str]] = []
        for title, url in KNOWN_OFFICIAL_SOURCE_HINTS.get(normalized_competitor, {}).get(
            normalized_dimension, []
        ):
            raw_candidates.append((title, url, "Curated official source registry entry."))
        for candidate in find_official_docs(
            competitor=competitor,
            dimension=dimension,
            homepage_hint=detail.plan.homepage_hints.get(competitor),
        ):
            raw_candidates.append((candidate.title, candidate.url, candidate.rationale))

        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for title, url, snippet in raw_candidates:
            normalized_url = url.rstrip("/")
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            results.append(SearchResult(title=title, url=url, snippet=snippet))
        return results

    def _should_collect_official_first(self, dimension: str) -> bool:
        key = dimension.casefold()
        return any(
            token in key
            for token in (
                "pricing",
                "security",
                "compliance",
                "trust",
                "feature",
                "persona",
                "user",
                "customer",
                "buyer",
            )
        )

    async def _collect_competitor_with_skill_tools(
        self,
        record: RunRecord,
        dimension: str,
        competitor: str,
        context: SubagentContext,
        qa_feedback: list[dict[str, object]],
    ) -> list[RawSource]:
        return await collect_competitor_with_skill_tools(
            self,
            record,
            dimension=dimension,
            competitor=competitor,
            context=context,
            qa_feedback=qa_feedback,
        )

    def _web_search_query(self, detail: RunDetail, competitor: str, dimension: str) -> str:
        skill = self._skill_registry.get(dimension)
        if skill and skill.query_templates:
            template = skill.query_templates[0]
            query = template.format(competitor=competitor)
        else:
            query = f"{competitor} {dimension}"
        qualifier = self._competitor_search_qualifier(competitor)
        if qualifier and qualifier.casefold() not in query.casefold():
            query = f"{query} {qualifier}"
        return f"{query} {detail.topic} official source"

    def _rank_search_results(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        homepage_host = self._host(detail.plan.homepage_hints.get(competitor, ""))
        competitor_terms = [
            term for term in re.split(r"[^a-z0-9]+", competitor.casefold()) if len(term) >= 3
        ]
        dimension_terms = self._dimension_source_terms(dimension)

        def score(result: SearchResult) -> tuple[int, str]:
            url = result.url.casefold()
            host = self._host(result.url)
            haystack = f"{result.title} {result.url} {result.snippet}".casefold()
            value = 0
            if homepage_host and (host == homepage_host or host.endswith(f".{homepage_host}")):
                value += 100
            if any(term in host for term in competitor_terms):
                value += 35
            if any(term in haystack for term in dimension_terms):
                value += 20
            if any(token in host for token in ("docs.", "developer.", "help.", "trust.")):
                value += 12
            if any(token in url for token in ("/pricing", "/security", "/trust", "/docs")):
                value += 12
            if host in {"medium.com", "www.medium.com", "reddit.com", "www.reddit.com"}:
                value -= 25
            return (value, result.url)

        return sorted(results, key=score, reverse=True)

    def _dimension_source_terms(self, dimension: str) -> list[str]:
        normalized = dimension.casefold()
        if "pricing" in normalized:
            return ["pricing", "billing", "plans", "price", "cost"]
        if "security" in normalized:
            return [
                "security",
                "trust",
                "compliance",
                "soc",
                "iso",
                "saml",
                "scim",
                "audit",
            ]
        if "persona" in normalized:
            return ["persona", "customer", "user", "buyer", "case study"]
        return [normalized, "feature", "docs"]

    def _official_registry_key(self, competitor: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", competitor.casefold())

    def _official_dimension_key(self, dimension: str) -> str:
        normalized = dimension.casefold()
        if "pricing" in normalized:
            return "pricing"
        if any(token in normalized for token in ("security", "trust", "compliance")):
            return "security"
        return normalized

    def _host(self, url: str) -> str:
        if not url:
            return ""
        return (urlparse(url).hostname or "").casefold().removeprefix("www.")

    def _dimension_evidence_snippet(self, text: str, dimension: str, fallback: str) -> str:
        collapsed = re.sub(r"\s+", " ", text).strip()
        if not collapsed:
            return fallback
        terms = [*self._dimension_source_terms(dimension), *self._dimension_fact_terms(dimension)]
        scored_windows: list[tuple[int, int, str]] = []
        lowered = collapsed.casefold()
        for term in terms:
            start = lowered.find(term.casefold())
            if start < 0:
                continue
            window_start = max(0, start - 180)
            window_end = min(len(collapsed), start + 520)
            window = collapsed[window_start:window_end].strip(" ,.;|-")
            if len(window) < 80:
                continue
            score = self._dimension_window_score(window, dimension)
            scored_windows.append((score, start, window))
        if not scored_windows:
            return fallback
        snippets: list[str] = []
        seen: set[str] = set()
        for _, _, window in sorted(scored_windows, key=lambda item: item[:2], reverse=True):
            key = window[:120].casefold()
            if key in seen:
                continue
            seen.add(key)
            snippets.append(window)
            if len(snippets) >= 2:
                break
        return " ... ".join(snippets)[:1000]

    def _dimension_fact_terms(self, dimension: str) -> list[str]:
        normalized = dimension.casefold()
        if "pricing" in normalized:
            return ["$", "usd", "month", "annual", "free", "pro", "team", "enterprise", "seat"]
        if any(token in normalized for token in ("security", "trust", "compliance")):
            return [
                "sso",
                "scim",
                "soc 2",
                "iso",
                "encryption",
                "retention",
                "audit log",
                "privacy",
                "indemnity",
            ]
        return []

    def _dimension_window_score(self, text: str, dimension: str) -> int:
        lowered = text.casefold()
        score = 0
        for term in self._dimension_source_terms(dimension):
            if term.casefold() in lowered:
                score += 3
        for term in self._dimension_fact_terms(dimension):
            if term.casefold() in lowered:
                score += 5
        if "pricing" in dimension.casefold() and re.search(r"[$€£]\s?\d|\b\d+\s?usd\b", lowered):
            score += 12
        return score

    def _verified_source_confidence(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        url: str,
        snippet: str,
    ) -> float:
        homepage_host = self._host(detail.plan.homepage_hints.get(competitor, ""))
        source_host = self._host(url)
        official_host = bool(
            homepage_host
            and (source_host == homepage_host or source_host.endswith(f".{homepage_host}"))
        )
        dimension_fact = self._has_dimension_specific_fact(dimension, snippet.casefold())
        if official_host and dimension_fact:
            return 0.96
        if official_host:
            return 0.92
        if dimension_fact:
            return 0.9
        return 0.84

    def _source_is_usable(self, source: RawSource) -> bool:
        return self._source_quality_problem(source) is None

    def _source_quality_problem(self, source: RawSource) -> str | None:
        text = f"{source.title}\n{source.snippet}".strip()
        normalized = text.casefold()
        snippet_normalized = source.snippet.casefold()
        if len(source.snippet.strip()) < 24 and not self._has_concrete_source_signal(
            source.dimension, normalized
        ):
            return (
                f"Source {source.id} snippet is too short to support a reliable "
                f"{source.dimension} claim."
            )
        if self._looks_like_binary_or_pdf(source.snippet):
            return (
                f"Source {source.id} looks like unreadable binary/PDF text, "
                "not usable extracted evidence."
            )
        if self._looks_like_soft_404(source):
            return f"Source {source.id} appears to be a soft 404 or not-found page."
        if self._looks_like_navigation_only(
            snippet_normalized
        ) and not self._has_dimension_specific_fact(source.dimension, snippet_normalized):
            return f"Source {source.id} appears to contain mostly navigation or boilerplate text."
        if (
            source.source_type == "webpage_verified"
            and source.confidence <= 0.88
            and not self._has_dimension_specific_fact(source.dimension, snippet_normalized)
        ):
            return (
                f"Source {source.id} has low confidence ({source.confidence:.2f}) "
                "and does not expose "
                f"a concrete {source.dimension} fact in the fetched snippet."
            )
        if source.url and self._is_low_value_url(str(source.url)):
            return (
                f"Source {source.id} points to a low-value page for structured evidence extraction."
            )
        if source.url and self._is_dimension_mismatch_url(source.dimension, str(source.url)):
            return (
                f"Source {source.id} points to a page whose URL is mismatched for "
                f"{source.dimension} evidence."
            )
        if identity_problem := self._competitor_identity_problem(source):
            return identity_problem
        if not self._dimension_terms_present(source.dimension, normalized):
            return (
                f"Source {source.id} does not contain enough {source.dimension} "
                "terminology for this dimension."
            )
        return None

    def _has_concrete_source_signal(self, dimension: str, normalized_text: str) -> bool:
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            return bool(
                re.search(
                    r"(?:\$|usd|rmb|cny|eur|£|€|\d+\s*(?:/|per)\s*(?:token|seat|month|year))",
                    normalized_text,
                )
            )
        if "persona" in dimension_key or "user" in dimension_key:
            return any(
                term in normalized_text
                for term in ["developer", "customer", "enterprise", "team", "user"]
            )
        return any(
            term in normalized_text for term in ["model", "api", "feature", "coding", "reasoning"]
        )

    def _looks_like_binary_or_pdf(self, text: str) -> bool:
        if "%pdf" in text[:80].casefold() or " endobj" in text.casefold():
            return True
        if not text:
            return True
        replacement_ratio = text.count("\ufffd") / max(1, len(text))
        control_ratio = sum(1 for char in text if ord(char) < 32 and char not in "\n\r\t") / max(
            1, len(text)
        )
        return replacement_ratio > 0.02 or control_ratio > 0.01

    def _looks_like_soft_404(self, source: RawSource) -> bool:
        normalized = f"{source.title}\n{source.snippet}".casefold()
        title = source.title.casefold().strip()
        if title in {"404", "not found", "404: this page could not be found"}:
            return True
        markers = (
            "page not found",
            "404 not found",
            "this page could not be found",
            "this page does not exist",
            "this page doesn't exist",
            "we couldn't find that page",
            "we could not find that page",
        )
        if any(marker in normalized for marker in markers):
            return True
        if re.search(r"(?:^|\s)404(?:\s|:|-)", normalized) and "not found" in normalized:
            return True
        return False

    def _looks_like_navigation_only(self, normalized_text: str) -> bool:
        nav_markers = [
            "skip to main content",
            "open menu",
            "toggle theme",
            "sign in",
            "sign up",
            "log in",
            "language",
            "cookie",
            "this browser is no longer supported",
            "download microsoft edge",
            "search docs",
            "search...",
            "navigation",
            "home page",
            "resources",
            "back to blog",
        ]
        marker_count = sum(1 for marker in nav_markers if marker in normalized_text)
        return marker_count >= 3 and not self._has_dimension_specific_fact(
            "generic", normalized_text
        )

    def _has_dimension_specific_fact(self, dimension: str, normalized_text: str) -> bool:
        if not normalized_text.strip():
            return False
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            return bool(
                re.search(
                    r"(?:\$|usd|cny|rmb|eur|free|per\s+(?:user|seat|month|year|token)|\bplan\b|\btier\b)",
                    normalized_text,
                )
            )
        if "persona" in dimension_key or "user" in dimension_key:
            return bool(
                re.search(
                    r"(?:target(?:ed)?\s+(?:user|customer|persona)|for\s+(?:developers|teams|enterprises|"
                    r"engineering|marketing|sales)|case stud(?:y|ies)|customer|"
                    r"enterprise|adoption|use case)",
                    normalized_text,
                )
            )
        if "review" in dimension_key or "feedback" in dimension_key:
            return bool(
                re.search(
                    r"(?:review|feedback|rating|complaint|praise|customer|user|adoption|"
                    r"switching|pain point)",
                    normalized_text,
                )
            )
        if "generic" in dimension_key:
            return bool(
                re.search(
                    r"(?:\$\d+|\d+\s*(?:k|m|%|tokens?|users?|seats?)|supports|provides|includes|"
                    r"offers|built for|used by|target(?:ed)?)",
                    normalized_text,
                )
            )
        return bool(
            re.search(
                r"(?:supports|provides|includes|offers|can\s+(?:write|generate|explain|run)|"
                r"context window|context awareness|tool calls?|code completion|"
                r"pull requests?|api|benchmark|cascade|autocomplete|supercomplete|"
                r"write/chat modes?|auto-execution|model context protocol|mcp|"
                r"jetbrains plugin|command|tab)",
                normalized_text,
            )
        )

    def _is_low_value_url(self, url: str) -> bool:
        lowered = url.casefold()
        return any(
            host in lowered
            for host in [
                "youtube.com",
                "youtu.be",
                "google.com/search",
                "accounts.google",
            ]
        )

    def _is_dimension_mismatch_url(self, dimension: str, url: str) -> bool:
        lowered = url.casefold()
        dimension_key = dimension.casefold()
        if "persona" in dimension_key or "user" in dimension_key:
            return any(
                token in lowered
                for token in (
                    "/pricing",
                    "/plans",
                    "/billing",
                    "/accounts/usage",
                    "/subscription",
                    "/manage-plan",
                )
            )
        return False

    def _competitor_search_qualifier(self, competitor: str) -> str:
        key = self._official_registry_key(competitor)
        if key == "cursor":
            return "AI code editor"
        if key == "githubcopilot":
            return "GitHub Copilot coding assistant"
        if key == "windsurf":
            return "Windsurf AI code editor"
        if key == "claudecode":
            return "Claude Code coding agent"
        return ""

    def _competitor_identity_problem(self, source: RawSource) -> str | None:
        if source.source_type in USER_RESEARCH_SOURCE_TYPES:
            return None
        key = self._official_registry_key(source.competitor)
        if not key or key.startswith("crossmodel"):
            return None
        haystack = f"{source.title}\n{source.url or ''}\n{source.snippet}".casefold()
        for term in PRODUCT_CONFUSION_TERMS.get(key, ()):
            if (
                key == "windsurf"
                and term == "devin.ai"
                and self._is_windsurf_docs_redirect_source(source, haystack)
            ):
                continue
            if term in haystack:
                return (
                    f"Source {source.id} appears to describe `{term}` rather than "
                    f"{source.competitor}."
                )
        hints = PRODUCT_IDENTITY_HINTS.get(key, ())
        if hints and not any(term in haystack for term in hints):
            return (
                f"Source {source.id} does not expose a recognizable {source.competitor} "
                "product identity signal."
            )
        return None

    def _is_windsurf_docs_redirect_source(self, source: RawSource, haystack: str) -> bool:
        url = str(source.url or "").casefold()
        return (
            any(path in url for path in ("docs.devin.ai/desktop", "docs.devin.ai/windsurf"))
            and "windsurf" in haystack
            and "devin desktop" not in haystack
            and "cognition devin" not in haystack
        )

    def _dimension_terms_present(self, dimension: str, normalized_text: str) -> bool:
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            terms = [
                "pricing",
                "price",
                "cost",
                "billing",
                "token",
                "tier",
                "free",
                "enterprise",
                "plan",
                "$",
            ]
        elif "persona" in dimension_key or "user" in dimension_key:
            terms = [
                "customer",
                "user",
                "developer",
                "enterprise",
                "team",
                "persona",
                "target",
                "use case",
                "case study",
                "organization",
            ]
        elif "review" in dimension_key or "feedback" in dimension_key:
            terms = [
                "review",
                "feedback",
                "rating",
                "complaint",
                "praise",
                "customer",
                "user",
                "adoption",
                "switching",
                "pain point",
            ]
        else:
            terms = [
                "feature",
                "capability",
                "model",
                "context",
                "multimodal",
                "coding",
                "reasoning",
                "benchmark",
                "api",
                "tool",
            ]
        return any(term in normalized_text for term in terms)

    async def _source_from_search_result(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        result: SearchResult,
        record: RunRecord | None = None,
        context: SubagentContext | None = None,
    ) -> RawSource | None:
        if any(
            source.url
            and str(source.url) == result.url
            and source.dimension == dimension
            and self._source_matches_competitor(source, competitor)
            for source in detail.raw_sources
        ):
            return None
        fetched = (
            await self._trace_fetch(record, "collector", dimension, result.url, context)
            if record is not None
            else await fetch_page(result.url)
        )
        verified = fetched is not None and fetched.ok
        snippet = (
            self._dimension_evidence_snippet(fetched.text, dimension, fetched.snippet)
            if verified
            else result.snippet
        )
        confidence = (
            self._verified_source_confidence(
                detail,
                competitor,
                dimension,
                fetched.url,
                snippet,
            )
            if verified and fetched is not None
            else 0.68
        )
        provisional = RawSource(
            id=compute_raw_source_id(
                source_type="webpage_verified" if verified else "web_search_result",
                competitor=competitor,
                dimension=dimension,
                url=fetched.url if verified else result.url,
                content_hash=(
                    fetched.content_hash
                    if fetched is not None
                    else hashlib.sha256(
                        (snippet or result.title or result.url).encode()
                    ).hexdigest()[:16]
                ),
                title=fetched.title if verified and fetched.title else result.title,
                snippet=snippet,
                run_id=detail.id,
            ),
            competitor=competitor,
            dimension=dimension,
            source_type="webpage_verified" if verified else "web_search_result",
            title=(fetched.title if verified and fetched.title else result.title),
            url=(fetched.url if verified else result.url),
            snippet=snippet,
            content_hash=(
                fetched.content_hash
                if fetched is not None
                else hashlib.sha256((snippet or result.title or result.url).encode()).hexdigest()[
                    :16
                ]
            ),
            confidence=confidence,
        )
        if not self._source_is_usable(provisional):
            return None
        content_basis = snippet or result.title or result.url
        content_hash = (
            fetched.content_hash
            if fetched is not None
            else hashlib.sha256(content_basis.encode()).hexdigest()[:16]
        )
        return RawSource(
            id=compute_raw_source_id(
                source_type="webpage_verified" if verified else "web_search_result",
                competitor=competitor,
                dimension=dimension,
                url=fetched.url if verified else result.url,
                content_hash=content_hash,
                title=fetched.title if verified and fetched.title else result.title,
                snippet=snippet,
                run_id=detail.id,
            ),
            competitor=competitor,
            dimension=dimension,
            source_type="webpage_verified" if verified else "web_search_result",
            title=(fetched.title if verified and fetched.title else result.title),
            url=(fetched.url if verified else result.url),
            snippet=snippet,
            content_hash=content_hash,
            confidence=confidence,
        )

    async def _real_collector_step(self, record: RunRecord, dimension: str) -> None:
        detail = record.detail
        skill = self._skill_registry.get(dimension)
        context = SubagentContext(run_id=detail.id, agent="collector", subagent=dimension)
        detail.current_node = "collector"
        self._append_agent_message(
            record,
            from_agent="collector_dispatch",
            to_agent="collector",
            message_type="collect_task",
            payload_schema="CollectTaskPayload",
            payload={
                "topic": detail.topic,
                "dimension": dimension,
                "competitors": detail.plan.competitors,
                "homepage_hints": detail.plan.homepage_hints,
            },
        )
        await self.emit(
            detail.id,
            "node_started",
            "collector",
            dimension,
            f"Calling {dimension} collector.",
            {"context": context.metadata()},
        )
        web_payload: dict[str, object] = {
            "provider": self._settings.web_search_provider,
            "results": [],
        }
        if self._settings.collector_react_enabled and self._search.is_enabled:
            try:
                added = await self._run_collector_react(record, dimension, context)
                web_payload["react_added"] = added
                if added > 0:
                    self._append_agent_message(
                        record,
                        from_agent="collector",
                        to_agent="collect_join",
                        message_type="raw_sources_collected",
                        payload_schema="RawSource[]",
                        payload={
                            "dimension": dimension,
                            "source_ids": [
                                source.id
                                for source in detail.raw_sources
                                if source.dimension == dimension
                            ],
                            "count": added,
                        },
                    )
                    detail.updated_at = datetime.utcnow()
                    await self.emit(
                        detail.id,
                        "node_completed",
                        "collector",
                        dimension,
                        f"ReAct collector returned {added} {dimension} evidence source(s).",
                        {
                            "react": web_payload,
                            "context": context.metadata(),
                            **self._collector_source_trace_payload(
                                detail,
                                dimension,
                                added,
                                "collector_react_finish",
                            ),
                        },
                    )
                    return
            except Exception as exc:  # noqa: BLE001 - bounded ReAct falls back to deterministic collection.
                web_payload["react_error"] = str(exc)

        if self._search.is_enabled:
            try:
                added = await self._collect_with_web_search(record, dimension, context)
                web_payload["added"] = added
                if added > 0:
                    self._append_agent_message(
                        record,
                        from_agent="collector",
                        to_agent="collect_join",
                        message_type="raw_sources_collected",
                        payload_schema="RawSource[]",
                        payload={
                            "dimension": dimension,
                            "source_ids": [
                                source.id
                                for source in detail.raw_sources
                                if source.dimension == dimension
                            ],
                            "count": added,
                        },
                    )
                    detail.updated_at = datetime.utcnow()
                    await self.emit(
                        detail.id,
                        "node_completed",
                        "collector",
                        dimension,
                        f"Perplexity web_search returned {added} {dimension} evidence source(s).",
                        {
                            "web_search": web_payload,
                            "context": context.metadata(),
                            **self._collector_source_trace_payload(
                                detail,
                                dimension,
                                added,
                                "collector_web_search_finish",
                            ),
                        },
                    )
                    return
            except Exception as exc:  # noqa: BLE001 - web search is best effort; LLM fallback continues.
                web_payload["error"] = str(exc)

        payload = await self._trace_llm_json(
            record,
            agent="collector",
            subagent=dimension,
            name=f"{dimension}_collector",
            system=(
                "You are a collector subagent. Produce compact evidence candidates "
                "for competitive analysis. "
                "Use public knowledge only and mark confidence lower when evidence is uncertain."
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Dimension: {dimension}\n"
                f"Dimension description: {skill.description if skill else dimension}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n\n"
                "For each competitor return one concise evidence candidate. "
                "Prefer official URLs when known."
            ),
            schema_hint=(
                '{"sources":[{"competitor":"name","title":"evidence title",'
                '"url":"https://... or null","summary":"short factual summary",'
                '"confidence":0.0}]}'
            ),
            context=context,
        )
        sources = payload.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        added = 0
        for item in sources:
            if not isinstance(item, dict):
                continue
            competitor = str(item.get("competitor") or detail.plan.competitors[0])
            title = str(item.get("title") or f"{competitor} {dimension} evidence")
            summary = str(item.get("summary") or title)
            url_value = item.get("url")
            if not isinstance(url_value, str) or not url_value.startswith(("http://", "https://")):
                url_value = None
            confidence = self._coerce_confidence(item.get("confidence"), default=0.62)
            fetched = (
                await self._trace_fetch(record, "collector", dimension, url_value, context)
                if url_value
                else None
            )
            verified = fetched is not None and fetched.ok
            snippet = fetched.snippet if verified else summary
            source_title = fetched.title if verified and fetched.title else title
            source_url = fetched.url if fetched is not None and fetched.ok else url_value
            content_hash = (
                fetched.content_hash
                if fetched is not None
                else hashlib.sha256(summary.encode()).hexdigest()[:16]
            )
            source_type = "webpage_verified" if verified else "llm_public_knowledge"
            detail.raw_sources.append(
                RawSource(
                    id=compute_raw_source_id(
                        source_type=source_type,
                        competitor=competitor,
                        dimension=dimension,
                        url=source_url,
                        content_hash=content_hash,
                        title=source_title,
                        snippet=snippet,
                        run_id=detail.id,
                    ),
                    competitor=competitor,
                    dimension=dimension,
                    source_type=source_type,
                    title=source_title,
                    url=source_url,
                    snippet=snippet,
                    content_hash=content_hash,
                    confidence=min(1.0, confidence + 0.03) if verified else confidence,
                )
            )
            added += 1
        self._append_agent_message(
            record,
            from_agent="collector",
            to_agent="collect_join",
            message_type="raw_sources_collected",
            payload_schema="RawSource[]",
            payload={
                "dimension": dimension,
                "source_ids": [
                    source.id for source in detail.raw_sources if source.dimension == dimension
                ],
                "count": added,
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "collector",
            dimension,
            f"Collector returned {added} {dimension} evidence candidates.",
            {
                "collector": payload,
                "web_search": web_payload,
                "context": context.metadata(),
                **self._collector_source_trace_payload(
                    detail,
                    dimension,
                    added,
                    "collector_finish",
                ),
            },
        )

    def _collector_source_trace_payload(
        self,
        detail: RunDetail,
        dimension: str,
        added: int,
        retrieval_stage: str,
    ) -> dict[str, object]:
        sources = [source for source in detail.raw_sources if source.dimension == dimension]
        return {
            "dimension": dimension,
            "source_count": added,
            "source_ids": [source.id for source in sources],
            "sources": [source.model_dump(mode="json") for source in sources],
            "retrieval_stage": retrieval_stage,
        }

    async def _real_collector_dispatch_step(
        self,
        record: RunRecord,
        dimensions: list[str],
        competitors: list[str],
    ) -> None:
        detail = record.detail
        detail.current_node = "collector_dispatch"
        self._consume_queued_agent_messages(
            record,
            to_agent="collector_dispatch",
            consumer_agent="collector_dispatch",
            message_types={"analysis_plan_ready"},
        )
        branch_count = len(dimensions) * len(competitors)
        self._append_agent_message(
            record,
            from_agent="orchestrator",
            to_agent="collector_dispatch",
            message_type="dispatch_collectors",
            payload_schema="CollectorDispatchPlan",
            payload={
                "topic": detail.topic,
                "dimensions": dimensions,
                "competitors": competitors,
                "branch_count": branch_count,
                "fanout": "competitor_x_dimension",
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_started",
            "collector_dispatch",
            None,
            f"Dispatching {branch_count} collector branch(es).",
            {"dimensions": dimensions, "competitors": competitors, "branch_count": branch_count},
        )
        await self.emit(
            detail.id,
            "node_completed",
            "collector_dispatch",
            None,
            "Collector dispatch completed.",
            {"fanout": "competitor_x_dimension"},
        )

    async def _real_collector_branch_step(
        self, record: RunRecord, dimension: str, competitor: str
    ) -> None:
        detail = record.detail
        skill = self._skill_registry.get(dimension)
        branch_id = self._analyst_branch_id(dimension, competitor)
        context = SubagentContext(run_id=detail.id, agent="collector", subagent=branch_id)
        qa_feedback = self._qa_feedback_for_branch(detail, "collector", dimension, competitor)
        task_metadata = self._plan_task_metadata(detail.plan, "collector", dimension, competitor)
        detail.current_node = "collector"
        task_message = self._append_agent_message(
            record,
            from_agent="collector_dispatch",
            to_agent="collector",
            message_type="collect_task",
            payload_schema="CollectTaskPayload",
            payload={
                "topic": detail.topic,
                "competitor": competitor,
                "dimension": dimension,
                "homepage_hint": detail.plan.homepage_hints.get(competitor),
                "required_output_schema": "RawSource[]",
                "qa_feedback": qa_feedback,
                **task_metadata,
            },
        )
        self._consume_agent_message(
            record, task_message, consumer_agent="collector", context=context
        )
        await self.emit(
            detail.id,
            "node_started",
            "collector",
            branch_id,
            f"Calling {competitor} / {dimension} collector.",
            {
                "context": context.metadata(),
                "dimension": dimension,
                "competitor": competitor,
                **task_metadata,
            },
        )
        sources: list[RawSource] = []
        collect_payload: dict[str, object] = {
            "provider": self._settings.web_search_provider,
            "results": [],
            **task_metadata,
        }
        memory_official_first = self._memory_prefers_official_sources(detail.plan)
        if self._should_collect_official_first(dimension) or memory_official_first:
            try:
                sources = await self._collect_official_sources(
                    record,
                    detail,
                    dimension,
                    competitor,
                    context,
                )
                collect_payload["official_added"] = len(sources)
                collect_payload["memory_official_first"] = memory_official_first
            except Exception as exc:  # noqa: BLE001 - official-first should degrade to search.
                collect_payload["official_error"] = str(exc)
                collect_payload["memory_official_first"] = memory_official_first
        if not sources and self._settings.collector_react_enabled and self._search.is_enabled:
            try:
                sources = await self._run_collector_competitor_react(
                    record, dimension, competitor, context
                )
                collect_payload["react_added"] = len(sources)
            except Exception as exc:  # noqa: BLE001 - deterministic fallback continues.
                collect_payload["react_error"] = str(exc)
        if not sources and self._search.is_enabled:
            try:
                sources = await self._collect_competitor_with_web_search(
                    record, dimension, competitor, context
                )
                collect_payload["added"] = len(sources)
            except Exception as exc:  # noqa: BLE001 - LLM fallback continues.
                collect_payload["error"] = str(exc)
        if not sources:
            try:
                sources = await self._collect_competitor_with_skill_tools(
                    record,
                    dimension,
                    competitor,
                    context,
                    qa_feedback,
                )
                collect_payload["skill_tool_added"] = len(sources)
            except Exception as exc:  # noqa: BLE001 - skill tools degrade to LLM fallback.
                collect_payload["skill_tool_error"] = str(exc)
        if not sources:
            payload = await self._trace_llm_json(
                record,
                agent="collector",
                subagent=branch_id,
                name=f"{dimension}_{self._issue_id_fragment(competitor)}_collector",
                system=(
                    "You are a collector subagent for exactly one competitor and "
                    "one dimension. "
                    "Return structured evidence candidates only for the assigned competitor. "
                    "Use public knowledge only if no URL can be identified and mark "
                    "confidence lower."
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Competitor: {competitor}\n"
                    f"Dimension: {dimension}\n"
                    f"Dimension description: {skill.description if skill else dimension}\n"
                    f"Homepage hint: {detail.plan.homepage_hints.get(competitor, '')}\n\n"
                    f"QA feedback for this branch: "
                    f"{json.dumps(qa_feedback, ensure_ascii=False)}\n\n"
                    "Return one concise evidence candidate."
                ),
                schema_hint='{"sources":[{"title":"evidence title","url":"https://... or null",'
                '"summary":"short factual summary","confidence":0.0}]}',
                context=context,
            )
            raw_sources = self._force_source_competitor(payload.get("sources"), competitor)
            sources = await self._sources_from_react_finish(
                record,
                detail,
                dimension,
                {"sources": raw_sources},
                context,
                {},
            )
            collect_payload["llm_added"] = len(sources)
        detail.raw_sources.extend(sources)
        message = self._append_agent_message(
            record,
            from_agent="collector",
            to_agent="collect_join",
            message_type="raw_sources_collected",
            payload_schema="RawSource[]",
            payload={
                "competitor": competitor,
                "dimension": dimension,
                "source_ids": [source.id for source in sources],
                "sources": [source.model_dump(mode="json") for source in sources],
            },
            source_message_ids=[task_message.id],
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "collector",
            branch_id,
            f"Collector completed {competitor} / {dimension} with {len(sources)} source(s).",
            {
                "collect": collect_payload,
                "context": context.metadata(),
                "dimension": dimension,
                "competitor": competitor,
                "source_count": len(sources),
                "source_ids": [source.id for source in sources],
                "sources": [source.model_dump(mode="json") for source in sources],
                "retrieval_stage": "collector_branch_finish",
                "message_id": message.id,
            },
        )

    async def _real_collect_join_step(self, record: RunRecord, dimensions: list[str]) -> None:
        detail = record.detail
        before_count = len(detail.raw_sources)
        detail.current_node = "collect_join"
        self._consume_queued_agent_messages(
            record,
            to_agent="collect_join",
            consumer_agent="collect_join",
            message_types={
                "raw_sources_collected",
                "cross_competitor_sources_collected",
                "cross_competitor_search_failed",
            },
        )
        await self.emit(
            detail.id,
            "node_started",
            "collect_join",
            "collect_join",
            "Normalizing collected evidence sources.",
        )
        await self._collect_cross_competitor_evidence(record, dimensions)
        self._consume_queued_agent_messages(
            record,
            to_agent="collect_join",
            consumer_agent="collect_join",
            message_types={"cross_competitor_sources_collected", "cross_competitor_search_failed"},
        )
        detail.raw_sources = self._normalize_collected_sources(detail, dimensions)
        normalized_count = len(detail.raw_sources)
        self._append_agent_message(
            record,
            from_agent="collect_join",
            to_agent="qa",
            message_type="collect_join_completed",
            payload_schema="RawSourceDigest",
            payload={
                "before_count": before_count,
                "after_count": normalized_count,
                "dimensions": dimensions,
                "source_ids": [
                    source.id for source in detail.raw_sources if source.dimension in dimensions
                ],
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "collect_join",
            "collect_join",
            f"Collect join normalized {normalized_count} source(s).",
            {
                "collect_join": {
                    "before_count": before_count,
                    "after_count": normalized_count,
                    "dimensions": dimensions,
                }
            },
        )

    def _normalize_collected_sources(
        self, detail: RunDetail, dimensions: list[str]
    ) -> list[RawSource]:
        scoped_dimensions = set(dimensions)
        normalized: list[RawSource] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for source in detail.raw_sources:
            if scoped_dimensions and source.dimension not in scoped_dimensions:
                normalized.append(source)
                continue
            covered_competitors = self._normalize_covered_competitors(detail, source.competitor)
            url_key = str(source.url) if source.url else ""
            key = (
                source.dimension,
                url_key,
                source.content_hash,
                source.title.strip().casefold(),
                "|".join(covered_competitors),
            )
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                source.model_copy(update={"covered_competitors": covered_competitors})
            )
        return normalized

    async def _collect_cross_competitor_evidence(
        self, record: RunRecord, dimensions: list[str]
    ) -> None:
        detail = record.detail
        if not self._search.is_enabled or len(detail.plan.competitors) < 2:
            return
        for dimension in dimensions:
            if self._has_cross_competitor_source(detail, dimension):
                continue
            covered_competitors = self._branch_covered_competitors(detail, dimension)
            if len(covered_competitors) >= len(detail.plan.competitors):
                await self.emit(
                    detail.id,
                    "node_completed",
                    "collector",
                    f"cross::{dimension}",
                    (
                        "Skipped cross-competitor evidence search; branch evidence "
                        "already covers all competitors."
                    ),
                    {
                        "dimension": dimension,
                        "covered_competitors": sorted(covered_competitors),
                        "skipped": True,
                        "reason": "branch_coverage_complete",
                    },
                )
                continue
            query = self._cross_competitor_query(detail, dimension)
            try:
                results = await self._trace_search(
                    record,
                    agent="collector",
                    subagent=f"cross::{dimension}",
                    query=query,
                    max_results=3,
                )
            except Exception as exc:  # noqa: BLE001 - cross evidence is optional; QA/reflector can flag gaps.
                self._append_agent_message(
                    record,
                    from_agent="collector",
                    to_agent="collect_join",
                    message_type="cross_competitor_search_failed",
                    payload_schema="ToolError",
                    payload={
                        "dimension": dimension,
                        "query": query,
                        "error": str(exc),
                        "degraded": True,
                    },
                )
                await self.emit(
                    detail.id,
                    "node_completed",
                    "collector",
                    f"cross::{dimension}",
                    "Cross-competitor evidence search failed; continuing with branch evidence.",
                    {"dimension": dimension, "query": query, "error": str(exc), "degraded": True},
                )
                continue
            cross_label = f"Cross-model all {len(detail.plan.competitors)} competitors"
            for result in results:
                source = await self._source_from_search_result(
                    detail,
                    cross_label,
                    dimension,
                    result,
                    record,
                    None,
                )
                if source is None:
                    continue
                source.covered_competitors = list(detail.plan.competitors)
                detail.raw_sources.append(source)
                self._append_agent_message(
                    record,
                    from_agent="collector",
                    to_agent="collect_join",
                    message_type="cross_competitor_sources_collected",
                    payload_schema="RawSource[]",
                    payload={
                        "dimension": dimension,
                        "source_ids": [source.id],
                        "covered_competitors": source.covered_competitors,
                    },
                )
                break

    def _has_cross_competitor_source(self, detail: RunDetail, dimension: str) -> bool:
        expected = set(detail.plan.competitors)
        for source in detail.raw_sources:
            if source.dimension != dimension:
                continue
            covered = set(
                source.covered_competitors
                or self._normalize_covered_competitors(detail, source.competitor)
            )
            if len(covered & expected) >= max(2, min(len(expected), 3)):
                return True
        return False

    def _branch_covered_competitors(self, detail: RunDetail, dimension: str) -> set[str]:
        covered: set[str] = set()
        for source in detail.raw_sources:
            if source.dimension != dimension:
                continue
            labels = source.covered_competitors or [source.competitor]
            for label in labels:
                for competitor in detail.plan.competitors:
                    if self._competitor_label_matches(label, competitor):
                        covered.add(competitor)
        return covered

    def _cross_competitor_query(self, detail: RunDetail, dimension: str) -> str:
        competitors = " ".join(detail.plan.competitors)
        if dimension == "pricing":
            focus = "pricing comparison API cost per token tiers"
        elif dimension == "persona":
            focus = "target users customers personas use cases comparison"
        else:
            focus = "feature benchmark capabilities comparison"
        return f"{detail.topic} {competitors} {focus} source"

    def _normalize_covered_competitors(
        self, detail: RunDetail, source_competitor: str
    ) -> list[str]:
        source_key = source_competitor.strip().casefold()
        if self._competitor_label_means_all(source_key):
            return list(detail.plan.competitors)
        matched = [
            competitor
            for competitor in detail.plan.competitors
            if self._competitor_label_matches(source_competitor, competitor)
        ]
        if matched:
            return matched
        cleaned = source_competitor.strip()
        return [cleaned] if cleaned else []
