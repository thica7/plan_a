from __future__ import annotations

import json

from packages.agents.writer.evidence_pack import (
    QUOTE_EXCERPT_LIMIT,
    SEGMENT_INPUT_TARGET_CHARS,
    SEGMENT_SOURCE_BATCH_SIZE,
    WriterEvidencePack,
    WriterEvidencePackMetrics,
    WriterEvidencePackResult,
    WriterSourceRegistryItem,
    build_writer_evidence_pack,
)
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan,
    ComparisonCell,
    ComparisonMatrix,
    CompetitorKB,
    CompetitorKnowledge,
    PricingModel,
    PricingTier,
    RawSource,
)


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


def test_writer_evidence_pack_includes_all_raw_sources() -> None:
    sources = [
        RawSource(
            id=f"raw-source-{index:02d}",
            competitor="Cursor",
            dimension="persona" if index > 24 else "pricing",
            source_type="interview_record" if index > 24 else "webpage_verified",
            title=f"Cursor source {index}",
            url=None,
            snippet=(
                (
                    f"Source {index} contains decision-relevant enterprise developer "
                    "team, workflow, and adoption evidence for the report writer."
                )
                if index > 24
                else (
                    f"Source {index} contains decision-relevant buyer, pricing, and adoption "
                    "evidence for the report writer."
                )
            ),
            content_hash=f"source-{index}-hash",
            confidence=0.9,
        )
        for index in range(1, 31)
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))

    assert len(result.pack.source_registry) == 30
    assert result.pack.source_registry[-1].id == "raw-source-30"
    assert result.metrics.source_registry_count == 30
    assert result.metrics.raw_source_count == 30
    assert result.metrics.represented_source_count == 30
    assert result.metrics.dropped_source_count == 0


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


def test_evidence_pack_preflight_flags_unrepresented_source() -> None:
    source = RawSource(
        id="cursor-empty",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor empty",
        snippet="",
        content_hash="cursor-empty-hash",
        confidence=0.9,
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))

    assert result.pack.source_registry[0].no_signal_reason == "no_clean_business_signal"
    assert result.preflight_errors() == []


def test_evidence_pack_preflight_errors_report_unrepresented_and_dropped_counts() -> None:
    result = WriterEvidencePackResult(
        pack=WriterEvidencePack(
            source_registry=[
                WriterSourceRegistryItem(
                    id="cursor-unrepresented",
                    competitor="Cursor",
                    dimension="pricing",
                    source_type="webpage_verified",
                    title="Cursor unrepresented",
                    confidence=0.9,
                )
            ]
        ),
        metrics=WriterEvidencePackMetrics(
            dropped_source_count=2,
            dropped_kb_slice_count=3,
        ),
    )

    assert result.preflight_errors() == [
        "source_not_represented:cursor-unrepresented",
        "dropped_source_count:2",
        "dropped_kb_slice_count:3",
    ]


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
    assert len(result.pack.quotes[0].excerpt) <= QUOTE_EXCERPT_LIMIT
    assert group.facts[0].quote_ids == [result.pack.quotes[0].id]
    assert result.metrics.deduped_quote_count == 64
    assert result.metrics.largest_quote_projection_chars < 900
    assert result.metrics.writer_evidence_pack_chars < 80_000


def test_run_58_style_pricing_source_stays_below_prompt_budget() -> None:
    quote = "Standard Batch Flex Priority Standard Short context Long context Model Input Cached input Output. " * 80
    source = RawSource(
        id="raw-source-openai-pricing",
        competitor="OpenAI Codex",
        dimension="pricing",
        source_type="webpage_verified",
        title="Pricing | OpenAI API",
        snippet="OpenAI API pricing table.",
        content_hash="openai-pricing-run58-hash",
        confidence=0.96,
        metadata={
            "normalized_fields": [
                {
                    "kind": "pricing",
                    "dimension": "pricing",
                    "competitor": "OpenAI Codex",
                    "model_type": "api_usage_based",
                    "tier_name": f"gpt-5.{index}",
                    "price": f"${index}.00",
                    "billing_cycle": "per 1m",
                    "usage_limit": "short context",
                    "enterprise_condition": "enterprise_available",
                    "source_quote": quote,
                }
                for index in range(65)
            ]
        },
    )
    detail = _detail_with_sources([source])
    detail.plan.competitors = ["OpenAI Codex"]
    detail.plan.dimensions = ["pricing"]

    result = build_writer_evidence_pack(detail)

    assert result.metrics.raw_source_count == 1
    assert result.metrics.represented_source_count == 1
    assert result.metrics.writer_evidence_pack_chars < 90_000
    assert result.metrics.largest_quote_projection_chars < 1_100
    assert result.metrics.deduped_quote_count == 64


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


def test_identical_pricing_facts_dedupe_across_source_specific_metadata() -> None:
    sources = [
        RawSource(
            id="cursor-pricing-a",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing A",
            snippet="Cursor Pro costs $20/month.",
            content_hash="cursor-pricing-a-hash",
            confidence=0.91,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$20/month",
                        "billing_cycle": "monthly",
                        "confidence": 0.91,
                        "evidence_item_ids": ["evidence-a"],
                        "source_quote": "Cursor Pro costs $20/month.",
                    }
                ]
            },
        ),
        RawSource(
            id="cursor-pricing-b",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing B",
            snippet="Cursor Pro costs $20/month.",
            content_hash="cursor-pricing-b-hash",
            confidence=0.96,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$20/month",
                        "billing_cycle": "monthly",
                        "confidence": 0.72,
                        "evidence_item_ids": ["evidence-b"],
                        "source_quote": "Cursor Pro costs $20/month.",
                    }
                ]
            },
        ),
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))
    fact = result.pack.groups[0].facts[0]

    assert len(result.pack.groups[0].facts) == 1
    assert fact.source_ids == ["cursor-pricing-a", "cursor-pricing-b"]
    assert fact.confidence == 0.91
    assert "confidence" not in fact.values
    assert "evidence_item_ids" not in fact.values
    assert result.metrics.deduped_fact_count == 1


