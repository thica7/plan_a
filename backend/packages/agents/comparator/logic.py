from __future__ import annotations

import json
from datetime import datetime

from packages.schema.models import ComparisonCell, ComparisonMatrix


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
        payload = await self._trace_llm_json(
            record,
            agent="comparator",
            subagent=None,
            name="comparison_matrix",
            system="You are a comparator. Build a compact cross-competitor matrix summary.",
            user=(
                f"Topic: {detail.topic}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                f"Competitor KB JSON: {json.dumps({k: v.model_dump(mode='json') for k, v in detail.competitor_kbs.items()}, ensure_ascii=False)}\n"
                f"Competitor Knowledge Schema JSON: {json.dumps({k: v.model_dump(mode='json') for k, v in detail.competitor_knowledge.items()}, ensure_ascii=False)}\n"
                f"Source digest JSON: {json.dumps(self._source_digest(detail.raw_sources), ensure_ascii=False)}"
            ),
            schema_hint='{"matrix_summary":["row"],"winner_by_dimension":{"dimension":"competitor or tie"}}',
        )
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
        await self.emit(detail.id, "node_completed", "comparator", None, "Comparator completed.", {"matrix": payload})

    def _build_comparison_matrix(self, detail: RunDetail, payload: dict) -> ComparisonMatrix:
        cells: list[ComparisonCell] = []
        for dimension in detail.plan.dimensions:
            for competitor in detail.plan.competitors:
                kb = detail.competitor_kbs.get(competitor)
                findings = kb.slices.get(dimension, []) if kb else []
                related_sources = [
                    source for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
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
                            sum(source.confidence for source in related_sources) / len(related_sources)
                            if related_sources
                            else 0.0
                        ),
                    )
                )

        winners = payload.get("winner_by_dimension")
        if not isinstance(winners, dict):
            winners = {}
        return ComparisonMatrix(
            competitors=detail.plan.competitors,
            dimensions=detail.plan.dimensions,
            cells=cells,
            winner_by_dimension={str(key): str(value) for key, value in winners.items()},
            summary=self._string_list(payload.get("matrix_summary")),
        )

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
