from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

from packages.schema.api_dto import RunDetail
from packages.schema.models import ComparisonCell, ComparisonMatrix, RawSource

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


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
                value = "; ".join(findings[:2])
                if not value and related_sources:
                    value = related_sources[0].snippet or related_sources[0].title
                cells.append(
                    ComparisonCell(
                        competitor=competitor,
                        dimension=dimension,
                        value=value or "No structured finding available.",
                        source_ids=[source.id for source in related_sources],
                        confidence=(
                            sum(source.confidence for source in related_sources)
                            / len(related_sources)
                            if related_sources
                            else 0.0
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

    def _matrix_standardization_summary(self, detail: RunDetail) -> list[str]:
        summary: list[str] = []
        for dimension in detail.plan.dimensions:
            dimension_key = dimension.casefold()
            if "pricing" in dimension_key:
                summary.append(self._pricing_standardization_summary(detail, dimension))
            elif "persona" in dimension_key or "user" in dimension_key:
                summary.append(self._persona_standardization_summary(detail, dimension))
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
                for tier in tiers[:4]
            ]
            profiles.append(f"{competitor} tiers={'|'.join(tier_parts)}")
        missing_note = f"; missing={','.join(missing)}" if missing else ""
        return (
            f"[pricing-standardization:{dimension}] "
            "aligned_fields=tier_name,price,billing_cycle; "
            f"{'; '.join(profiles)}{missing_note}"
        )

    def _compact_pricing_tier(self, name: str, price: str, billing_cycle: str) -> str:
        compact_name = self._compact_matrix_text(name or "unknown", 32)
        compact_price = self._compact_matrix_text(price or "unknown", 48)
        compact_cycle = self._compact_matrix_text(billing_cycle or "unknown", 24)
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

    def _compact_matrix_text(self, value: str, limit: int) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1].rstrip()}..."

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
                signals["confidence"] = confidence_winner
            if finding_winner:
                signals["findings"] = finding_winner
            llm_winner = payload_winners.get(dimension)
            if llm_winner in detail.plan.competitors or llm_winner == "tie":
                signals["llm"] = llm_winner
            winner = self._winner_from_votes(signals)
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