def test_pricing_conflicts_use_canonical_price_and_cycle_values() -> None:
    sources = [
        RawSource(
            id="cursor-slash",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing slash",
            snippet="Cursor Pro costs $20/month.",
            content_hash="cursor-slash-hash",
            confidence=0.95,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$20/month",
                        "billing_cycle": "monthly",
                    }
                ]
            },
        ),
        RawSource(
            id="cursor-words",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing words",
            snippet="Cursor Pro costs $20 per month.",
            content_hash="cursor-words-hash",
            confidence=0.93,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$20 per month",
                        "billing_cycle": "month",
                    }
                ]
            },
        ),
        RawSource(
            id="cursor-higher",
            competitor="Cursor",
            dimension="pricing",
            source_type="community_forum",
            title="Cursor pricing higher",
            snippet="A community post says Cursor Pro costs $25/month.",
            content_hash="cursor-higher-hash",
            confidence=0.73,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$25/month",
                        "billing_cycle": "monthly",
                    }
                ],
                "community_evidence": True,
            },
        ),
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))
    conflict = result.pack.groups[0].conflicts[0]

    assert len(result.pack.groups[0].conflicts) == 1
    assert conflict.claim_area == "pricing:pro:monthly"
    assert "cursor-slash" in conflict.source_ids_by_position["$20/month"]
    assert "cursor-words" in conflict.source_ids_by_position["$20/month"]
    assert "$20 per month" not in conflict.source_ids_by_position
    assert "cursor-higher" in conflict.source_ids_by_position["$25/month"]


def test_equivalent_pricing_facts_dedupe_across_price_spellings() -> None:
    sources = [
        RawSource(
            id="cursor-slash-price",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing slash",
            snippet="Cursor Pro costs $20/month.",
            content_hash="cursor-slash-price-hash",
            confidence=0.95,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$20/month",
                        "billing_cycle": "monthly",
                    }
                ]
            },
        ),
        RawSource(
            id="cursor-word-price",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing words",
            snippet="Cursor Pro costs $20 per month.",
            content_hash="cursor-word-price-hash",
            confidence=0.92,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "tier_name": "Pro",
                        "price": "$20 per month",
                        "billing_cycle": "month",
                    }
                ]
            },
        ),
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))
    fact = result.pack.groups[0].facts[0]

    assert len(result.pack.groups[0].facts) == 1
    assert fact.source_ids == ["cursor-slash-price", "cursor-word-price"]
    assert result.metrics.deduped_fact_count == 1


