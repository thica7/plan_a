from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from packages.agents.writer.evidence_pack import SEGMENT_INPUT_TARGET_CHARS
from packages.schema.api_dto import RunDetail

ValidatedSegmentWriter = Callable[..., Awaitable[tuple[str, Any]]]
ShardSegmentFactory = Callable[..., dict[str, object]]


@dataclass(frozen=True)
class SectionWriter:
    validated_segment_markdown: ValidatedSegmentWriter
    shard_segment_factory: ShardSegmentFactory

    async def write_markdown_parts(
        self,
        record: object,
        *,
        evidence_pack_result: object,
        segments: Sequence[dict[str, object]],
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
    ) -> list[str]:
        detail = _record_detail(record)
        sections: list[str] = []
        shards_by_section: dict[tuple[str, str | None], list[str]] = {}
        section_allowed_source_ids: dict[tuple[str, str | None], set[str]] = {}
        for segment in segments:
            segment_md, contract = await self.validated_segment_markdown(
                record,
                evidence_pack_result=evidence_pack_result,
                segment=segment,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
            )
            if getattr(contract, "segment_kind", None) == "evidence_shard":
                section_id = str(contract.section_id)
                segment_competitor = (
                    segment.get("segment_competitor")
                    if isinstance(segment.get("segment_competitor"), str)
                    else None
                )
                shard_key = (
                    section_id,
                    segment_competitor if section_id == "competitor_deep_dives" else None,
                )
                shards_by_section.setdefault(shard_key, []).append(segment_md)
                section_allowed_source_ids.setdefault(shard_key, set()).update(
                    source_id
                    for source_id in (segment.get("allowed_source_ids") or [])
                    if isinstance(source_id, str)
                )
                continue
            sections.append(segment_md)

        for (section_id, segment_competitor), shard_notes in shards_by_section.items():
            section_segment = self.shard_segment_factory(
                detail,
                section_id=section_id,
                segment_competitor=segment_competitor,
                shard_notes=shard_notes,
                allowed_source_ids=section_allowed_source_ids[
                    (section_id, segment_competitor)
                ],
            )
            section_md, _ = await self.validated_segment_markdown(
                record,
                evidence_pack_result=evidence_pack_result,
                segment=section_segment,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
            )
            sections.append(section_md)
        return sections

    @staticmethod
    def build_section_segment_from_shards(
        detail: RunDetail,
        *,
        section_id: str,
        segment_competitor: str | None,
        shard_notes: Sequence[str],
        allowed_source_ids: set[str],
    ) -> dict[str, object]:
        segment_name = (
            f"{section_id} {segment_competitor}"
            if section_id == "competitor_deep_dives" and segment_competitor
            else section_id
        )
        section_segment: dict[str, object] = {
            "segment_name": segment_name,
            "segment_kind": "section_fragment",
            "section_id": section_id,
            "segment_competitor": segment_competitor,
            "output_language": detail.output_language,
            "segment_input_chars": 0,
            "allowed_source_ids": sorted(allowed_source_ids),
            "groups": [],
            "sources": [],
            "shard_notes": list(shard_notes),
            "segment_batch": "from_evidence_shards",
        }
        refresh_segment_input_chars(section_segment)
        if section_segment["segment_input_chars"] > SEGMENT_INPUT_TARGET_CHARS:
            section_segment["segment_input_target_chars"] = SEGMENT_INPUT_TARGET_CHARS
            section_segment["segment_over_budget_reason"] = "shard_notes_exceed_budget"
            refresh_segment_input_chars(section_segment)
        return section_segment


def refresh_segment_input_chars(segment: dict[str, object]) -> None:
    import json

    segment["segment_input_chars"] = 0
    while True:
        segment_input_chars = len(json.dumps(segment, ensure_ascii=False))
        if segment["segment_input_chars"] == segment_input_chars:
            return
        segment["segment_input_chars"] = segment_input_chars


def _record_detail(record: object) -> RunDetail:
    detail = getattr(record, "detail", None)
    if not isinstance(detail, RunDetail):
        raise TypeError("section writer record must expose RunDetail as .detail")
    return detail