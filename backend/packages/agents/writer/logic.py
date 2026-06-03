from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

from packages.schema.api_dto import RunDetail

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


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
        competitor_kb_json = json.dumps(
            {key: value.model_dump(mode="json") for key, value in detail.competitor_kbs.items()},
            ensure_ascii=False,
        )
        competitor_knowledge_json = json.dumps(
            {
                key: value.model_dump(mode="json")
                for key, value in detail.competitor_knowledge.items()
            },
            ensure_ascii=False,
        )
        comparison_matrix_json = json.dumps(
            (detail.comparison_matrix.model_dump(mode="json") if detail.comparison_matrix else {}),
            ensure_ascii=False,
        )
        source_digest_json = json.dumps(self._source_digest(detail.raw_sources), ensure_ascii=False)
        reflections_json = json.dumps(
            [reflection.model_dump(mode="json") for reflection in detail.reflections],
            ensure_ascii=False,
        )
        qa_findings_json = json.dumps(
            [issue.model_dump(mode="json") for issue in detail.qa_findings],
            ensure_ascii=False,
        )
        layer_context = self._writer_layer_context(detail)
        memory_context = "\n".join(detail.plan.memory_prompt_context) or "none"
        required_sections = self._writer_required_sections(detail)
        try:
            report_md = await self._trace_llm_text(
                record,
                agent="writer",
                subagent=None,
                name="report_writer",
                system=(
                    "You are a senior enterprise competitive-intelligence analyst. "
                    "Produce a decision-grade markdown report, not a short summary. "
                    "Write with consulting depth: executive recommendation, source quality, "
                    "side-by-side matrices, dimension analysis, risks, buying implications, "
                    "and explicit next validation tasks. Cite factual claims with existing "
                    "source IDs using [source:ID]. Do not invent source IDs. "
                    "Do not use web_search_result or confidence < 0.75 as the sole support "
                    "for a winner, legal/security certification, pricing, or procurement "
                    "recommendation. If evidence is incomplete, say the conclusion is "
                    "tentative and list the exact evidence gap. Do not claim all sources are "
                    "verified when any source_type is web_search_result or llm_public_knowledge. "
                    "Treat survey_simulated and interview_record as user-research signals, "
                    "not as official factual proof. "
                    "Honor confirmed memory preferences when they do not conflict with evidence, "
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
                    f"Competitor KB JSON: {competitor_kb_json}\n"
                    f"Competitor Knowledge Schema JSON: {competitor_knowledge_json}\n"
                    f"Comparison Matrix JSON: {comparison_matrix_json}\n"
                    f"Source digest JSON: {source_digest_json}\n"
                    f"Reflections JSON: {reflections_json}\n"
                    f"Run QA Findings JSON: {qa_findings_json}\n\n"
                    f"Required sections:\n{required_sections}\n"
                    "Prefer complete analysis over brevity, but stay under 12,000 characters."
                ),
            )
            detail.report_md = self._harden_report_markdown(detail, report_md)
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
            "The report writer hit a transient generation error, so this fallback "
            "report summarizes "
            "the latest structured knowledge and comparison matrix."
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
        lines.extend(self._fallback_layer_sections(detail, matrix_sources))
        lines.extend(self._fallback_source_quality_section(detail))
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
        lines.extend(self._fallback_next_collection_plan(detail))
        lines.extend(self._fallback_evidence_appendix(detail))
        lines.extend(["", "## Writer Fallback Reason", f"- {reason}"])
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
            "Use this fallback as an evidence-indexed interim readout until the writer "
            "can regenerate a fuller narrative."
            if fallback
            else "Use this section as an evidence-indexed business readout with explicit uncertainty."
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
            lines.append(f"- Resolve QA finding `{issue.rule_id}`: {issue.problem}")
        if planned == 0:
            lines.append("- Re-run collection only for stale, rejected, or low-confidence evidence.")
        return lines

    def _fallback_evidence_appendix(self, detail: RunDetail) -> list[str]:
        lines = ["", "## Evidence Appendix"]
        if not detail.raw_sources:
            lines.append("- No evidence records are attached to this fallback report.")
            return lines
        for source in detail.raw_sources[:8]:
            lines.append(
                f"- {source.id}: {source.title} / {source.source_type} / confidence "
                f"{source.confidence:.2f} [source:{source.id}]"
            )
        if len(detail.raw_sources) > 8:
            omitted_count = len(detail.raw_sources) - 8
            lines.append(f"- {omitted_count} additional source(s) omitted from fallback appendix.")
        return lines

    def _harden_report_markdown(self, detail: RunDetail, markdown: str) -> str:
        return self._ensure_report_claim_citations(
            detail,
            self._ensure_report_required_sections(detail, markdown),
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
            ("Next Collection / Verification Plan", self._fallback_next_collection_plan(detail)),
            ("Evidence Appendix", self._fallback_evidence_appendix(detail)),
        ]
        for heading, lines in section_groups:
            if not self._report_has_heading(hardened, heading):
                hardened = f"{hardened}\n\n{self._section_body(lines)}"
        return hardened

    def _layer_section_heading(self, detail: RunDetail, *, fallback: bool = True) -> str:
        if detail.plan.competitor_layer == "L1":
            return "Battlecard Fallback" if fallback else "Battlecard"
        if detail.plan.competitor_layer == "L2":
            return (
                "Workflow & Enterprise Risk Fallback"
                if fallback
                else "Workflow & Enterprise Risk"
            )
        if detail.plan.competitor_layer == "L3":
            return "Market Landscape Fallback" if fallback else "Market Landscape"
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
            "Next Collection / Verification Plan.",
            "Evidence Appendix listing important source IDs with type and confidence.",
        ]
        return "\n".join(
            f"{index}. {section}"
            for index, section in enumerate([*common, *specific, *ending], start=1)
        )

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

    def _extract_cited_source_ids(self, report_md: str) -> set[str]:
        patterns = [
            r"\bsource(?:\s+id)?\s*:\s*([A-Za-z0-9_.:-]+)",
            r"\[source(?:\s+id)?\s+([A-Za-z0-9_.:-]+)\]",
        ]
        cited: set[str] = set()
        for pattern in patterns:
            cited.update(re.findall(pattern, report_md, flags=re.IGNORECASE))
        return cited

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