def test_structured_pricing_without_quote_suppresses_duplicate_residual_signal() -> None:
    source = RawSource(
        id="cursor-pricing-structured-only",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="A Pro plan costs $20/month for developers.",
        content_hash="cursor-pricing-structured-only-hash",
        confidence=0.94,
        metadata={
            "normalized_fields": [
                {
                    "kind": "pricing",
                    "tier_name": "Pro",
                    "price": "$20/month",
                    "billing_cycle": "monthly",
                    "usage_limit": "for developers",
                }
            ]
        },
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    group = result.pack.groups[0]

    assert len(group.facts) == 1
    assert group.unstructured_signals == []


def test_mixed_structured_without_quote_keeps_unique_residual_signal() -> None:
    source = RawSource(
        id="cursor-pricing-noquote-mixed",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet=(
            "A Pro plan costs $20/month. Enterprise procurement requires sales "
            "contact and security review before rollout."
        ),
        content_hash="cursor-pricing-noquote-mixed-hash",
        confidence=0.94,
        metadata={
            "normalized_fields": [
                {
                    "kind": "pricing",
                    "tier_name": "Pro",
                    "price": "$20/month",
                    "billing_cycle": "monthly",
                }
            ]
        },
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    group = result.pack.groups[0]

    assert len(group.facts) == 1
    assert len(group.unstructured_signals) == 1
    assert (
        "procurement requires sales contact"
        in group.unstructured_signals[0].signal_summary
    )
    assert "security review" in group.unstructured_signals[0].signal_summary


def test_community_clusters_project_compact_fact_sources_and_confidence() -> None:
    source = RawSource(
        id="cursor-community",
        competitor="Cursor",
        dimension="pricing",
        source_type="reddit_thread",
        title="Cursor community pricing",
        snippet="Community users report Cursor Pro pricing caveats.",
        content_hash="cursor-community-hash",
        confidence=0.62,
        metadata={
            "community_evidence": True,
            "community_claim_clusters": [
                {
                    "kind": "pricing",
                    "label": "community_observed",
                    "claim": "Community users report Cursor Pro costs $20/month.",
                    "source_ids": ["thread-a", "thread-b"],
                    "confidence": 0.6789,
                    "evidence": ["Cursor Pro costs $20/month."],
                }
            ],
        },
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    fact = result.pack.groups[0].facts[0]

    assert fact.kind == "community_pricing"
    assert fact.source_ids == ["cursor-community", "thread-a", "thread-b"]
    assert fact.confidence == 0.679


def test_evidence_pack_preserves_every_kb_slice_with_provenance() -> None:
    findings = [
        (
            f"Persona evidence {index}: segment=Enterprise engineering teams; "
            "role=technical buyer; company_size=enterprise; "
            "use_cases=agentic coding, refactoring, IDE workflow, pull request governance; "
            "pain_points=security risk, cost control, developer onboarding, audit readiness."
        )
        for index in range(1, 6)
    ]
    detail = _detail_with_sources([])
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["persona"]
    detail.competitor_kbs = {
        "Cursor": CompetitorKB(
            competitor="Cursor",
            sources=["cursor-kb-source"],
            slices={"persona": findings},
        )
    }

    result = build_writer_evidence_pack(detail)
    group = result.pack.groups[0]

    assert result.metrics.kb_slice_count == 5
    assert result.metrics.represented_kb_slice_count == 5
    assert result.metrics.dropped_kb_slice_count == 0
    assert result.pack.coverage["kb_slice_count"] == 5
    assert result.pack.coverage["represented_kb_slice_count"] == 5
    assert result.pack.coverage["dropped_kb_slice_count"] == 0
    assert [signal.id for signal in group.kb_signals] == [
        f"kb:Cursor:persona:{index}" for index in range(5)
    ]
    assert [signal.source_ids for signal in group.kb_signals] == [
        ["cursor-kb-source"] for _ in findings
    ]
    assert [signal.text for signal in group.kb_signals] == findings


def test_evidence_pack_kb_provenance_marks_source_represented() -> None:
    source = RawSource(
        id="cursor-kb-source",
        competitor="Cursor",
        dimension="persona",
        source_type="webpage_verified",
        title="Cursor KB source",
        snippet="Skip to content Navigation Menu Sign in Cookie Privacy policy",
        content_hash="cursor-kb-source-hash",
        confidence=0.9,
    )
    detail = _detail_with_sources([source])
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["persona"]
    detail.competitor_kbs = {
        "Cursor": CompetitorKB(
            competitor="Cursor",
            sources=["cursor-kb-source"],
            slices={
                "persona": [
                    "Enterprise buyers evaluate Cursor for security review."
                ]
            },
        )
    }

    result = build_writer_evidence_pack(detail)
    registry_item = result.pack.source_registry[0]

    assert registry_item.represented_by == ["kb:Cursor:persona:0"]
    assert registry_item.no_signal_reason is None
    assert result.metrics.represented_source_count == 1


def test_evidence_pack_kb_provenance_prefers_dimension_sources() -> None:
    sources = [
        RawSource(
            id="cursor-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            snippet="Cursor pricing evidence supports the pricing slice.",
            content_hash="cursor-pricing-hash",
            confidence=0.92,
        ),
        RawSource(
            id="cursor-persona",
            competitor="Cursor",
            dimension="persona",
            source_type="interview_record",
            title="Cursor persona",
            snippet="Cursor persona evidence supports the persona slice.",
            content_hash="cursor-persona-hash",
            confidence=0.88,
        ),
    ]
    detail = _detail_with_sources(sources)
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["pricing", "persona"]
    detail.competitor_kbs = {
        "Cursor": CompetitorKB(
            competitor="Cursor",
            sources=["cursor-pricing", "cursor-persona"],
            slices={
                "pricing": ["Pricing slice"],
                "persona": ["Persona slice"],
            },
        )
    }

    result = build_writer_evidence_pack(detail)
    groups = {(group.competitor, group.dimension): group for group in result.pack.groups}
    registry = {item.id: item for item in result.pack.source_registry}

    assert groups[("Cursor", "pricing")].kb_signals[0].source_ids == ["cursor-pricing"]
    assert groups[("Cursor", "persona")].kb_signals[0].source_ids == ["cursor-persona"]
    assert "kb:Cursor:persona:0" not in registry["cursor-pricing"].represented_by
    assert "kb:Cursor:pricing:0" not in registry["cursor-persona"].represented_by


def test_evidence_pack_preserves_comparison_matrix_digest() -> None:
    detail = _detail_with_sources([])
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["pricing"]
    detail.comparison_matrix = ComparisonMatrix(
        competitors=["Cursor"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Cursor Pro is priced at $20/month for individual developers.",
                source_ids=["cursor-pricing"],
                confidence=0.94,
            )
        ],
        winner_by_dimension={"pricing": "Cursor"},
        summary=["Cursor has clear individual pricing."],
    )

    result = build_writer_evidence_pack(detail)

    assert result.pack.matrix["winner_by_dimension"]["pricing"] == "Cursor"
    assert result.pack.matrix["cells"][0]["source_ids"] == ["cursor-pricing"]


def test_evidence_pack_structured_knowledge_stays_visible() -> None:
    detail = _detail_with_sources([])
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["pricing"]
    detail.competitor_knowledge = {
        "Cursor": CompetitorKnowledge(competitor="Cursor", confidence=0.8764),
        "Codeium": CompetitorKnowledge(
            competitor="Codeium",
            confidence=0.7123,
            pricing_model=PricingModel(
                tiers=[PricingTier(name="Pro", price="$20/month")]
            ),
        ),
    }

    result = build_writer_evidence_pack(detail)
    payload = result.pack.model_dump(mode="json")

    assert "structured_knowledge" in payload
    assert payload["structured_knowledge"]["Cursor"] == {"confidence": 0.876}
    assert payload["structured_knowledge"]["Codeium"]["confidence"] == 0.712
    assert payload["structured_knowledge"]["Codeium"]["pricing_model"]["tiers"] == [
        {"name": "Pro", "price": "$20/month"}
    ]
    assert "review_summary" not in payload["structured_knowledge"]["Codeium"]


def test_source_appendix_rows_are_generated_from_registry() -> None:
    source = RawSource(
        id="cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://cursor.com/pricing",
        snippet="Cursor Pro costs $20 per month.",
        content_hash="cursor-pricing-hash",
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
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    rows = result.source_appendix_rows()

    assert rows == [
        {
            "source_id": "cursor-pricing",
            "title": "Cursor pricing",
            "url": "https://cursor.com/pricing",
            "source_type": "webpage_verified",
            "competitor": "Cursor",
            "dimension": "pricing",
            "confidence": 0.96,
            "represented_by": list(result.pack.source_registry[0].represented_by),
            "no_signal_reason": None,
        }
    ]


def test_evidence_pack_builds_segment_inputs_with_allowed_source_ids() -> None:
    sources = [
        RawSource(
            id="cursor-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            snippet="Cursor Pro costs $20 per month.",
            content_hash="cursor-pricing-hash",
            confidence=0.96,
        ),
        RawSource(
            id="cursor-persona",
            competitor="Cursor",
            dimension="persona",
            source_type="interview_record",
            title="Cursor persona",
            snippet="Enterprise buyers evaluate Cursor for security review.",
            content_hash="cursor-persona-hash",
            confidence=0.82,
        ),
    ]

    result = build_writer_evidence_pack(_detail_with_sources(sources))
    segments = result.segment_inputs()

    by_name = {segment["segment_name"]: segment for segment in segments}
    assert "decision_summary" in by_name
    assert "user_research" in by_name
    assert "cursor-pricing" in by_name["decision_summary"]["allowed_source_ids"]
    assert "cursor-persona" in by_name["user_research"]["allowed_source_ids"]


def test_segment_inputs_keep_non_core_dimensions_in_broad_segments() -> None:
    source = RawSource(
        id="cursor-security",
        competitor="Cursor",
        dimension="security",
        source_type="webpage_verified",
        title="Cursor security",
        snippet="Cursor enterprise buyers require SSO and security review.",
        content_hash="cursor-security-hash",
        confidence=0.91,
    )
    detail = _detail_with_sources([source])
    detail.plan.dimensions = ["security"]

    result = build_writer_evidence_pack(detail)
    by_name = {segment["segment_name"]: segment for segment in result.segment_inputs()}

    assert "cursor-security" in by_name["decision_summary"]["allowed_source_ids"]
    assert "cursor-security" in by_name["support_appendix"]["allowed_source_ids"]


def test_segment_inputs_treat_customer_dimensions_as_user_research() -> None:
    source = RawSource(
        id="cursor-customer-feedback",
        competitor="Cursor",
        dimension="customer_feedback",
        source_type="interview_record",
        title="Cursor customer feedback",
        snippet="Customers report onboarding friction and procurement review needs.",
        content_hash="cursor-customer-feedback-hash",
        confidence=0.87,
    )
    detail = _detail_with_sources([source])
    detail.plan.dimensions = ["customer_feedback"]

    result = build_writer_evidence_pack(detail)
    user_research = {
        segment["segment_name"]: segment for segment in result.segment_inputs()
    }["user_research"]

    assert "cursor-customer-feedback" in user_research["allowed_source_ids"]
    assert user_research["groups"][0]["dimension"] == "customer_feedback"


def test_support_appendix_segment_includes_coverage_counts() -> None:
    source = RawSource(
        id="cursor-persona",
        competitor="Cursor",
        dimension="persona",
        source_type="interview_record",
        title="Cursor persona",
        snippet="Enterprise buyers evaluate Cursor for security review.",
        content_hash="cursor-persona-hash",
        confidence=0.82,
    )
    detail = _detail_with_sources([source])
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["persona"]
    detail.competitor_kbs = {
        "Cursor": CompetitorKB(
            competitor="Cursor",
            sources=["cursor-persona"],
            slices={"persona": ["Enterprise buyers evaluate rollout."]},
        )
    }

    result = build_writer_evidence_pack(detail)
    support_appendix = {
        segment["segment_name"]: segment for segment in result.segment_inputs()
    }["support_appendix"]

    assert support_appendix["coverage"] == result.pack.coverage
    assert support_appendix["coverage"]["raw_source_count"] == 1
    assert support_appendix["coverage"]["represented_source_count"] == 1
    assert support_appendix["coverage"]["kb_slice_count"] == 1
    assert support_appendix["coverage"]["represented_kb_slice_count"] == 1


def test_segment_inputs_include_relevant_pack_quotes() -> None:
    source = RawSource(
        id="cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor Pro costs $20 per month.",
        content_hash="cursor-pricing-hash",
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
    )

    result = build_writer_evidence_pack(_detail_with_sources([source]))
    decision_summary = {
        segment["segment_name"]: segment for segment in result.segment_inputs()
    }["decision_summary"]

    referenced_quote_ids = {
        quote_id
        for group in decision_summary["groups"]
        for fact in group["facts"]
        for quote_id in fact["quote_ids"]
    }
    segment_quote_ids = {quote["id"] for quote in decision_summary["quotes"]}
    assert referenced_quote_ids
    assert referenced_quote_ids <= segment_quote_ids


def test_segment_inputs_include_structured_knowledge() -> None:
    source = RawSource(
        id="cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor Pro costs $20 per month.",
        content_hash="cursor-pricing-hash",
        confidence=0.96,
    )
    detail = _detail_with_sources([source])
    detail.competitor_knowledge = {
        "Cursor": CompetitorKnowledge(
            competitor="Cursor",
            confidence=0.91,
            pricing_model=PricingModel(
                tiers=[PricingTier(name="Pro", price="$20/month")]
            ),
        )
    }

    result = build_writer_evidence_pack(detail)
    decision_summary = {
        segment["segment_name"]: segment for segment in result.segment_inputs()
    }["decision_summary"]

    assert decision_summary["structured_knowledge"]["Cursor"]["confidence"] == 0.91


def test_segment_inputs_partition_large_pack_without_dropping_sources() -> None:
    competitors = ["Cursor", "Copilot", "Codeium"]
    dimensions = ["pricing", "feature", "persona", "security"]
    sources: list[RawSource] = []
    kb_slices: dict[str, CompetitorKB] = {}
    for competitor in competitors:
        competitor_slug = competitor.lower()
        kb_sources: list[str] = []
        slices: dict[str, list[str]] = {}
        for dimension in dimensions:
            source_id = f"{competitor_slug}-{dimension}"
            kb_sources.append(source_id)
            quote = (
                f"{competitor} {dimension} evidence describes procurement, rollout, "
                "buyer risk, adoption tradeoffs, implementation depth, and operating "
                "constraints for competitive analysis. "
            ) * 10
            metadata = {
                "normalized_fields": [
                    {
                        "kind": dimension,
                        "dimension": dimension,
                        "competitor": competitor,
                        "claim": f"{competitor} {dimension} claim {index}",
                        "source_quote": f"{quote} claim {index}",
                    }
                    for index in range(3)
                ],
            }
            sources.append(
                RawSource(
                    id=source_id,
                    competitor=competitor,
                    dimension=dimension,
                    source_type=(
                        "interview_record"
                        if dimension == "persona"
                        else "webpage_verified"
                    ),
                    title=f"{competitor} {dimension}",
                    snippet=quote,
                    content_hash=f"{source_id}-hash",
                    confidence=0.84,
                    metadata=metadata,
                )
            )
            slices[dimension] = [
                (
                    f"{competitor} {dimension} KB slice {index} explains buyer "
                    "decision criteria, gaps, and validation needs."
                )
                for index in range(3)
            ]
        kb_slices[competitor] = CompetitorKB(
            competitor=competitor,
            sources=kb_sources,
            slices=slices,
        )
    detail = _detail_with_sources(sources)
    detail.plan.competitors = competitors
    detail.plan.dimensions = dimensions
    detail.competitor_kbs = kb_slices

    result = build_writer_evidence_pack(detail)
    segments = result.segment_inputs()
    source_sets = {frozenset(segment["allowed_source_ids"]) for segment in segments}
    registry_ids = {item.id for item in result.pack.source_registry}
    union_segment_ids = {
        source_id
        for segment in segments
        for source_id in segment["allowed_source_ids"]
    }
    user_research = next(
        segment for segment in segments if segment["segment_name"] == "user_research"
    )

    assert len(source_sets) > 1
    assert (
        max(segment["segment_input_chars"] for segment in segments)
        < result.metrics.writer_evidence_pack_chars * 0.75
    )
    assert union_segment_ids == registry_ids
    assert "cursor-persona" in user_research["allowed_source_ids"]
    assert "cursor-pricing" not in user_research["allowed_source_ids"]
    assert "cursor-feature" not in user_research["allowed_source_ids"]
    assert "cursor-security" not in user_research["allowed_source_ids"]


def test_user_research_segment_includes_user_sources_in_non_user_dimensions() -> None:
    sources = [
        RawSource(
            id="cursor-pricing-interview",
            competitor="Cursor",
            dimension="pricing",
            source_type="interview_record",
            title="Cursor pricing interview",
            snippet="A buyer interview reports pricing approval friction.",
            content_hash="cursor-pricing-interview-hash",
            confidence=0.84,
        ),
        RawSource(
            id="cursor-security-official",
            competitor="Cursor",
            dimension="security",
            source_type="webpage_verified",
            title="Cursor security",
            snippet="Cursor publishes enterprise security controls.",
            content_hash="cursor-security-official-hash",
            confidence=0.92,
        ),
    ]
    detail = _detail_with_sources(sources)
    detail.plan.dimensions = ["pricing", "security"]

    result = build_writer_evidence_pack(detail)
    user_research = {
        segment["segment_name"]: segment for segment in result.segment_inputs()
    }["user_research"]

    assert "cursor-pricing-interview" in user_research["allowed_source_ids"]
    assert "cursor-security-official" not in user_research["allowed_source_ids"]
    assert [group["dimension"] for group in user_research["groups"]] == ["pricing"]


def test_user_research_segments_stay_under_absolute_budget() -> None:
    quote_base = (
        "Customer feedback describes onboarding friction, pricing review, team "
        "adoption concerns, administrative controls, and renewal decision criteria. "
    )
    heavy_fact_value = (
        "Interview detail covers rollout blockers, procurement review, renewal "
        "criteria, enablement gaps, governance concerns, and team-level adoption "
        "patterns. "
        * 50
    )
    sources = [
        RawSource(
            id="cursor-customer-interview-heavy",
            competitor="Cursor",
            dimension="customer_feedback",
            source_type="interview_record",
            title="Cursor customer interview heavy",
            snippet="Customer interviews report adoption and procurement feedback.",
            content_hash="cursor-customer-interview-heavy-hash",
            confidence=0.86,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "customer_feedback",
                        "dimension": "customer_feedback",
                        "competitor": "Cursor",
                        "theme": f"feedback-theme-{field_index}",
                        "sentiment": "mixed",
                        "buyer_role": "engineering leader",
                        "detailed_takeaway": (
                            f"{heavy_fact_value} item={field_index}"
                        ),
                        **{
                            f"detailed_takeaway_{detail_index}": (
                                f"{heavy_fact_value} detail={detail_index} "
                                f"item={field_index}"
                            )
                            for detail_index in range(20)
                        },
                        "source_quote": f"{quote_base} field={field_index}. " * 12,
                    }
                    for field_index in range(64)
                ]
            },
        )
    ]
    detail = _detail_with_sources(sources)
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["customer_feedback"]

    result = build_writer_evidence_pack(detail)
    segments = result.segment_inputs()
    registry_ids = {item.id for item in result.pack.source_registry}
    union_segment_ids = {
        source_id
        for segment in segments
        for source_id in segment["allowed_source_ids"]
    }

    assert max(segment["segment_input_chars"] for segment in segments) <= (
        SEGMENT_INPUT_TARGET_CHARS
    )
    assert union_segment_ids == registry_ids
    assert any(segment["segment_name"] == "user_research" for segment in segments)


