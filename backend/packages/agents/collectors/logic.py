from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from packages.agents import SubagentContext
from packages.agents.collectors.skill_tools import collect_competitor_with_skill_tools
from packages.business_intel.entity_resolver import (
    confusion_terms_for_competitor,
    identity_terms_for_competitor,
    is_trusted_url_for_competitor,
    normalize_competitor_key,
    search_qualifier_for_competitor,
)
from packages.identity import compute_raw_source_id
from packages.research.discovery import (
    homepage_candidates,
    trusted_registry_candidates,
)
from packages.research.evidence import (
    raw_sources_from_research_result,
    source_quality_problem,
)
from packages.research.models import ResearchBrief
from packages.research.pipeline import run_research_pipeline
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    RawSource,
)
from packages.search import SearchResult
from packages.tools import (
    fetch_evidence_page,
    search_review_site_queries,
    survey_simulator,
)
from packages.tools.source_discovery import (
    SourceCandidate,
    source_candidate_from_search_result,
)

CORE_SCHEMA_DIMENSIONS = ("pricing", "feature", "persona")

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
                seed_candidates = self._source_candidates_from_react_finish(
                    detail,
                    dimension,
                    payload,
                )
                for competitor, candidates in self._group_candidates_by_competitor(
                    seed_candidates,
                    default_competitor=detail.plan.competitors[0],
                ).items():
                    pipeline_sources = await self._collect_competitor_with_research_pipeline(
                        record,
                        detail,
                        dimension,
                        competitor,
                        context,
                        batch_sources=detail.raw_sources,
                        target_source_count=self._collector_target_source_count(
                            detail,
                            dimension,
                        ),
                        include_official=False,
                        seed_candidates=candidates,
                        enable_search=False,
                        enable_repair=False,
                    )
                    for source in pipeline_sources:
                        if self._source_already_in_batch(source, detail.raw_sources):
                            continue
                        detail.raw_sources.append(source)
                        added += 1
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
    ) -> list[SourceCandidate]:
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
                brief = self._research_brief(detail, competitor, dimension)
                candidates = [
                    *trusted_registry_candidates(brief),
                    *homepage_candidates(brief),
                ]
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
                        [candidate.model_dump(mode="json") for candidate in candidates],
                        ensure_ascii=False,
                    ),
                    context=context,
                    metadata={"candidate_count": len(candidates)},
                )
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "candidates": [
                            candidate.model_dump(mode="json") for candidate in candidates[:4]
                        ],
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
                return self._source_candidates_from_react_finish(
                    detail,
                    dimension,
                    {
                        **payload,
                        "sources": self._force_source_competitor(
                            payload.get("sources"), competitor
                        ),
                    },
                    default_competitor=competitor,
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

    def _group_candidates_by_competitor(
        self,
        candidates: list[SourceCandidate],
        *,
        default_competitor: str,
    ) -> dict[str, list[SourceCandidate]]:
        grouped: dict[str, list[SourceCandidate]] = {}
        for candidate in candidates:
            competitor = candidate.competitor or default_competitor
            grouped.setdefault(competitor, []).append(candidate)
        return grouped

    def _source_candidates_from_react_finish(
        self,
        detail: RunDetail,
        dimension: str,
        payload: dict[str, Any],
        *,
        default_competitor: str | None = None,
    ) -> list[SourceCandidate]:
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list):
            return []
        candidates: list[SourceCandidate] = []
        for rank, item in enumerate(raw_sources):
            if not isinstance(item, dict):
                continue
            competitor = str(
                item.get("competitor")
                or default_competitor
                or detail.plan.competitors[0]
            )
            title = str(item.get("title") or f"{competitor} {dimension} evidence")
            summary = str(item.get("summary") or title)
            url_value = item.get("url")
            if not isinstance(url_value, str) or not url_value.startswith(("http://", "https://")):
                continue
            candidates.append(
                SourceCandidate(
                    title=title,
                    url=url_value,
                    snippet=summary,
                    origin="llm_fallback",
                    competitor=competitor,
                    dimension=dimension,
                    rank=rank,
                    confidence=self._coerce_confidence(item.get("confidence"), default=0.7),
                    reason="collector_react_finish",
                    metadata={
                        "collector_adapter": "react_candidate_proposer",
                        "react_finish_summary": summary,
                    },
                )
            )
        return candidates

    async def _collect_with_web_search(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
    ) -> int:
        detail = record.detail
        added = 0
        for competitor in detail.plan.competitors:
            competitor_sources = await self._collect_competitor_with_web_search(
                record,
                dimension,
                competitor,
                context,
                include_official=True,
            )
            for source in competitor_sources:
                if self._source_already_in_batch(source, detail.raw_sources):
                    continue
                detail.raw_sources.append(source)
                added += 1
        return added

    async def _collect_competitor_with_web_search(
        self,
        record: RunRecord,
        dimension: str,
        competitor: str,
        context: SubagentContext,
        *,
        seed_sources: list[RawSource] | None = None,
        include_official: bool = True,
    ) -> list[RawSource]:
        detail = record.detail
        target_source_count = self._collector_target_source_count(detail, dimension)
        sources = list(seed_sources or [])
        if len(sources) >= target_source_count:
            return sources
        pipeline_sources = await self._collect_competitor_with_research_pipeline(
            record,
            detail,
            dimension,
            competitor,
            context,
            batch_sources=sources,
            target_source_count=target_source_count,
            include_official=include_official,
        )
        self._extend_source_batch(sources, pipeline_sources, target_source_count)
        return sources

    async def _collect_competitor_with_research_pipeline(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
        *,
        batch_sources: list[RawSource],
        target_source_count: int,
        include_official: bool,
        seed_candidates: list[SourceCandidate] | None = None,
        enable_search: bool = True,
        enable_repair: bool = True,
    ) -> list[RawSource]:
        max_repair_rounds = (
            1 if enable_repair and self._requires_verified_web_evidence(detail, dimension) else 0
        )
        brief = self._research_brief(detail, competitor, dimension).model_copy(
            update={
                "target_source_count": target_source_count,
                "max_repair_rounds": max_repair_rounds,
                "include_trusted_sources": include_official,
                "include_homepage_candidates": include_official,
                "metadata": {
                    "collector_adapter": "clean_research_pipeline",
                    "include_official": include_official,
                    "seed_candidate_count": len(seed_candidates or []),
                    "search_enabled": enable_search and self._search.is_enabled,
                    "repair_enabled": enable_repair,
                },
            }
        )

        async def search(query: str, max_results: int) -> list[SearchResult]:
            if not self._search.is_enabled:
                return []
            return await self._trace_search(
                record,
                agent="collector",
                subagent=context.subagent,
                query=query,
                max_results=max_results,
                context=context,
            )

        async def fetch(url: str):
            return await self._trace_fetch(record, "collector", dimension, url, context)

        result = await run_research_pipeline(
            brief,
            fetch=fetch,
            search=search if enable_search and self._search.is_enabled else None,
            seed_candidates=seed_candidates,
        )
        sources = self._raw_sources_from_research_result(
            detail,
            brief,
            result,
            batch_sources=batch_sources,
            target_source_count=target_source_count,
        )
        self._trace_local_tool(
            record,
            agent="collector",
            subagent=context.subagent,
            name="clean_research_pipeline",
            input_text=json.dumps(
                {
                    "competitor": competitor,
                    "dimension": dimension,
                    "homepage_hint": detail.plan.homepage_hints.get(competitor),
                    "target_source_count": target_source_count,
                },
                ensure_ascii=False,
            ),
            output_text=json.dumps(
                {
                    "source_ids": [source.id for source in sources],
                    "gap_ids": [gap.id for gap in result.gaps],
                    "repair_task_ids": [task.id for task in result.repair_tasks],
                    "metrics": result.metrics,
                },
                ensure_ascii=False,
            ),
            context=context,
            metadata={
                "source_count": len(sources),
                "candidate_count": len(result.candidates),
                "captured_ok_count": result.metrics.get("captured_ok_count", 0),
                "gap_count": len(result.gaps),
                "repair_round_count": result.metrics.get("repair_round_count", 0),
            },
        )
        return sources

    def _raw_sources_from_research_result(
        self,
        detail: RunDetail,
        brief: ResearchBrief,
        result,
        *,
        batch_sources: list[RawSource],
        target_source_count: int,
    ) -> list[RawSource]:
        return raw_sources_from_research_result(
            brief,
            result,
            batch_sources=batch_sources,
            target_source_count=target_source_count,
            requires_accepted_evidence=self._requires_verified_web_evidence(
                detail,
                brief.dimension,
            ),
            source_exists=lambda url, current_sources: self._candidate_already_collected(
                detail,
                current_sources,
                competitor=brief.competitor,
                dimension=brief.dimension,
                url=url,
            ),
            confidence_for_source=lambda candidate, page, snippet, items: max(
                self._verified_source_confidence(
                    detail,
                    brief.competitor,
                    brief.dimension,
                    page.final_url,
                    snippet,
                ),
                max((item.confidence for item in items), default=0.0),
                min(0.96, candidate.confidence + 0.03),
            ),
            fallback_snippet=lambda page: self._dimension_evidence_snippet(
                page.text or page.markdown,
                brief.dimension,
                page.snippet,
            ),
            source_is_usable=self._source_is_usable,
        )

    async def _collect_official_sources(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
    ) -> list[RawSource]:
        candidates = self._official_source_candidates(detail, competitor, dimension)
        target_source_count = self._collector_target_source_count(detail, dimension)
        sources = await self._collect_competitor_with_research_pipeline(
            record,
            detail,
            dimension,
            competitor,
            context,
            batch_sources=[],
            target_source_count=target_source_count,
            include_official=True,
            seed_candidates=candidates,
            enable_search=False,
            enable_repair=False,
        )
        if sources:
            self._trace_local_tool(
                record,
                agent="collector",
                subagent=context.subagent,
                name="source_discovery_trusted_registry",
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
                metadata={
                    "source_count": len(sources),
                    "target_source_count": target_source_count,
                    "candidate_count": len(candidates),
                    "candidate_origins": ",".join(
                        sorted({candidate.origin for candidate in candidates})
                    ),
                },
            )
        return sources

    def _official_source_candidates(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> list[SourceCandidate]:
        brief = self._research_brief(detail, competitor, dimension)
        trusted = trusted_registry_candidates(brief)
        return trusted or homepage_candidates(brief)

    def _homepage_source_candidates(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> list[SourceCandidate]:
        return homepage_candidates(self._research_brief(detail, competitor, dimension))

    async def _collect_homepage_fallback_sources(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
        *,
        batch_sources: list[RawSource],
        target_source_count: int,
    ) -> list[RawSource]:
        candidates = self._homepage_source_candidates(detail, competitor, dimension)
        if not candidates:
            return []
        sources = await self._collect_competitor_with_research_pipeline(
            record,
            detail,
            dimension,
            competitor,
            context,
            batch_sources=batch_sources,
            target_source_count=target_source_count,
            include_official=True,
            seed_candidates=candidates,
            enable_search=False,
            enable_repair=False,
        )
        if sources:
            self._trace_local_tool(
                record,
                agent="collector",
                subagent=context.subagent,
                name="source_discovery_homepage_fallback",
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
                metadata={
                    "source_count": len(sources),
                    "target_source_count": target_source_count,
                    "candidate_count": len(candidates),
                    "candidate_origins": "homepage_derived",
                },
            )
        return sources

    def _extend_source_batch(
        self,
        target: list[RawSource],
        additions: list[RawSource],
        target_source_count: int,
    ) -> None:
        for source in additions:
            if len(target) >= target_source_count:
                break
            if self._source_already_in_batch(source, target):
                continue
            target.append(source)

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

    def _collector_target_source_count(self, detail: RunDetail, dimension: str) -> int:
        if not self._requires_verified_web_evidence(detail, dimension):
            return 1
        return max(1, int(self._settings.collector_target_verified_sources_per_branch))

    def _collector_search_max_results(self) -> int:
        return max(3, int(self._settings.collector_search_max_results))

    def _candidate_already_collected(
        self,
        detail: RunDetail,
        batch_sources: list[RawSource],
        *,
        competitor: str,
        dimension: str,
        url: str | None,
    ) -> bool:
        if not url:
            return False
        normalized_url = url.rstrip("/")
        for source in (*detail.raw_sources, *batch_sources):
            if source.dimension != dimension or not self._source_matches_competitor(
                source, competitor
            ):
                continue
            if source.url and str(source.url).rstrip("/") == normalized_url:
                return True
        return False

    def _source_already_in_batch(self, source: RawSource, batch_sources: list[RawSource]) -> bool:
        source_url = str(source.url).rstrip("/") if source.url else None
        for existing in batch_sources:
            if source.id == existing.id:
                return True
            existing_url = str(existing.url).rstrip("/") if existing.url else None
            if source_url and existing_url and source_url == existing_url:
                return True
        return False

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
        return normalize_competitor_key(competitor)

    def _host(self, url: str) -> str:
        if not url:
            return ""
        return (urlparse(url).hostname or "").casefold().removeprefix("www.")

    def _research_brief(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> ResearchBrief:
        return ResearchBrief(
            run_id=detail.id,
            topic=detail.topic,
            competitor=competitor,
            dimension=dimension,
            execution_mode=detail.execution_mode,
            homepage_hint=detail.plan.homepage_hints.get(competitor),
            target_source_count=self._collector_target_source_count(detail, dimension),
            max_search_queries=2,
            max_candidates=max(6, self._collector_search_max_results()),
            max_fetches=max(3, self._collector_target_source_count(detail, dimension)),
            max_advanced_fetches=getattr(self._settings, "web_fetch_advanced_max", 3),
        )

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
        ) or is_trusted_url_for_competitor(competitor, url)
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
        return source_quality_problem(source)

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
        return search_qualifier_for_competitor(competitor)

    def _competitor_identity_problem(self, source: RawSource) -> str | None:
        if source.source_type in USER_RESEARCH_SOURCE_TYPES:
            return None
        key = self._official_registry_key(source.competitor)
        if not key or key.startswith("crossmodel"):
            return None
        haystack = f"{source.title}\n{source.url or ''}\n{source.snippet}".casefold()
        for term in confusion_terms_for_competitor(source.competitor):
            if (
                key == "windsurf"
                and term in {"devin.ai", "devin desktop"}
                and self._is_windsurf_devin_redirect_source(source, haystack)
            ):
                continue
            if term in haystack:
                return (
                    f"Source {source.id} appears to describe `{term}` rather than "
                    f"{source.competitor}."
                )
        hints = identity_terms_for_competitor(source.competitor)
        if hints and not any(term in haystack for term in hints):
            return (
                f"Source {source.id} does not expose a recognizable {source.competitor} "
                "product identity signal."
            )
        return None

    def _is_windsurf_devin_redirect_source(self, source: RawSource, haystack: str) -> bool:
        url = str(source.url or "").casefold()
        docs_redirect = (
            any(path in url for path in ("docs.devin.ai/desktop", "docs.devin.ai/windsurf"))
            and "windsurf" in haystack
            and "devin desktop" not in haystack
            and "cognition devin" not in haystack
        )
        pricing_rebrand = (
            "devin.ai/pricing" in url
            and "windsurf is now devin desktop" in haystack
            and self._has_dimension_specific_fact("pricing", haystack)
            and "cognition devin" not in haystack
        )
        return docs_redirect or pricing_rebrand

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
        *,
        candidate: SourceCandidate | None = None,
    ) -> RawSource | None:
        source_candidate = candidate or source_candidate_from_search_result(
            result,
            origin=self._settings.web_search_provider or "web_search",
            rank=0,
            confidence=0.68,
            competitor=competitor,
            dimension=dimension,
        )
        if any(
            source.url
            and str(source.url) == result.url
            and source.dimension == dimension
            and self._source_matches_competitor(source, competitor)
            for source in detail.raw_sources
            ):
            return None

        brief = self._research_brief(detail, competitor, dimension).model_copy(
            update={
                "target_source_count": 1,
                "max_search_queries": 0,
                "max_candidates": 1,
                "max_fetches": 1,
                "max_repair_rounds": 0,
                "metadata": {
                    "collector_adapter": "single_source_search_result",
                    "seed_candidate_id": source_candidate.id,
                },
            }
        )

        async def fetch(url: str):
            if record is not None:
                return await self._trace_fetch(record, "collector", dimension, url, context)
            return await fetch_evidence_page(url)

        result_obj = await run_research_pipeline(
            brief,
            fetch=fetch,
            search=None,
            seed_candidates=[source_candidate],
        )
        sources = self._raw_sources_from_research_result(
            detail,
            brief,
            result_obj,
            batch_sources=[],
            target_source_count=1,
        )
        if not sources and not self._requires_verified_web_evidence(detail, dimension):
            source = self._demo_search_result_source(
                detail,
                competitor,
                dimension,
                result,
                source_candidate,
            )
            return source if self._source_is_usable(source) else None
        if not sources and self._requires_verified_web_evidence(detail, dimension):
            page = result_obj.captured_pages[0] if result_obj.captured_pages else None
            reason = (
                self._fetch_rejection_reason(page)
                if page is not None and page.status != "ok"
                else "research_pipeline_no_accepted_evidence"
            )
            self._trace_rejected_source_candidate(
                record,
                context=context,
                competitor=competitor,
                dimension=dimension,
                title=result.title,
                url=result.url,
                reason=reason,
                candidate=source_candidate,
            )
            return None
        return sources[0] if sources else None

    def _demo_search_result_source(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        result: SearchResult,
        candidate: SourceCandidate,
    ) -> RawSource:
        snippet = result.snippet or result.title
        content_hash = hashlib.sha256(snippet.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return RawSource(
            id=compute_raw_source_id(
                source_type="web_search_result",
                competitor=competitor,
                dimension=dimension,
                url=result.url,
                content_hash=content_hash,
                title=result.title,
                snippet=snippet,
                run_id=detail.id,
            ),
            competitor=competitor,
            dimension=dimension,
            source_type="web_search_result",
            title=result.title,
            url=result.url,
            snippet=snippet,
            content_hash=content_hash,
            confidence=min(0.72, candidate.confidence),
            candidate_origin=candidate.origin,
            candidate_rank=candidate.rank,
            candidate_confidence=candidate.confidence,
            fetch_method="not_fetched_demo",
            quality_score=0.0,
            failure_reason="demo_unverified_search_result",
        )

    def _requires_verified_web_evidence(self, detail: RunDetail, dimension: str) -> bool:
        return detail.execution_mode == "real" and dimension in detail.plan.dimensions

    def _fetch_rejection_reason(self, fetched: Any | None) -> str:
        if fetched is None:
            return "fetch_not_available"
        if getattr(fetched, "ok", False):
            return "not_rejected"
        failure_reason = str(getattr(fetched, "failure_reason", "") or "").strip()
        if failure_reason:
            return f"fetch_failed:{failure_reason[:160]}"
        error = str(getattr(fetched, "error", "") or "").strip()
        if error:
            return f"fetch_failed:{error[:160]}"
        status_code = getattr(fetched, "status_code", None)
        if status_code:
            return f"fetch_failed:http_{status_code}"
        return "fetch_failed"

    def _trace_rejected_source_candidate(
        self,
        record: RunRecord | None,
        *,
        context: SubagentContext | None,
        competitor: str,
        dimension: str,
        title: str,
        url: str | None,
        reason: str,
        candidate: SourceCandidate | None = None,
    ) -> None:
        if record is None:
            return
        self._trace_local_tool(
            record,
            agent="collector",
            subagent=context.subagent if context is not None else dimension,
            name="source_candidate_rejected",
            input_text=json.dumps(
                {
                    "competitor": competitor,
                    "dimension": dimension,
                    "title": title,
                    "url": url,
                    "candidate_origin": candidate.origin if candidate is not None else None,
                    "candidate_rank": candidate.rank if candidate is not None else None,
                    "candidate_confidence": (
                        candidate.confidence if candidate is not None else None
                    ),
                },
                ensure_ascii=False,
            ),
            output_text=json.dumps({"accepted": False, "reason": reason}, ensure_ascii=False),
            context=context,
            metadata={
                "competitor": competitor,
                "dimension": dimension,
                "has_url": bool(url),
                "reason": reason[:180],
                "candidate_origin": candidate.origin if candidate is not None else "unknown",
                "candidate_rank": candidate.rank if candidate is not None else None,
            },
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
        target_source_count = self._collector_target_source_count(detail, dimension)
        collect_payload: dict[str, object] = {
            "provider": self._settings.web_search_provider,
            "results": [],
            "target_source_count": target_source_count,
            **task_metadata,
        }
        memory_official_first = self._memory_prefers_official_sources(detail.plan)
        try:
            sources = await self._collect_competitor_with_web_search(
                record,
                dimension,
                competitor,
                context,
                seed_sources=sources,
                include_official=True,
            )
            collect_payload["research_pipeline_source_count"] = len(sources)
            collect_payload["memory_official_first"] = memory_official_first
        except Exception as exc:  # noqa: BLE001 - deterministic fallbacks continue.
            collect_payload["research_pipeline_error"] = str(exc)
            collect_payload["memory_official_first"] = memory_official_first
        if (
            len(sources) < target_source_count
            and self._settings.collector_react_enabled
            and self._search.is_enabled
        ):
            try:
                react_candidates = await self._run_collector_competitor_react(
                    record, dimension, competitor, context
                )
                react_sources = await self._collect_competitor_with_research_pipeline(
                    record,
                    detail,
                    dimension,
                    competitor,
                    context,
                    batch_sources=sources,
                    target_source_count=target_source_count,
                    include_official=False,
                    seed_candidates=react_candidates,
                    enable_search=False,
                    enable_repair=False,
                )
                self._extend_source_batch(sources, react_sources, target_source_count)
                collect_payload["react_candidate_count"] = len(react_candidates)
                collect_payload["react_pipeline_added"] = len(react_sources)
            except Exception as exc:  # noqa: BLE001 - deterministic fallback continues.
                collect_payload["react_error"] = str(exc)
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
            seed_candidates = self._source_candidates_from_react_finish(
                detail,
                dimension,
                {"sources": raw_sources},
                default_competitor=competitor,
            )
            llm_sources = await self._collect_competitor_with_research_pipeline(
                record,
                detail,
                dimension,
                competitor,
                context,
                batch_sources=sources,
                target_source_count=target_source_count,
                include_official=False,
                seed_candidates=seed_candidates,
                enable_search=False,
                enable_repair=False,
            )
            self._extend_source_batch(sources, llm_sources, target_source_count)
            collect_payload["llm_candidate_count"] = len(seed_candidates)
            collect_payload["llm_pipeline_added"] = len(llm_sources)
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
        # Auto-ingest collected sources into global KB
        try:
            from packages.tools.ingest_document import ingest_document_tool
            for source in detail.raw_sources:
                if source.text and source.ok:
                    await ingest_document_tool.ainvoke({
                        "url": source.url or "",
                        "title": source.title or "",
                        "text": source.text[:50000],
                        "competitor": source.competitor or "",
                        "dimension": source.dimension or "",
                        "source_type": source.source_type or "web",
                    })
        except Exception:
            pass  # Non-fatal: KB ingestion should not block pipeline
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
            covered_competitors = source.covered_competitors or self._normalize_covered_competitors(
                detail, source.competitor
            )
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
                covered = self._cross_source_covered_competitors(detail, source)
                if len(covered) < 2:
                    continue
                source.covered_competitors = covered
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

    def _cross_source_covered_competitors(
        self,
        detail: RunDetail,
        source: RawSource,
    ) -> list[str]:
        text = " ".join(
            [
                source.competitor,
                source.title,
                str(source.url or ""),
                source.snippet,
            ]
        )
        return [
            competitor
            for competitor in detail.plan.competitors
            if self._source_text_mentions_competitor(text, competitor)
        ]

    def _source_text_mentions_competitor(self, text: str, competitor: str) -> bool:
        haystack = " ".join(text.casefold().split())
        for term in self._competitor_mention_terms(competitor):
            if self._term_appears_in_text(term, haystack):
                return True
        return False

    def _competitor_mention_terms(self, competitor: str) -> list[str]:
        generic = {
            "ai",
            "agent",
            "assistant",
            "code",
            "coding",
            "desktop",
            "editor",
            "model",
            "models",
            "openai",
            "tool",
            "tools",
        }
        terms: list[str] = []
        raw_terms = [
            competitor,
            re.sub(r"\([^)]*\)", "", competitor),
            *re.findall(r"\(([^)]*)\)", competitor),
            *identity_terms_for_competitor(competitor),
        ]
        raw_terms.extend(re.split(r"[\s/()&+-]+", competitor))
        seen: set[str] = set()
        for value in raw_terms:
            term = " ".join(str(value).casefold().split()).strip(" -_/")
            if not term or len(term) < 4 or term in generic:
                continue
            if term in seen:
                continue
            seen.add(term)
            terms.append(term)
        return terms

    def _term_appears_in_text(self, term: str, haystack: str) -> bool:
        if any(separator in term for separator in (".", "/")):
            return term in haystack
        parts = [part for part in re.split(r"[\s._/-]+", term) if part]
        if not parts:
            return False
        pattern = r"(?<![a-z0-9])" + r"[\s._/-]+".join(
            re.escape(part) for part in parts
        ) + r"(?![a-z0-9])"
        return re.search(pattern, haystack, flags=re.IGNORECASE) is not None

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
