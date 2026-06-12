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
from packages.refs import merge_ordered_refs
from packages.research.evidence.text import (
    deterministic_claim_text_from_source,
    source_business_snippet,
)
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
    ReviewThemeItem,
    ReviewThemeSummary,
    UserPersonaModel,
    UserPersonaSegment,
)

CORE_SCHEMA_DIMENSIONS = ("pricing", "feature", "persona")
REVIEW_SUMMARY_DIMENSION_HINTS = (
    "review",
    "persona",
    "user",
    "customer",
    "buyer",
    "feedback",
    "adoption",
    "switching",
)
POSITIVE_REVIEW_TERMS = (
    "praise",
    "like",
    "liked",
    "love",
    "fast",
    "easy",
    "strong",
    "preferred",
    "adopted",
    "productive",
    "accelerate",
)
NEGATIVE_REVIEW_TERMS = (
    "complain",
    "complaint",
    "friction",
    "difficult",
    "slow",
    "confusing",
    "expensive",
    "risk",
    "cost",
    "onboarding",
    "effort",
    "uncertainty",
    "blocker",
    "concern",
    "pain",
)
SWITCHING_REVIEW_TERMS = (
    "switch",
    "switching",
    "migrate",
    "migration",
    "replace",
    "alternative",
)

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
                    payload, fallback_reason = self._ensure_structured_payload_has_claims(
                        competitor=competitor,
                        dimension=dimension,
                        dimension_sources=dimension_sources,
                        payload=payload,
                    )
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
                            "fallback_reason": fallback_reason,
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
        payload, fallback_reason = self._ensure_structured_payload_has_claims(
            competitor=competitor,
            dimension=dimension,
            dimension_sources=dimension_sources,
            payload=payload,
        )
        if fallback_reason:
            react_payload["fallback_reason"] = fallback_reason
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

    def _ensure_structured_payload_has_claims(
        self,
        *,
        competitor: str,
        dimension: str,
        dimension_sources: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if self._claims_from_structured_payload(payload, dimension):
            return payload, ""
        if not any(str(source.get("id") or "").strip() for source in dimension_sources):
            return payload, ""
        return (
            self._deterministic_structured_knowledge_payload(
                competitor=competitor,
                dimension=dimension,
                dimension_sources=dimension_sources,
            ),
            "empty_structured_payload",
        )

    def _deterministic_structured_knowledge_payload(
        self,
        *,
        competitor: str,
        dimension: str,
        dimension_sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        uses_review_summary = self._dimension_uses_review_summary(dimension)
        usable_sources = [
            source
            for source in dimension_sources
            if str(source.get("id") or "").strip()
            and (
                source_business_snippet(source, dimension=dimension)
                or (
                    uses_review_summary
                    and any(
                        str(source.get(key) or "").strip()
                        for key in ("summary", "snippet", "text")
                    )
                )
            )
        ][:3]
        claims = [
            {
                "claim": deterministic_claim_text_from_source(
                    competitor=competitor,
                    dimension=dimension,
                    source=source,
                ),
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
        review_summary = (
            self._build_review_summary_from_source_dicts(
                competitor=competitor,
                dimension=dimension,
                sources=usable_sources,
            )
            if uses_review_summary
            else None
        )
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            claim_models = [
                KnowledgeClaim.model_validate(claim)
                for claim in claims
                if claim.get("source_ids")
            ]
            claim_text = " ".join(claim.claim for claim in claim_models)
            return {
                "pricing_model": {
                    "tiers": [
                        tier.model_dump(mode="json")
                        for tier in self._pricing_tiers_from_text(
                            claim_text, claim_models
                        )
                    ]
                    if claim_models
                    else [],
                    "notes": claims,
                }
            }
        if "persona" in dimension_key or "user" in dimension_key:
            claim_models = [
                KnowledgeClaim.model_validate(claim)
                for claim in claims
                if claim.get("source_ids")
            ]
            claim_text = " ".join(claim.claim for claim in claim_models)
            payload = {
                "user_personas": {
                    "segments": [
                        segment.model_dump(mode="json")
                        for segment in self._persona_segments_from_text(
                            claim_text, competitor, claim_models
                        )
                    ]
                    if claim_models
                    else [],
                    "summary_claims": claims,
                }
            }
            if review_summary is not None:
                payload["review_summary"] = review_summary.model_dump(mode="json")
            return payload
        if review_summary is not None:
            return {"review_summary": review_summary.model_dump(mode="json")}
        claim_models = [
            KnowledgeClaim.model_validate(claim)
            for claim in claims
            if claim.get("source_ids")
        ]
        return {
            "feature_tree": {
                "nodes": [
                    node.model_dump(mode="json")
                    for node in self._feature_nodes_from_text(
                        " ".join(claim.claim for claim in claim_models),
                        claim_models,
                    )
                ]
                if claim_models
                else [],
                "summary_claims": claims,
            }
        }

    def _deterministic_claim_text(
        self,
        competitor: str,
        dimension: str,
        source: dict[str, Any],
    ) -> str:
        return deterministic_claim_text_from_source(
            competitor=competitor,
            dimension=dimension,
            source=source,
        )

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

    def _source_matches_competitor(self, source: RawSource, competitor: str) -> bool:
        if source.covered_competitors:
            return competitor in source.covered_competitors
        return self._competitor_label_matches(source.competitor, competitor)

    def _competitor_label_matches(self, source_competitor: str, competitor: str) -> bool:
        source_competitor = source_competitor.strip()
        source_key = source_competitor.casefold()
        competitor_key = competitor.strip().casefold()
        if source_key == competitor_key:
            return True
        if self._competitor_label_means_all(source_key):
            return True
        parts = [
            part.strip().casefold()
            for part in re.split(r",|;|/|\||\s+and\s+|\s*&\s*", source_competitor)
            if part.strip()
        ]
        if competitor_key in parts:
            return True
        return competitor_key in source_key

    def _competitor_label_means_all(self, source_key: str) -> bool:
        return bool(
            source_key.startswith("all ")
            or "all target" in source_key
            or "all competitors" in source_key
            or "all models" in source_key
            or "cross-model all" in source_key
            or "cross model all" in source_key
            or re.search(r"\ball\s+\d+\s+(?:target\s+)?(?:models|competitors|llms)\b", source_key)
        )

    def _source_ids_for_competitor_dimension(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> list[str]:
        return [
            source.id
            for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
        ]

    def _filter_findings_to_known_source_ids(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        findings: list[str],
    ) -> list[str]:
        valid_source_ids = set(
            self._source_ids_for_competitor_dimension(detail, competitor, dimension)
        )
        if not valid_source_ids:
            return [finding.strip() for finding in findings if finding.strip()]
        filtered: list[str] = []
        seen: set[str] = set()
        for finding in findings:
            clean = finding.strip()
            if not clean:
                continue
            cited_ids = self._extract_cited_source_ids(clean)
            unknown_ids = {
                source_id for source_id in cited_ids if source_id not in valid_source_ids
            }
            if cited_ids and unknown_ids == cited_ids:
                continue
            if unknown_ids:
                clean = self._remove_unknown_source_refs(clean, unknown_ids)
            key = " ".join(clean.split()).casefold()
            if clean and key not in seen:
                seen.add(key)
                filtered.append(clean)
        return filtered

    def _remove_unknown_source_refs(self, text: str, source_ids: set[str]) -> str:
        cleaned = text
        for source_id in source_ids:
            escaped = re.escape(source_id)
            cleaned = re.sub(
                rf"\s*\[source(?:\s+id)?(?::|\s+){escaped}\]",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
        return " ".join(cleaned.split())

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
        valid_source_ids = self._source_ids_for_competitor_dimension(
            detail,
            entry.competitor,
            entry.dimension,
        )
        kb = detail.competitor_kbs.get(entry.competitor) or CompetitorKB(
            competitor=entry.competitor
        )
        kb.slices[entry.dimension] = self._filter_findings_to_known_source_ids(
            detail,
            entry.competitor,
            entry.dimension,
            entry.kb_slice,
        )
        kb.sources = merge_ordered_refs(kb.sources, valid_source_ids)
        kb.confidence = entry.confidence
        detail.competitor_kbs[entry.competitor] = kb

        knowledge = detail.competitor_knowledge.get(entry.competitor) or CompetitorKnowledge(
            competitor=entry.competitor
        )
        cached = entry.knowledge.model_copy(deep=True)
        dimension_key = entry.dimension.casefold()
        if "pricing" in dimension_key:
            knowledge.pricing_model = cached.pricing_model
        elif "persona" in dimension_key or "user" in dimension_key:
            knowledge.user_personas = cached.user_personas
        else:
            knowledge.feature_tree = cached.feature_tree
        self._sanitize_structured_knowledge_slice_sources(
            detail,
            entry.competitor,
            entry.dimension,
            knowledge,
        )
        knowledge.source_ids = merge_ordered_refs(
            knowledge.source_ids,
            valid_source_ids,
            cached.source_ids,
        )
        knowledge.source_ids = [
            source_id for source_id in knowledge.source_ids if source_id in valid_source_ids
        ]
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
            findings = self._filter_findings_to_known_source_ids(
                detail,
                competitor,
                dimension,
                findings,
            )
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
            kb.sources = merge_ordered_refs(kb.sources, source_ids)
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
        clean_findings = self._filter_findings_to_known_source_ids(
            detail,
            competitor,
            dimension,
            clean_findings,
        )
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
        kb.sources = merge_ordered_refs(kb.sources, source_ids)
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
            claim_text = " ".join(claim.claim for claim in claims)
            knowledge.pricing_model.notes = claims
            if claims:
                knowledge.pricing_model.tiers = self._pricing_tiers_from_text(
                    claim_text, claims
                )
            self._dedupe_pricing_model_tiers(knowledge.pricing_model)
        elif "persona" in dimension_key or "user" in dimension_key:
            claim_text = " ".join(claim.claim for claim in claims)
            knowledge.user_personas.summary_claims = claims
            if claims:
                knowledge.user_personas.segments = self._persona_segments_from_text(
                    claim_text, competitor, claims
                )
        else:
            knowledge.feature_tree.summary_claims = claims
            knowledge.feature_tree.nodes = self._feature_nodes_from_text(
                " ".join(claim.claim for claim in claims), claims
            )
        if self._dimension_uses_review_summary(dimension):
            review_sources = [
                source.model_dump(mode="json")
                for source in self._sources_for_competitor_dimension(
                    detail, competitor, dimension
                )
            ]
            knowledge.review_summary = self._build_review_summary_from_source_dicts(
                competitor=competitor,
                dimension=dimension,
                sources=review_sources,
            )
        source_ids = [
            source.id
            for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
        ]
        knowledge.source_ids = merge_ordered_refs(knowledge.source_ids, source_ids)
        self._sanitize_structured_knowledge_slice_sources(
            detail,
            competitor,
            dimension,
            knowledge,
        )
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
                    self._enrich_pricing_model_from_sources(
                        detail, competitor, dimension, knowledge.pricing_model
                    )
                    self._dedupe_pricing_model_tiers(knowledge.pricing_model)
                except Exception:
                    knowledge.pricing_model.tiers = []
                    knowledge.pricing_model.notes = []
        elif "persona" in dimension_key or "user" in dimension_key:
            section = raw.get("user_personas")
            if isinstance(section, dict):
                try:
                    knowledge.user_personas = UserPersonaModel.model_validate(section)
                    self._enrich_persona_model_from_sources(
                        detail, competitor, dimension, knowledge.user_personas
                    )
                except Exception:
                    knowledge.user_personas.segments = []
                    knowledge.user_personas.summary_claims = []
        else:
            section = raw.get("feature_tree")
            if isinstance(section, dict):
                try:
                    knowledge.feature_tree = FeatureTree.model_validate(section)
                    self._enrich_feature_tree_from_sources(
                        detail, competitor, dimension, knowledge.feature_tree
                    )
                except Exception:
                    knowledge.feature_tree.nodes = []
                    knowledge.feature_tree.summary_claims = []

        review_section = raw.get("review_summary")
        review_summary_changed = False
        if isinstance(review_section, dict):
            knowledge.review_summary = self._review_summary_from_dict(
                review_section,
                competitor=competitor,
                dimension=dimension,
            )
            review_summary_changed = True
        elif self._dimension_uses_review_summary(dimension):
            review_sources = [
                source.model_dump(mode="json")
                for source in self._sources_for_competitor_dimension(
                    detail, competitor, dimension
                )
            ]
            knowledge.review_summary = self._build_review_summary_from_source_dicts(
                competitor=competitor,
                dimension=dimension,
                sources=review_sources,
            )
            review_summary_changed = True

        if self._dimension_uses_review_summary(
            dimension
        ) and not self._review_summary_has_theme_items(knowledge.review_summary):
            review_sources = [
                source.model_dump(mode="json")
                for source in self._sources_for_competitor_dimension(
                    detail, competitor, dimension
                )
            ]
            fallback_review_summary = self._build_review_summary_from_source_dicts(
                competitor=competitor,
                dimension=dimension,
                sources=review_sources,
            )
            if self._review_summary_has_cited_items(fallback_review_summary):
                knowledge.review_summary = fallback_review_summary
                review_summary_changed = True

        self._sanitize_structured_knowledge_slice_sources(
            detail,
            competitor,
            dimension,
            knowledge,
            sanitize_review_summary=review_summary_changed,
        )
        claims = self._structured_claims_for_dimension(knowledge, dimension)
        knowledge.source_ids = merge_ordered_refs(
            knowledge.source_ids,
            (sid for claim in claims for sid in claim.source_ids),
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
        kb.sources = merge_ordered_refs(
            kb.sources,
            (source_id for claim in claims for source_id in claim.source_ids),
        )
        kb.confidence = self._claim_list_confidence(claims)
        detail.competitor_kbs[competitor] = kb

    def _claim_list_confidence(self, claims: list[KnowledgeClaim]) -> float:
        if not claims:
            return 0.0
        return sum(claim.confidence for claim in claims) / len(claims)

    def _sanitize_structured_knowledge_slice_sources(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        knowledge: CompetitorKnowledge,
        *,
        sanitize_review_summary: bool = False,
    ) -> None:
        valid_source_ids = set(
            self._source_ids_for_competitor_dimension(detail, competitor, dimension)
        )
        if sanitize_review_summary:
            self._sanitize_review_summary_source_ids(knowledge.review_summary, valid_source_ids)
        if not valid_source_ids:
            return
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            self._sanitize_pricing_model_source_ids(knowledge.pricing_model, valid_source_ids)
        elif "persona" in dimension_key or "user" in dimension_key:
            self._sanitize_persona_model_source_ids(knowledge.user_personas, valid_source_ids)
        else:
            self._sanitize_feature_tree_source_ids(knowledge.feature_tree, valid_source_ids)
        knowledge.source_ids = [
            source_id for source_id in knowledge.source_ids if source_id in valid_source_ids
        ]

    def _sanitize_review_summary_source_ids(
        self,
        review_summary: ReviewThemeSummary,
        valid_source_ids: set[str],
    ) -> None:
        review_summary.source_ids = self._known_source_ids(
            review_summary.source_ids,
            valid_source_ids,
        )
        for items in (
            review_summary.praise_themes,
            review_summary.complaint_themes,
            review_summary.adoption_blockers,
            review_summary.switching_triggers,
        ):
            self._sanitize_review_theme_item_source_ids(items, valid_source_ids)

    def _sanitize_review_theme_item_source_ids(
        self,
        items: list[ReviewThemeItem],
        valid_source_ids: set[str],
    ) -> None:
        for item in items:
            had_source_ids = bool(item.source_ids)
            item.source_ids = self._known_source_ids(item.source_ids, valid_source_ids)
            if had_source_ids and not item.source_ids:
                item.evidence_gap = True

    def _review_summary_has_content(self, review_summary: ReviewThemeSummary) -> bool:
        return bool(
            review_summary.source_ids
            or review_summary.praise_themes
            or review_summary.complaint_themes
            or review_summary.adoption_blockers
            or review_summary.switching_triggers
            or review_summary.persona_segments
        )

    def _review_summary_theme_items(
        self, review_summary: ReviewThemeSummary
    ) -> list[ReviewThemeItem]:
        return [
            *review_summary.praise_themes,
            *review_summary.complaint_themes,
            *review_summary.adoption_blockers,
            *review_summary.switching_triggers,
        ]

    def _review_summary_has_theme_items(self, review_summary: ReviewThemeSummary) -> bool:
        return bool(self._review_summary_theme_items(review_summary))

    def _review_summary_has_cited_items(self, review_summary: ReviewThemeSummary) -> bool:
        return any(item.source_ids for item in self._review_summary_theme_items(review_summary))

    def _known_source_ids(
        self,
        source_ids: list[str],
        valid_source_ids: set[str],
    ) -> list[str]:
        return merge_ordered_refs(
            source_id for source_id in source_ids if source_id in valid_source_ids
        )

    def _sanitize_pricing_model_source_ids(
        self,
        pricing_model: PricingModel,
        valid_source_ids: set[str],
    ) -> None:
        pricing_model.notes = self._claims_with_known_source_ids(
            pricing_model.notes,
            valid_source_ids,
        )
        for tier in pricing_model.tiers:
            tier.claims = self._claims_with_known_source_ids(tier.claims, valid_source_ids)

    def _sanitize_persona_model_source_ids(
        self,
        personas: UserPersonaModel,
        valid_source_ids: set[str],
    ) -> None:
        personas.summary_claims = self._claims_with_known_source_ids(
            personas.summary_claims,
            valid_source_ids,
        )
        for segment in personas.segments:
            segment.claims = self._claims_with_known_source_ids(segment.claims, valid_source_ids)

    def _sanitize_feature_tree_source_ids(
        self,
        feature_tree: FeatureTree,
        valid_source_ids: set[str],
    ) -> None:
        feature_tree.summary_claims = self._claims_with_known_source_ids(
            feature_tree.summary_claims,
            valid_source_ids,
        )
        for node in feature_tree.nodes:
            self._sanitize_feature_node_source_ids(node, valid_source_ids)

    def _sanitize_feature_node_source_ids(
        self,
        node: FeatureNode,
        valid_source_ids: set[str],
    ) -> None:
        node.claims = self._claims_with_known_source_ids(node.claims, valid_source_ids)
        for child in node.children:
            self._sanitize_feature_node_source_ids(child, valid_source_ids)

    def _claims_with_known_source_ids(
        self,
        claims: list[KnowledgeClaim],
        valid_source_ids: set[str],
    ) -> list[KnowledgeClaim]:
        filtered: list[KnowledgeClaim] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for claim in claims:
            source_ids = [
                source_id for source_id in claim.source_ids if source_id in valid_source_ids
            ]
            if not source_ids:
                continue
            claim.source_ids = merge_ordered_refs(source_ids)
            key = (claim.claim.casefold(), tuple(claim.source_ids))
            if key in seen:
                continue
            seen.add(key)
            filtered.append(claim)
        return filtered

    def _structured_knowledge_schema_hint(self, dimension: str) -> str:
        claim = {"claim": "factual claim", "source_ids": ["source-id"], "confidence": 0.0}
        review_item = {
            "theme": "review theme",
            "evidence": "short cited evidence",
            "source_ids": ["source-id"],
            "confidence": 0.0,
            "evidence_gap": False,
        }
        review_summary = {
            "competitor": "competitor name",
            "dimension": dimension,
            "praise_themes": [review_item],
            "complaint_themes": [review_item],
            "adoption_blockers": [review_item],
            "switching_triggers": [review_item],
            "persona_segments": ["segment"],
            "sentiment_hint": "positive|mixed|negative|unknown",
            "source_ids": ["source-id"],
            "confidence": 0.0,
        }
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
            hint = {
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
            if self._dimension_uses_review_summary(dimension):
                hint["review_summary"] = review_summary
            return json.dumps(hint)
        if self._dimension_uses_review_summary(dimension):
            return json.dumps({"review_summary": review_summary})
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

    def _structured_claims_for_dimension(
        self,
        knowledge: CompetitorKnowledge | None,
        dimension: str,
    ) -> list[KnowledgeClaim]:
        if knowledge is None:
            return []
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            claims = [
                *knowledge.pricing_model.notes,
                *[claim for tier in knowledge.pricing_model.tiers for claim in tier.claims],
            ]
        elif "persona" in dimension_key or "user" in dimension_key:
            claims = [
                *knowledge.user_personas.summary_claims,
                *[
                    claim
                    for segment in knowledge.user_personas.segments
                    for claim in segment.claims
                ],
            ]
        else:
            claims = [
                *knowledge.feature_tree.summary_claims,
                *[claim for node in knowledge.feature_tree.nodes for claim in node.claims],
            ]
        if self._dimension_uses_review_summary(dimension):
            claims = [*claims, *self._review_summary_claims(knowledge.review_summary)]
        return claims

    def _review_summary_claims(
        self,
        review_summary: ReviewThemeSummary,
    ) -> list[KnowledgeClaim]:
        claims: list[KnowledgeClaim] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for item in (
            *review_summary.praise_themes,
            *review_summary.complaint_themes,
            *review_summary.adoption_blockers,
            *review_summary.switching_triggers,
        ):
            if not item.source_ids:
                continue
            source_ids = merge_ordered_refs(item.source_ids)
            claim_text = self._review_theme_claim_text(item)
            key = (claim_text.casefold(), tuple(source_ids))
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                KnowledgeClaim(
                    claim=claim_text,
                    source_ids=source_ids,
                    confidence=item.confidence,
                )
            )
        return claims

    def _review_theme_claim_text(self, item: ReviewThemeItem) -> str:
        theme = " ".join((item.theme or "").split())
        evidence = " ".join((item.evidence or "").split())
        if theme and evidence:
            return f"{theme}: {evidence}"
        return theme or evidence or "Review theme"

    def _review_summary_from_dict(
        self,
        raw: dict[str, Any],
        *,
        competitor: str,
        dimension: str,
    ) -> ReviewThemeSummary:
        try:
            repaired = self._repair_uncited_review_theme_items(raw)
            return ReviewThemeSummary.model_validate(repaired)
        except Exception:
            return ReviewThemeSummary(competitor=competitor, dimension=dimension)

    def _repair_uncited_review_theme_items(
        self,
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        repaired = dict(raw)
        for field in (
            "praise_themes",
            "complaint_themes",
            "adoption_blockers",
            "switching_triggers",
        ):
            items = repaired.get(field)
            if not isinstance(items, list):
                continue
            repaired_items: list[Any] = []
            for item in items:
                if not isinstance(item, dict):
                    repaired_items.append(item)
                    continue
                item_data = dict(item)
                if not self._raw_review_item_has_source_ids(item_data):
                    item_data["evidence_gap"] = True
                repaired_items.append(item_data)
            repaired[field] = repaired_items
        return repaired

    def _raw_review_item_has_source_ids(self, raw: dict[str, Any]) -> bool:
        source_ids = raw.get("source_ids")
        if not isinstance(source_ids, list):
            return False
        return any(str(source_id).strip() for source_id in source_ids)

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
            review_section = raw.get("review_summary")
            if isinstance(review_section, dict):
                probe.review_summary = self._review_summary_from_dict(
                    review_section,
                    competitor="probe",
                    dimension=dimension,
                )
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
        valid_source_ids = set(fallback_source_ids)
        claims: list[KnowledgeClaim] = []
        for finding in findings:
            clean = finding.strip()
            if not clean:
                continue
            cited_source_ids = sorted(self._extract_cited_source_ids(clean))
            if valid_source_ids:
                source_ids = [
                    source_id for source_id in cited_source_ids if source_id in valid_source_ids
                ]
                if cited_source_ids and not source_ids:
                    continue
                unknown_source_ids = set(cited_source_ids) - valid_source_ids
                if unknown_source_ids:
                    clean = self._remove_unknown_source_refs(clean, unknown_source_ids)
            else:
                source_ids = cited_source_ids
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
        match = self._price_hint_regex().search(text)
        if match:
            return " ".join(match.group(0).split())
        if re.search(r"\bfree\b|no credit card required", text, flags=re.IGNORECASE):
            return "$0"
        return "unknown"

    def _price_hint_regex(self) -> re.Pattern[str]:
        return re.compile(
            (
                r"(?:\$|USD\s*)\s?\d+(?:[.,]\d+)?"
                r"(?:\s*(?:/|per)\s*(?:month|mo|year|yr|seat|user|developer|credit|"
                r"request|token|million tokens|usage))?"
            ),
            flags=re.IGNORECASE,
        )

    def _pricing_tiers_from_text(
        self, text: str, claims: list[KnowledgeClaim]
    ) -> list[PricingTier]:
        tiers: list[PricingTier] = []
        seen_keys: set[tuple[str, str]] = set()
        if re.search(r"\bfree\b|no credit card required", text, flags=re.IGNORECASE):
            window = self._pricing_window_for_keyword(text, "free")
            tiers.append(
                PricingTier(
                    name="Free",
                    price="$0",
                    billing_cycle=self._extract_billing_cycle_hint(window),
                    limits=self._extract_limit_hints(window),
                    claims=claims,
                )
            )
            seen_keys.add((tiers[-1].name.casefold(), tiers[-1].price.casefold()))
        for index, match in enumerate(self._price_hint_regex().finditer(text), start=1):
            price = " ".join(match.group(0).split())
            window = self._pricing_window_around_match(text, match)
            name = self._extract_pricing_tier_name_near_price(text, match)
            if not name:
                name = self._extract_pricing_tier_name(window)
            if not name:
                name = f"Extracted pricing tier {index}"
            key = (name.casefold(), price.casefold())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            tiers.append(
                PricingTier(
                    name=name,
                    price=price,
                    billing_cycle=self._extract_billing_cycle_hint(window),
                    limits=self._extract_limit_hints(window),
                    claims=claims,
                )
            )
            if len(tiers) >= 6:
                break
        if tiers:
            return tiers
        return [
            PricingTier(
                name="Extracted pricing evidence",
                price=self._extract_price_hint(text),
                billing_cycle=self._extract_billing_cycle_hint(text),
                limits=self._extract_limit_hints(text),
                claims=claims,
            )
        ]

    def _pricing_window_around_match(self, text: str, match: re.Match[str]) -> str:
        start = self._previous_pricing_tier_keyword_index(text, match.start())
        end = self._next_pricing_tier_keyword_index(text, match.end())
        return text[start:end]

    def _pricing_window_for_keyword(self, text: str, keyword: str) -> str:
        match = re.search(re.escape(keyword), text, flags=re.IGNORECASE)
        if not match:
            return text[:180]
        end = self._next_pricing_tier_keyword_index(text, match.end())
        return text[match.start() : end]

    def _pricing_tier_keyword_regex(self) -> re.Pattern[str]:
        return re.compile(
            r"\b(?:free|hobby|pro\+|ultra|max|business|enterprise|teams?|individual|pro)\b",
            flags=re.IGNORECASE,
        )

    def _previous_pricing_tier_keyword_index(self, text: str, position: int) -> int:
        matches = list(self._pricing_tier_keyword_regex().finditer(text[:position]))
        return matches[-1].start() if matches else max(0, position - 90)

    def _next_pricing_tier_keyword_index(self, text: str, position: int) -> int:
        match = self._pricing_tier_keyword_regex().search(text, position)
        return match.start() if match else min(len(text), position + 140)

    def _extract_pricing_tier_name(self, text: str) -> str:
        patterns = [
            (r"\bpro\+\b", "Pro+"),
            (r"\bultra\b", "Ultra"),
            (r"\bmax\b", "Max"),
            (r"\bbusiness\b", "Business"),
            (r"\benterprise\b", "Enterprise"),
            (r"\bteam(?:s)?\b", "Team"),
            (r"\bindividual\b", "Individual"),
            (r"\bpro\b", "Pro"),
            (r"\bfree\b|\bhobby\b", "Free"),
        ]
        for pattern, name in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return name
        return ""

    def _extract_pricing_tier_name_near_price(
        self, text: str, match: re.Match[str]
    ) -> str:
        before = text[max(0, match.start() - 90) : match.start()]
        candidates: list[tuple[int, str]] = []
        patterns = [
            (r"\bpro\+\b", "Pro+"),
            (r"\bultra\b", "Ultra"),
            (r"\bmax\b", "Max"),
            (r"\bbusiness\b", "Business"),
            (r"\benterprise\b", "Enterprise"),
            (r"\bteam(?:s)?\b", "Team"),
            (r"\bindividual\b", "Individual"),
            (r"\bpro\b", "Pro"),
            (r"\bfree\b|\bhobby\b", "Free"),
        ]
        for pattern, name in patterns:
            matches = list(re.finditer(pattern, before, flags=re.IGNORECASE))
            if matches:
                candidates.append((matches[-1].start(), name))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        after = text[match.end() : min(len(text), match.end() + 60)]
        return self._extract_pricing_tier_name(after)

    def _extract_billing_cycle_hint(self, text: str) -> str:
        normalized = text.casefold()
        if re.search(r"\b(per month|/month|monthly|/mo|per mo)\b", normalized):
            return "monthly"
        if re.search(r"\b(per year|/year|annual|annually|yearly|/yr|per yr)\b", normalized):
            return "annual"
        if re.search(r"\b(usage|credit|request|token|metered|consumption)\b", normalized):
            return "usage"
        return "unknown"

    def _extract_limit_hints(self, text: str) -> list[str]:
        patterns = [
            r"\b\d[\d,]*(?:\.\d+)?\s*(?:k|m|million|billion)?\s+"
            r"(?:completions|requests|credits|tokens|messages|agent requests|premium requests)"
            r"(?:\s+per\s+\w+)?\b",
            r"\b(?:unlimited|limited)\s+"
            r"(?:completions|requests|credits|tokens|messages|usage|agent requests)\b",
            r"\b\d[\d,]*(?:\.\d+)?\s*(?:x|times)\s+(?:usage|capacity|limit)\b",
        ]
        hints: list[str] = []
        seen: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                hint = " ".join(match.group(0).split())
                key = hint.casefold()
                if key not in seen:
                    seen.add(key)
                    hints.append(hint)
                if len(hints) >= 3:
                    return hints
        return hints

    def _enrich_pricing_model_from_sources(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        pricing_model: PricingModel,
    ) -> None:
        evidence_text = " ".join(
            " ".join((source.title, source.snippet))
            for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
        )
        if not evidence_text.strip():
            return
        price = self._extract_price_hint(evidence_text)
        billing_cycle = self._extract_billing_cycle_hint(evidence_text)
        limits = self._extract_limit_hints(evidence_text)
        existing_claims = [
            *pricing_model.notes,
            *[claim for tier in pricing_model.tiers for claim in tier.claims],
        ]
        extracted_tiers = self._pricing_tiers_from_text(evidence_text, existing_claims)
        for tier in pricing_model.tiers:
            if tier.price == "unknown" and price != "unknown":
                tier.price = price
            if tier.billing_cycle == "unknown" and billing_cycle != "unknown":
                tier.billing_cycle = billing_cycle
            if not tier.limits and limits:
                tier.limits = limits
        seen_keys = {
            (tier.name.casefold(), tier.price.casefold()) for tier in pricing_model.tiers
        }
        for tier in extracted_tiers:
            key = (tier.name.casefold(), tier.price.casefold())
            if key not in seen_keys and tier.price != "unknown":
                pricing_model.tiers.append(tier)
                seen_keys.add(key)
            if len(pricing_model.tiers) >= 6:
                break
        self._dedupe_pricing_model_tiers(pricing_model)

    def _dedupe_pricing_model_tiers(self, pricing_model: PricingModel) -> None:
        merged: dict[tuple[str, str], PricingTier] = {}
        ordered_keys: list[tuple[str, str]] = []
        for tier in pricing_model.tiers:
            key = self._pricing_tier_dedupe_key(tier)
            existing = merged.get(key)
            if existing is None:
                merged[key] = tier
                ordered_keys.append(key)
                continue
            self._merge_pricing_tier(existing, tier)
        pricing_model.tiers = [merged[key] for key in ordered_keys]
        self._standardize_pricing_tier_metadata(pricing_model)
        self._disambiguate_duplicate_pricing_tier_names(pricing_model)

    def _standardize_pricing_tier_metadata(self, pricing_model: PricingModel) -> None:
        for tier in pricing_model.tiers:
            if tier.billing_cycle == "unknown":
                cycle = self._extract_billing_cycle_hint(
                    " ".join([tier.price, *tier.limits])
                )
                if cycle != "unknown":
                    tier.billing_cycle = cycle
            if not tier.limits and self._is_paid_pricing_tier(tier):
                tier.limits = ["not stated in collected source"]

    def _is_paid_pricing_tier(self, tier: PricingTier) -> bool:
        name = self._canonical_pricing_tier_name(tier.name)
        price = self._canonical_pricing_price(tier.price)
        return name != "free" and price not in {"$0", "unknown"}

    def _disambiguate_duplicate_pricing_tier_names(
        self, pricing_model: PricingModel
    ) -> None:
        canonical_counts: dict[str, int] = {}
        for tier in pricing_model.tiers:
            canonical = self._canonical_pricing_tier_name(tier.name)
            canonical_counts[canonical] = canonical_counts.get(canonical, 0) + 1
        if not any(count > 1 for count in canonical_counts.values()):
            return
        seen: dict[str, int] = {}
        for tier in pricing_model.tiers:
            canonical = self._canonical_pricing_tier_name(tier.name)
            if canonical_counts.get(canonical, 0) <= 1:
                continue
            seen[canonical] = seen.get(canonical, 0) + 1
            tier.name = self._qualified_pricing_tier_name(
                canonical,
                tier,
                seen[canonical],
            )

    def _qualified_pricing_tier_name(
        self, canonical_name: str, tier: PricingTier, index: int
    ) -> str:
        display_name = self._display_pricing_tier_name(canonical_name, tier.name)
        qualifier = self._pricing_tier_name_qualifier(tier, index)
        return f"{display_name} ({qualifier})" if qualifier else display_name

    def _display_pricing_tier_name(self, canonical_name: str, fallback: str) -> str:
        labels = {
            "business": "Business",
            "enterprise": "Enterprise",
            "free": "Free",
            "individual": "Individual",
            "max": "Max",
            "pro": "Pro",
            "pro+": "Pro+",
            "team": "Team",
            "ultra": "Ultra",
        }
        return labels.get(canonical_name, fallback or "Pricing tier")

    def _pricing_tier_name_qualifier(self, tier: PricingTier, index: int) -> str:
        price = " ".join((tier.price or "").split())
        if price and price != "unknown":
            return self._compact_pricing_label(price)
        cycle = " ".join((tier.billing_cycle or "").split())
        if cycle and cycle != "unknown":
            return cycle
        return f"entry {index}"

    def _compact_pricing_label(self, value: str, limit: int = 42) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1].rstrip()}..."

    def _pricing_tier_dedupe_key(self, tier: PricingTier) -> tuple[str, str]:
        name = self._canonical_pricing_tier_name(tier.name)
        price = self._canonical_pricing_price(tier.price)
        if name == "free" or price == "$0":
            return ("free", "$0")
        return (name, price)

    def _canonical_pricing_tier_name(self, name: str) -> str:
        text = " ".join((name or "").split()).casefold()
        patterns = [
            (r"\bfree\b|\bhobby\b", "free"),
            (r"\bpro\+\b", "pro+"),
            (r"\bultra\b", "ultra"),
            (r"\bmax\b", "max"),
            (r"\bbusiness\b", "business"),
            (r"\benterprise\b", "enterprise"),
            (r"\bteam(?:s)?\b", "team"),
            (r"\bindividual\b", "individual"),
            (r"\bpro\b", "pro"),
        ]
        for pattern, canonical in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return canonical
        return text or "unknown"

    def _canonical_pricing_price(self, price: str) -> str:
        text = " ".join((price or "").split()).casefold()
        if not text or text == "unknown":
            return "unknown"
        if "free" in text or re.search(r"(?:^|\D)(?:\$|usd\s*)?0(?:\.0+)?(?:\D|$)", text):
            return "$0"
        if re.search(r"\b(custom|contact|enterprise)\b", text):
            return "custom"
        return re.sub(r"\s+", "", text)

    def _merge_pricing_tier(self, target: PricingTier, duplicate: PricingTier) -> None:
        if target.price == "unknown" and duplicate.price != "unknown":
            target.price = duplicate.price
        if target.billing_cycle == "unknown" and duplicate.billing_cycle != "unknown":
            target.billing_cycle = duplicate.billing_cycle
        target.limits = self._merge_unique_texts(target.limits, duplicate.limits)
        target.claims = self._merge_unique_claims(target.claims, duplicate.claims)

    def _merge_unique_texts(self, left: list[str], right: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in [*left, *right]:
            cleaned = " ".join((value or "").split())
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                merged.append(cleaned)
        return merged

    def _merge_unique_claims(
        self, left: list[KnowledgeClaim], right: list[KnowledgeClaim]
    ) -> list[KnowledgeClaim]:
        merged: list[KnowledgeClaim] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for claim in [*left, *right]:
            key = (claim.claim.casefold(), tuple(sorted(claim.source_ids)))
            if key not in seen:
                seen.add(key)
                merged.append(claim)
        return merged

    def _feature_taxonomy(self) -> list[tuple[str, str, list[str]]]:
        return [
            (
                "Code completion",
                "Inline suggestions, autocomplete, and completion assistance.",
                [r"\bautocomplete\b", r"\bcompletion", r"inline suggestion", r"\bsuggest"],
            ),
            (
                "Agentic coding",
                "Agent-driven multi-step coding, editing, and refactoring workflows.",
                [r"\bagentic\b", r"\bagent\b", r"\bcascade\b", r"multi-?file", r"refactor"],
            ),
            (
                "Chat and Q&A",
                "Conversational coding assistance and repository question answering.",
                [r"\bchat\b", r"\bask\b", r"question", r"assistant", r"conversation"],
            ),
            (
                "IDE integration",
                "Editor, IDE, extension, and plugin integration.",
                [
                    r"\bide\b",
                    r"\beditor\b",
                    r"vs\s*code",
                    r"\bvscode\b",
                    r"jetbrains",
                    r"plugin",
                    r"extension",
                ],
            ),
            (
                "Code review and security",
                "Pull request review, vulnerability scanning, and secret/security support.",
                [
                    r"pull request",
                    r"\bpr\b",
                    r"review",
                    r"vulnerab",
                    r"secret",
                    r"security",
                    r"scan",
                ],
            ),
            (
                "Tool and terminal use",
                "Tool calling, terminal commands, MCP, and external workflow actions.",
                [
                    r"terminal",
                    r"command",
                    r"tool use",
                    r"\bmcp\b",
                    r"model context protocol",
                    r"\bshell\b",
                ],
            ),
            (
                "Repository context",
                "Codebase, repository, directory, and project context understanding.",
                [r"codebase", r"repository", r"\brepo\b", r"context", r"directory", r"index"],
            ),
            (
                "Enterprise administration",
                "Team, organization, governance, policy, SSO, and admin controls.",
                [
                    r"enterprise",
                    r"organization",
                    r"\bteam\b",
                    r"admin",
                    r"policy",
                    r"\bsso\b",
                    r"governance",
                ],
            ),
        ]

    def _feature_nodes_from_text(
        self, text: str, claims: list[KnowledgeClaim]
    ) -> list[FeatureNode]:
        nodes: list[FeatureNode] = []
        for name, description, patterns in self._feature_taxonomy():
            if not self._any_pattern_matches(text, patterns):
                continue
            related_claims = [
                claim
                for claim in claims
                if self._any_pattern_matches(claim.claim, patterns)
            ]
            nodes.append(
                FeatureNode(
                    name=name,
                    description=description,
                    claims=related_claims or claims,
                    children=[],
                )
            )
            if len(nodes) >= 6:
                break
        if nodes:
            return nodes
        return [
            FeatureNode(
                name="Feature evidence",
                description=claim.claim,
                claims=[claim],
                children=[],
            )
            for claim in claims
        ]

    def _enrich_feature_tree_from_sources(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        feature_tree: FeatureTree,
    ) -> None:
        evidence_text = " ".join(
            " ".join((source.title, source.snippet))
            for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
        )
        if not evidence_text.strip():
            return
        existing_claims = [
            *feature_tree.summary_claims,
            *[claim for node in feature_tree.nodes for claim in node.claims],
        ]
        extracted_nodes = self._feature_nodes_from_text(evidence_text, existing_claims)
        seen_names = {node.name.casefold() for node in feature_tree.nodes}
        for node in extracted_nodes:
            if node.name.casefold() not in seen_names:
                feature_tree.nodes.append(node)
                seen_names.add(node.name.casefold())
            if len(feature_tree.nodes) >= 8:
                break

    def _any_pattern_matches(self, text: str, patterns: list[str]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    def _dimension_uses_review_summary(self, dimension: str) -> bool:
        key = dimension.casefold().replace("-", "_")
        return any(hint in key for hint in REVIEW_SUMMARY_DIMENSION_HINTS)

    def _build_review_summary_from_source_dicts(
        self,
        *,
        competitor: str,
        dimension: str,
        sources: list[dict[str, Any]],
    ) -> ReviewThemeSummary:
        source_ids = [
            str(source.get("id") or "").strip()
            for source in sources
            if str(source.get("id") or "").strip()
        ]
        text = " ".join(
            " ".join(
                str(source.get(key) or "")
                for key in ("title", "summary", "snippet", "text")
            )
            for source in sources
        )
        confidence = max(
            (
                float(source.get("confidence") or 0.0)
                for source in sources
                if str(source.get("id") or "").strip()
            ),
            default=0.0,
        )
        praise = []
        complaints = []
        blockers = []
        switching = []
        if any(term in text.casefold() for term in POSITIVE_REVIEW_TERMS):
            praise.append(
                self._review_theme_item(
                    "Praised workflow or value theme",
                    text,
                    source_ids,
                    confidence,
                )
            )
        if any(term in text.casefold() for term in NEGATIVE_REVIEW_TERMS):
            item = self._review_theme_item(
                "Complaint or adoption friction theme",
                text,
                source_ids,
                confidence,
            )
            complaints.append(item)
            blockers.append(item)
        if any(term in text.casefold() for term in SWITCHING_REVIEW_TERMS):
            switching.append(
                self._review_theme_item(
                    "Switching or migration trigger",
                    text,
                    source_ids,
                    confidence,
                )
            )
        return ReviewThemeSummary(
            competitor=competitor,
            dimension=dimension,
            praise_themes=praise,
            complaint_themes=complaints,
            adoption_blockers=blockers,
            switching_triggers=switching,
            persona_segments=self._review_persona_segments(text),
            sentiment_hint=self._review_sentiment_hint(bool(praise), bool(complaints)),
            source_ids=source_ids,
            confidence=confidence,
        )

    def _review_theme_item(
        self,
        theme: str,
        text: str,
        source_ids: list[str],
        confidence: float,
    ) -> ReviewThemeItem:
        evidence = self._compact_review_evidence(text)
        return ReviewThemeItem(
            theme=theme,
            evidence=evidence,
            source_ids=source_ids,
            confidence=confidence,
            evidence_gap=not source_ids,
        )

    def _compact_review_evidence(self, text: str, limit: int = 220) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return f"{compact[: limit - 1].rstrip()}..."

    def _review_persona_segments(self, text: str) -> list[str]:
        normalized = text.casefold()
        segments: list[str] = []
        for label, terms in (
            ("developers", ("developer", "engineer", "coding")),
            ("enterprise buyers", ("enterprise", "buyer", "procurement")),
            ("teams", ("team", "workspace", "organization")),
        ):
            if any(term in normalized for term in terms):
                segments.append(label)
        return segments[:4]

    def _review_sentiment_hint(self, has_praise: bool, has_complaint: bool) -> str:
        if has_praise and has_complaint:
            return "mixed"
        if has_praise:
            return "positive"
        if has_complaint:
            return "negative"
        return "unknown"

    def _enrich_persona_model_from_sources(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        personas: UserPersonaModel,
    ) -> None:
        evidence_text = " ".join(
            " ".join((source.title, source.snippet))
            for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
        )
        if not evidence_text.strip():
            return
        inferred_segments = self._persona_segments_from_text(
            evidence_text,
            competitor,
            personas.summary_claims,
        )
        segment_name = self._extract_persona_segment_name(evidence_text, competitor)
        role = self._extract_persona_role_hint(evidence_text)
        company_size = self._extract_company_size_hint(evidence_text)
        pain_points = self._extract_persona_pain_points(evidence_text)
        use_cases = self._extract_persona_use_cases(evidence_text)
        if not personas.segments:
            personas.segments = inferred_segments
            return
        for segment in personas.segments:
            if segment.name.casefold() in {"unknown", "inferred target segment"}:
                segment.name = segment_name
            if segment.role == "unknown" and role != "unknown":
                segment.role = role
            if segment.company_size == "unknown" and company_size != "unknown":
                segment.company_size = company_size
            if not segment.pain_points and pain_points:
                segment.pain_points = pain_points
            if not segment.use_cases and use_cases:
                segment.use_cases = use_cases
        existing_keys = {
            self._persona_segment_key(segment) for segment in personas.segments
        }
        for segment in inferred_segments:
            key = self._persona_segment_key(segment)
            if key in existing_keys:
                continue
            personas.segments.append(segment)
            existing_keys.add(key)
            if len(personas.segments) >= 4:
                break

    def _persona_segments_from_text(
        self,
        text: str,
        competitor: str = "",
        claims: list[KnowledgeClaim] | None = None,
    ) -> list[UserPersonaSegment]:
        normalized = text.casefold()
        pain_points = self._extract_persona_pain_points(text)
        use_cases = self._extract_persona_use_cases(text) or [
            claim.claim for claim in (claims or [])[:3]
        ]
        segment_specs: list[tuple[str, str, str]] = []
        if re.search(r"\bindividual|solo|hobby(?:ist)?|indie developer\b", normalized):
            segment_specs.append(("Individual developers", "developer", "individual"))
        if re.search(
            r"\bsmb|startup|founder|small team|small business|small compan",
            normalized,
        ):
            segment_specs.append(
                ("SMB and startup engineering teams", "developer", "startup")
            )
        if re.search(
            r"\benterprise|large organization|organization|governance|procurement\b",
            normalized,
        ):
            segment_specs.append(
                (
                    "Enterprise engineering teams",
                    self._extract_persona_role_hint(text),
                    "enterprise",
                )
            )
        if not segment_specs:
            segment_specs.append(
                (
                    self._extract_persona_segment_name(text, competitor),
                    self._extract_persona_role_hint(text),
                    self._extract_company_size_hint(text),
                )
            )
        segments: list[UserPersonaSegment] = []
        seen: set[tuple[str, str]] = set()
        for name, role, company_size in segment_specs:
            key = (name.casefold(), company_size.casefold())
            if key in seen:
                continue
            seen.add(key)
            segments.append(
                UserPersonaSegment(
                    name=name,
                    role=role,
                    company_size=company_size,
                    pain_points=pain_points,
                    use_cases=use_cases,
                    claims=claims or [],
                )
            )
            if len(segments) >= 4:
                break
        return segments

    def _persona_segment_key(self, segment: UserPersonaSegment) -> tuple[str, str]:
        return (
            " ".join((segment.name or "").split()).casefold(),
            " ".join((segment.company_size or "").split()).casefold(),
        )

    def _extract_persona_segment_name(self, text: str, competitor: str = "") -> str:
        competitor_key = competitor.casefold()
        if "github" in competitor_key and "copilot" in competitor_key:
            return "GitHub workflow developers"
        if "cursor" in competitor_key:
            return "Cursor AI-native IDE developers"
        if "claude" in competitor_key:
            return "Claude Code agentic coding teams"
        if "windsurf" in competitor_key:
            return "Windsurf Cascade IDE developers"
        normalized = text.casefold()
        if re.search(r"\benterprise|governance|procurement\b", normalized):
            return "Enterprise engineering teams"
        if re.search(r"\bstartup|founder|small team\b", normalized):
            return "Startup engineering teams"
        if re.search(r"\bdeveloper|engineer|coder|programmer\b", normalized):
            return "Developers"
        return "Inferred target segment"

    def _extract_persona_role_hint(self, text: str) -> str:
        normalized = text.casefold()
        if re.search(r"\bprocurement|buyer|cio|cto|it admin|administrator\b", normalized):
            return "technical buyer"
        if re.search(r"\bdeveloper|engineer|coder|programmer\b", normalized):
            return "developer"
        if re.search(r"\bproduct manager|pm\b", normalized):
            return "product"
        return "unknown"

    def _extract_company_size_hint(self, text: str) -> str:
        normalized = text.casefold()
        if re.search(r"\benterprise|large organization|organization|governance\b", normalized):
            return "enterprise"
        if re.search(r"\bsmb|startup|small team|small business|small compan", normalized):
            return "startup"
        if re.search(r"\bteam|teams|company|companies\b", normalized):
            return "team"
        if re.search(r"\bindividual|solo|hobby\b", normalized):
            return "individual"
        return "unknown"

    def _extract_persona_pain_points(self, text: str) -> list[str]:
        patterns = [
            (r"context switching", "context switching"),
            (r"legacy code|large codebase|codebase", "large codebase maintenance"),
            (r"security|vulnerabilit|secret", "security risk"),
            (r"cost|budget|spend", "cost control"),
            (r"onboarding|ramp", "developer onboarding"),
            (r"review|pull request|pr\b", "code review throughput"),
        ]
        return self._extract_labeled_hints(text, patterns)

    def _extract_persona_use_cases(self, text: str) -> list[str]:
        patterns = [
            (r"code completion|autocomplete|completion", "code completion"),
            (r"agentic|agent|multi-file|edit", "agentic coding"),
            (r"debug|fix", "debugging and fixes"),
            (r"refactor|migration", "refactoring"),
            (r"ide|editor", "IDE workflow"),
            (r"review|pull request|pr\b", "code review"),
            (r"documentation|docs", "documentation lookup"),
        ]
        return self._extract_labeled_hints(text, patterns)

    def _extract_labeled_hints(
        self, text: str, patterns: list[tuple[str, str]]
    ) -> list[str]:
        normalized = text.casefold()
        hints: list[str] = []
        for pattern, label in patterns:
            if re.search(pattern, normalized) and label not in hints:
                hints.append(label)
            if len(hints) >= 3:
                break
        return hints

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