def test_competitor_deep_dive_segments_stay_under_absolute_budget() -> None:
    quote_base = (
        "Pricing evidence covers batch priority models, cached input, output, "
        "long context, enterprise controls, procurement review, and rollout risk. "
    )
    heavy_fact_value = (
        "Pricing table detail covers model rows, context windows, batch priority, "
        "cached input, output, enterprise availability, procurement controls, and "
        "rollout assumptions. "
        * 50
    )
    sources = [
        RawSource(
            id="openai-pricing-heavy",
            competitor="OpenAI Codex",
            dimension="pricing",
            source_type="webpage_verified",
            title="OpenAI pricing heavy",
            snippet="OpenAI pricing source includes detailed model rows.",
            content_hash="openai-pricing-heavy-hash",
            confidence=0.94,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "dimension": "pricing",
                        "competitor": "OpenAI Codex",
                        "model_type": "api_usage_based",
                        "tier_name": f"gpt-heavy-{field_index}",
                        "price": f"${field_index}.00",
                        "billing_cycle": "per 1m",
                        "usage_limit": "long context",
                        "enterprise_condition": "enterprise_available",
                        "detailed_pricing_note": (
                            f"{heavy_fact_value} item={field_index}"
                        ),
                        **{
                            f"detailed_pricing_note_{detail_index}": (
                                f"{heavy_fact_value} detail={detail_index} "
                                f"item={field_index}"
                            )
                            for detail_index in range(20)
                        },
                        "source_quote": f"{quote_base} field={field_index}. " * 12,
                    }
                    for field_index in range(64)
                ]
            },
        )
    ]
    detail = _detail_with_sources(sources)
    detail.plan.competitors = ["OpenAI Codex"]
    detail.plan.dimensions = ["pricing"]
    detail.competitor_kbs = {
        "OpenAI Codex": CompetitorKB(
            competitor="OpenAI Codex",
            sources=[source.id for source in sources],
            slices={
                "pricing": [
                    (
                        f"OpenAI pricing KB slice {index} explains pricing model rows, "
                        "enterprise constraints, context limits, and buyer validation needs."
                    )
                    for index in range(40)
                ]
            },
        )
    }

    result = build_writer_evidence_pack(detail)
    segments = result.segment_inputs()
    registry_ids = {item.id for item in result.pack.source_registry}
    union_segment_ids = {
        source_id
        for segment in segments
        for source_id in segment["allowed_source_ids"]
    }

    assert max(segment["segment_input_chars"] for segment in segments) <= (
        SEGMENT_INPUT_TARGET_CHARS
    )
    assert union_segment_ids == registry_ids
    assert any(
        segment["segment_name"] == "competitor_deep_dives"
        and segment.get("segment_competitor") == "OpenAI Codex"
        for segment in segments
    )


