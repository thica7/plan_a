from __future__ import annotations

import os
from pathlib import Path

from packages.schema.enterprise import ToolRegistryEntry, ToolRegistryReport


def build_tool_registry_report(settings: object) -> ToolRegistryReport:
    has_search = bool(getattr(settings, "has_web_search_credentials", False))
    redaction_enabled = bool(getattr(settings, "compliance_redaction_enabled", True))
    trace_required = bool(getattr(settings, "compliance_require_trace_context", True))
    advanced_fetch_root = Path(
        os.getenv("WEBFETCH_V2_ROOT", r"D:\codex_workspace\webfetch_v2")
    )
    advanced_fetch_configured = advanced_fetch_root.exists()
    entries = [
        ToolRegistryEntry(
            name="web_search",
            category="collection",
            description="External web search used by collector and online gap fill.",
            input_schema="WebSearchRequest",
            output_schema="list[SearchResult]",
            estimated_cost_usd=0.01,
            side_effects=["network_read"],
            policy_tags=["tenant_scoped", "cost_metered", "requires_trace"],
            status="enabled" if has_search and trace_required else "guarded",
            allowed_in_real_mode=has_search and trace_required,
            reason=(
                "Search credentials and trace context are configured."
                if has_search and trace_required
                else "Requires search credentials and trace context before real runs."
            ),
        ),
        ToolRegistryEntry(
            name="fetch_page",
            category="collection",
            description="Fetches source pages after robots compliance checks.",
            input_schema="url",
            output_schema="FetchPageResult",
            estimated_cost_usd=0.0,
            side_effects=["network_read"],
            policy_tags=["requires_robots", "requires_trace"],
            status="enabled" if trace_required else "guarded",
            allowed_in_real_mode=trace_required,
            reason="Fetch is allowed when trace context records source lineage.",
        ),
        ToolRegistryEntry(
            name="advanced_fetch_page",
            category="collection",
            description=(
                "Optional external webfetch_v2 boundary for JavaScript-heavy pages, "
                "quality diagnostics, markdown extraction, and screenshots."
            ),
            input_schema="AdvancedFetchRequest",
            output_schema="AdvancedFetchResult",
            estimated_cost_usd=0.0,
            side_effects=["network_read", "file_write"],
            policy_tags=[
                "requires_robots",
                "requires_trace",
                "human_review_recommended",
            ],
            status="enabled" if advanced_fetch_configured and trace_required else "guarded",
            allowed_in_real_mode=advanced_fetch_configured and trace_required,
            reason=(
                f"webfetch_v2 root is configured at {advanced_fetch_root}."
                if advanced_fetch_configured and trace_required
                else "Requires WEBFETCH_V2_ROOT and trace context before real browser fetches."
            ),
        ),
        ToolRegistryEntry(
            name="rag_search_evidence",
            category="retrieval",
            description="Searches project evidence embeddings for gap fill and QA.",
            input_schema="EvidenceSearchQuery",
            output_schema="list[EvidenceSearchHit]",
            estimated_cost_usd=0.0,
            side_effects=["none"],
            policy_tags=["tenant_scoped"],
            status="enabled",
            reason="Read-only tenant-scoped retrieval.",
        ),
        ToolRegistryEntry(
            name="online_gap_fill",
            category="retrieval",
            description=(
                "Searches and fetches missing evidence for open EvidenceGap records, then "
                "stores accepted evidence back into the tenant-scoped Evidence Center."
            ),
            input_schema="EvidenceGapReport",
            output_schema="EvidenceGapFillResult",
            estimated_cost_usd=0.02,
            side_effects=["network_read", "database_write"],
            policy_tags=[
                "requires_robots",
                "requires_redaction",
                "requires_trace",
                "tenant_scoped",
                "cost_metered",
            ],
            status=(
                "enabled"
                if has_search and redaction_enabled and trace_required
                else "guarded"
            ),
            allowed_in_real_mode=has_search and redaction_enabled and trace_required,
            reason=(
                "Search credentials, redaction, robots checks, and trace context are configured."
                if has_search and redaction_enabled and trace_required
                else (
                    "Requires search credentials, redaction, robots checks, and trace "
                    "context before online evidence gap fill can run in real mode."
                )
            ),
        ),
        ToolRegistryEntry(
            name="memory_recall",
            category="retrieval",
            description="Retrieves confirmed MemoryAgent guidance for planner and QA context.",
            input_schema="MemoryRecallQuery",
            output_schema="MemoryRecallResult",
            estimated_cost_usd=0.0,
            side_effects=["none"],
            policy_tags=["tenant_scoped", "requires_trace"],
            status="enabled" if trace_required else "guarded",
            allowed_in_real_mode=trace_required,
            reason="Memory recall is read-only but must remain traceable to user feedback.",
        ),
        ToolRegistryEntry(
            name="claim_validator",
            category="analysis",
            description=(
                "Validates report claims against evidence, source quality, and triangulation."
            ),
            input_schema="ClaimValidationRequest",
            output_schema="ClaimValidationReport",
            estimated_cost_usd=0.0,
            side_effects=["none"],
            policy_tags=["requires_trace", "tenant_scoped"],
            status="enabled" if trace_required else "guarded",
            allowed_in_real_mode=trace_required,
            reason="Claim validation is deterministic and must emit audit-grade trace events.",
        ),
        ToolRegistryEntry(
            name="self_consistency_sampler",
            category="analysis",
            description="Samples claim validation checks and records minority validation failures.",
            input_schema="ClaimValidationResult",
            output_schema="list[ClaimValidationSample]",
            estimated_cost_usd=0.0,
            side_effects=["none"],
            policy_tags=["requires_trace", "tenant_scoped"],
            status="enabled" if trace_required else "guarded",
            allowed_in_real_mode=trace_required,
            reason="Self-consistency sampling is part of the report quality gate trace.",
        ),
        ToolRegistryEntry(
            name="source_snapshot",
            category="storage",
            description="Stores webpage, PDF, screenshot, survey, or transcript snapshots.",
            input_schema="SourceSnapshotCreateRequest",
            output_schema="SourceSnapshotResult",
            estimated_cost_usd=0.0,
            side_effects=["file_write", "database_write"],
            policy_tags=["requires_redaction", "requires_trace", "tenant_scoped"],
            status="enabled" if redaction_enabled and trace_required else "guarded",
            allowed_in_real_mode=redaction_enabled and trace_required,
            reason="Snapshots require redaction and traceable source lineage.",
        ),
        ToolRegistryEntry(
            name="model_backed_agent",
            category="analysis",
            description="Pydantic-AI model-backed RedTeam/EvidenceGap style execution.",
            input_schema="AgentExecutionRequest",
            output_schema="AgentExecutionResult",
            estimated_cost_usd=0.03,
            side_effects=["network_read"],
            policy_tags=["requires_redaction", "requires_trace", "cost_metered"],
            status="enabled" if redaction_enabled and trace_required else "guarded",
            allowed_in_real_mode=redaction_enabled and trace_required,
            reason="Model-backed tools are governed by redaction, trace, and cost policy.",
        ),
        ToolRegistryEntry(
            name="report_publish",
            category="workflow",
            description="Publishes report versions after release gate and compliance checks.",
            input_schema="ReportVersionRecord",
            output_schema="ReportReleaseGate",
            estimated_cost_usd=0.0,
            side_effects=["database_write"],
            policy_tags=["requires_trace", "human_review_recommended"],
            status="enabled" if trace_required else "guarded",
            allowed_in_real_mode=trace_required,
            reason="Publishing is allowed after release gate and audit trace checks.",
        ),
    ]
    return ToolRegistryReport(
        entries=entries,
        total_count=len(entries),
        guarded_count=sum(1 for item in entries if item.status == "guarded"),
        disabled_count=sum(1 for item in entries if item.status == "disabled"),
        side_effect_tool_count=sum(
            1 for item in entries if any(effect != "none" for effect in item.side_effects)
        ),
    )
