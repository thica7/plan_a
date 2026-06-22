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
    identity_terms_for_competitor,
    is_trusted_url_for_competitor,
    normalize_competitor_key,
    search_qualifier_for_competitor,
)
from packages.community import (
    CommunityClaimCluster,
    build_community_queries,
    cluster_community_claims,
    extract_community_claims_from_source,
    reclassify_community_source,
    snippet_only_source_from_candidate,
)
from packages.community.source_classifier import classify_community_source
from packages.identity import compute_raw_source_id
from packages.refs import merge_ordered_refs
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


def _metadata_number(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None

KB_INGEST_ALLOWED_SOURCE_TYPES = {
    "official",
    "official_site",
    "official_docs",
    "official_pricing",
    "official_api",
    "trust_center",
    "webpage_verified",
    "verified_webpage",
    "verified_document",
    "review_site",
    "manual_transcript",
    "manual_note",
    "manual",
}

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


class CollectorAgentMixin:
    COLLECTOR_REACT_ACTIONS = (
        "web_search",
        "robots_check",
        "fetch_page",
        "find_official_docs",
        "search_review_site",
    )

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
        allowed_actions = [
            action
            for action in self._collector_react_allowed_actions(dimension)
            if action in {"web_search", "fetch_page", "finish"}
        ]
        for turn in range(1, max_turns + 1):
            payload = await self._trace_llm_json(
                record,
                agent="collector",
                subagent=dimension,
                name=f"{dimension}_react_turn_{turn}",
                system=(
                    "You are a bounded collector ReAct runner. Decide exactly one next action. "
                    f"Allowed actions are {', '.join(allowed_actions)}. "
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
                    f'{{"action":"{"|".join(allowed_actions)}","query":"query or null",'
                    '"url":"https://... or null","rationale":"short reason",'
                    '"sources":[{"competitor":"name","title":"title","url":"https://... or null",'
                    '"summary":"summary","confidence":0.0}]}'
                ),
                context=context,
            )
            action = str(payload.get("action") or "").strip().lower()
            if action not in allowed_actions:
                observations.append(
                    {
                        "turn": turn,
                        "action": action or "unknown",
                        "error": "unsupported_action",
                        "allowed_actions": allowed_actions,
                    }
                )
                continue
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
        allowed_actions = self._collector_react_allowed_actions(dimension)
        for turn in range(1, max_turns + 1):
            payload = await self._trace_llm_json(
                record,
                agent="collector",
                subagent=context.subagent,
                name=f"{dimension}_{self._issue_id_fragment(competitor)}_collector_react_turn_{turn}",
                system=(
                    "You are a bounded collector ReAct runner for exactly one competitor "
                    "and one dimension. "
                    f"Allowed actions are {', '.join(allowed_actions)}. "
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
                    f'{{"action":"{"|".join(allowed_actions)}","query":"query or null",'
                    '"url":"https://... or null","rationale":"short reason",'
                    '"sources":[{"title":"title","url":"https://... or null",'
                    '"summary":"summary","confidence":0.0}]}'
                ),
                context=context,
            )
            action = str(payload.get("action") or "").strip().lower()
            if action not in allowed_actions:
                observations.append(
                    {
                        "turn": turn,
                        "action": action or "unknown",
                        "error": "unsupported_action",
                        "allowed_actions": allowed_actions,
                    }
                )
                continue
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

    def _collector_react_allowed_actions(self, dimension: str) -> list[str]:
        skill = self._skill_registry.get(dimension)
        configured = list(skill.tools_allowlist if skill is not None else [])
        supported = set(self.COLLECTOR_REACT_ACTIONS)
        actions: list[str] = []
        for action in configured:
            if action in supported and action not in actions:
                actions.append(action)
        if not actions:
            actions.extend(["web_search", "fetch_page"])
        actions.append("finish")
        return actions

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

    def _record_collector_coverage(
        self,
        run_id: str,
        subagent: str,
        competitor: str,
        dimension: str,
        coverage: dict[str, object],
    ) -> None:
        if not hasattr(self, "_collector_coverage_by_branch"):
            self._collector_coverage_by_branch = {}
        self._collector_coverage_by_branch[
            (run_id, subagent, competitor.casefold(), dimension.casefold())
        ] = dict(coverage)

    def _collector_coverage_for(
        self,
        run_id: str,
        subagent: str,
        competitor: str,
        dimension: str,
    ) -> dict[str, object] | None:
        store = getattr(self, "_collector_coverage_by_branch", {})
        value = store.get((run_id, subagent, competitor.casefold(), dimension.casefold()))
        return dict(value) if isinstance(value, dict) else None

    @staticmethod
    def _collector_coverage_failed(coverage: dict[str, object] | None) -> bool:
        if not coverage:
            return False
        return coverage.get("passed") is False

    async def _collect_competitor_from_kb(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
        *,
        target_source_count: int,
    ) -> list[RawSource]:
        query = self._kb_retrieval_query(detail, competitor, dimension)
        request = {
            "query": query,
            "competitors": [competitor],
            "dimensions": [dimension],
            "top_k": max(target_source_count * 3, 5),
            "mode": "sparse",
        }
        try:
            from packages.tools.rag_retrieve import rag_retrieve_tool

            raw_hits = await rag_retrieve_tool.ainvoke(request)
        except Exception as exc:  # noqa: BLE001 - KB reuse is a warm-start, not a hard dependency.
            self._trace_local_tool(
                record,
                agent="collector",
                subagent=context.subagent,
                name="rag_kb_warm_start",
                input_text=json.dumps(request, ensure_ascii=False),
                output_text=json.dumps({"error": str(exc), "degraded": True}, ensure_ascii=False),
                context=context,
                metadata={"degraded": True, "source_count": 0},
            )
            return []

        hits = raw_hits if isinstance(raw_hits, list) else []
        sources: list[RawSource] = []
        rejections: list[dict[str, object]] = []
        for rank, hit in enumerate(hits):
            if not isinstance(hit, dict):
                rejections.append({"rank": rank, "reason": "invalid_hit"})
                continue
            rejection_reason = self._kb_hit_rejection_reason(hit)
            if rejection_reason is not None:
                rejections.append(
                    self._kb_hit_rejection_diagnostic(
                        hit,
                        rank=rank,
                        reason=rejection_reason,
                    )
                )
                continue
            source = self._raw_source_from_kb_hit(
                detail,
                competitor,
                dimension,
                hit,
                rank=rank,
                query=query,
            )
            if source is None:
                rejections.append(
                    self._kb_hit_rejection_diagnostic(
                        hit,
                        rank=rank,
                        reason="raw_source_build_failed",
                    )
                )
                continue
            if self._candidate_already_collected(
                detail,
                sources,
                competitor=competitor,
                dimension=dimension,
                url=str(source.url) if source.url else None,
            ):
                rejections.append(
                    self._kb_hit_rejection_diagnostic(
                        hit,
                        rank=rank,
                        reason="duplicate_source",
                        source_id=source.id,
                    )
                )
                continue
            problem = self._source_quality_problem(source)
            if problem is not None:
                rejections.append(
                    self._kb_hit_rejection_diagnostic(
                        hit,
                        rank=rank,
                        reason="source_quality_problem",
                        source_id=source.id,
                        detail=problem,
                    )
                )
                continue
            sources.append(source)
            if len(sources) >= target_source_count:
                break

        self._trace_local_tool(
            record,
            agent="collector",
            subagent=context.subagent,
            name="rag_kb_warm_start",
            input_text=json.dumps(request, ensure_ascii=False),
            output_text=json.dumps(
                {
                    "hit_count": len(hits),
                    "source_ids": [source.id for source in sources],
                    "rejections": rejections[:8],
                },
                ensure_ascii=False,
            ),
            context=context,
            metadata={
                "hit_count": len(hits),
                "source_count": len(sources),
                "rejection_count": len(rejections),
                "top_rejection_reason": self._top_kb_rejection_reason(rejections),
            },
        )
        return sources

    @staticmethod
    def _kb_hit_rejection_reason(hit: dict[str, object]) -> str | None:
        text = str(hit.get("text") or "").strip()
        url = str(hit.get("url") or "").strip()
        source_type = str(hit.get("source_type") or "webpage_verified").strip()
        if not text:
            return "missing_text"
        if not url:
            return "missing_url"
        if not url.startswith(("http://", "https://")):
            return "non_http_url"
        if source_type in {"llm_public_knowledge", "web_search_result"}:
            return "disallowed_source_type"
        return None

    @staticmethod
    def _kb_hit_rejection_diagnostic(
        hit: dict[str, object],
        *,
        rank: int,
        reason: str,
        source_id: str | None = None,
        detail: str | None = None,
    ) -> dict[str, object]:
        diagnostic: dict[str, object] = {"rank": rank, "reason": reason}
        field_map = {
            "document_id": "document_id",
            "chunk_id": "chunk_id",
            "source_type": "source_type",
            "url": "url",
            "title": "title",
            "status": "status",
            "competitor": "competitor",
            "dimension": "dimension",
        }
        for source_key, target_key in field_map.items():
            value = hit.get(source_key)
            if value not in (None, ""):
                diagnostic[target_key] = str(value)
        score = _metadata_number(hit.get("rerank_score"))
        if score is None:
            score = _metadata_number(hit.get("score"))
        if score is not None:
            diagnostic["score"] = score
        if source_id:
            diagnostic["source_id"] = source_id
        if detail:
            diagnostic["detail"] = detail[:300]
        hit_metadata = hit.get("metadata")
        if isinstance(hit_metadata, dict):
            raw_source_id = hit_metadata.get("raw_source_id") or hit_metadata.get(
                "kb_raw_source_id"
            )
            collector_run_id = hit_metadata.get("run_id") or hit_metadata.get(
                "kb_collector_run_id"
            )
            if raw_source_id not in (None, ""):
                diagnostic["kb_raw_source_id"] = str(raw_source_id)
            if collector_run_id not in (None, ""):
                diagnostic["kb_collector_run_id"] = str(collector_run_id)
        return diagnostic

    @staticmethod
    def _top_kb_rejection_reason(rejections: list[dict[str, object]]) -> str | None:
        counts: dict[str, int] = {}
        for item in rejections:
            reason = str(item.get("reason") or "").strip()
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda item: item[1])[0]

    @staticmethod
    def _copy_kb_source_metadata(
        metadata: dict[str, object],
        hit_metadata: dict[str, Any],
    ) -> None:
        key_map = {
            "raw_source_id": "kb_raw_source_id",
            "kb_raw_source_id": "kb_raw_source_id",
            "run_id": "kb_collector_run_id",
            "collector_run_id": "kb_collector_run_id",
            "kb_collector_run_id": "kb_collector_run_id",
            "collector_candidate_origin": "kb_collector_candidate_origin",
            "kb_collector_candidate_origin": "kb_collector_candidate_origin",
            "collector_fetch_method": "kb_collector_fetch_method",
            "kb_collector_fetch_method": "kb_collector_fetch_method",
        }
        for source_key, target_key in key_map.items():
            value = hit_metadata.get(source_key)
            if value not in (None, "") and target_key not in metadata:
                metadata[target_key] = str(value)
        confidence = hit_metadata.get("collector_confidence")
        if confidence is None:
            confidence = hit_metadata.get("kb_collector_confidence")
        if confidence is not None:
            metadata["kb_collector_confidence"] = confidence

    def _kb_retrieval_query(self, detail: RunDetail, competitor: str, dimension: str) -> str:
        skill = self._skill_registry.get(dimension)
        parts = [
            self._web_search_query(detail, competitor, dimension),
            detail.topic,
            competitor,
            dimension,
            skill.description if skill is not None else "",
        ]
        seen: set[str] = set()
        terms: list[str] = []
        for part in parts:
            value = " ".join(str(part).split())
            key = value.casefold()
            if not value or key in seen:
                continue
            seen.add(key)
            terms.append(value)
        return " ".join(terms)

    def _raw_source_from_kb_hit(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        hit: dict[str, object],
        *,
        rank: int,
        query: str,
    ) -> RawSource | None:
        text = str(hit.get("text") or "").strip()
        url = str(hit.get("url") or "").strip()
        if not text or not url.startswith(("http://", "https://")):
            return None
        source_type = (
            str(hit.get("source_type") or "webpage_verified").strip()
            or "webpage_verified"
        )
        if source_type in {"llm_public_knowledge", "web_search_result"}:
            return None
        title = str(hit.get("title") or f"{competitor} {dimension} KB evidence").strip()
        snippet = self._dimension_evidence_snippet(text, dimension, text[:1000])
        content_hash = str(hit.get("content_hash") or "").strip() or hashlib.sha256(
            text.encode("utf-8", errors="ignore")
        ).hexdigest()[:16]
        score = self._coerce_confidence(
            hit.get("rerank_score") if hit.get("rerank_score") is not None else hit.get("score"),
            default=0.5,
        )
        hit_metadata = hit.get("metadata")
        if not isinstance(hit_metadata, dict):
            hit_metadata = {}
        confidence = max(
            0.89,
            min(0.96, 0.86 + score * 0.10),
            self._verified_source_confidence(detail, competitor, dimension, url, snippet),
        )
        metadata = {
            "kb_retrieved": True,
            "kb_retrieval_query": query,
            "kb_document_id": str(hit.get("document_id") or ""),
            "kb_chunk_id": str(hit.get("chunk_id") or ""),
            "kb_hit_score": score,
            "kb_rerank_score": hit.get("rerank_score"),
            "kb_source_type": source_type,
            "kb_competitor": str(hit.get("competitor") or ""),
            "kb_dimension": str(hit.get("dimension") or ""),
            "kb_document_status": str(hit.get("status") or "active"),
            "kb_fetched_at": str(hit.get("fetched_at") or ""),
            "kb_last_seen_at": str(hit.get("last_seen_at") or ""),
            "source_material_level": "kb_retrieval_chunk",
        }
        self._copy_kb_source_metadata(metadata, hit_metadata)
        try:
            return RawSource(
                id=compute_raw_source_id(
                    source_type=source_type,
                    competitor=competitor,
                    dimension=dimension,
                    url=url,
                    content_hash=content_hash,
                    title=title,
                    snippet=snippet,
                    run_id=detail.id,
                    source_role="kb-retrieved",
                ),
                competitor=competitor,
                dimension=dimension,
                source_type=source_type,
                title=title,
                url=url,
                snippet=snippet,
                content_hash=content_hash,
                confidence=confidence,
                candidate_origin="rag_kb",
                candidate_rank=rank,
                candidate_confidence=score,
                fetch_method="rag_kb_retrieve",
                quality_score=confidence,
                metadata=metadata,
            )
        except Exception:
            return None

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
            try:
                return await self._trace_fetch(record, "collector", dimension, url, context)
            except Exception:  # noqa: BLE001 - one failed candidate should not abort collection.
                return None

        result = await run_research_pipeline(
            brief,
            fetch=fetch,
            search=search if enable_search and self._search.is_enabled else None,
            seed_candidates=seed_candidates,
        )
        if result.coverage is not None:
            self._record_collector_coverage(
                detail.id,
                context.subagent,
                competitor,
                dimension,
                result.coverage.model_dump(mode="json"),
            )
        admission_diagnostics: list[dict[str, object]] = []
        sources = self._raw_sources_from_research_result(
            detail,
            brief,
            result,
            batch_sources=batch_sources,
            target_source_count=target_source_count,
            rejection_diagnostics=admission_diagnostics,
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
                    "admission_rejections": admission_diagnostics[:12],
                    "candidate_ledger": [
                        {
                            "candidate_id": entry.candidate_id,
                            "url": entry.url,
                            "origin": entry.origin,
                            "intent": entry.intent,
                            "status": entry.status,
                            "reason": entry.reason,
                            "selected": entry.selected,
                            "fetched": entry.fetched,
                            "source_fitness": entry.source_fitness,
                            "coverage_intent": entry.coverage_intent,
                            "final_url": entry.final_url,
                            "page_status": entry.page_status,
                            "evidence_status": entry.evidence_status,
                        }
                        for entry in result.candidate_ledger[:12]
                    ],
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
                "admission_rejection_count": len(admission_diagnostics),
                "candidate_ledger_count": len(result.candidate_ledger),
                "source_fitness_counts": json.dumps(
                    result.metrics.get("source_fitness_counts", {}),
                    ensure_ascii=False,
                ),
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
        rejection_diagnostics: list[dict[str, object]] | None = None,
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
            source_is_usable=self._research_source_is_usable,
            rejection_diagnostics=rejection_diagnostics,
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
        if self._dimension_needs_persona_strength_gate(dimension):
            persona_terms = (
                "customers case studies developer adoption user reviews "
                "onboarding switching workflow fit"
            )
            query = f"{query} {persona_terms}"
        qualifier = self._competitor_search_qualifier(competitor)
        if qualifier and qualifier.casefold() not in query.casefold():
            query = f"{query} {qualifier}"
        return f"{query} {detail.topic} official source"

    async def _community_source_candidates(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
    ) -> list[SourceCandidate]:
        if not self._settings.collector_community_enabled or not self._search.is_enabled:
            return []
        queries = build_community_queries(
            competitor=competitor,
            dimension=dimension,
            topic=detail.topic,
            limit=max(0, int(self._settings.collector_community_queries_per_branch)),
        )
        candidates: list[SourceCandidate] = []
        for query in queries:
            results = await self._trace_search(
                record,
                agent="collector",
                subagent=context.subagent,
                query=query,
                max_results=max(1, int(self._settings.collector_community_max_results_per_query)),
                context=context,
            )
            for rank, result in enumerate(results):
                classification = classify_community_source(
                    url=result.url,
                    title=result.title,
                    snippet=result.snippet,
                )
                if not classification.is_community:
                    continue
                candidates.append(
                    SourceCandidate(
                        title=result.title,
                        url=result.url,
                        snippet=result.snippet,
                        origin="community_search",
                        competitor=competitor,
                        dimension=dimension,
                        rank=rank,
                        confidence=classification.base_confidence,
                        query=query,
                        date=result.date,
                        last_updated=result.last_updated,
                        reason="community_evidence_search",
                        metadata={
                            "community_evidence": True,
                            "community_source_type": classification.source_type,
                            "community_authority_signal": classification.authority_signal,
                            "community_classification_reason": classification.reason,
                        },
                    )
                )
        self._append_agent_message(
            record,
            from_agent="collector",
            to_agent="collect_join",
            message_type="community_search_completed",
            payload_schema="CommunitySearchSummary",
            payload={
                "competitor": competitor,
                "dimension": dimension,
                "queries": queries,
                "query_count": len(queries),
                "candidate_count": len(candidates),
                "candidate_ids": [candidate.id for candidate in candidates],
                "no_result": not candidates,
            },
        )
        return candidates

    async def _collect_community_sources_for_branch(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
    ) -> list[RawSource]:
        target_count = max(0, int(self._settings.collector_community_target_sources_per_branch))
        if target_count <= 0:
            return []
        candidates = await self._community_source_candidates(
            record, detail, dimension, competitor, context
        )
        if not candidates:
            return []
        fetched_sources = await self._collect_competitor_with_research_pipeline(
            record,
            detail,
            dimension,
            competitor,
            context,
            batch_sources=[],
            target_source_count=target_count,
            include_official=False,
            seed_candidates=candidates,
            enable_search=False,
            enable_repair=False,
        )
        community_sources = [
            reclassify_community_source(source, run_id=detail.id) for source in fetched_sources
        ]
        if len(community_sources) < target_count:
            existing_urls = {
                str(source.url).rstrip("/")
                for source in community_sources
                if source.url is not None
            }
            for candidate in candidates:
                if len(community_sources) >= target_count:
                    break
                if candidate.url.rstrip("/") in existing_urls:
                    continue
                snippet_source = snippet_only_source_from_candidate(candidate, run_id=detail.id)
                if snippet_source is None:
                    continue
                community_sources.append(snippet_source)
                existing_urls.add(candidate.url.rstrip("/"))
        return [
            source
            for source in community_sources
            if not self._candidate_already_collected(
                detail,
                [],
                competitor=competitor,
                dimension=dimension,
                url=str(source.url) if source.url else None,
            )
        ]

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
        if "persona" in normalized or "user" in normalized:
            return [
                "persona",
                "customer",
                "customers",
                "user",
                "buyer",
                "case study",
                "case studies",
                "customer story",
                "developer adoption",
                "review",
                "feedback",
                "workflow fit",
                "onboarding",
                "switching",
            ]
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
        if "persona" in normalized or "user" in normalized:
            return [
                "developer",
                "developers",
                "engineering team",
                "enterprise team",
                "customer adoption",
                "user reviews",
                "buyer persona",
                "workflow fit",
                "onboarding effort",
                "switching cost",
                "use case",
                "pain point",
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

    def _research_source_is_usable(self, source: RawSource) -> bool:
        problem = self._source_quality_problem(source)
        if problem is None:
            return True
        if (
            source.candidate_origin == "community_search"
            and "does not expose a recognizable" in problem
            and self._community_source_mentions_competitor(source)
        ):
            classification = classify_community_source(
                url=str(source.url or ""),
                title=source.title,
                snippet=source.snippet,
            )
            return classification.is_community
        return False

    def _community_source_mentions_competitor(self, source: RawSource) -> bool:
        haystack = f"{source.title}\n{source.url or ''}\n{source.snippet}".casefold()
        competitor_terms = {
            source.competitor.casefold(),
            normalize_competitor_key(source.competitor),
        }
        return any(term and term in haystack for term in competitor_terms)

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
                for term in [
                    "developer",
                    "customer",
                    "enterprise",
                    "team",
                    "user",
                    "adoption",
                    "review",
                    "feedback",
                    "workflow fit",
                    "onboarding",
                    "switching",
                    "use case",
                ]
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
                    r"enterprise|adoption|use case|user reviews?|feedback|workflow fit|"
                    r"onboarding|switching|pain point)",
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
        admission_diagnostics: list[dict[str, object]] = []
        sources = self._raw_sources_from_research_result(
            detail,
            brief,
            result_obj,
            batch_sources=[],
            target_source_count=1,
            rejection_diagnostics=admission_diagnostics,
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
                else self._admission_rejection_reason(admission_diagnostics)
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

    def _admission_rejection_reason(self, diagnostics: list[dict[str, object]]) -> str:
        if not diagnostics:
            return "research_pipeline_no_accepted_evidence"
        first = diagnostics[0]
        reason = str(first.get("reason") or "raw_source_admission_rejected")
        detail = str(first.get("detail") or "").strip()
        if detail:
            return f"{reason}:{detail[:180]}"
        return reason

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
            kb_sources = await self._collect_competitor_from_kb(
                record,
                detail,
                dimension,
                competitor,
                context,
                target_source_count=target_source_count,
            )
            self._extend_source_batch(sources, kb_sources, target_source_count)
            collect_payload["kb_warm_start_source_count"] = len(kb_sources)
            collect_payload["kb_warm_start_source_ids"] = [source.id for source in kb_sources]
        except Exception as exc:  # noqa: BLE001 - KB warm-start must never block collection.
            collect_payload["kb_warm_start_error"] = str(exc)
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
        coverage = self._collector_coverage_for(
            detail.id,
            context.subagent,
            competitor,
            dimension,
        )
        if coverage is not None:
            collect_payload["coverage_contract"] = coverage
        coverage_repair_needed = self._collector_coverage_failed(coverage)
        if (
            (len(sources) < target_source_count or coverage_repair_needed)
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
                if coverage_repair_needed:
                    for source in react_sources:
                        if not self._source_already_in_batch(source, sources):
                            sources.append(source)
                else:
                    self._extend_source_batch(sources, react_sources, target_source_count)
                collect_payload["react_candidate_count"] = len(react_candidates)
                collect_payload["react_pipeline_added"] = len(react_sources)
                collect_payload["react_triggered_by_coverage"] = coverage_repair_needed
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
        community_sources = [
            source for source in sources if source.metadata.get("community_evidence")
        ]
        if not community_sources:
            try:
                community_sources = await self._collect_community_sources_for_branch(
                    record,
                    detail,
                    dimension,
                    competitor,
                    context,
                )
            except Exception as exc:  # noqa: BLE001 - optional community search degrades.
                collect_payload["community_error"] = str(exc)
                self._append_agent_message(
                    record,
                    from_agent="collector",
                    to_agent="collect_join",
                    message_type="community_search_failed",
                    payload_schema="CommunitySearchSummary",
                    payload={
                        "competitor": competitor,
                        "dimension": dimension,
                        "queries": [],
                        "query_count": 0,
                        "candidate_count": 0,
                        "candidate_ids": [],
                        "no_result": True,
                        "failed": True,
                        "error": str(exc),
                    },
                    source_message_ids=[task_message.id],
                )
                community_sources = []
            for source in community_sources:
                if not self._source_already_in_batch(source, sources):
                    sources.append(source)
        collect_payload["community_source_count"] = len(community_sources)
        collect_payload["community_source_ids"] = [source.id for source in community_sources]
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

    async def _sync_collected_sources_to_kb(
        self,
        record: RunRecord,
        detail: RunDetail,
        sources: list[RawSource],
        context: SubagentContext | None = None,
    ) -> dict[str, object]:
        try:
            from packages.tools.ingest_document import ingest_document_tool
        except Exception as exc:  # noqa: BLE001 - KB persistence is non-blocking.
            return {"attempted": 0, "ingested": 0, "error": str(exc)}

        attempted = 0
        ingested = 0
        skipped: list[dict[str, str]] = []
        errors: list[str] = []
        for source in sources:
            text = self._kb_text_from_raw_source(source)
            skip_reason = self._kb_ingest_skip_reason(source, text)
            if skip_reason:
                skipped.append({"source_id": source.id, "reason": skip_reason})
                continue
            attempted += 1
            try:
                await ingest_document_tool.ainvoke(
                    {
                        "url": str(source.url) if source.url else "",
                        "title": source.title or source.id,
                        "text": text[:50000],
                        "competitor": source.competitor or "",
                        "dimension": source.dimension or "",
                        "source_type": source.source_type or "webpage_verified",
                        "metadata": {
                            **source.metadata,
                            "run_id": detail.id,
                            "raw_source_id": source.id,
                            "collector_confidence": source.confidence,
                            "collector_candidate_origin": source.candidate_origin,
                            "collector_fetch_method": source.fetch_method,
                        },
                        "crawl_run_id": detail.id,
                        "index_vectors": False,
                    }
                )
                ingested += 1
            except Exception as exc:  # noqa: BLE001 - one bad KB write must not block the run.
                errors.append(f"{source.id}: {str(exc)[:160]}")

        summary: dict[str, object] = {
            "attempted": attempted,
            "ingested": ingested,
            "skipped": skipped[:12],
            "errors": errors[:5],
        }
        self._trace_local_tool(
            record,
            agent="collect_join",
            subagent="collect_join",
            name="kb_ingest_collected_sources",
            input_text=json.dumps(
                {"source_ids": [source.id for source in sources]}, ensure_ascii=False
            ),
            output_text=json.dumps(summary, ensure_ascii=False),
            context=context,
            metadata={
                "attempted": attempted,
                "ingested": ingested,
                "skipped": len(skipped),
                "errors": len(errors),
            },
        )
        return summary

    def _kb_text_from_raw_source(self, source: RawSource) -> str:
        pieces = [source.title, source.snippet]
        full_text = source.metadata.get("full_text")
        if isinstance(full_text, str):
            pieces.append(full_text)
        return "\n\n".join(
            part.strip() for part in pieces if isinstance(part, str) and part.strip()
        )

    def _kb_ingest_skip_reason(self, source: RawSource, text: str) -> str:
        if source.metadata.get("kb_retrieved"):
            return "already_from_kb"
        if not source.url:
            return "missing_url"
        if source.source_type.casefold() not in KB_INGEST_ALLOWED_SOURCE_TYPES:
            return "source_type_not_allowlisted"
        if source.failure_reason:
            return "failed_source"
        if source.confidence < 0.75:
            return "low_confidence"
        if len(text.strip()) < 40:
            return "text_too_short"
        if self._source_quality_problem(source) is not None:
            return "source_quality_problem"
        return ""

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
                "community_search_completed",
                "community_search_failed",
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
            message_types={
                "community_search_completed",
                "community_search_failed",
                "cross_competitor_sources_collected",
                "cross_competitor_search_failed",
            },
        )
        detail.raw_sources = self._normalize_collected_sources(detail, dimensions)
        self._annotate_community_claim_clusters(detail, dimensions)
        normalized_count = len(detail.raw_sources)
        kb_ingest = await self._sync_collected_sources_to_kb(record, detail, detail.raw_sources)
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
                "kb_ingest": kb_ingest,
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
                    "kb_ingest": kb_ingest,
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

    def _annotate_community_claim_clusters(
        self,
        detail: RunDetail,
        dimensions: list[str],
    ) -> None:
        scoped_dimensions = set(dimensions)
        claims = [
            claim
            for source in detail.raw_sources
            if (not scoped_dimensions or source.dimension in scoped_dimensions)
            for claim in extract_community_claims_from_source(source)
        ]
        clusters = cluster_community_claims(claims)
        clusters_by_source_id: dict[str, list[dict[str, object]]] = {}
        for cluster in clusters:
            payload = cluster.model_dump(mode="json")
            if (
                payload.get("label") == "community_observed"
                and cluster.independent_domain_count >= 2
                and len(cluster.source_ids) >= 2
                and cluster.confidence >= 0.70
            ):
                payload["label"] = "community_triangulated"
            official_source_ids = self._official_confirmation_source_ids(detail, cluster)
            if official_source_ids:
                payload["label"] = "official_confirmed"
                payload["confidence"] = max(float(payload.get("confidence") or 0.0), 0.95)
                payload["official_source_ids"] = official_source_ids
                payload["source_ids"] = merge_ordered_refs(
                    cluster.source_ids,
                    official_source_ids,
                )
            for source_id in cluster.source_ids:
                clusters_by_source_id.setdefault(source_id, []).append(payload)
        updated_sources: list[RawSource] = []
        for source in detail.raw_sources:
            source_clusters = clusters_by_source_id.get(source.id)
            if not source_clusters:
                updated_sources.append(source)
                continue
            metadata = dict(source.metadata)
            metadata["community_claim_clusters"] = source_clusters
            updated_sources.append(source.model_copy(update={"metadata": metadata}))
        detail.raw_sources = updated_sources

    def _official_confirmation_source_ids(
        self,
        detail: RunDetail,
        cluster: CommunityClaimCluster,
    ) -> list[str]:
        if not self._cluster_has_concrete_official_confirmation_value(cluster):
            return []
        normalized_value = cluster.normalized_value.casefold()
        return [
            source.id
            for source in detail.raw_sources
            if source.competitor == cluster.competitor
            and source.dimension == cluster.dimension
            and source.source_type == "webpage_verified"
            and normalized_value in source.snippet.casefold()
        ]

    def _cluster_has_concrete_official_confirmation_value(
        self,
        cluster: CommunityClaimCluster,
    ) -> bool:
        normalized_value = cluster.normalized_value.strip()
        if cluster.kind != "pricing" or not normalized_value:
            return False
        return normalized_value.startswith("$") or any(
            character.isdigit() for character in normalized_value
        )

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
            weak_persona_competitors = self._weak_persona_branch_competitors(detail, dimension)
            if (
                len(covered_competitors) >= len(detail.plan.competitors)
                and not weak_persona_competitors
            ):
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
                        "weak_persona_competitors": weak_persona_competitors,
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

    def _weak_persona_branch_competitors(
        self,
        detail: RunDetail,
        dimension: str,
    ) -> list[str]:
        if not self._dimension_needs_persona_strength_gate(dimension):
            return []
        weak: list[str] = []
        for competitor in detail.plan.competitors:
            strength = self._persona_evidence_strength(detail, dimension, competitor)
            if strength.is_weak and strength.reason != "no_sources":
                weak.append(competitor)
        return weak

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
            focus = (
                "target users customers personas use cases developer adoption user reviews "
                "onboarding switching workflow fit comparison"
            )
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