def test_repair_segment_inputs_partition_large_competitor_section_by_child_segment() -> None:
    quote_base = (
        "Pricing evidence covers batch priority models, cached input, output, "
        "long context, enterprise controls, procurement review, and rollout risk. "
    )
    heavy_fact_value = (
        "Pricing table detail covers model rows, context windows, batch priority, "
        "cached input, output, enterprise availability, procurement controls, and "
        "rollout assumptions. "
        * 50
    )
    sources = [
        RawSource(
            id="openai-pricing-repair-heavy",
            competitor="OpenAI Codex",
            dimension="pricing",
            source_type="webpage_verified",
            title="OpenAI pricing repair heavy",
            snippet="OpenAI pricing source includes detailed model rows.",
            content_hash="openai-pricing-repair-heavy-hash",
            confidence=0.94,
            metadata={
                "normalized_fields": [
                    {
                        "kind": "pricing",
                        "dimension": "pricing",
                        "competitor": "OpenAI Codex",
                        "model_type": "api_usage_based",
                        "tier_name": f"gpt-repair-heavy-{field_index}",
                        "price": f"${field_index}.00",
                        "billing_cycle": "per 1m",
                        "usage_limit": "long context",
                        "enterprise_condition": "enterprise_available",
                        "detailed_pricing_note": (
                            f"{heavy_fact_value} item={field_index}"
                        ),
                        **{
                            f"detailed_pricing_note_{detail_index}": (
                                f"{heavy_fact_value} detail={detail_index} "
                                f"item={field_index}"
                            )
                            for detail_index in range(20)
                        },
                        "source_quote": f"{quote_base} field={field_index}. " * 12,
                    }
                    for field_index in range(64)
                ]
            },
        )
    ]
    detail = _detail_with_sources(sources)
    detail.plan.competitors = ["OpenAI Codex"]
    detail.plan.dimensions = ["pricing"]
    detail.competitor_kbs = {
        "OpenAI Codex": CompetitorKB(
            competitor="OpenAI Codex",
            sources=[source.id for source in sources],
            slices={
                "pricing": [
                    (
                        f"OpenAI repair KB slice {index} explains pricing rows, "
                        "enterprise constraints, context limits, and validation needs."
                    )
                    for index in range(40)
                ]
            },
        )
    }

    result = build_writer_evidence_pack(detail)
    selected_segments = [
        segment
        for segment in result.segment_inputs()
        if segment["segment_name"] == "competitor_deep_dives"
    ]
    selected_source_ids = {
        source_id
        for segment in selected_segments
        for source_id in segment["allowed_source_ids"]
    }

    repair_payloads = result.repair_segment_inputs(["competitor_deep_dives"])
    repair_source_ids = {
        source_id
        for payload in repair_payloads
        for source_id in payload["allowed_source_ids"]
    }

    assert len(selected_segments) > 1
    assert len(repair_payloads) == len(selected_segments)
    assert repair_source_ids == selected_source_ids
    assert [payload["repair_part"] for payload in repair_payloads] == list(
        range(1, len(repair_payloads) + 1)
    )
    for payload in repair_payloads:
        assert payload["repair_part_count"] == len(repair_payloads)
        assert payload["segment_input_target_chars"] == SEGMENT_INPUT_TARGET_CHARS
        assert payload["segment_count"] == 1
        if payload["repair_input_chars"] > SEGMENT_INPUT_TARGET_CHARS:
            assert payload["segments"][0].get("segment_over_budget_reason") in {
                "single_fact_exceeds_budget",
                "single_source_exceeds_budget",
            }
        else:
            assert payload["repair_input_chars"] <= SEGMENT_INPUT_TARGET_CHARS


