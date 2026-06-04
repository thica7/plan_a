from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    ComparisonCell,
    ComparisonMatrix,
    FeatureNode,
    FeatureTree,
    PricingModel,
    RawSource,
    UserPersonaModel,
)

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


FEATURE_TAXONOMY_ORDER = (
    "code completion",
    "agentic coding",
    "chat and q&a",
    "ide integration",
    "code review and security",
    "tool and terminal use",
    "repository context",
    "enterprise administration",
)


class ComparatorAgentMixin:
    async def _real_comparator_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "comparator"
        self._consume_queued_agent_messages(
            record,
            to_agent="comparator",
            consumer_agent="comparator",
            message_types={"analyst_qa_result"},
        )
        await self.emit(detail.id, "node_started", "comparator", None, "Calling comparator.")
        fallback: dict[str, object] = {}
        timeout_seconds = max(0.05, float(self._settings.comparator_timeout_seconds))
        try:
            payload = await asyncio.wait_for(
                self._trace_llm_json(
                    record,
                    agent="comparator",
                    subagent=None,
                    name="comparison_matrix",
                    system="You are a comparator. Build a compact cross-competitor matrix summary.",
                    user=(
                        f"Topic: {detail.topic}\n"
                        f"Competitors: {', '.join(detail.plan.competitors)}\n"
                        f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                        f"Competitor KB JSON: {self._competitor_kb_json(detail)}\n"
                        "Competitor Knowledge Schema JSON: "
                        f"{self._competitor_knowledge_json(detail)}\n"
                        f"Source digest JSON: {self._source_digest_json(detail)}"
                    ),
                    schema_hint=(
                        '{"matrix_summary":["row"],'
                        '"winner_by_dimension":{"dimension":"competitor or tie"}}'
                    ),
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            payload = self._deterministic_comparator_payload(timeout_seconds)
            fallback = {
                "reason": "timeout",
                "timeout_seconds": timeout_seconds,
                "deterministic_fallback": True,
            }
        detail.comparison_matrix = self._build_comparison_matrix(detail, payload)
        self._append_agent_message(
            record,
            from_agent="comparator",
            to_agent="reflector",
            message_type="comparison_matrix_ready",
            payload_schema="ComparisonMatrix",
            payload={"comparison_matrix": detail.comparison_matrix.model_dump(mode="json")},
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "comparator",
            None,
            "Comparator completed.",
            {"matrix": payload, "fallback": fallback},
        )

    def _deterministic_comparator_payload(self, timeout_seconds: float) -> dict[str, object]:
        return {
            "matrix_summary": [
                (
                    "Comparator LLM exceeded "
                    f"{timeout_seconds:g}s; generated deterministic evidence matrix."
                )
            ],
            "winner_by_dimension": {},
        }

    def _build_comparison_matrix(self, detail: RunDetail, payload: dict) -> ComparisonMatrix:
        cells: list[ComparisonCell] = []
        for dimension in detail.plan.dimensions:
            for competitor in detail.plan.competitors:
                kb = detail.competitor_kbs.get(competitor)
                findings = kb.slices.get(dimension, []) if kb else []
                related_sources = [
                    source
                    for source in self._sources_for_competitor_dimension(
                        detail, competitor, dimension
                    )
                ]
                value = self._structured_matrix_value(detail, competitor, dimension)
                if not value:
                    value = "; ".join(findings[:2])
                if not value and related_sources:
                    value = related_sources[0].snippet or related_sources[0].title
                cells.append(
                    ComparisonCell(
                        competitor=competitor,
                        dimension=dimension,
                        value=value or "No structured finding available.",
                        source_ids=[source.id for source in related_sources],
                        confidence=self._matrix_cell_confidence(
                            detail,
                            competitor,
                            dimension,
                            related_sources,
                        ),
                    )
                )

        payload_winners = payload.get("winner_by_dimension")
        if not isinstance(payload_winners, dict):
            payload_winners = {}
        voted_winners, vote_summary = self._matrix_majority_vote(
            detail,
            cells,
            {str(key): str(value) for key, value in payload_winners.items()},
        )
        return ComparisonMatrix(
            competitors=detail.plan.competitors,
            dimensions=detail.plan.dimensions,
            cells=cells,
            winner_by_dimension=voted_winners,
            summary=[
                *self._matrix_standardization_summary(detail),
                *self._string_list(payload.get("matrix_summary")),
                *vote_summary,
            ],
        )

    def _structured_matrix_value(
        self, detail: RunDetail, competitor: str, dimension: str
    ) -> str:
        knowledge = detail.competitor_knowledge.get(competitor)
        if knowledge is None:
            return ""
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            return self._structured_pricing_cell_value(knowledge.pricing_model)
        if "persona" in dimension_key or "user" in dimension_key:
            return self._structured_persona_cell_value(knowledge.user_personas)
        if "feature" in dimension_key:
            return self._structured_feature_cell_value(knowledge.feature_tree)
        return ""

    def _structured_pricing_cell_value(self, pricing: PricingModel) -> str:
        tier_parts = [
            (
                "tier_name={name}; price={price}; billing_cycle={cycle}; limits={limits}"
            ).format(
                name=self._compact_matrix_text(tier.name or "unknown", 44),
                price=self._compact_matrix_text(tier.price or "unknown", 120),
                cycle=self._compact_matrix_text(tier.billing_cycle or "unknown", 40),
                limits=self._compact_list_text(tier.limits, 160),
            )
            for tier in pricing.tiers[:6]
        ]
        note_parts = [
            self._compact_matrix_text(claim.claim, 180) for claim in pricing.notes[:2]
        ]
        return self._join_structured_parts(tier_parts, "notes", note_parts)

    def _structured_persona_cell_value(self, personas: UserPersonaModel) -> str:
        segment_parts = [
            (
                "segment={segment}; role={role}; company_size={size}; "
                "use_cases={use_cases}; pain_points={pain_points}"
            ).format(
                segment=self._compact_matrix_text(segment.name or "unknown", 36),
                role=self._compact_matrix_text(segment.role or "unknown", 36),
                size=self._compact_matrix_text(segment.company_size or "unknown", 32),
                use_cases=self._compact_list_text(segment.use_cases, 72),
                pain_points=self._compact_list_text(segment.pain_points, 72),
            )
            for segment in personas.segments[:3]
        ]
        summary_parts = [
            self._compact_matrix_text(claim.claim, 96)
            for claim in personas.summary_claims[:2]
        ]
        return self._join_structured_parts(segment_parts, "summary", summary_parts)

    def _structured_feature_cell_value(self, feature_tree: FeatureTree) -> str:
        feature_parts = [
            (
                "feature_name={name}; description={description}; "
                "claim_count={claim_count}; child_count={child_count}"
            ).format(
                name=self._compact_matrix_text(node.name or "unknown", 44),
                description=self._compact_matrix_text(node.description or "unknown", 120),
                claim_count=len(node.claims),
                child_count=len(node.children),
            )
            for node in self._prioritized_feature_nodes(feature_tree)[:6]
        ]
        summary_parts = [
            self._compact_matrix_text(claim.claim, 140)
            for claim in feature_tree.summary_claims[:2]
        ]
        return self._join_structured_parts(feature_parts, "summary", summary_parts)

    def _join_structured_parts(
        self, primary_parts: list[str], fallback_label: str, fallback_parts: list[str]
    ) -> str:
        parts = list(primary_parts)
        if not parts and fallback_parts:
            parts = [f"{fallback_label}={part}" for part in fallback_parts]
        return " | ".join(parts)

    def _compact_list_text(self, values: list[str], limit: int) -> str:
        cleaned = [value.strip() for value in values if value and value.strip()]
        if not cleaned:
            return "unknown"
        return self._compact_matrix_text(", ".join(cleaned[:3]), limit)

    def _matrix_standardization_summary(self, detail: RunDetail) -> list[str]:
        summary: list[str] = []
        for dimension in detail.plan.dimensions:
            dimension_key = dimension.casefold()
            if "pricing" in dimension_key:
                summary.append(self._pricing_standardization_summary(detail, dimension))
            elif "persona" in dimension_key or "user" in dimension_key:
                summary.append(self._persona_standardization_summary(detail, dimension))
            elif "feature" in dimension_key:
                summary.append(self._feature_standardization_summary(detail, dimension))
        return summary

    def _pricing_standardization_summary(self, detail: RunDetail, dimension: str) -> str:
        profiles: list[str] = []
        missing: list[str] = []
        for competitor in detail.plan.competitors:
            knowledge = detail.competitor_knowledge.get(competitor)
            pricing = knowledge.pricing_model if knowledge is not None else None
            tiers = list(pricing.tiers) if pricing is not None else []
            if not tiers:
                missing.append(competitor)
                profiles.append(f"{competitor} tiers=missing")
                continue
            tier_parts = [
                self._compact_pricing_tier(tier.name, tier.price, tier.billing_cycle)
                for tier in tiers[:6]
            ]
            profiles.append(f"{competitor} tiers={'|'.join(tier_parts)}")
        missing_note = f"; missing={','.join(missing)}" if missing else ""
        return (
            f"[pricing-standardization:{dimension}] "
            "aligned_fields=tier_name,price,billing_cycle; "
            f"{'; '.join(profiles)}{missing_note}"
        )

    def _compact_pricing_tier(self, name: str, price: str, billing_cycle: str) -> str:
        compact_name = self._compact_matrix_text(name or "unknown", 36)
        compact_price = self._compact_matrix_text(price or "unknown", 72)
        compact_cycle = self._compact_matrix_text(billing_cycle or "unknown", 32)
        if compact_cycle == "unknown" or compact_cycle in compact_price.casefold():
            return f"{compact_name}={compact_price}"
        return f"{compact_name}={compact_price}/{compact_cycle}"

    def _persona_standardization_summary(self, detail: RunDetail, dimension: str) -> str:
        profiles: list[str] = []
        missing: list[str] = []
        for competitor in detail.plan.competitors:
            knowledge = detail.competitor_knowledge.get(competitor)
            personas = knowledge.user_personas if knowledge is not None else None
            segments = list(personas.segments) if personas is not None else []
            if not segments:
                missing.append(competitor)
                profiles.append(f"{competitor} segments=missing")
                continue
            segment_parts = [
                self._compact_persona_segment(
                    segment.name,
                    segment.role,
                    segment.company_size,
                    len(segment.use_cases),
                    len(segment.pain_points),
                )
                for segment in segments[:3]
            ]
            profiles.append(f"{competitor} segments={'|'.join(segment_parts)}")
        missing_note = f"; missing={','.join(missing)}" if missing else ""
        return (
            f"[persona-standardization:{dimension}] "
            "aligned_fields=segment,role,company_size,use_cases,pain_points; "
            f"{'; '.join(profiles)}{missing_note}"
        )

    def _compact_persona_segment(
        self,
        name: str,
        role: str,
        company_size: str,
        use_case_count: int,
        pain_point_count: int,
    ) -> str:
        compact_name = self._compact_matrix_text(name or "unknown", 32)
        compact_role = self._compact_matrix_text(role or "unknown", 32)
        compact_size = self._compact_matrix_text(company_size or "unknown", 28)
        return (
            f"{compact_name}({compact_role}/{compact_size};"
            f"use_cases={use_case_count};pain_points={pain_point_count})"
        )

    def _feature_standardization_summary(self, detail: RunDetail, dimension: str) -> str:
        profiles: list[str] = []
        missing: list[str] = []
        for competitor in detail.plan.competitors:
            knowledge = detail.competitor_knowledge.get(competitor)
            feature_tree = knowledge.feature_tree if knowledge is not None else None
            nodes = list(feature_tree.nodes) if feature_tree is not None else []
            if not nodes:
                missing.append(competitor)
                profiles.append(f"{competitor} features=missing")
                continue
            feature_parts = [
                self._compact_feature_node(
                    node.name,
                    node.description,
                    len(node.claims),
                    len(node.children),
                )
                for node in self._prioritized_feature_nodes(feature_tree)[:6]
            ]
            profiles.append(f"{competitor} features={'|'.join(feature_parts)}")
        missing_note = f"; missing={','.join(missing)}" if missing else ""
        return (
            f"[feature-standardization:{dimension}] "
            "aligned_fields=feature_name,description,claim_count,child_count; "
            f"{'; '.join(profiles)}{missing_note}"
        )

    def _prioritized_feature_nodes(self, feature_tree: FeatureTree) -> list[FeatureNode]:
        return [
            node
            for _, _, node in sorted(
                (
                    self._feature_taxonomy_rank(node.name),
                    index,
                    node,
                )
                for index, node in enumerate(feature_tree.nodes)
            )
        ]

    def _feature_taxonomy_rank(self, name: str) -> int:
        normalized = (name or "").casefold()
        if normalized == "autocomplete":
            normalized = "code completion"
        try:
            return FEATURE_TAXONOMY_ORDER.index(normalized)
        except ValueError:
            return len(FEATURE_TAXONOMY_ORDER)

    def _compact_feature_node(
        self,
        name: str,
        description: str,
        claim_count: int,
        child_count: int,
    ) -> str:
        compact_name = self._compact_matrix_text(name or "unknown", 36)
        compact_description = self._compact_matrix_text(description or "unknown", 72)
        return (
            f"{compact_name}({compact_description};claims={claim_count};"
            f"children={child_count})"
        )

    def _compact_matrix_text(self, value: str, limit: int) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1].rstrip()}..."

    def _matrix_cell_confidence(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        related_sources: list[RawSource],
    ) -> float:
        source_confidence = (
            sum(source.confidence for source in related_sources) / len(related_sources)
            if related_sources
            else 0.0
        )
        claim_confidences = self._structured_claim_confidences(detail, competitor, dimension)
        if not claim_confidences:
            return self._persona_user_research_confidence_cap(
                dimension, related_sources, source_confidence
            )
        claim_confidence = sum(claim_confidences) / len(claim_confidences)
        if source_confidence <= 0:
            return self._persona_user_research_confidence_cap(
                dimension, related_sources, claim_confidence
            )
        confidence = min(source_confidence, claim_confidence)
        return self._persona_user_research_confidence_cap(
            dimension, related_sources, confidence
        )

    def _persona_user_research_confidence_cap(
        self,
        dimension: str,
        related_sources: list[RawSource],
        confidence: float,
    ) -> float:
        dimension_key = dimension.casefold()
        if "persona" not in dimension_key and "user" not in dimension_key:
            return confidence
        user_research_sources = [
            source
            for source in related_sources
            if source.source_type in {"interview_record", "survey_simulated"}
        ]
        if not user_research_sources:
            return confidence
        return min(confidence, min(source.confidence for source in user_research_sources))

    def _structured_claim_confidences(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> list[float]:
        knowledge = detail.competitor_knowledge.get(competitor)
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
        return [claim.confidence for claim in claims if claim.confidence > 0]

    def _matrix_majority_vote(
        self,
        detail: RunDetail,
        cells: list[ComparisonCell],
        payload_winners: dict[str, str],
    ) -> tuple[dict[str, str], list[str]]:
        winners: dict[str, str] = {}
        summary: list[str] = []
        cell_by_key = {(cell.dimension, cell.competitor): cell for cell in cells}
        for dimension in detail.plan.dimensions:
            signals: dict[str, str] = {}
            evidence_winner = self._winner_from_numeric_signal(
                {
                    competitor: len(
                        self._matrix_cell(cell_by_key, dimension, competitor).source_ids
                    )
                    for competitor in detail.plan.competitors
                }
            )
            confidence_winner = self._winner_from_numeric_signal(
                {
                    competitor: self._matrix_cell(
                        cell_by_key, dimension, competitor
                    ).confidence
                    for competitor in detail.plan.competitors
                }
            )
            finding_winner = self._winner_from_numeric_signal(
                {
                    competitor: self._matrix_finding_count(detail, dimension, competitor)
                    for competitor in detail.plan.competitors
                }
            )
            if evidence_winner:
                signals["evidence"] = evidence_winner
            if confidence_winner:
                signals["cell_confidence_winner"] = confidence_winner
            if finding_winner:
                signals["findings"] = finding_winner
            llm_winner = payload_winners.get(dimension)
            if llm_winner in detail.plan.competitors or llm_winner == "tie":
                signals["llm"] = llm_winner
            winner = self._winner_from_matrix_signals(dimension, signals)
            if winner is None:
                winner = llm_winner if isinstance(llm_winner, str) and llm_winner else "tie"
            winners[dimension] = winner
            summary.append(
                "[majority-vote:{dimension}] winner={winner}; {signals}".format(
                    dimension=dimension,
                    winner=winner,
                    signals=", ".join(
                        f"{name}={value}" for name, value in sorted(signals.items())
                    )
                    or "no decisive signal",
                )
            )
        return winners, summary

    def _matrix_cell(
        self,
        cell_by_key: dict[tuple[str, str], ComparisonCell],
        dimension: str,
        competitor: str,
    ) -> ComparisonCell:
        return cell_by_key.get(
            (dimension, competitor),
            ComparisonCell(competitor=competitor, dimension=dimension, value=""),
        )

    def _matrix_finding_count(
        self, detail: RunDetail, dimension: str, competitor: str
    ) -> int:
        kb = detail.competitor_kbs.get(competitor)
        return len(kb.slices.get(dimension, [])) if kb else 0

    def _winner_from_numeric_signal(self, scores: dict[str, float | int]) -> str | None:
        positive = {key: value for key, value in scores.items() if value > 0}
        if not positive:
            return None
        best = max(positive.values())
        winners = [key for key, value in positive.items() if value == best]
        return winners[0] if len(winners) == 1 else "tie"

    def _winner_from_votes(self, signals: dict[str, str]) -> str | None:
        votes = Counter(value for value in signals.values() if value != "tie")
        if not votes:
            return "tie" if "tie" in signals.values() else None
        [(winner, count), *rest] = votes.most_common()
        if rest and rest[0][1] == count:
            return "tie"
        return winner

    def _winner_from_matrix_signals(
        self, dimension: str, signals: dict[str, str]
    ) -> str | None:
        dimension_key = dimension.casefold()
        structural_winners = [
            signals[name]
            for name in ("evidence", "findings")
            if signals.get(name) and signals[name] != "tie"
        ]
        if "pricing" in dimension_key and not structural_winners:
            return "tie" if signals else None
        return self._winner_from_votes(signals)

    def _source_digest(self, sources: list[RawSource]) -> list[dict[str, object]]:
        return [
            {
                "id": source.id,
                "competitor": source.competitor,
                "covered_competitors": source.covered_competitors,
                "dimension": source.dimension,
                "source_type": source.source_type,
                "title": source.title[:160],
                "url": str(source.url) if source.url else None,
                "snippet": source.snippet[:420],
                "confidence": source.confidence,
            }
            for source in sources
        ]

    def _competitor_kb_json(self, detail: RunDetail) -> str:
        return json.dumps(
            {key: value.model_dump(mode="json") for key, value in detail.competitor_kbs.items()},
            ensure_ascii=False,
        )

    def _competitor_knowledge_json(self, detail: RunDetail) -> str:
        return json.dumps(
            {
                key: value.model_dump(mode="json")
                for key, value in detail.competitor_knowledge.items()
            },
            ensure_ascii=False,
        )

    def _source_digest_json(self, detail: RunDetail) -> str:
        return json.dumps(self._source_digest(detail.raw_sources), ensure_ascii=False)
