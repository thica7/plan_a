from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from packages.agents import SubagentContext
from packages.agents.analysts.citation_tools import inspect_sources, validate_source_ids
from packages.memory import KBCacheEntry
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    CompetitorKB,
    CompetitorKnowledge,
    FeatureNode,
    FeatureTree,
    KnowledgeClaim,
    PricingModel,
    PricingTier,
    RawSource,
    UserPersonaModel,
    UserPersonaSegment,
)

CORE_SCHEMA_DIMENSIONS = ("pricing", "feature", "persona")

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


class AnalystAgentMixin:
    async def _real_analyst_dispatch_step(
        self,
        record: RunRecord,
        dimensions: list[str],
        competitors: list[str],
    ) -> None:
        detail = record.detail
        detail.current_node = "analyst_dispatch"
        self._consume_queued_agent_messages(
            record,
            to_agent="analyst_dispatch",
            consumer_agent="analyst_dispatch",
            message_types={"collect_qa_result"},
        )
        branch_count = len(dimensions) * len(competitors)
        self._append_agent_message(
            record,
            from_agent="collect_join",
            to_agent="analyst_dispatch",
            message_type="dispatch_analysts",
            payload_schema="AnalystDispatchPlan",
            payload={
                "topic": detail.topic,
                "dimensions": dimensions,
                "competitors": competitors,
                "branch_count": branch_count,
                "fanout": "competitor_x_slice",
                "source_ids": [
                    source.id
                    for source in detail.raw_sources
                    if source.dimension in dimensions
                    and any(
                        self._source_matches_competitor(source, competitor)
                        for competitor in competitors
                    )
                ],
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_started",
            "analyst_dispatch",
            None,
            f"Dispatching {branch_count} analyst branch(es).",
            {"dimensions": dimensions, "competitors": competitors, "branch_count": branch_count},
        )
        await self.emit(
            detail.id,
            "node_completed",
            "analyst_dispatch",
            None,
            "Analyst dispatch completed.",
            {"fanout": "competitor_x_slice"},
        )

    async def _run_analyst_react(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
        dimension_sources: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        detail = record.detail
        observations: list[dict[str, object]] = []
        inspected = False
        validated_source_ids: set[str] = set()
        qa_feedback = [
            item
            for competitor in detail.plan.competitors
            for item in self._qa_feedback_for_branch(detail, "analyst", dimension, competitor)
        ]
        max_turns = self._analyst_task_max_turns(detail.plan, dimension)
        for turn in range(1, max_turns + 1):
            payload = await self._trace_llm_json(
                record,
                agent="analyst",
                subagent=dimension,
                name=f"{dimension}_analyst_react_turn_{turn}",
                system=(
                    "You are a bounded analyst ReAct runner. Decide exactly one next action. "
                    "Allowed actions are inspect_sources, validate_citations, finish. "
                    "Use only the provided RawSource JSON. Do not invent facts. "
                    "Finish only when findings are grouped by competitor and cite source IDs "
                    "when possible."
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Dimension: {dimension}\n"
                    f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Sources JSON: {json.dumps(dimension_sources, ensure_ascii=False)}\n"
                    f"QA feedback for redo: {json.dumps(qa_feedback, ensure_ascii=False)}\n"
                    f"Observations JSON: {json.dumps(observations, ensure_ascii=False)}\n\n"
                    "Return one action. For finish, include competitor_findings, "
                    "source_ids_used, and caveats."
                ),
                schema_hint=(
                    '{"action":"inspect_sources|validate_citations|finish",'
                    '"source_ids":["source-id"],"rationale":"short reason",'
                    '"competitor_findings":{"competitor":["finding with source id"]},'
                    '"source_ids_used":["source-id"],"caveats":["caveat"]}'
                ),
                context=context,
            )
            action = str(payload.get("action") or "").strip().lower()
            if action == "inspect_sources":
                observation = self._inspect_sources_tool(
                    record, dimension, context, dimension_sources
                )
                inspected = True
                observations.append({"turn": turn, "action": action, "observation": observation})
                continue
            if action == "validate_citations":
                requested_source_ids = self._string_list(
                    payload.get("source_ids") or payload.get("source_ids_used")
                )
                observation = self._validate_source_ids_tool(
                    record,
                    dimension,
                    context,
                    dimension_sources,
                    requested_source_ids,
                )
                validated_source_ids.update(
                    str(source_id) for source_id in observation["valid_source_ids"]
                )
                observations.append({"turn": turn, "action": action, "observation": observation})
                continue
            if action == "finish":
                normalized = self._normalize_competitor_findings(detail, payload)
                if not any(findings for findings in normalized.values()):
                    observations.append({"turn": turn, "action": action, "error": "empty_findings"})
                    continue
                if not inspected:
                    observation = self._inspect_sources_tool(
                        record, dimension, context, dimension_sources
                    )
                    inspected = True
                    observations.append(
                        {
                            "turn": turn,
                            "action": "inspect_sources",
                            "observation": observation,
                            "reason": "required_before_finish",
                        }
                    )
                used_source_ids = self._source_ids_from_analyst_payload(payload, dimension_sources)
                unvalidated_source_ids = [
                    source_id
                    for source_id in used_source_ids
                    if source_id not in validated_source_ids
                ]
                if used_source_ids and unvalidated_source_ids:
                    observation = self._validate_source_ids_tool(
                        record,
                        dimension,
                        context,
                        dimension_sources,
                        unvalidated_source_ids,
                    )
                    validated_source_ids.update(
                        str(source_id) for source_id in observation["valid_source_ids"]
                    )
                    observations.append(
                        {
                            "turn": turn,
                            "action": "validate_citations",
                            "observation": observation,
                            "reason": "required_before_finish",
                        }
                    )
                    if (
                        observation["unknown_source_ids"]
                        and turn < max_turns
                    ):
                        continue
                return self._ensure_analyst_citations(detail, dimension, payload, normalized)
            observations.append(
                {"turn": turn, "action": action or "unknown", "error": "unsupported_action"}
            )
        return None

    def _source_ids_from_analyst_payload(
        self,
        payload: dict[str, Any],
        dimension_sources: list[dict[str, Any]],
    ) -> list[str]:
        known_source_ids = [
            str(source.get("id") or "")
            for source in dimension_sources
            if str(source.get("id") or "").strip()
        ]
        explicit_ids = self._string_list(
            payload.get("source_ids_used") or payload.get("source_ids")
        )
        payload_text = json.dumps(payload, ensure_ascii=False)
        found_ids: list[str] = []
        seen: set[str] = set()
        for source_id in [*explicit_ids, *known_source_ids]:
            if not source_id or source_id in seen:
                continue
            if source_id in explicit_ids or source_id in payload_text:
                found_ids.append(source_id)
                seen.add(source_id)
        return found_ids

    def _ensure_analyst_citations(
        self,
        detail: RunDetail,
        dimension: str,
        payload: dict[str, Any],
        normalized: dict[str, list[str]],
    ) -> dict[str, Any]:
        source_ids_by_competitor: dict[str, list[str]] = {
            competitor: [
                source.id
                for source in detail.raw_sources
                if source.dimension == dimension
                and self._source_matches_competitor(source, competitor)
            ]
            for competitor in detail.plan.competitors
        }
        competitor_findings: dict[str, list[str]] = {}
        changed = False
        for competitor in detail.plan.competitors:
            competitor_source_ids = source_ids_by_competitor.get(competitor, [])
            findings: list[str] = []
            for finding in normalized.get(competitor, []):
                has_known_citation = any(
                    source_id in finding for source_id in competitor_source_ids
                )
                if not has_known_citation and competitor_source_ids:
                    finding = f"{finding} [source:{competitor_source_ids[0]}]"
                    changed = True
                findings.append(finding)
            competitor_findings[competitor] = findings
        if not changed:
            return payload
        enriched = dict(payload)
        enriched["competitor_findings"] = competitor_findings
        enriched["source_ids_used"] = sorted(
            {
                source_id
                for source_ids in source_ids_by_competitor.values()
                for source_id in source_ids
                if any(
                    source_id in finding
                    for findings in competitor_findings.values()
                    for finding in findings
                )
            }
        )
        return enriched

    def _inspect_sources_tool(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
        dimension_sources: list[dict[str, Any]],
    ) -> dict[str, object]:
        return inspect_sources(
            self,
            record,
            dimension=dimension,
            context=context,
            dimension_sources=dimension_sources,
        )

    def _source_dict_matches_competitor(self, source: dict[str, Any], competitor: str) -> bool:
        covered = source.get("covered_competitors")
        if isinstance(covered, list):
            return competitor in [str(value) for value in covered]
        return self._competitor_label_matches(str(source.get("competitor") or ""), competitor)

    def _validate_source_ids_tool(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
        dimension_sources: list[dict[str, Any]],
        requested_source_ids: list[str],
    ) -> dict[str, object]:
        return validate_source_ids(
            self,
            record,
            dimension=dimension,
            context=context,
            dimension_sources=dimension_sources,
            requested_source_ids=requested_source_ids,
        )

    async def _run_analyst_competitor_react(
        self,
        record: RunRecord,
        dimension: str,
        competitor: str,
        context: SubagentContext,
        dimension_sources: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        detail = record.detail
        observations: list[dict[str, object]] = []
        inspected = False
        validated_source_ids: set[str] = set()
        qa_feedback = self._qa_feedback_for_branch(detail, "analyst", dimension, competitor)
        max_turns = self._analyst_task_max_turns(detail.plan, dimension, competitor)
        for turn in range(1, max_turns + 1):
            payload = await self._trace_llm_json(
                record,
                agent="analyst",
                subagent=context.subagent,
                name=f"{dimension}_{self._issue_id_fragment(competitor)}_analyst_react_turn_{turn}",
                system=(
                    "You are a bounded analyst ReAct runner for exactly one competitor "
                    "and one dimension. "
                    "Decide exactly one next action. Allowed actions are inspect_sources, "
                    "validate_citations, finish. "
                    "Use only the provided RawSource JSON. Do not invent facts. "
                    "Finish only with strict structured knowledge whose claims cite source IDs."
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Competitor: {competitor}\n"
                    f"Dimension: {dimension}\n"
                    f"Sources JSON: {json.dumps(dimension_sources, ensure_ascii=False)}\n"
                    f"QA feedback for redo: {json.dumps(qa_feedback, ensure_ascii=False)}\n"
                    f"Observations JSON: {json.dumps(observations, ensure_ascii=False)}\n\n"
                    "Return one action. For finish, include the strict structured "
                    "knowledge slice for this dimension."
                ),
                schema_hint=json.dumps(
                    {
                        "action": "inspect_sources|validate_citations|finish",
                        "source_ids": ["source-id"],
                        "rationale": "short reason",
                        "structured_knowledge": json.loads(
                            self._structured_knowledge_schema_hint(dimension)
                        ),
                    }
                ),
                context=context,
            )
            action = str(payload.get("action") or "").strip().lower()
            if action == "inspect_sources":
                observation = self._inspect_sources_tool(
                    record, dimension, context, dimension_sources
                )
                inspected = True
                observations.append({"turn": turn, "action": action, "observation": observation})
                continue
            if action == "validate_citations":
                requested_source_ids = self._string_list(
                    payload.get("source_ids") or payload.get("source_ids_used")
                )
                observation = self._validate_source_ids_tool(
                    record,
                    dimension,
                    context,
                    dimension_sources,
                    requested_source_ids,
                )
                validated_source_ids.update(
                    str(source_id) for source_id in observation["valid_source_ids"]
                )
                observations.append({"turn": turn, "action": action, "observation": observation})
                continue
            if action == "finish":
                claims = self._claims_from_structured_payload(payload, dimension)
                if not claims:
                    observations.append({"turn": turn, "action": action, "error": "empty_findings"})
                    continue
                if not inspected:
                    observation = self._inspect_sources_tool(
                        record, dimension, context, dimension_sources
                    )
                    inspected = True
                    observations.append(
                        {
                            "turn": turn,
                            "action": "inspect_sources",
                            "observation": observation,
                            "reason": "required_before_finish",
                        }
                    )
                used_source_ids = self._source_ids_from_analyst_payload(payload, dimension_sources)
                unvalidated_source_ids = [
                    source_id
                    for source_id in used_source_ids
                    if source_id not in validated_source_ids
                ]
                if used_source_ids and unvalidated_source_ids:
                    observation = self._validate_source_ids_tool(
                        record,
                        dimension,
                        context,
                        dimension_sources,
                        unvalidated_source_ids,
                    )
                    validated_source_ids.update(
                        str(source_id) for source_id in observation["valid_source_ids"]
                    )
                    observations.append(
                        {
                            "turn": turn,
                            "action": "validate_citations",
                            "observation": observation,
                            "reason": "required_before_finish",
                        }
                    )
                    if (
                        observation["unknown_source_ids"]
                        and turn < max_turns
                    ):
                        continue
                return payload
            observations.append(
                {"turn": turn, "action": action or "unknown", "error": "unsupported_action"}
            )
        return None

    async def _real_analyst_branch_step(
        self, record: RunRecord, dimension: str, competitor: str
    ) -> None:
        detail = record.detail
        branch_id = self._analyst_branch_id(dimension, competitor)
        context = SubagentContext(run_id=detail.id, agent="analyst", subagent=branch_id)
        detail.current_node = "analyst"
        qa_feedback = self._qa_feedback_for_branch(detail, "analyst", dimension, competitor)
        task_metadata = self._plan_task_metadata(
            detail.plan, "analyst", dimension, competitor
        )
        task_message = self._append_agent_message(
            record,
            from_agent="analyst_dispatch",
            to_agent="analyst",
            message_type="analysis_task",
            payload_schema="AnalysisTaskPayload",
            payload={
                "competitor": competitor,
                "dimension": dimension,
                "source_ids": [
                    source.id
                    for source in self._sources_for_competitor_dimension(
                        detail, competitor, dimension
                    )
                ],
                "qa_feedback": qa_feedback,
                **task_metadata,
            },
        )
        self._consume_agent_message(record, task_message, consumer_agent="analyst", context=context)
        await self.emit(
            detail.id,
            "node_started",
            "analyst",
            branch_id,
            f"Calling {competitor} / {dimension} analyst.",
            {
                "context": context.metadata(),
                "dimension": dimension,
                "competitor": competitor,
                **task_metadata,
            },
        )
        dimension_sources = [
            source.model_dump(mode="json")
            for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
        ]
        cache_content_hash = self._kb_cache_content_hash(detail, competitor, dimension)
        if self._kb_cache is not None and cache_content_hash and not qa_feedback:
            cache_entry = self._kb_cache.get(competitor, dimension, cache_content_hash)
            if cache_entry is not None:
                self._apply_kb_cache_entry(detail, cache_entry)
                self._append_agent_message(
                    record,
                    from_agent="kb_cache",
                    to_agent="analyst_join",
                    message_type="kb_cache_hit",
                    payload_schema="KBCacheEntry",
                    payload={
                        "competitor": competitor,
                        "dimension": dimension,
                        "content_hash": cache_content_hash,
                        "source_ids": cache_entry.source_ids,
                    },
                )
                detail.updated_at = datetime.utcnow()
                await self.emit(
                    detail.id,
                    "node_completed",
                    "analyst",
                    branch_id,
                    f"KB cache reused {competitor} / {dimension} slice.",
                    {
                        "cache": {
                            "hit": True,
                            "content_hash": cache_content_hash,
                            "source_ids": cache_entry.source_ids,
                        },
                        "context": context.metadata(),
                        "dimension": dimension,
                        "competitor": competitor,
                        **task_metadata,
                    },
                )
                return
        react_payload: dict[str, object] = {}
        use_react = self._should_use_analyst_react(
            detail,
            dimension=dimension,
            qa_feedback=qa_feedback,
        )
        if use_react:
            try:
                payload = await self._run_analyst_competitor_react(
                    record,
                    dimension,
                    competitor,
                    context,
                    dimension_sources,
                )
                if payload is not None:
                    self._merge_structured_knowledge_payload(detail, competitor, dimension, payload)
                    self._store_kb_cache_entry(detail, competitor, dimension, cache_content_hash)
                    knowledge = detail.competitor_knowledge.get(competitor)
                    self._append_agent_message(
                        record,
                        from_agent="analyst",
                        to_agent="analyst_join",
                        message_type="competitor_knowledge_ready",
                        payload_schema="CompetitorKnowledge",
                        payload={
                            "competitor": competitor,
                            "dimension": dimension,
                            "knowledge": knowledge.model_dump(mode="json") if knowledge else {},
                        },
                        source_message_ids=[task_message.id],
                    )
                    detail.updated_at = datetime.utcnow()
                    await self.emit(
                        detail.id,
                        "node_completed",
                        "analyst",
                        branch_id,
                        f"ReAct analyst completed {competitor} / {dimension} slice.",
                        {
                            "analysis": payload,
                            "context": context.metadata(),
                            "dimension": dimension,
                            "competitor": competitor,
                            **task_metadata,
                        },
                    )
                    return
            except Exception as exc:  # noqa: BLE001 - bounded ReAct falls back to one-shot analysis.
                react_payload["react_error"] = str(exc)
        elif self._settings.analyst_react_enabled:
            react_payload["react_skipped"] = "fanout_budget"
            react_payload["fanout_branch_count"] = self._analyst_fanout_branch_count(detail)
            react_payload["fanout_threshold"] = self._settings.analyst_react_fanout_threshold

        qa_feedback_json = json.dumps(qa_feedback, ensure_ascii=False)
        branch_timeout = self._analyst_branch_timeout_seconds(
            detail,
            qa_feedback=qa_feedback,
        )
        try:
            payload = await asyncio.wait_for(
                self._trace_llm_json(
                    record,
                    agent="analyst",
                    subagent=branch_id,
                    name=f"{dimension}_{self._issue_id_fragment(competitor)}_analyst",
                    system=(
                        "You are an analyst subagent. Produce strict structured competitor "
                        "knowledge for exactly one competitor and one dimension. Do not output "
                        "free-form findings as the primary artifact. Every factual claim must "
                        "include at least one source_id from the provided RawSource JSON."
                    ),
                    user=(
                        f"Topic: {detail.topic}\n"
                        f"Competitor: {competitor}\n"
                        f"Dimension: {dimension}\n"
                        f"Sources JSON: {json.dumps(dimension_sources, ensure_ascii=False)}\n\n"
                        f"QA feedback for this branch: {qa_feedback_json}\n\n"
                        "Return only the relevant CompetitorKnowledge slice for this dimension."
                    ),
                    schema_hint=self._structured_knowledge_schema_hint(dimension),
                    context=context,
                ),
                timeout=branch_timeout,
            )
        except TimeoutError:
            payload = self._deterministic_structured_knowledge_payload(
                competitor=competitor,
                dimension=dimension,
                dimension_sources=dimension_sources,
            )
            react_payload["analysis_timeout"] = (
                f"one-shot analyst exceeded {branch_timeout:g}s"
            )
            react_payload["deterministic_fallback"] = True
        self._merge_structured_knowledge_payload(detail, competitor, dimension, payload)
        self._store_kb_cache_entry(detail, competitor, dimension, cache_content_hash)
        knowledge = detail.competitor_knowledge.get(competitor)
        self._append_agent_message(
            record,
            from_agent="analyst",
            to_agent="analyst_join",
            message_type="competitor_knowledge_ready",
            payload_schema="CompetitorKnowledge",
            payload={
                "competitor": competitor,
                "dimension": dimension,
                "knowledge": knowledge.model_dump(mode="json") if knowledge else {},
            },
            source_message_ids=[task_message.id],
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "analyst",
            branch_id,
            f"Analyst completed {competitor} / {dimension} slice.",
            {
                "analysis": payload,
                "react": react_payload,
                "context": context.metadata(),
                "dimension": dimension,
                "competitor": competitor,
                **task_metadata,
            },
        )

    def _should_use_analyst_react(
        self,
        detail: RunDetail,
        *,
        dimension: str,
        qa_feedback: list[dict[str, Any]],
    ) -> bool:
        if not self._settings.analyst_react_enabled:
            return False
        if qa_feedback:
            return True
        if (
            self._analyst_fanout_branch_count(detail)
            <= self._settings.analyst_react_fanout_threshold
        ):
            return True
        dimension_sources = [
            source
            for source in detail.raw_sources
            if source.dimension == dimension
        ]
        return not dimension_sources

    def _analyst_fanout_branch_count(self, detail: RunDetail) -> int:
        return len(detail.plan.competitors) * len(detail.plan.dimensions)

    def _analyst_branch_timeout_seconds(
        self,
        detail: RunDetail,
        *,
        qa_feedback: list[dict[str, Any]],
    ) -> float:
        base_timeout = max(0.05, float(self._settings.analyst_branch_timeout_seconds))
        if qa_feedback:
            return base_timeout
        if (
            self._analyst_fanout_branch_count(detail)
            <= self._settings.analyst_react_fanout_threshold
        ):
            return base_timeout
        fanout_timeout = max(
            0.05,
            float(self._settings.analyst_fanout_branch_timeout_seconds),
        )
        return min(base_timeout, fanout_timeout)

    def _deterministic_structured_knowledge_payload(
        self,
        *,
        competitor: str,
        dimension: str,
        dimension_sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        usable_sources = [
            source
            for source in dimension_sources
            if str(source.get("id") or "").strip()
        ][:3]
        claims = [
            {
                "claim": self._deterministic_claim_text(competitor, dimension, source),
                "source_ids": [str(source.get("id"))],
                "confidence": float(source.get("confidence") or 0.65),
            }
            for source in usable_sources
        ]
        if not claims:
            claims = [
                {
                    "claim": f"{competitor} has no usable {dimension} source in this run.",
                    "source_ids": [],
                    "confidence": 0.0,
                }
            ]
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            claim_text = " ".join(str(claim.get("claim") or "") for claim in claims)
            return {
                "pricing_model": {
                    "tiers": [
                        {
                            "name": "Extracted pricing evidence",
                            "price": self._extract_price_hint(claim_text),
                            "billing_cycle": "unknown",
                            "limits": [],
                            "claims": claims,
                        }
                    ]
                    if claims
                    else [],
                    "notes": claims,
                }
            }
        if "persona" in dimension_key or "user" in dimension_key:
            return {
                "user_personas": {
                    "segments": [
                        {
                            "name": "Inferred target segment",
                            "role": "unknown",
                            "company_size": "unknown",
                            "pain_points": [],
                            "use_cases": [
                                str(claim.get("claim") or "") for claim in claims[:3]
                            ],
                            "claims": claims,
                        }
                    ]
                    if claims
                    else [],
                    "summary_claims": claims,
                }
            }
        return {
            "feature_tree": {
                "nodes": [
                    {
                        "name": f"{dimension} evidence",
                        "description": claim["claim"],
                        "claims": [claim],
                        "children": [],
                    }
                    for claim in claims
                ],
                "summary_claims": claims,
            }
        }

    def _deterministic_claim_text(
        self,
        competitor: str,
        dimension: str,
        source: dict[str, Any],
    ) -> str:
        snippet = " ".join(str(source.get("snippet") or "").split())
        title = " ".join(str(source.get("title") or "").split())
        evidence_text = snippet or title or "has collected evidence"
        return f"{competitor} {dimension}: {evidence_text[:240]}"

    async def _real_analyst_step(self, record: RunRecord, dimension: str) -> None:
        detail = record.detail
        context = SubagentContext(run_id=detail.id, agent="analyst", subagent=dimension)
        detail.current_node = "analyst"
        await self.emit(
            detail.id,
            "node_started",
            "analyst",
            dimension,
            f"Calling {dimension} analyst.",
            {"context": context.metadata()},
        )
        dimension_sources = [
            source.model_dump(mode="json")
            for source in detail.raw_sources
            if source.dimension == dimension
        ]
        react_payload: dict[str, object] = {}
        if self._settings.analyst_react_enabled:
            try:
                payload = await self._run_analyst_react(
                    record, dimension, context, dimension_sources
                )
                if payload is not None:
                    self._merge_kb_slice(
                        detail, dimension, self._normalize_competitor_findings(detail, payload)
                    )
                    detail.updated_at = datetime.utcnow()
                    await self.emit(
                        detail.id,
                        "node_completed",
                        "analyst",
                        dimension,
                        f"ReAct analyst completed {dimension} slice.",
                        {"analysis": payload, "context": context.metadata()},
                    )
                    return
            except Exception as exc:  # noqa: BLE001 - bounded ReAct falls back to one-shot analysis.
                react_payload["react_error"] = str(exc)

        payload = await self._trace_llm_json(
            record,
            agent="analyst",
            subagent=dimension,
            name=f"{dimension}_analyst",
            system=(
                "You are an analyst subagent. Convert source candidates into "
                "comparison-ready findings."
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Dimension: {dimension}\n"
                f"Sources JSON: {json.dumps(dimension_sources, ensure_ascii=False)}\n\n"
                "Return concise findings grouped by competitor. Use only the provided sources."
            ),
            schema_hint='{"competitor_findings":{"competitor":["finding"]},"caveats":["caveat"]}',
            context=context,
        )
        self._merge_kb_slice(
            detail, dimension, self._normalize_competitor_findings(detail, payload)
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "analyst",
            dimension,
            f"Analyst completed {dimension} slice.",
            {"analysis": payload, "react": react_payload, "context": context.metadata()},
        )

    async def _real_analyst_join_step(
        self,
        record: RunRecord,
        dimensions: list[str],
        competitors: list[str],
    ) -> None:
        detail = record.detail
        detail.current_node = "analyst_join"
        self._consume_queued_agent_messages(
            record,
            to_agent="analyst_join",
            consumer_agent="analyst_join",
            message_types={"competitor_knowledge_ready", "kb_cache_hit"},
        )
        kb_summary = {
            competitor: {
                "dimensions": sorted(
                    dimension
                    for dimension in dimensions
                    if detail.competitor_kbs.get(competitor)
                    and detail.competitor_kbs[competitor].slices.get(dimension)
                ),
                "source_ids": detail.competitor_kbs.get(competitor).sources
                if detail.competitor_kbs.get(competitor)
                else [],
            }
            for competitor in competitors
        }
        self._append_agent_message(
            record,
            from_agent="analyst_join",
            to_agent="qa",
            message_type="analyst_join_completed",
            payload_schema="CompetitorKBDigest",
            payload={
                "dimensions": dimensions,
                "competitors": competitors,
                "kb_summary": kb_summary,
                "competitor_knowledge_count": len(detail.competitor_knowledge),
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_started",
            "analyst_join",
            None,
            "Merging analyst branch outputs.",
            {"dimensions": dimensions, "competitors": competitors},
        )
        await self.emit(
            detail.id,
            "node_completed",
            "analyst_join",
            None,
            "Analyst join completed.",
            {"kb_summary": kb_summary},
        )

    def _sources_for_competitor_dimension(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> list[RawSource]:
        return [
            source
            for source in detail.raw_sources
            if source.dimension == dimension and self._source_matches_competitor(source, competitor)
        ]

    def _kb_cache_content_hash(self, detail: RunDetail, competitor: str, dimension: str) -> str:
        sources = self._sources_for_competitor_dimension(detail, competitor, dimension)
        if not sources:
            return ""
        basis = [
            {
                "id": source.id,
                "content_hash": source.content_hash,
                "source_type": source.source_type,
                "url": str(source.url) if source.url else "",
            }
            for source in sorted(sources, key=lambda item: item.id)
        ]
        return hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:24]

    def _apply_kb_cache_entry(self, detail: RunDetail, entry: KBCacheEntry) -> None:
        kb = detail.competitor_kbs.get(entry.competitor) or CompetitorKB(
            competitor=entry.competitor
        )
        kb.slices[entry.dimension] = entry.kb_slice
        kb.sources = sorted(set(kb.sources + entry.source_ids))
        kb.confidence = entry.confidence
        detail.competitor_kbs[entry.competitor] = kb

        knowledge = detail.competitor_knowledge.get(entry.competitor) or CompetitorKnowledge(
            competitor=entry.competitor
        )
        cached = entry.knowledge
        dimension_key = entry.dimension.casefold()
        if "pricing" in dimension_key:
            knowledge.pricing_model = cached.pricing_model
        elif "persona" in dimension_key or "user" in dimension_key:
            knowledge.user_personas = cached.user_personas
        else:
            knowledge.feature_tree = cached.feature_tree
        knowledge.source_ids = sorted(
            set(knowledge.source_ids + entry.source_ids + cached.source_ids)
        )
        knowledge.confidence = max(knowledge.confidence, cached.confidence, entry.confidence)
        detail.competitor_knowledge[entry.competitor] = knowledge

    def _store_kb_cache_entry(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        content_hash: str,
    ) -> None:
        if self._kb_cache is None or not content_hash:
            return
        kb = detail.competitor_kbs.get(competitor)
        knowledge = detail.competitor_knowledge.get(competitor)
        if kb is None or knowledge is None or not kb.slices.get(dimension):
            return
        entry = KBCacheEntry(
            competitor=competitor,
            dimension=dimension,
            content_hash=content_hash,
            kb_slice=kb.slices.get(dimension, []),
            source_ids=[
                source.id
                for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
            ],
            confidence=kb.confidence,
            knowledge=knowledge,
        )
        self._kb_cache.put(entry)

    def _merge_kb_slice(
        self,
        detail: RunDetail,
        dimension: str,
        competitor_findings: dict[str, list[str]],
    ) -> None:
        for competitor in detail.plan.competitors:
            findings = [
                finding for finding in competitor_findings.get(competitor, []) if finding.strip()
            ]
            if not findings:
                findings = [
                    source.snippet or source.title
                    for source in self._sources_for_competitor_dimension(
                        detail, competitor, dimension
                    )
                ][:3]
            kb = detail.competitor_kbs.get(competitor) or CompetitorKB(competitor=competitor)
            kb.slices[dimension] = findings
            source_ids = [
                source.id
                for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
            ]
            kb.sources = sorted(set(kb.sources + source_ids))
            source_confidences = [
                source.confidence
                for source in detail.raw_sources
                if self._source_matches_competitor(source, competitor)
            ]
            kb.confidence = (
                sum(source_confidences) / len(source_confidences)
                if source_confidences
                else kb.confidence
            )
            detail.competitor_kbs[competitor] = kb
            self._merge_structured_knowledge_slice(detail, competitor, dimension, findings)

    def _merge_competitor_kb_slice(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        findings: list[str],
    ) -> None:
        clean_findings = [finding for finding in findings if finding.strip()]
        if not clean_findings:
            clean_findings = [
                source.snippet or source.title
                for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
            ][:3]
        kb = detail.competitor_kbs.get(competitor) or CompetitorKB(competitor=competitor)
        kb.slices[dimension] = clean_findings
        source_ids = [
            source.id
            for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
        ]
        kb.sources = sorted(set(kb.sources + source_ids))
        source_confidences = [
            source.confidence
            for source in detail.raw_sources
            if self._source_matches_competitor(source, competitor)
        ]
        kb.confidence = (
            sum(source_confidences) / len(source_confidences)
            if source_confidences
            else kb.confidence
        )
        detail.competitor_kbs[competitor] = kb
        self._merge_structured_knowledge_slice(detail, competitor, dimension, clean_findings)

    def _merge_structured_knowledge_slice(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        findings: list[str],
    ) -> None:
        knowledge = detail.competitor_knowledge.get(competitor) or CompetitorKnowledge(
            competitor=competitor
        )
        claims = self._claims_from_findings(detail, competitor, dimension, findings)
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            knowledge.pricing_model.notes = claims
            if claims:
                knowledge.pricing_model.tiers = [
                    PricingTier(
                        name="Extracted pricing evidence",
                        claims=claims,
                        price=self._extract_price_hint(" ".join(claim.claim for claim in claims)),
                    )
                ]
        elif "persona" in dimension_key or "user" in dimension_key:
            knowledge.user_personas.summary_claims = claims
            if claims:
                knowledge.user_personas.segments = [
                    UserPersonaSegment(
                        name="Inferred target segment",
                        claims=claims,
                        use_cases=[claim.claim for claim in claims[:3]],
                    )
                ]
        else:
            knowledge.feature_tree.summary_claims = claims
            knowledge.feature_tree.nodes = [
                FeatureNode(name=dimension, description=claim.claim, claims=[claim])
                for claim in claims
            ]
        source_ids = [
            source.id
            for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
        ]
        knowledge.source_ids = sorted(set(knowledge.source_ids + source_ids))
        source_confidences = [
            source.confidence
            for source in detail.raw_sources
            if self._source_matches_competitor(source, competitor)
        ]
        knowledge.confidence = (
            sum(source_confidences) / len(source_confidences)
            if source_confidences
            else knowledge.confidence
        )
        detail.competitor_knowledge[competitor] = knowledge

    def _merge_structured_knowledge_payload(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        payload: dict[str, Any],
    ) -> None:
        raw = payload.get("structured_knowledge")
        if not isinstance(raw, dict):
            raw = payload
        knowledge = detail.competitor_knowledge.get(competitor) or CompetitorKnowledge(
            competitor=competitor
        )
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            section = raw.get("pricing_model")
            if isinstance(section, dict):
                try:
                    knowledge.pricing_model = PricingModel.model_validate(section)
                except Exception:
                    knowledge.pricing_model.tiers = []
                    knowledge.pricing_model.notes = []
        elif "persona" in dimension_key or "user" in dimension_key:
            section = raw.get("user_personas")
            if isinstance(section, dict):
                try:
                    knowledge.user_personas = UserPersonaModel.model_validate(section)
                except Exception:
                    knowledge.user_personas.segments = []
                    knowledge.user_personas.summary_claims = []
        else:
            section = raw.get("feature_tree")
            if isinstance(section, dict):
                try:
                    knowledge.feature_tree = FeatureTree.model_validate(section)
                except Exception:
                    knowledge.feature_tree.nodes = []
                    knowledge.feature_tree.summary_claims = []

        claims = self._structured_claims_for_dimension(knowledge, dimension)
        knowledge.source_ids = sorted(
            {
                source_id
                for source_id in [
                    *knowledge.source_ids,
                    *[sid for claim in claims for sid in claim.source_ids],
                ]
            }
        )
        knowledge.confidence = self._claim_list_confidence(claims)
        detail.competitor_knowledge[competitor] = knowledge
        self._sync_legacy_kb_from_structured_knowledge(detail, competitor, dimension, claims)

    def _sync_legacy_kb_from_structured_knowledge(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        claims: list[KnowledgeClaim],
    ) -> None:
        kb = detail.competitor_kbs.get(competitor) or CompetitorKB(competitor=competitor)
        kb.slices[dimension] = [
            f"{claim.claim} [source:{claim.source_ids[0]}]"
            if claim.source_ids[0] not in claim.claim
            else claim.claim
            for claim in claims
        ]
        kb.sources = sorted(
            set(kb.sources + [source_id for claim in claims for source_id in claim.source_ids])
        )
        kb.confidence = self._claim_list_confidence(claims)
        detail.competitor_kbs[competitor] = kb

    def _claim_list_confidence(self, claims: list[KnowledgeClaim]) -> float:
        if not claims:
            return 0.0
        return sum(claim.confidence for claim in claims) / len(claims)

    def _structured_knowledge_schema_hint(self, dimension: str) -> str:
        claim = {"claim": "factual claim", "source_ids": ["source-id"], "confidence": 0.0}
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            return json.dumps(
                {
                    "pricing_model": {
                        "tiers": [
                            {
                                "name": "tier name",
                                "price": "price or unknown",
                                "billing_cycle": "monthly|annual|usage|unknown",
                                "limits": ["limit"],
                                "claims": [claim],
                            }
                        ],
                        "notes": [claim],
                    }
                }
            )
        if "persona" in dimension_key or "user" in dimension_key:
            return json.dumps(
                {
                    "user_personas": {
                        "segments": [
                            {
                                "name": "segment",
                                "role": "role or unknown",
                                "company_size": "size or unknown",
                                "pain_points": ["pain"],
                                "use_cases": ["case"],
                                "claims": [claim],
                            }
                        ],
                        "summary_claims": [claim],
                    }
                }
            )
        return json.dumps(
            {
                "feature_tree": {
                    "nodes": [
                        {
                            "name": "feature category",
                            "description": "description",
                            "claims": [claim],
                            "children": [],
                        }
                    ],
                    "summary_claims": [claim],
                }
            }
        )

    def _claims_from_structured_payload(
        self, payload: dict[str, Any], dimension: str
    ) -> list[KnowledgeClaim]:
        raw = payload.get("structured_knowledge")
        if not isinstance(raw, dict):
            raw = payload
        try:
            probe = CompetitorKnowledge(competitor="probe")
            dimension_key = dimension.casefold()
            if "pricing" in dimension_key and isinstance(raw.get("pricing_model"), dict):
                probe.pricing_model = PricingModel.model_validate(raw["pricing_model"])
            elif ("persona" in dimension_key or "user" in dimension_key) and isinstance(
                raw.get("user_personas"), dict
            ):
                probe.user_personas = UserPersonaModel.model_validate(raw["user_personas"])
            elif isinstance(raw.get("feature_tree"), dict):
                probe.feature_tree = FeatureTree.model_validate(raw["feature_tree"])
            return self._structured_claims_for_dimension(probe, dimension)
        except Exception:
            return []

    def _claims_from_findings(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        findings: list[str],
    ) -> list[KnowledgeClaim]:
        fallback_source_ids = [
            source.id
            for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
        ]
        claims: list[KnowledgeClaim] = []
        for finding in findings:
            clean = finding.strip()
            if not clean:
                continue
            source_ids = sorted(self._extract_cited_source_ids(clean))
            if not source_ids:
                source_ids = fallback_source_ids[:1]
            if not source_ids:
                continue
            confidence = self._claim_confidence(detail, source_ids)
            claims.append(KnowledgeClaim(claim=clean, source_ids=source_ids, confidence=confidence))
        return claims

    def _claim_confidence(self, detail: RunDetail, source_ids: list[str]) -> float:
        confidences = [
            source.confidence for source in detail.raw_sources if source.id in source_ids
        ]
        if not confidences:
            return 0.0
        return sum(confidences) / len(confidences)

    def _extract_price_hint(self, text: str) -> str:
        match = re.search(
            r"(?:\$|USD\s*)\s?\d+(?:[.,]\d+)?(?:\s?/\s?\w+)?", text, flags=re.IGNORECASE
        )
        return match.group(0) if match else "unknown"

    def _normalize_competitor_findings(
        self, detail: RunDetail, payload: dict
    ) -> dict[str, list[str]]:
        raw = payload.get("competitor_findings")
        if isinstance(raw, dict):
            normalized: dict[str, list[str]] = {}
            for competitor in detail.plan.competitors:
                values = raw.get(competitor) or raw.get(competitor.lower()) or []
                if isinstance(values, list):
                    normalized[competitor] = [str(value) for value in values if str(value).strip()]
                elif values:
                    normalized[competitor] = [str(values)]
            return normalized

        findings = self._string_list(payload.get("findings"))
        return {competitor: findings for competitor in detail.plan.competitors}

    def _normalize_single_competitor_findings(
        self,
        payload: dict[str, Any],
        competitor: str,
    ) -> list[str]:
        raw = payload.get("competitor_findings")
        if isinstance(raw, dict):
            values = raw.get(competitor) or raw.get(competitor.lower()) or []
            if isinstance(values, list):
                return [str(value) for value in values if str(value).strip()]
            if values:
                return [str(values)]
        return self._string_list(payload.get("findings"))

    def _ensure_single_analyst_citations(
        self,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        payload: dict[str, Any],
        findings: list[str],
    ) -> dict[str, Any]:
        competitor_source_ids = [
            source.id
            for source in detail.raw_sources
            if source.dimension == dimension and self._source_matches_competitor(source, competitor)
        ]
        enriched_findings: list[str] = []
        changed = False
        for finding in findings:
            has_known_citation = any(source_id in finding for source_id in competitor_source_ids)
            if not has_known_citation and competitor_source_ids:
                finding = f"{finding} [source:{competitor_source_ids[0]}]"
                changed = True
            enriched_findings.append(finding)
        if not changed and payload.get("competitor_findings"):
            return payload
        enriched = dict(payload)
        enriched["competitor_findings"] = {competitor: enriched_findings}
        enriched["source_ids_used"] = sorted(
            {
                source_id
                for source_id in competitor_source_ids
                if any(source_id in finding for finding in enriched_findings)
            }
        )
        return enriched
