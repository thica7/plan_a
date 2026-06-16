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
    payload = json.loads(result.to_prompt_json())
    assert result.metrics.writer_evidence_pack_chars == len(result.to_prompt_json())
    assert payload["coverage"]["raw_source_count"] == result.metrics.raw_source_count
    assert "writer_evidence_pack_chars" not in payload["coverage"]
    registry_by_id = {item.id: item for item in result.pack.source_registry}
    assert set(registry_by_id) == {"cursor-pricing", "cursor-persona"}
    signals_by_id = {
        signal.id: signal
        for group in result.pack.groups
        for signal in group.unstructured_signals
    }
    pricing_signal = signals_by_id["signal:cursor-pricing"]
    persona_signal = signals_by_id["signal:cursor-persona"]
    assert pricing_signal.source_id == "cursor-pricing"
    assert pricing_signal.signal_summary == (
        "Cursor Pro costs $20 per month for individual developers."
    )
    assert pricing_signal.confidence == 0.96
    assert persona_signal.source_id == "cursor-persona"
    assert persona_signal.signal_summary == (
        "Enterprise engineering managers evaluate Cursor for repository-aware "
        "agentic coding, security review, onboarding friction, and budget control."
    )
    assert persona_signal.confidence == 0.82
    assert registry_by_id["cursor-pricing"].represented_by == ["signal:cursor-pricing"]
    assert registry_by_id["cursor-persona"].represented_by == ["signal:cursor-persona"]
    assert registry_by_id["cursor-pricing"].no_signal_reason is None
    expected_projection_chars = len(
        json.dumps(
            {
                "registry_item": registry_by_id["cursor-pricing"].model_dump(mode="json"),
                "unstructured_signals": [pricing_signal.model_dump(mode="json")],
                "facts": [],
                "quotes": [],
            },
            ensure_ascii=False,
        )
    )
    assert result.metrics.largest_source_projection_chars >= expected_projection_chars


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
    assert result.pack.groups[0].unstructured_signals == []
    assert result.metrics.no_signal_source_count == 1
    assert result.metrics.dropped_source_count == 0
    assert json.loads(result.to_prompt_json())["coverage"]["raw_source_count"] == 1


def test_pricing_normalized_fields_become_deduped_facts_and_bounded_quote() -> None:
    repeated_quote = "OpenAI pricing table lists model input cached input and output rates. " * 80
    fields = [
        {
            "kind": "pricing",
            "dimension": "pricing",
            "competitor": "OpenAI Codex",
            "model_type": "api_usage_based",
            "tier_name": f"gpt-5.{index}",
            "price": "$5.00",
            "billing_cycle": "per 1m tokens",
            "usage_limit": "short context",
            "enterprise_condition": "enterprise_available",
            "source_quote": repeated_quote,
        }
        for index in range(65)
    ]
    source = RawSource(
        id="openai-pricing",
        competitor="OpenAI Codex",
        dimension="pricing",
        source_type="webpage_verified",
        title="Pricing | OpenAI API",
        url="https://openai.com/api/pricing",
        snippet="Pricing table for OpenAI API models.",
        content_hash="openai-pricing-hash",
        confidence=0.96,
        metadata={"normalized_fields": fields},
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    group = result.pack.groups[0]

    assert len(group.facts) == 65
    assert len(result.pack.quotes) == 1
    assert result.pack.quotes[0].raw_quote_chars == len(repeated_quote)
    assert len(result.pack.quotes[0].excerpt) <= 500
    assert group.facts[0].quote_ids == [result.pack.quotes[0].id]
    assert result.metrics.deduped_quote_count == 64
    assert result.metrics.largest_quote_projection_chars < 900
    assert result.metrics.writer_evidence_pack_chars < 80_000


def test_mixed_structured_source_keeps_residual_snippet_signal() -> None:
    source = RawSource(
        id="cursor-pricing-mixed",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://cursor.com/pricing",
        snippet=(
            "Cursor Pro costs $20 per month. Enterprise procurement requires sales "
            "contact and security review before rollout."
        ),
        content_hash="cursor-pricing-mixed-hash",
        confidence=0.95,
        metadata={
            "normalized_fields": [
                {
                    "kind": "pricing",
                    "model_type": "subscription_saas",
                    "tier_name": "Pro",
                    "price": "$20/month",
                    "billing_cycle": "monthly",
                    "source_quote": "Cursor Pro costs $20 per month.",
                }
            ]
        },
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    group = result.pack.groups[0]

    assert len(group.facts) == 1
    assert group.unstructured_signals
    assert (
        "Enterprise procurement requires sales contact"
        in group.unstructured_signals[0].signal_summary
    )
    assert result.pack.source_registry[0].represented_by


def test_conflicting_normalized_pricing_facts_create_conflict() -> None:
    sources = [
        RawSource(
            id="cursor-official",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            snippet="Cursor Pro costs $20 per month.",
            content_hash="cursor-official-hash",
            confidence=0.96,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$20/month",
                        "billing_cycle": "monthly",
                        "source_quote": "Cursor Pro costs $20 per month.",
                    }
                ]
            },
        ),
        RawSource(
            id="cursor-community",
            competitor="Cursor",
            dimension="pricing",
            source_type="community_forum",
            title="Cursor community pricing",
            snippet="A community post says Cursor Pro is $25 per month in one billing view.",
            content_hash="cursor-community-hash",
            confidence=0.74,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$25/month",
                        "billing_cycle": "monthly",
                        "source_quote": "Cursor Pro is $25 per month in one billing view.",
                    }
                ],
                "community_evidence": True,
            },
        ),
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))
    group = result.pack.groups[0]

    assert group.conflicts
    assert group.conflicts[0].claim_area == "pricing:pro:monthly"
    assert "cursor-official" in group.conflicts[0].source_ids_by_position["$20/month"]
    assert (
        "cursor-community"
        in group.conflicts[0].source_ids_by_position["$25/month"]
    )
