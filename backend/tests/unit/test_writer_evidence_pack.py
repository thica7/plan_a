from __future__ import annotations

import json

from packages.agents.writer.evidence_pack import build_writer_evidence_pack
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource


def _detail_with_sources(sources: list[RawSource]) -> RunDetail:
    return RunDetail(
        id="run-evidence-pack",
        topic="AI coding agent",
        status="running",
        execution_mode="real",
        created_at="2026-06-16T00:00:00",
        updated_at="2026-06-16T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Cursor"],
            dimensions=["pricing", "persona"],
        ),
        raw_sources=sources,
    )


def test_evidence_pack_source_registry_represents_every_accepted_source() -> None:
    sources = [
        RawSource(
            id="cursor-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.com/pricing",
            snippet="Cursor Pro costs $20 per month for individual developers.",
            content_hash="cursor-pricing-hash",
            confidence=0.96,
        ),
        RawSource(
            id="cursor-persona",
            competitor="Cursor",
            dimension="persona",
            source_type="interview_record",
            title="Cursor persona interview",
            snippet=(
                "Enterprise engineering managers evaluate Cursor for repository-aware "
                "agentic coding, security review, onboarding friction, and budget control."
            ),
            content_hash="cursor-persona-hash",
            confidence=0.82,
        ),
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))

    assert result.pack.schema_version == "writer_evidence_pack.v1"
    assert result.metrics.raw_source_count == 2
    assert result.metrics.represented_source_count == 2
    assert result.metrics.dropped_source_count == 0
    registry_by_id = {item.id: item for item in result.pack.source_registry}
    assert set(registry_by_id) == {"cursor-pricing", "cursor-persona"}
    assert registry_by_id["cursor-pricing"].represented_by
    assert registry_by_id["cursor-persona"].represented_by
    assert registry_by_id["cursor-pricing"].no_signal_reason is None


def test_evidence_pack_marks_noisy_source_without_inventing_signal() -> None:
    source = RawSource(
        id="cursor-noisy",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing navigation",
        snippet="Skip to content Navigation Menu Sign in Cookie Privacy policy",
        content_hash="cursor-noisy-hash",
        confidence=0.9,
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))

    registry_item = result.pack.source_registry[0]
    assert registry_item.id == "cursor-noisy"
    assert registry_item.represented_by == []
    assert registry_item.no_signal_reason == "no_clean_business_signal"
    assert result.metrics.no_signal_source_count == 1
    assert result.metrics.dropped_source_count == 0
    assert json.loads(result.to_prompt_json())["coverage"]["raw_source_count"] == 1