def test_repair_segment_inputs_mark_wrapper_budget_overflow(monkeypatch) -> None:
    result = WriterEvidencePackResult(
        pack=WriterEvidencePack(
            source_registry=[
                WriterSourceRegistryItem(
                    id="cursor-near-budget",
                    competitor="Cursor",
                    dimension="pricing",
                    source_type="webpage_verified",
                    title="Cursor near-budget source",
                    confidence=0.95,
                    represented_by=["fact:cursor-near-budget"],
                )
            ]
        ),
        metrics=WriterEvidencePackMetrics(),
    )

    def make_segment(filler_chars: int) -> dict[str, object]:
        segment: dict[str, object] = {
            "schema_version": "writer_evidence_pack.v1",
            "segment_name": "competitor_deep_dives",
            "segment_competitor": "Cursor",
            "segment_dimension": "pricing",
            "segment_batch": "facts:1",
            "source_registry": [{"id": "cursor-near-budget"}],
            "groups": [],
            "quotes": [],
            "matrix": {},
            "structured_knowledge": {},
            "allowed_source_ids": ["cursor-near-budget"],
            "near_budget_padding": "x" * filler_chars,
        }
        for _ in range(3):
            segment["segment_input_chars"] = len(
                json.dumps(segment, ensure_ascii=False)
            )
        return segment

    selected_segment = None
    selected_payload = None
    for filler_chars in range(SEGMENT_INPUT_TARGET_CHARS, 0, -25):
        candidate = make_segment(filler_chars)
        monkeypatch.setattr(
            WriterEvidencePackResult,
            "segment_inputs",
            lambda self, candidate=candidate: [candidate],
        )
        payload = result.repair_segment_inputs(["competitor_deep_dives"])[0]
        if (
            candidate["segment_input_chars"] <= SEGMENT_INPUT_TARGET_CHARS
            and payload["repair_input_chars"] > SEGMENT_INPUT_TARGET_CHARS
        ):
            selected_segment = candidate
            selected_payload = payload
            break

    assert selected_segment is not None
    assert selected_payload is not None
    assert selected_payload["repair_input_chars"] <= SEGMENT_INPUT_TARGET_CHARS or (
        selected_payload.get("repair_over_budget_reason")
        == "single_repair_segment_exceeds_budget"
        or selected_payload["segments"][0].get("segment_over_budget_reason")
        in {"single_fact_exceeds_budget", "single_source_exceeds_budget"}
    )


