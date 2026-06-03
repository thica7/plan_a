from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from packages.business_intel.homepage import verify_homepages
from packages.schema.models import (
    CompetitorCandidate,
    CompetitorDiscovery,
)
from packages.search import SearchResult

CORE_SCHEMA_DIMENSIONS = ("pricing", "feature", "persona")

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


class PlannerAgentMixin:
    async def _real_planner_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "planner"
        await self.emit(detail.id, "node_started", "planner", None, "Calling LLM planner.")
        discovery_payload: dict[str, object] = {}
        if not detail.plan.competitors:
            discovery = await self._discover_competitors(record)
            discovered = discovery.selected_competitors
            if not discovered:
                raise ValueError(
                    "Unable to discover competitors for this topic. "
                    "Add competitors manually and retry."
                )
            discovery = self._verify_discovered_competitors(discovery)
            discovered = discovery.selected_competitors
            detail.plan.competitors = discovered
            detail.competitor_discovery = discovery
            homepage_verifications = verify_homepages(discovered)
            detail.plan.homepage_hints = {}
            detail.plan.homepage_verified = {}
            for name in discovered:
                verification = homepage_verifications[name]
                detail.plan.homepage_verified[name] = verification.verified
                if verification.homepage_url is not None:
                    detail.plan.homepage_hints[name] = str(verification.homepage_url)
            discovery_payload = {"competitor_discovery": discovery.model_dump(mode="json")}
            await self.emit(
                detail.id,
                "node_completed",
                "planner",
                None,
                f"Discovered {len(discovered)} competitors for topic-only run.",
                discovery_payload,
            )
        payload = await self._trace_llm_json(
            record,
            agent="planner",
            subagent=None,
            name="planner_scope",
            system=(
                "You are a competitive intelligence planner. "
                "Validate the user scope and keep outputs concise."
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Requested dimensions: {', '.join(detail.plan.dimensions)}\n\n"
                "Return homepage hints if you know official domains. Do not invent certainty."
            ),
            schema_hint='{"complexity":"low|medium|high","homepage_hints":{"competitor":"https://..."},'
            '"planning_notes":["short note"]}',
        )
        complexity = payload.get("complexity")
        if complexity in {"low", "medium", "high"}:
            detail.plan.complexity = complexity
        hints = payload.get("homepage_hints")
        if isinstance(hints, dict):
            selected_competitors = {name.casefold() for name in detail.plan.competitors}
            detail.plan.homepage_hints.update(
                {
                    str(key): str(value)
                    for key, value in hints.items()
                    if str(key).casefold() in selected_competitors
                }
            )
        self._append_agent_message(
            record,
            from_agent="planner",
            to_agent="collector_dispatch",
            message_type="analysis_plan_ready",
            payload_schema="AnalysisPlan",
            payload={"plan": detail.plan.model_dump(mode="json"), "planner": payload},
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "planner",
            None,
            "LLM planner completed.",
            {"planner": payload, "competitor_discovery": discovery_payload},
        )

    async def _real_planner_hitl_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "planner_hitl"
        await self.emit(
            detail.id, "node_started", "hitl", "planner", "Planner HITL checkpoint reached."
        )
        decision = await self._maybe_interrupt(
            record,
            stage="planner",
            message="Planner is ready for review.",
            payload={"plan": detail.plan.model_dump(mode="json")},
        )
        await self.emit(
            detail.id,
            "node_completed",
            "hitl",
            "planner",
            f"Planner HITL checkpoint completed with {decision.decision}.",
            {"decision": decision.model_dump(exclude_none=True)},
        )

    async def _discover_competitors(self, record: RunRecord) -> CompetitorDiscovery:
        detail = record.detail
        query = f"{detail.topic} competitors alternatives market leaders official"
        search_results: list[SearchResult] = []
        if self._search.is_enabled:
            search_results = await self._trace_search(
                record,
                agent="planner",
                subagent="discovery",
                query=query,
                max_results=6,
            )
        search_context = [result.__dict__ for result in search_results]
        payload = await self._trace_llm_json(
            record,
            agent="planner",
            subagent="discovery",
            name="competitor_discovery",
            system=(
                "You are a competitive intelligence scoping agent. "
                "Identify direct competitors worth comparing for the given topic."
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Search results JSON: {json.dumps(search_context, ensure_ascii=False)}\n\n"
                "Return 3 to 5 direct competitors. "
                "Prefer product or company names, not article titles. "
                "If search results are provided, use them as evidence. Keep names short."
            ),
            schema_hint=(
                '{"candidates":[{"name":"name","rationale":"why direct","confidence":0.0}],'
                '"selected_competitors":["name"],"rationale":"short reason"}'
            ),
        )
        selected = self._normalize_competitor_names(
            payload.get("selected_competitors") or payload.get("competitors")
        )[:5]
        candidate_names = self._candidate_names(payload, selected)
        selected_set = {name.casefold() for name in selected}
        candidates = [
            CompetitorCandidate(
                name=name,
                rank=index + 1,
                selected=name.casefold() in selected_set,
                rationale=self._candidate_rationale(payload, name),
                evidence_titles=[
                    result.title for result in self._candidate_evidence(name, search_results)
                ],
                evidence_urls=[
                    result.url for result in self._candidate_evidence(name, search_results)
                ],
                confidence=self._candidate_confidence(payload, name),
            )
            for index, name in enumerate(candidate_names)
        ]
        return CompetitorDiscovery(
            query=query,
            candidates=candidates,
            selected_competitors=selected,
            rationale=str(payload.get("rationale") or ""),
        )

    def _verify_discovered_competitors(
        self,
        discovery: CompetitorDiscovery,
    ) -> CompetitorDiscovery:
        verifications = verify_homepages(discovery.selected_competitors)
        verified_names = [
            name for name in discovery.selected_competitors if verifications[name].verified
        ]
        if not verified_names:
            return discovery
        verified_set = {name.casefold() for name in verified_names}
        return discovery.model_copy(
            update={
                "selected_competitors": verified_names,
                "candidates": [
                    candidate.model_copy(
                        update={"selected": candidate.name.casefold() in verified_set}
                    )
                    for candidate in discovery.candidates
                ],
            }
        )

    def _candidate_names(self, payload: dict, selected: list[str]) -> list[str]:
        names: list[str] = []
        raw_candidates = payload.get("candidates")
        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                if isinstance(item, dict):
                    names.append(str(item.get("name") or ""))
                else:
                    names.append(str(item))
        names.extend(selected)
        return self._normalize_competitor_names(names)

    def _candidate_rationale(self, payload: dict, name: str) -> str:
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            return ""
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip().casefold() == name.casefold():
                return str(item.get("rationale") or "")
        return ""

    def _candidate_confidence(self, payload: dict, name: str) -> float:
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            return 0.65
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip().casefold() == name.casefold():
                return self._coerce_confidence(item.get("confidence"), default=0.65)
        return 0.65

    def _candidate_evidence(self, name: str, results: list[SearchResult]) -> list[SearchResult]:
        key = name.casefold()
        matched = [
            result
            for result in results
            if key in f"{result.title} {result.snippet} {result.url}".casefold()
        ]
        return (matched or results)[:2]
