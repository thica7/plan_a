from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from packages.agents.writer.section_writer import SectionWriter
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan


@pytest.mark.asyncio
async def test_section_writer_synthesizes_section_from_evidence_shards() -> None:
    detail = RunDetail(
        id="run-section-writer",
        topic="AI coding agent",
        status="running",
        execution_mode="demo",
        created_at="2026-06-20T00:00:00",
        updated_at="2026-06-20T00:00:00",
        output_language="en-US",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Acme"],
            dimensions=["pricing"],
        ),
    )
    record = SimpleNamespace(detail=detail)
    calls: list[dict[str, object]] = []
    factory_kwargs: list[dict[str, Any]] = []

    async def validated_segment_markdown(*args: object, **kwargs: object) -> tuple[str, Any]:
        segment = kwargs["segment"]
        assert isinstance(segment, dict)
        calls.append(segment.copy())
        if segment.get("segment_kind") == "evidence_shard":
            return (
                f"- shard note {segment['segment_batch']} "
                f"[source:{segment['allowed_source_ids'][0]}]",
                SimpleNamespace(
                    segment_kind="evidence_shard",
                    section_id=segment["section_id"],
                ),
            )
        assert segment["segment_kind"] == "section_fragment"
        return (
            "## Decision Summary\n"
            "Acme pricing is ready after shard synthesis [source:pricing-a].",
            SimpleNamespace(segment_kind="section_fragment"),
        )

    def shard_segment_factory(*args: object, **kwargs: Any) -> dict[str, object]:
        factory_kwargs.append(kwargs.copy())
        return SectionWriter.build_section_segment_from_shards(detail, **kwargs)

    writer = SectionWriter(
        validated_segment_markdown=validated_segment_markdown,
        shard_segment_factory=shard_segment_factory,
    )

    parts = await writer.write_markdown_parts(
        record,
        evidence_pack_result=object(),
        segments=[
            {
                "segment_name": "decision_summary",
                "segment_kind": "evidence_shard",
                "section_id": "decision_summary",
                "segment_batch": "sources:1",
                "allowed_source_ids": ["pricing-a"],
            },
            {
                "segment_name": "decision_summary",
                "segment_kind": "evidence_shard",
                "section_id": "decision_summary",
                "segment_batch": "sources:2",
                "allowed_source_ids": ["pricing-b"],
            },
        ],
        timeout_seconds=1.0,
        language_guidance="Use English.",
        memory_context="",
        layer_context="",
        required_sections="## Decision Summary",
    )

    assert parts == [
        "## Decision Summary\n"
        "Acme pricing is ready after shard synthesis [source:pricing-a]."
    ]
    assert [call["segment_kind"] for call in calls] == [
        "evidence_shard",
        "evidence_shard",
        "section_fragment",
    ]
    assert factory_kwargs[0]["section_id"] == "decision_summary"
    assert factory_kwargs[0]["shard_notes"] == [
        "- shard note sources:1 [source:pricing-a]",
        "- shard note sources:2 [source:pricing-b]",
    ]
    assert calls[-1]["allowed_source_ids"] == ["pricing-a", "pricing-b"]
    assert calls[-1]["segment_input_chars"] > 0