def test_source_batched_segments_trim_deduped_fact_source_ids() -> None:
    heavy_fact_value = (
        "Pricing evidence includes model rows, procurement notes, rollout "
        "constraints, billing assumptions, context windows, and enterprise "
        "conditions. "
        * 50
    )
    sources = []
    for source_index in range(12):
        normalized_fields = [
            {
                "kind": "pricing",
                "dimension": "pricing",
                "competitor": "OpenAI Codex",
                "model_type": "api_usage_based",
                "tier_name": "Shared enterprise",
                "price": "$99.00",
                "billing_cycle": "per month",
                "usage_limit": "shared context",
                "enterprise_condition": "enterprise_available",
                "source_quote": (
                    "Shared enterprise pricing is available for rollout planning."
                ),
            }
        ]
        normalized_fields.extend(
            {
                "kind": "pricing",
                "dimension": "pricing",
                "competitor": "OpenAI Codex",
                "model_type": "api_usage_based",
                "tier_name": f"Unique {source_index}-{field_index}",
                "price": f"${source_index}{field_index}.00",
                "billing_cycle": "per 1m",
                "usage_limit": "long context",
                "enterprise_condition": "enterprise_available",
                "detailed_pricing_note": (
                    f"{heavy_fact_value} source={source_index} field={field_index}"
                ),
                **{
                    f"detailed_pricing_note_{detail_index}": (
                        f"{heavy_fact_value} detail={detail_index} "
                        f"source={source_index} field={field_index}"
                    )
                    for detail_index in range(20)
                },
                "source_quote": (
                    f"Unique pricing source={source_index} field={field_index}. " * 12
                ),
            }
            for field_index in range(2)
        )
        sources.append(
            RawSource(
                id=f"openai-pricing-dedupe-{source_index}",
                competitor="OpenAI Codex",
                dimension="pricing",
                source_type="webpage_verified",
                title=f"OpenAI pricing dedupe {source_index}",
                snippet="OpenAI pricing includes shared and unique model rows.",
                content_hash=f"openai-pricing-dedupe-{source_index}-hash",
                confidence=0.93,
                metadata={"normalized_fields": normalized_fields},
            )
        )
    detail = _detail_with_sources(sources)
    detail.plan.competitors = ["OpenAI Codex"]
    detail.plan.dimensions = ["pricing"]

    result = build_writer_evidence_pack(detail)
    segments = result.segment_inputs()
    source_batched_segments = [
        segment
        for segment in segments
        if segment["segment_name"] == "competitor_deep_dives"
        and str(segment.get("segment_batch") or "").startswith("sources:")
    ]
    registry_ids = {item.id for item in result.pack.source_registry}
    union_segment_ids = {
        source_id
        for segment in segments
        for source_id in segment["allowed_source_ids"]
    }

    assert source_batched_segments
    assert union_segment_ids == registry_ids
    for segment in source_batched_segments:
        allowed = set(segment["allowed_source_ids"])
        assert len(allowed) <= SEGMENT_SOURCE_BATCH_SIZE
        assert segment["segment_input_chars"] <= SEGMENT_INPUT_TARGET_CHARS
        for group in segment["groups"]:
            for fact in group["facts"]:
                assert set(fact["source_ids"]) <= allowed


