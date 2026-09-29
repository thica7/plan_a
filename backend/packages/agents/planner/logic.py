from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from packages.business_intel.entity_resolver import normalize_competitor_key
from packages.business_intel.homepage import verify_homepage, verify_homepages
from packages.research.budget import research_depth_budget
from packages.research.discovery.planner import build_competitor_queries
from packages.schema.models import (
    AnalysisPlan,
    CompetitorCandidate,
    CompetitorDiscovery,
    TargetProductEvidence,
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
        await self._research_target_product(record)
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
                if verification.verified and verification.homepage_url is not None:
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
                f"Target product: {detail.plan.target_product.name if detail.plan.target_product else 'none'}\n"
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
            selected_by_key = {name.casefold(): name for name in detail.plan.competitors}
            candidate_hints = {
                selected_by_key[str(key).casefold()]: str(value)
                for key, value in hints.items()
                if str(key).casefold() in selected_by_key
            }
            for name, verification in verify_homepages(
                detail.plan.competitors,
                candidate_hints,
            ).items():
                detail.plan.homepage_verified[name] = verification.verified
                if verification.verified and verification.homepage_url is not None:
                    detail.plan.homepage_hints[name] = str(verification.homepage_url)
                else:
                    detail.plan.homepage_hints.pop(name, None)
        self._include_target_product_in_plan(detail.plan)
        self._refresh_task_decomposition(detail.plan)
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
        product = detail.plan.target_product
        depth_budget = research_depth_budget(detail.plan.research_depth)
        if depth_budget is None:
            candidate_instruction = (
                "Return 3 to 5 candidates, separating direct products, adjacent products, "
            )
        else:
            candidate_instruction = (
                f"Select at most {depth_budget.competitor_limit} competitors. "
                f"Return up to {depth_budget.competitor_limit} candidates, "
                "separating direct products, adjacent products, "
            )
        queries = (
            build_competitor_queries(product, topic=detail.topic)
            if product is not None
            else [f"{detail.topic} competitors alternatives market leaders official"]
        )
        query = queries[0]
        search_results: list[SearchResult] = []
        if self._search.is_enabled:
            seen_urls: set[str] = set()
            for discovery_query in queries:
                results = await self._trace_search(
                    record,
                    agent="planner",
                    subagent="discovery",
                    query=discovery_query,
                    max_results=6,
                )
                for result in results:
                    key = result.url.rstrip("/").casefold()
                    if key not in seen_urls:
                        seen_urls.add(key)
                        search_results.append(result)
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
                f"Target product: {product.model_dump_json() if product else 'not specified'}\n"
                f"Target page evidence: {detail.plan.target_product_evidence.model_dump_json() if detail.plan.target_product_evidence else 'not available'}\n"
                f"Search results JSON: {json.dumps(search_context, ensure_ascii=False)}\n\n"
                f"{candidate_instruction}"
                "and substitutes for the same user task. "
                "Prefer product or company names, not article titles. "
                "Use matched search results as evidence and name the shared user task. "
                "Keep names short; do not invent a source for an unmatched candidate."
            ),
            schema_hint=(
                '{"candidates":[{"name":"name","rationale":"shared task and difference",'
                '"relationship":"direct|adjacent|substitute","confidence":0.0}],'
                '"selected_competitors":["name"],"rationale":"short reason"}'
            ),
        )
        selected = self._normalize_competitor_names(
            payload.get("selected_competitors") or payload.get("competitors")
        )[:depth_budget.competitor_limit if depth_budget is not None else 5]
        candidate_names = self._candidate_names(payload, selected)
        if product is not None:
            target_key = normalize_competitor_key(product.name)
            selected = [
                name for name in selected
                if normalize_competitor_key(name) != target_key
                and self._candidate_evidence(name, search_results)
            ]
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
                relationship=self._candidate_relationship(payload, name)
                if name.casefold() in selected_set else "unverified",
            )
            for index, name in enumerate(candidate_names)
        ]
        return CompetitorDiscovery(
            query=query,
            search_queries=queries,
            candidates=candidates,
            selected_competitors=selected,
            rationale=str(payload.get("rationale") or ""),
        )

    async def _research_target_product(self, record: RunRecord) -> None:
        product = record.detail.plan.target_product
        if product is None or product.official_url is None:
            return
        url = str(product.official_url)
        result = await self._trace_fetch(
            record, agent="planner", subagent="target_product", url=url,
        )
        text = str(getattr(result, "text", "") or "")
        title = str(getattr(result, "title", "") or "")
        identity_text = f"{title} {text}".casefold()
        status = (
            "unavailable" if not result.ok else
            "verified" if product.name.casefold() in identity_text else "unverified"
        )
        record.detail.plan.target_product_evidence = TargetProductEvidence(
            status=status,
            source_url=str(getattr(result, "url", "") or url),
            title=title,
            snippet=text[:700],
            content_hash=str(getattr(result, "content_hash", "") or ""),
            fetch_method=str(getattr(result, "fetch_method", "") or ""),
            reason="" if status == "verified" else
            str(getattr(result, "error", "") or "product identity not confirmed by page"),
        )

    @staticmethod
    def _include_target_product_in_plan(plan: AnalysisPlan) -> None:
        product = plan.target_product
        if product is None:
            return
        target_key = normalize_competitor_key(product.name)
        plan.competitors = [
            product.name,
            *(name for name in plan.competitors if normalize_competitor_key(name) != target_key),
        ]
        plan.homepage_verified[product.name] = False
        plan.homepage_hints.pop(product.name, None)
        if product.official_url is not None:
            verification = verify_homepage(product.name, str(product.official_url))
            if verification.verified and verification.homepage_url is not None:
                plan.homepage_hints[product.name] = str(verification.homepage_url)
                plan.homepage_verified[product.name] = True

    def _verify_discovered_competitors(
        self,
        discovery: CompetitorDiscovery,
    ) -> CompetitorDiscovery:
        verifications = verify_homepages(discovery.selected_competitors)
        eligible = [
            name for name in discovery.selected_competitors
            if verifications[name].reason != "phantom_name"
        ]
        selected_set = {name.casefold() for name in eligible}
        return discovery.model_copy(
            update={
                "selected_competitors": eligible,
                "candidates": [
                    candidate.model_copy(
                        update={"selected": candidate.name.casefold() in selected_set}
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
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(name.casefold())}(?![a-z0-9])")
        matched = [
            result
            for result in results
            if pattern.search(
                f"{result.title} {result.snippet} {urlsplit(result.url).hostname or ''}".casefold()
            )
        ]
        return matched[:2]

    def _candidate_relationship(self, payload: dict, name: str) -> str:
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            for item in candidates:
                if isinstance(item, dict) and str(item.get("name") or "").casefold() == name.casefold():
                    relation = str(item.get("relationship") or "").casefold()
                    if relation in {"direct", "adjacent", "substitute"}:
                        return relation
        return "unverified"
