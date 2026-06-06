from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

from packages.business_intel.scenarios import get_scenario_pack
from packages.rag.grounded_prompt import build_run_grounding_prompt
from packages.research.evidence.text import source_business_snippet
from packages.schema.api_dto import RunDetail
from packages.schema.models import FeatureNode, KnowledgeClaim, QCIssue, RawSource

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


USER_RESEARCH_SOURCE_TYPE_ORDER = (
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
)
USER_RESEARCH_SOURCE_TYPES = set(USER_RESEARCH_SOURCE_TYPE_ORDER)


def writer_user_research_policy_text() -> str:
    source_types = ", ".join(USER_RESEARCH_SOURCE_TYPE_ORDER)
    return (
        f"Treat {source_types} as user-research signals, not as official factual proof."
    )


class WriterAgentMixin:
    async def _real_writer_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "writer"
        self._consume_queued_agent_messages(
            record,
            to_agent="writer",
            consumer_agent="writer",
            message_types={"reflection_ready"},
        )
        await self.emit(detail.id, "node_started", "writer", None, "Calling report writer.")
        previous_report = detail.report_md
        writer_mode = "real LLM call"
        writer_error: str | None = None
        writer_context_json = json.dumps(
            self._writer_context_package(detail),
            ensure_ascii=False,
        )
        layer_context = self._writer_layer_context(detail)
        memory_context = "\n".join(detail.plan.memory_prompt_context) or "none"
        required_sections = self._writer_required_sections(detail)
        grounding_prompt = self._writer_grounding_prompt(detail)
        user_research_policy = writer_user_research_policy_text()
        try:
            timeout_seconds = max(0.05, float(self._settings.writer_timeout_seconds))
            report_md = await asyncio.wait_for(
                self._trace_llm_text(
                    record,
                    agent="writer",
                    subagent=None,
                    name="report_writer",
                    system=(
                        "You are a senior enterprise competitive-intelligence analyst. "
                        "Produce a concise decision-grade markdown first draft, not a short "
                        "summary. Write with consulting depth: executive recommendation, "
                        "source quality, "
                        "side-by-side matrices, dimension analysis, risks, buying implications, "
                        "and explicit next validation tasks. Cite factual claims with existing "
                        "source IDs using [source:ID]. Do not invent source IDs. "
                        "Do not use web_search_result or confidence < 0.75 as the sole support "
                        "for a winner, legal/security certification, pricing, or procurement "
                        "recommendation. If evidence is incomplete, say the conclusion is "
                        "tentative and list the exact evidence gap. Do not claim all sources are "
                        "verified when any source_type is web_search_result or "
                        "llm_public_knowledge. "
                        "Follow the Grounded Evidence Contract exactly. "
                        f"{user_research_policy} "
                        "Honor confirmed memory guidance when it does not conflict with evidence, "
                        "schema requirements, or compliance policy. "
                        "Use the requested competitive layer to choose the report shape: L1 is a "
                        "direct battlecard, L2 is adjacent workflow and enterprise-risk analysis, "
                        "and L3 is market landscape and category strategy."
                    ),
                    user=(
                        f"Topic: {detail.topic}\n"
                        f"Competitors: {', '.join(detail.plan.competitors)}\n"
                        f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                        f"Competitive Layer: {detail.plan.competitor_layer}\n"
                        f"Scenario ID: {detail.plan.scenario_id or 'auto'}\n"
                        "Scenario Recommended Dimensions: "
                        f"{', '.join(detail.plan.scenario_recommended_dimensions)}\n"
                        f"QA Rule IDs: {', '.join(detail.plan.qa_rule_ids)}\n"
                        f"Confirmed Memory Preferences:\n{memory_context}\n"
                        f"Layer Report Context: {layer_context}\n"
                        f"{grounding_prompt}\n"
                        f"Writer Context JSON: {writer_context_json}\n\n"
                        f"Required sections:\n{required_sections}\n"
                        "Keep the first draft under 4,500 characters with compact bullets and "
                        "tables; prioritize cited conclusions over narrative polish."
                    ),
                ),
                timeout=timeout_seconds,
            )
            detail.report_md = self._harden_report_markdown(detail, report_md)
        except TimeoutError as exc:
            timeout_reason = str(exc) or f"writer LLM exceeded {timeout_seconds:g}s"
            writer_error = timeout_reason
            if previous_report.strip():
                detail.report_md = previous_report
                writer_mode = "preserved previous report after writer error"
            else:
                detail.report_md = self._harden_report_markdown(
                    detail,
                    self._fallback_report_markdown(detail, writer_error),
                )
                writer_mode = "deterministic fallback after writer error"
        except Exception as exc:  # noqa: BLE001 - writer fallback keeps long runs demo-safe.
            writer_error = str(exc)
            if previous_report.strip():
                detail.report_md = previous_report
                writer_mode = "preserved previous report after writer error"
            else:
                detail.report_md = self._harden_report_markdown(
                    detail,
                    self._fallback_report_markdown(detail, writer_error),
                )
                writer_mode = "deterministic fallback after writer error"
        self._append_agent_message(
            record,
            from_agent="writer",
            to_agent="qa",
            message_type="report_ready",
            payload_schema="MarkdownReport",
            payload={
                "report_md": detail.report_md,
                "writer_mode": writer_mode,
                "error": writer_error,
            },
        )
        detail.updated_at = datetime.utcnow()
        projection = self._sync_enterprise_projection(record)
        await self.emit(
            detail.id,
            "report_updated",
            "writer",
            None,
            f"Report markdown updated from {writer_mode}.",
            {
                "report_md": detail.report_md,
                "writer_mode": writer_mode,
                "error": writer_error,
                **self._enterprise_projection_payload(projection),
            },
        )
        await self.emit(detail.id, "node_completed", "writer", None, "Writer completed.")

    def _fallback_report_markdown(self, detail: RunDetail, reason: str) -> str:
        layer_label = self._writer_layer_label(detail)
        lines = [
            f"# {detail.topic} {layer_label}",
            "",
            "## Executive Overview",
        ]
        matrix_sources = self._matrix_source_ids(detail)
        lines.append(
            "This evidence-indexed report summarizes the latest structured knowledge "
            "and comparison matrix while preserving explicit uncertainty."
            + self._format_source_refs(matrix_sources)
        )
        if detail.comparison_matrix is not None:
            lines.extend(["", "## Dimension Winners"])
            for dimension, winner in detail.comparison_matrix.winner_by_dimension.items():
                source_ids = [
                    source_id
                    for cell in detail.comparison_matrix.cells
                    if cell.dimension == dimension
                    for source_id in cell.source_ids
                ]
                lines.append(f"- {dimension}: {winner}{self._format_source_refs(source_ids)}")
            lines.extend(["", "## Comparison Matrix"])
            for cell in detail.comparison_matrix.cells:
                lines.append(
                    f"- {cell.competitor} / {cell.dimension}: {cell.value}"
                    f"{self._format_source_refs(cell.source_ids)}"
                )
        lines.extend(self._fallback_layer_sections(detail, matrix_sources, fallback=False))
        lines.extend(self._fallback_source_quality_section(detail))
        lines.extend(self._fallback_scenario_checklist_section(detail))
        lines.extend(["", "## Knowledge Coverage"])
        for competitor in detail.plan.competitors:
            knowledge = detail.competitor_knowledge.get(competitor)
            source_ids = knowledge.source_ids if knowledge is not None else []
            confidence = f"{knowledge.confidence:.2f}" if knowledge is not None else "unknown"
            lines.append(
                f"- {competitor}: confidence {confidence}{self._format_source_refs(source_ids)}"
            )
        if detail.reflections:
            latest = detail.reflections[-1]
            lines.extend(["", "## Confidence Notes"])
            notes = [
                *latest.coverage_gaps[:3],
                *latest.confidence_outliers[:2],
                *latest.cross_competitor_gaps[:2],
            ]
            for note in notes:
                lines.append(f"- {note}{self._format_source_refs(matrix_sources)}")
        lines.extend(self._fallback_claim_validation_section(detail))
        lines.extend(self._fallback_next_collection_plan(detail))
        lines.extend(self._fallback_evidence_appendix(detail))
        lines.extend(
            [
                "",
                "## Generation Notes",
                (
                    "- The deterministic writer generated this report from structured "
                    "evidence because the narrative writer could not complete."
                ),
                f"- Internal reason: {reason}",
            ]
        )
        return "\n".join(lines)

    def _fallback_layer_sections(
        self,
        detail: RunDetail,
        source_ids: list[str],
        *,
        fallback: bool = True,
    ) -> list[str]:
        refs = self._format_source_refs(source_ids)
        layer = detail.plan.competitor_layer
        if layer == "L1":
            return [
                "",
                f"## {self._layer_section_heading(detail, fallback=fallback)}",
                (
                    "- Direct-use position: treat this as a near-term replacement decision "
                    f"until stronger evidence changes the matrix.{refs}"
                ),
                (
                    "- Objection handling: prioritize pricing, packaging, feature parity, "
                    f"and switching triggers in sales or product response.{refs}"
                ),
                (
                    "- Action bias: use the highest-confidence dimension winners as the "
                    f"initial battlecard spine, then verify weak cells before publication.{refs}"
                ),
            ]
        if layer == "L2":
            return [
                "",
                f"## {self._layer_section_heading(detail, fallback=fallback)}",
                (
                    "- Adjacent-workflow threat: read the matrix through workflow overlap, "
                    f"integration leverage, and switching-cost exposure.{refs}"
                ),
                (
                    "- Buying risk: separate proven enterprise controls from search-only or "
                    f"low-confidence claims before procurement recommendations.{refs}"
                ),
                (
                    "- Watchlist: monitor the dimensions where adjacent competitors could "
                    f"absorb the target workflow with one integration or packaging change.{refs}"
                ),
            ]
        if layer == "L3":
            return [
                "",
                f"## {self._layer_section_heading(detail, fallback=fallback)}",
                (
                    "- Category view: avoid a single direct winner and group competitors by "
                    f"segment, trend signal, and benchmark strength.{refs}"
                ),
                (
                    "- Strategy view: treat recommendations as portfolio options while "
                    f"evidence breadth remains below landscape-grade coverage.{refs}"
                ),
                (
                    "- Uncertainty view: prioritize adding competitors and market-level "
                    f"sources before making category-wide claims.{refs}"
                ),
            ]
        implication = (
            "Use this evidence-indexed interim readout until the narrative writer "
            "can regenerate a fuller version."
            if fallback
            else (
                "Use this section as an evidence-indexed business readout with explicit "
                "uncertainty."
            )
        )
        return [
            "",
            f"## {self._layer_section_heading(detail, fallback=fallback)}",
            f"- {implication}{refs}",
        ]

    def _fallback_source_quality_section(self, detail: RunDetail) -> list[str]:
        if not detail.raw_sources:
            return [
                "",
                "## Source Quality & Coverage",
                "- No raw sources are available, so all conclusions require collection before use.",
            ]
        by_type: dict[str, list[tuple[str, float]]] = {}
        for source in detail.raw_sources:
            by_type.setdefault(source.source_type, []).append((source.id, source.confidence))
        lines = ["", "## Source Quality & Coverage"]
        for source_type, values in sorted(by_type.items()):
            source_ids = [source_id for source_id, _confidence in values]
            avg_confidence = sum(confidence for _source_id, confidence in values) / len(values)
            lines.append(
                f"- {source_type}: {len(values)} source(s), avg confidence "
                f"{avg_confidence:.2f}{self._format_source_refs(source_ids)}"
            )
        return lines

    def _fallback_scenario_checklist_section(self, detail: RunDetail) -> list[str]:
        scenario_id = detail.plan.scenario_id or "auto"
        pack = get_scenario_pack(scenario_id) if detail.plan.scenario_id else None
        recommended = detail.plan.scenario_recommended_dimensions or detail.plan.dimensions
        lines = [
            "",
            "## Scenario QA Checklist",
            (
                f"- Scenario: {scenario_id}; layer: {detail.plan.competitor_layer}; "
                f"recommended dimensions: {', '.join(recommended) or 'none'}."
            ),
        ]
        if pack is not None:
            lines.append(f"- Scenario intent: {pack.description}")
            for question in pack.analyst_questions[:3]:
                lines.append(f"- Analyst question: {question}")
            for requirement in pack.evidence_requirements[:3]:
                lines.append(f"- Evidence requirement: {requirement}")
        if detail.plan.qa_rule_ids:
            lines.append(f"- QA rules: {', '.join(detail.plan.qa_rule_ids)}")
        return lines

    def _fallback_next_collection_plan(self, detail: RunDetail) -> list[str]:
        lines = ["", "## Next Collection / Verification Plan"]
        source_ids_by_dimension: dict[str, list[str]] = {}
        for source in detail.raw_sources:
            source_ids_by_dimension.setdefault(source.dimension, []).append(source.id)
        planned = 0
        for dimension in detail.plan.dimensions:
            source_ids = source_ids_by_dimension.get(dimension, [])
            if len(source_ids) >= max(1, min(2, len(detail.plan.competitors))):
                continue
            planned += 1
            lines.append(
                f"- Add stronger {dimension} evidence for under-covered competitors"
                f"{self._format_source_refs(source_ids)}"
            )
        for issue in detail.qa_findings[:3]:
            planned += 1
            lines.append(f"- Resolve QA finding `{issue.id}`: {issue.problem}")
        if planned == 0:
            lines.append(
                "- Re-run collection only for stale, rejected, or low-confidence evidence."
            )
        return lines

    def _fallback_evidence_appendix(self, detail: RunDetail) -> list[str]:
        lines = ["", "## Evidence Appendix"]
        if not detail.raw_sources:
            lines.append("- No evidence records are attached to this report draft.")
            return lines
        for source in detail.raw_sources[:8]:
            lines.append(
                f"- {source.id}: {source.title} / {source.source_type} / confidence "
                f"{source.confidence:.2f} [source:{source.id}]"
            )
        if len(detail.raw_sources) > 8:
            omitted_count = len(detail.raw_sources) - 8
            lines.append(f"- {omitted_count} additional source(s) omitted from this appendix.")
        return lines

    def _harden_report_markdown(self, detail: RunDetail, markdown: str) -> str:
        return self._ensure_report_claim_citations(
            detail,
            self._repair_report_source_tokens(
                detail,
                self._ensure_report_required_sections(detail, markdown),
            ),
        )

    def _ensure_report_required_sections(self, detail: RunDetail, markdown: str) -> str:
        hardened = markdown.strip()
        if not hardened:
            hardened = self._fallback_report_markdown(detail, "empty writer output")
        source_ids = self._matrix_source_ids(detail)
        section_groups = [
            ("Source Quality & Coverage", self._fallback_source_quality_section(detail)),
            (
                self._layer_section_heading(detail, fallback=False),
                self._fallback_layer_sections(detail, source_ids, fallback=False),
            ),
            ("Memory Context", self._fallback_memory_context_section(detail)),
            ("User Research Evidence", self._fallback_user_research_section(detail)),
            ("RAG Gap Fill", self._fallback_rag_gap_fill_section(detail)),
            ("Scenario QA Checklist", self._fallback_scenario_checklist_section(detail)),
            ("Claim Validation & Evidence Risk", self._fallback_claim_validation_section(detail)),
            ("Next Collection / Verification Plan", self._fallback_next_collection_plan(detail)),
            ("Evidence Appendix", self._fallback_evidence_appendix(detail)),
        ]
        for heading, lines in section_groups:
            if lines and not self._report_has_heading(hardened, heading):
                hardened = f"{hardened}\n\n{self._section_body(lines)}"
        return hardened

    def _layer_section_heading(self, detail: RunDetail, *, fallback: bool = True) -> str:
        if detail.plan.competitor_layer == "L1":
            return "Battlecard"
        if detail.plan.competitor_layer == "L2":
            return "Workflow & Enterprise Risk"
        if detail.plan.competitor_layer == "L3":
            return "Market Landscape"
        return "Business Implications"

    def _report_has_heading(self, markdown: str, heading: str) -> bool:
        return bool(
            re.search(
                rf"^#+\s+{re.escape(heading)}\s*$",
                markdown,
                flags=re.IGNORECASE | re.MULTILINE,
            )
        )

    def _section_body(self, lines: list[str]) -> str:
        return "\n".join(lines).strip()

    def _writer_layer_label(self, detail: RunDetail) -> str:
        if detail.plan.competitor_layer == "L1":
            return "Direct Battlecard"
        if detail.plan.competitor_layer == "L2":
            return "Adjacent Workflow Review"
        if detail.plan.competitor_layer == "L3":
            return "Market Landscape"
        return "Competitive Analysis Report"

    def _writer_layer_context(self, detail: RunDetail) -> str:
        layer = detail.plan.competitor_layer
        scenario = detail.plan.scenario_id or "auto"
        recommended = ", ".join(detail.plan.scenario_recommended_dimensions) or "none"
        if layer == "L1":
            focus = (
                "Direct replacement comparison. Emphasize winner/loser tradeoffs, pricing "
                "and packaging, feature parity, sales objections, switching triggers, and "
                "near-term product response."
            )
        elif layer == "L2":
            focus = (
                "Adjacent workflow comparison. Emphasize workflow overlap, ecosystem and "
                "integration leverage, enterprise adoption risk, switching cost, and where "
                "an adjacent product could absorb the user's use case."
            )
        elif layer == "L3":
            focus = (
                "Market landscape analysis. Emphasize category segmentation, clusters, trend "
                "signals, benchmark dimensions, uncertainty, and strategy options rather than "
                "a simplistic direct winner."
            )
        else:
            focus = "General competitive-intelligence report with explicit uncertainty."
        return f"{focus} Scenario={scenario}. Recommended dimensions={recommended}."

    def _writer_required_sections(self, detail: RunDetail) -> str:
        common = [
            "Executive Summary with confidence level and caveats before recommendations.",
            (
                "Source Quality & Coverage, separating official/fetched sources from "
                "search-only leads."
            ),
            "Side-by-Side Decision Matrix covering every competitor and dimension.",
            "Evidence-backed Deep Dives with no unsupported winner claims.",
            (
                "Scenario QA Checklist tying the selected ScenarioPack to analyst "
                "questions, evidence requirements, and QA rules."
            ),
        ]
        layer = detail.plan.competitor_layer
        if layer == "L1":
            specific = [
                "Battlecard: where each competitor wins, loses, and is vulnerable.",
                "Pricing, packaging, and sales objection handling.",
                "Recommended product or go-to-market response.",
            ]
        elif layer == "L2":
            specific = [
                "Workflow overlap and ecosystem leverage.",
                "Enterprise buying risks, switching costs, and integration exposure.",
                "Strategic watchlist: what would make this adjacent competitor more dangerous.",
            ]
        elif layer == "L3":
            specific = [
                "Market segmentation and competitor clusters.",
                "Trend and benchmark signals by category segment.",
                "Strategic options with uncertainty and evidence gaps clearly separated.",
            ]
        else:
            specific = ["Business implications and next validation tasks."]
        ending = [
            "Risks, Unknowns, and Evidence Gaps, including unresolved QA findings.",
            (
                "Claim Validation & Evidence Risk, listing weak claims, low-confidence "
                "sources, and any single-source high-risk conclusions."
            ),
            "Next Collection / Verification Plan.",
            "Evidence Appendix listing important source IDs with type and confidence.",
        ]
        return "\n".join(
            f"{index}. {section}"
            for index, section in enumerate([*common, *specific, *ending], start=1)
        )

    def _writer_grounding_prompt(self, detail: RunDetail) -> str:
        return build_run_grounding_prompt(
            sources=detail.raw_sources,
            qa_findings=detail.qa_findings,
        )

    def _writer_context_package(self, detail: RunDetail) -> dict[str, object]:
        return {
            "sources": self._writer_source_digest(detail.raw_sources),
            "competitors": {
                competitor: self._writer_competitor_digest(detail, competitor)
                for competitor in detail.plan.competitors
            },
            "comparison_matrix": self._writer_matrix_digest(detail),
            "qa_findings": [self._writer_issue_digest(issue) for issue in detail.qa_findings[:10]],
            "reflections": [
                {
                    "iteration": reflection.iteration,
                    "coverage_gaps": [
                        self._trim_sentence(item, 180) for item in reflection.coverage_gaps[:4]
                    ],
                    "confidence_outliers": [
                        self._trim_sentence(item, 180)
                        for item in reflection.confidence_outliers[:4]
                    ],
                    "cross_competitor_gaps": [
                        self._trim_sentence(item, 180)
                        for item in reflection.cross_competitor_gaps[:4]
                    ],
                }
                for reflection in detail.reflections[-2:]
            ],
        }

    def _writer_source_digest(self, sources: list[RawSource]) -> list[dict[str, object]]:
        digests: list[dict[str, object]] = []
        for source in sources[:24]:
            snippet = source_business_snippet(source, dimension=source.dimension, limit=240)
            digest = {
                "id": source.id,
                "competitor": source.competitor,
                "covered_competitors": source.covered_competitors,
                "dimension": source.dimension,
                "source_type": source.source_type,
                "title": self._trim_sentence(source.title, 120),
                "url": str(source.url) if source.url else None,
                "snippet": self._trim_sentence(snippet, 240),
                "confidence": round(source.confidence, 3),
            }
            if not snippet:
                digest["snippet_quality"] = "omitted_no_clean_business_snippet"
            digests.append(digest)
        return digests

    def _writer_competitor_digest(self, detail: RunDetail, competitor: str) -> dict[str, object]:
        kb = detail.competitor_kbs.get(competitor)
        knowledge = detail.competitor_knowledge.get(competitor)
        slices = {}
        if kb is not None:
            slices = {
                dimension: [self._trim_sentence(item, 180) for item in findings[:3]]
                for dimension, findings in kb.slices.items()
                if dimension in detail.plan.dimensions
            }
        return {
            "kb_slices": slices,
            "source_ids": (knowledge.source_ids[:8] if knowledge is not None else []),
            "confidence": (
                round(knowledge.confidence, 3) if knowledge is not None else None
            ),
            "pricing": self._writer_pricing_digest(knowledge),
            "feature_tree": self._writer_feature_tree_digest(knowledge),
            "feature_claims": self._writer_feature_claim_digest(knowledge),
            "persona_claims": self._writer_persona_claim_digest(knowledge),
        }

    def _writer_pricing_digest(self, knowledge: object | None) -> dict[str, object]:
        if knowledge is None or not hasattr(knowledge, "pricing_model"):
            return {"tiers": [], "notes": []}
        pricing = knowledge.pricing_model
        return {
            "tiers": [
                {
                    "name": self._trim_sentence(tier.name, 80),
                    "price": self._trim_sentence(tier.price, 80),
                    "claims": self._writer_claim_digest(tier.claims, limit=2),
                }
                for tier in pricing.tiers[:4]
            ],
            "notes": self._writer_claim_digest(pricing.notes, limit=3),
        }

    def _writer_feature_claim_digest(self, knowledge: object | None) -> list[dict[str, object]]:
        if knowledge is None or not hasattr(knowledge, "feature_tree"):
            return []
        claims = list(knowledge.feature_tree.summary_claims)
        for node in knowledge.feature_tree.nodes[:4]:
            claims.extend(node.claims[:2])
        return self._writer_claim_digest(claims, limit=8)

    def _writer_feature_tree_digest(self, knowledge: object | None) -> list[dict[str, object]]:
        if knowledge is None or not hasattr(knowledge, "feature_tree"):
            return []
        nodes = list(knowledge.feature_tree.nodes)
        return [
            {
                "name": self._trim_sentence(node.name, 80),
                "description": self._trim_sentence(node.description, 160),
                "source_ids": self._feature_node_source_ids(node)[:4],
                "claim_count": len(node.claims),
                "child_count": len(node.children),
            }
            for node in nodes[:8]
        ]

    def _writer_persona_claim_digest(self, knowledge: object | None) -> list[dict[str, object]]:
        if knowledge is None or not hasattr(knowledge, "user_personas"):
            return []
        claims = list(knowledge.user_personas.summary_claims)
        for segment in knowledge.user_personas.segments[:4]:
            claims.extend(segment.claims[:2])
        return self._writer_claim_digest(claims, limit=8)

    def _writer_claim_digest(
        self,
        claims: list[KnowledgeClaim],
        *,
        limit: int,
    ) -> list[dict[str, object]]:
        return [
            {
                "claim": self._trim_sentence(claim.claim, 180),
                "source_ids": claim.source_ids[:4],
                "confidence": round(claim.confidence, 3),
            }
            for claim in claims[:limit]
        ]

    def _writer_matrix_digest(self, detail: RunDetail) -> dict[str, object]:
        if detail.comparison_matrix is None:
            return {"winner_by_dimension": {}, "summary": [], "cells": []}
        return {
            "winner_by_dimension": detail.comparison_matrix.winner_by_dimension,
            "summary": [
                self._writer_matrix_summary_item(item)
                for item in detail.comparison_matrix.summary[:6]
            ],
            "cells": [
                {
                    "competitor": cell.competitor,
                    "dimension": cell.dimension,
                    "value": self._writer_matrix_cell_value(cell),
                    "source_ids": cell.source_ids[:4],
                    "confidence": round(cell.confidence, 3),
                }
                for cell in detail.comparison_matrix.cells[:32]
            ],
        }

    def _writer_matrix_summary_item(self, item: str) -> str:
        long_summary = item.startswith(
            ("[feature-standardization:", "[pricing-standardization:")
        )
        limit = 1200 if long_summary else 180
        return self._trim_sentence(item, limit)

    def _writer_matrix_cell_value(self, cell: object) -> str:
        dimension = str(getattr(cell, "dimension", "")).casefold()
        limit = 1200 if "feature" in dimension or "pricing" in dimension else 180
        return self._trim_sentence(str(getattr(cell, "value", "")), limit)

    def _feature_node_source_ids(self, node: FeatureNode) -> list[str]:
        source_ids: list[str] = []
        seen: set[str] = set()
        claims = [*node.claims, *self._feature_child_claims(node)]
        for claim in claims:
            for source_id in claim.source_ids:
                if source_id not in seen:
                    seen.add(source_id)
                    source_ids.append(source_id)
        return source_ids

    def _writer_issue_digest(self, issue: QCIssue) -> dict[str, object]:
        return {
            "id": issue.id,
            "severity": issue.severity,
            "target_agent": issue.target_agent,
            "target_subagent": issue.target_subagent,
            "target_competitor": issue.target_competitor,
            "problem": self._trim_sentence(issue.problem, 180),
        }

    def _matrix_source_ids(self, detail: RunDetail) -> list[str]:
        if detail.comparison_matrix is None:
            return [source.id for source in detail.raw_sources[:3]]
        source_ids: list[str] = []
        seen: set[str] = set()
        for cell in detail.comparison_matrix.cells:
            for source_id in cell.source_ids:
                if source_id not in seen:
                    seen.add(source_id)
                    source_ids.append(source_id)
                if len(source_ids) >= 6:
                    return source_ids
        return source_ids

    def _format_source_refs(self, source_ids: Iterable[str]) -> str:
        unique = []
        seen: set[str] = set()
        for source_id in source_ids:
            if source_id and source_id not in seen:
                unique.append(source_id)
                seen.add(source_id)
            if len(unique) >= 4:
                break
        if not unique:
            return ""
        return " " + " ".join(f"[source:{source_id}]" for source_id in unique)

    def _fallback_memory_context_section(self, detail: RunDetail) -> list[str]:
        if not detail.plan.memory_prompt_context:
            return []
        candidate_ids = ", ".join(detail.plan.memory_candidate_ids) or "none"
        lines = [
            "",
            "## Memory Context",
            (
                "Confirmed MemoryAgent guidance was used as planning and writing context; "
                "any remembered domain fact still needs current evidence before publication."
            ),
            f"- Candidate IDs: {candidate_ids}",
            f"- Recall score: {detail.plan.memory_recall_score}/100",
        ]
        lines.extend(
            f"- {self._memory_context_label(item)}: {item}"
            for item in detail.plan.memory_prompt_context[:6]
        )
        return lines

    def _memory_context_label(self, item: str) -> str:
        normalized = item.casefold()
        if normalized.startswith("[domain fact") or "domain fact" in normalized:
            return "Domain fact"
        if normalized.startswith("[qa policy") or "qa policy" in normalized:
            return "QA policy"
        if normalized.startswith("[failure pattern") or "failure pattern" in normalized:
            return "Failure pattern"
        return "Guidance"

    def _fallback_user_research_section(self, detail: RunDetail) -> list[str]:
        research_sources = [
            source
            for source in detail.raw_sources
            if source.source_type in USER_RESEARCH_SOURCE_TYPES
        ]
        persona_requested = any(
            dimension.casefold().replace("-", "_") in {"persona", "user", "review"}
            for dimension in detail.plan.dimensions
        )
        if not research_sources and not persona_requested:
            return []
        lines = [
            "",
            "## User Research Evidence",
            (
                "Survey, interview, and manual-note inputs are treated as directional "
                "buyer or user signals, not as official factual proof."
            ),
        ]
        if not research_sources:
            lines.append(
                "- Persona or review analysis was requested, but no user-research source "
                "is attached yet; keep persona conclusions in the evidence-gap lane."
                f"{self._format_source_refs(self._matrix_source_ids(detail))}"
            )
            return lines
        for source in research_sources[:5]:
            lines.append(
                f"- {source.title} / {source.source_type} / confidence {source.confidence:.2f}"
                f" [source:{source.id}]"
            )
        return lines

    def _fallback_rag_gap_fill_section(self, detail: RunDetail) -> list[str]:
        collector_gaps = [
            issue
            for issue in detail.qa_findings
            if issue.target_agent == "collector" and issue.severity in {"warn", "blocker"}
        ]
        if not collector_gaps:
            return []
        lines = [
            "",
            "## RAG Gap Fill",
            (
                "Collector evidence gaps should be closed through retrieval before this "
                "report is published or used as a final decision artifact."
            ),
        ]
        for issue in collector_gaps[:5]:
            scope = issue.redo_scope
            target = scope.target_subagent or issue.target_subagent or issue.field_path
            competitor = scope.target_competitor or issue.target_competitor or "all competitors"
            query = self._gap_fill_query(detail, issue)
            sources = self._format_source_refs(self._matrix_source_ids(detail))
            lines.append(
                f"- Gap `{issue.id}`: {issue.problem} Target={target}; "
                f"competitor={competitor}; redo={scope.kind}. "
                f"Suggested retrieval query: {query}.{sources}"
            )
        lines.append(
            "- Run the Evidence Gap Fill action to retrieve, rerank, and attach verified "
            "evidence. The resulting draft version should link filled gap IDs and "
            "retrieval contexts."
        )
        return lines

    def _gap_fill_query(self, detail: RunDetail, issue: QCIssue) -> str:
        dimension = issue.target_subagent or "evidence"
        competitor = (
            issue.target_competitor
            or ", ".join(detail.plan.competitors[:3])
            or detail.topic
        )
        query = f"{competitor} {dimension} {issue.problem}".strip()
        return " ".join(query.split())[:180]

    def _fallback_claim_validation_section(self, detail: RunDetail) -> list[str]:
        lines = ["", "## Claim Validation & Evidence Risk"]
        source_by_id = {source.id: source for source in detail.raw_sources}
        claims = self._knowledge_claims(detail)
        issue_counts = {
            "blocker": sum(1 for issue in detail.qa_findings if issue.severity == "blocker"),
            "warn": sum(1 for issue in detail.qa_findings if issue.severity == "warn"),
            "info": sum(1 for issue in detail.qa_findings if issue.severity == "info"),
        }
        lines.append(
            "- QA status: "
            f"{issue_counts['blocker']} blocker(s), {issue_counts['warn']} warning(s), "
            f"{issue_counts['info']} info finding(s) across {len(claims)} structured claim(s)."
            f"{self._format_source_refs(self._matrix_source_ids(detail))}"
        )

        weak_claims = [
            claim
            for claim in claims
            if claim.confidence < 0.65
            or self._claim_has_weak_sources(claim.source_ids, source_by_id)
            or self._claim_needs_triangulation(claim.claim, claim.source_ids)
        ]
        if weak_claims:
            for claim in weak_claims[:5]:
                labels = []
                if claim.confidence < 0.65:
                    labels.append(f"confidence {claim.confidence:.2f}")
                if self._claim_has_weak_sources(claim.source_ids, source_by_id):
                    labels.append("weak source mix")
                if self._claim_needs_triangulation(claim.claim, claim.source_ids):
                    labels.append("needs triangulation")
                lines.append(
                    f"- Review claim ({', '.join(labels)}): {self._trim_sentence(claim.claim)}"
                    f"{self._format_source_refs(claim.source_ids)}"
                )
        else:
            lines.append(
                "- No low-confidence or single-source high-risk structured claims were detected."
                f"{self._format_source_refs(self._matrix_source_ids(detail))}"
            )

        for issue in detail.qa_findings[:4]:
            lines.append(
                f"- QA {issue.severity} `{issue.id}`: "
                f"{self._trim_sentence(issue.problem)}"
            )

        reflection_gaps = self._reflection_gap_notes(detail)
        for note in reflection_gaps[:4]:
            lines.append(
                f"- Evidence gap: {self._trim_sentence(note)}"
                f"{self._format_source_refs(self._matrix_source_ids(detail))}"
            )
        return lines

    def _knowledge_claims(self, detail: RunDetail) -> list[KnowledgeClaim]:
        claims = []
        for knowledge in detail.competitor_knowledge.values():
            for node in knowledge.feature_tree.nodes:
                claims.extend(node.claims)
                claims.extend(self._feature_child_claims(node))
            claims.extend(knowledge.feature_tree.summary_claims)
            for tier in knowledge.pricing_model.tiers:
                claims.extend(tier.claims)
            claims.extend(knowledge.pricing_model.notes)
            for segment in knowledge.user_personas.segments:
                claims.extend(segment.claims)
            claims.extend(knowledge.user_personas.summary_claims)
        return claims

    def _feature_child_claims(self, node: FeatureNode) -> list[KnowledgeClaim]:
        claims = []
        for child in node.children:
            claims.extend(child.claims)
            claims.extend(self._feature_child_claims(child))
        return claims

    def _claim_has_weak_sources(
        self, source_ids: list[str], source_by_id: dict[str, RawSource]
    ) -> bool:
        if not source_ids:
            return True
        sources = [source_by_id[source_id] for source_id in source_ids if source_id in source_by_id]
        if not sources:
            return True
        weak_types = {"web_search_result", "llm_public_knowledge"}
        return all(
            source.source_type in weak_types or source.confidence < 0.75
            for source in sources
        )

    def _claim_needs_triangulation(self, claim: str, source_ids: list[str]) -> bool:
        if len(set(source_ids)) >= 2:
            return False
        return bool(
            re.search(
                r"\b(best|better|leader|recommended|safest|cheapest|fastest|"
                r"enterprise-ready|soc\s*2|sso|saml|security|compliance)\b",
                claim,
                flags=re.IGNORECASE,
            )
        )

    def _reflection_gap_notes(self, detail: RunDetail) -> list[str]:
        if not detail.reflections:
            return []
        latest = detail.reflections[-1]
        return [
            *latest.coverage_gaps,
            *latest.confidence_outliers,
            *latest.cross_competitor_gaps,
        ]

    def _trim_sentence(self, value: str, limit: int = 220) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1].rstrip()}..."

    def _extract_cited_source_ids(self, report_md: str) -> set[str]:
        patterns = [
            r"\bsource(?:\s+id)?\s*:\s*([A-Za-z0-9_.:-]+)",
            r"\[source(?:\s+id)?\s+([A-Za-z0-9_.:-]+)\]",
        ]
        cited: set[str] = set()
        for pattern in patterns:
            cited.update(re.findall(pattern, report_md, flags=re.IGNORECASE))
        return cited

    def _repair_report_source_tokens(self, detail: RunDetail, markdown: str) -> str:
        valid_source_ids = {source.id for source in detail.raw_sources}
        if not valid_source_ids:
            return markdown

        repaired_lines: list[str] = []
        for line in markdown.splitlines():
            repaired_lines.append(
                re.sub(
                    r"\[source:([A-Za-z0-9_.:#-]+)\]",
                    lambda match, current_line=line: self._repair_report_source_token(
                        detail,
                        current_line,
                        match.group(1),
                        valid_source_ids,
                    ),
                    line,
                )
            )
        return "\n".join(repaired_lines)

    def _repair_report_source_token(
        self,
        detail: RunDetail,
        line: str,
        token: str,
        valid_source_ids: set[str],
    ) -> str:
        source_id = token.split("#", 1)[0]
        if source_id in valid_source_ids:
            return f"[source:{token}]"

        dimension_match = [
            source.id
            for source in detail.raw_sources
            if source.dimension.casefold() == source_id.casefold()
        ]
        replacement_ids = dimension_match or self._source_ids_for_report_line(detail, line)
        if not replacement_ids:
            return f"[source:{token}]"
        return f"[source:{replacement_ids[0]}]"

    def _ensure_report_claim_citations(self, detail: RunDetail, markdown: str) -> str:
        hardened_lines: list[str] = []
        for line in markdown.splitlines():
            if not self._report_line_needs_citation(line):
                hardened_lines.append(line)
                continue
            if self._extract_cited_source_ids(line):
                hardened_lines.append(line)
                continue
            source_ids = self._source_ids_for_report_line(detail, line)
            if not source_ids:
                hardened_lines.append(line)
                continue
            citation_text = " ".join(f"[source:{source_id}]" for source_id in source_ids[:2])
            stripped = line.rstrip()
            if stripped.startswith("|") and stripped.endswith("|"):
                hardened_lines.append(f"{stripped[:-1].rstrip()} {citation_text} |")
            else:
                hardened_lines.append(f"{stripped} {citation_text}")
        return "\n".join(hardened_lines)

    def _report_line_needs_citation(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.startswith("#"):
            return False
        if set(stripped) <= {"-", " ", "|", ":"}:
            return False
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", stripped):
            return False
        return bool(re.search(r"[A-Za-z0-9]", stripped)) and len(stripped) >= 24

    def _source_ids_for_report_line(self, detail: RunDetail, line: str) -> list[str]:
        normalized = line.casefold()
        matched_competitors = [
            competitor
            for competitor in detail.plan.competitors
            if competitor.casefold() in normalized
        ]
        matched_dimensions = [
            dimension
            for dimension in detail.plan.dimensions
            if dimension.casefold() in normalized
            or (
                dimension == "pricing"
                and any(token in normalized for token in ("price", "pricing", "cost", "$"))
            )
            or (
                dimension == "feature"
                and any(token in normalized for token in ("feature", "capability", "function"))
            )
            or (
                dimension == "persona"
                and any(
                    token in normalized
                    for token in ("persona", "customer", "user", "buyer", "use case")
                )
            )
        ]

        def unique(ids: list[str]) -> list[str]:
            seen: set[str] = set()
            return [
                source_id for source_id in ids if not (source_id in seen or seen.add(source_id))
            ]

        source_ids = [
            source.id
            for source in detail.raw_sources
            if (
                not matched_competitors
                or any(
                    self._source_matches_competitor(source, competitor)
                    for competitor in matched_competitors
                )
            )
            and (not matched_dimensions or source.dimension in matched_dimensions)
        ]
        if not source_ids and matched_competitors:
            source_ids = [
                source.id
                for source in detail.raw_sources
                if any(
                    self._source_matches_competitor(source, competitor)
                    for competitor in matched_competitors
                )
            ]
        if not source_ids and matched_dimensions:
            source_ids = [
                source.id for source in detail.raw_sources if source.dimension in matched_dimensions
            ]
        if not source_ids:
            source_ids = [source.id for source in detail.raw_sources]
        return unique(source_ids)