def test_segment_inputs_enforce_budget_for_broad_registry_segments() -> None:
    sources = [
        RawSource(
            id=f"cursor-security-registry-{source_index}",
            competitor="Cursor",
            dimension="security",
            source_type="webpage_verified",
            title=f"Cursor security registry source {source_index}",
            snippet=(
                "Cursor security evidence covers SSO, audit logs, deployment "
                f"controls, and procurement review item {source_index}."
            ),
            content_hash=f"cursor-security-registry-{source_index}-hash",
            confidence=0.9,
        )
        for source_index in range(900)
    ]
    detail = _detail_with_sources(sources)
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["security"]

    result = build_writer_evidence_pack(detail)
    segments = result.segment_inputs()
    registry_ids = {item.id for item in result.pack.source_registry}
    union_segment_ids = {
        source_id
        for segment in segments
        for source_id in segment["allowed_source_ids"]
    }
    over_budget = [
        {
            "segment_name": segment["segment_name"],
            "segment_batch": segment.get("segment_batch"),
            "segment_input_chars": segment["segment_input_chars"],
        }
        for segment in segments
        if segment["segment_input_chars"] > SEGMENT_INPUT_TARGET_CHARS
        and segment.get("segment_over_budget_reason") != "single_fact_exceeds_budget"
    ]

    assert over_budget == []
    assert union_segment_ids == registry_ids


def test_segment_inputs_mark_single_source_broad_segment_over_budget() -> None:
    source = RawSource(
        id="cursor-heavy-matrix-source",
        competitor="Cursor",
        dimension="security",
        source_type="webpage_verified",
        title="Cursor heavy matrix source",
        snippet="Cursor security evidence covers SSO, audit logs, and procurement review.",
        content_hash="cursor-heavy-matrix-source-hash",
        confidence=0.9,
    )
    detail = _detail_with_sources([source])
    detail.plan.competitors = ["Cursor"]
    detail.plan.dimensions = ["security"]
    detail.comparison_matrix = ComparisonMatrix(
        competitors=["Cursor"],
        dimensions=["security"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="security",
                value=(
                    "Cursor security cell includes SSO, audit logging, deployment "
                    f"controls, procurement review, and governance item {cell_index}. "
                    * 12
                ),
                source_ids=["cursor-heavy-matrix-source"],
                confidence=0.9,
            )
            for cell_index in range(900)
        ],
    )

    result = build_writer_evidence_pack(detail)
    over_budget = [
        segment
        for segment in result.segment_inputs()
        if segment["segment_input_chars"] > SEGMENT_INPUT_TARGET_CHARS
    ]

    assert over_budget
    assert {
        segment.get("segment_over_budget_reason") for segment in over_budget
    } == {"single_source_exceeds_budget"}
    assert all(len(segment["allowed_source_ids"]) == 1 for segment in over_budget)


def test_segment_matrix_filters_source_ids_outside_allowed_segment_sources() -> None:
    sources = [
        RawSource(
            id="cursor-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            snippet="Cursor Pro costs $20 per month.",
            content_hash="cursor-pricing-hash",
            confidence=0.96,
        ),
        RawSource(
            id="cursor-persona",
            competitor="Cursor",
            dimension="persona",
            source_type="interview_record",
            title="Cursor persona",
            snippet="Enterprise buyers evaluate Cursor for security review.",
            content_hash="cursor-persona-hash",
            confidence=0.82,
        ),
    ]
    detail = _detail_with_sources(sources)
    detail.comparison_matrix = ComparisonMatrix(
        competitors=["Cursor"],
        dimensions=["pricing", "persona"],
        cells=[
            ComparisonCell(
                competitor="Cursor",
                dimension="pricing",
                value="Cursor has visible pricing.",
                source_ids=["cursor-pricing"],
                confidence=0.96,
            ),
            ComparisonCell(
                competitor="Cursor",
                dimension="persona",
                value="Enterprise buyers evaluate rollout.",
                source_ids=["cursor-pricing", "cursor-persona"],
                confidence=0.84,
            ),
        ],
        winner_by_dimension={"pricing": "Cursor", "persona": "Cursor"},
        summary=["Cursor has evidence across dimensions."],
    )

    result = build_writer_evidence_pack(detail)
    user_research = {
        segment["segment_name"]: segment for segment in result.segment_inputs()
    }["user_research"]

    matrix_cells = user_research["matrix"]["cells"]
    assert len(matrix_cells) == 1
    assert matrix_cells[0]["dimension"] == "persona"
    assert matrix_cells[0]["source_ids"] == ["cursor-persona"]


def test_segment_citation_validation_rejects_unsupplied_source_id() -> None:
    source = RawSource(
        id="cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor Pro costs $20 per month.",
        content_hash="cursor-pricing-hash",
        confidence=0.96,
    )
    result = build_writer_evidence_pack(_detail_with_sources([source]))

    errors = result.validate_segment_citations(
        "Cursor is priced clearly. [source:missing-source]",
        allowed_source_ids={"cursor-pricing"},
    )

    assert errors == ["missing-source"]


def test_segment_citation_validation_rejects_malformed_source_token() -> None:
    source = RawSource(
        id="cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor Pro costs $20 per month.",
        content_hash="cursor-pricing-hash",
        confidence=0.96,
    )
    result = build_writer_evidence_pack(_detail_with_sources([source]))

    errors = result.validate_segment_citations(
        "Cursor has unsupported aggregate evidence. [source:all persona cells]",
        allowed_source_ids={"cursor-pricing"},
    )

    assert errors == ["all persona cells"]


def test_segment_citation_validation_rejects_full_width_source_outside_allowlist() -> None:
    source = RawSource(
        id="cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Cursor Pro costs $20 per month.",
        content_hash="cursor-pricing-hash",
        confidence=0.96,
    )
    result = build_writer_evidence_pack(_detail_with_sources([source]))

    errors = result.validate_segment_citations(
        "Cursor is priced clearly. 【source:cursor-pricing】",
        allowed_source_ids=set(),
    )

    assert errors == ["cursor-pricing"]
