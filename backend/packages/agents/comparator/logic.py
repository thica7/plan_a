from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from packages.agents.comparator.decision_cards import build_decision_card_bundle
from packages.agents.comparator.prompt_builder import build_comparator_prompt
from packages.llm.errors import LLMExecutionLimitError
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.refs import merge_ordered_refs
from packages.research.evidence.capabilities import capability_alignment, capability_keys
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    ComparisonAssessment,
    ComparisonCell,
    ComparisonMatrix,
    FeatureNode,
    FeatureTree,
    PricingModel,
    RawSource,
    SWOTAnalysis,
    SWOTItem,
    UserPersonaModel,
)

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


FEATURE_TAXONOMY_ORDER = (
    "code completion",
    "agentic coding",
    "chat and q&a",
    "ide integration",
    "code review and security",
    "tool and terminal use",
    "repository context",
    "enterprise administration",
)

COMMUNITY_MATRIX_SOURCE_TYPES = {
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
    "snippet_only",
}

COMPARATOR_LLM_MAX_ATTEMPTS = 3


def _comparison_term_is_known(value: object) -> bool:
    return isinstance(value, str) and value.strip().casefold() not in {
        "", "unknown", "n/a", "none", "null", "未知", "未确认", "未采集",
    }


class ComparatorAgentMixin:
    async def _real_comparator_step(self, record: RunRecord) -> None:
        detail = record.detail
        await self._ensure_analysis_evidence(record)
        view, use, question_packets = await self._begin_question_evidence_use(record, agent="comparator")
        projected, dependency_gaps = self._project_evidence_detail(record, [view])
        baseline = self._analysis_artifacts_hash(detail)
        detail.current_node = "comparator"
        self._consume_queued_agent_messages(
            record,
            to_agent="comparator",
            consumer_agent="comparator",
            message_types={"analyst_qa_result"},
        )
        await self.emit(detail.id, "node_started", "comparator", None, "Calling comparator.")
        timeout_seconds = max(0.05, float(self._settings.comparator_timeout_seconds))
        payload, fallback = await self._comparator_payload_with_retries(
            record,
            timeout_seconds=timeout_seconds,
            evidence_view=view, evidence_detail=projected,
            context_max_bytes=use.max_bytes, evidence_use=use, question_packets=question_packets,
        )
        if fallback.get("used"):
            payload = self._deterministic_comparator_payload(timeout_seconds)
        if not isinstance(payload.get("assessments"), dict):
            payload["assessments"] = {
                dimension: {"status": "insufficient_evidence", "winner": None,
                            "gaps": ["No validated task-specific assessment was produced."]}
                for dimension in detail.plan.dimensions
            }
        module_status = "fallback" if fallback.get("used") else "llm"
        matrix = self._build_comparison_matrix(
            projected,
            payload,
            fallback_used=bool(fallback.get("used")),
            evidence_view=view,
        )
        # Compare matching semantic slots/tier names; keep time and other basis qualifiers.
        incomparable = set()
        basis_status = {}
        alignment = capability_alignment(view, projected.plan.competitors)
        from packages.research.evidence.operations import operation_alignment, required_operations
        required = required_operations(projected.topic, projected.plan.target_product.use_cases if projected.plan.target_product else ())
        if required and 'feature' in projected.plan.dimensions:
            matrix.operation_alignment = operation_alignment(view, projected.plan.competitors, required)
            for row in matrix.operation_alignment:
                if row['comparison_status'] != 'comparable':
                    incomparable.add('feature')
                    basis_status['feature'] = 'insufficient_evidence'
                    dependency_gaps.append(f"Not comparable: feature / operation.{row['operation']}; {row['comparison_status']}; {row['product_statuses']}.")
        for row in alignment:
            if row["comparison_status"] != "comparable":
                incomparable.add("feature")
                basis_status["feature"] = "insufficient_evidence"
                dependency_gaps.append(f"Not comparable: feature / {row['capability_key']}; "
                                       f"{row['comparison_status']}; {row['product_statuses']}.")
        for dimension in projected.plan.dimensions:
            groups = {}
            for fact in view.facts:
                if fact.dimension != dimension:
                    continue
                qualifiers = dict(fact.qualifiers)
                if dimension == 'pricing' and fact.field not in {'price', 'usage_limit', 'capacity'}:
                    # Plan names and billing labels are attributes to display,
                    # not assertions that all vendors sell identically named plans.
                    continue
                keys = capability_keys(fact, projected.plan.competitors)
                if dimension == "feature" and str(qualifiers.get("slot", "")).startswith(("semantic_capability_", "capability_")):
                    if fact.field == "evidence_terms" and not keys:
                        incomparable.add("feature")
                        basis_status["feature"] = "insufficient_evidence"
                        dependency_gaps.append(f"Unmapped feature observation: {fact.competitor}; "
                                               f"fact_id={fact.id}; capability interpretation needs review.")
                    continue
                if dimension == "feature" and keys:
                    # A raw page ordinal/hash identifies an observation, not a
                    # comparable capability. Presence is aligned above; distinct
                    # quotes remain intact, and conditions do not imply parity.
                    continue
                slot = tuple(
                    (key, str(qualifiers.pop(key)))
                    for key in ("slot", "tier_name")
                    if key in qualifiers
                )
                groups.setdefault((fact.field, slot), []).append((fact, qualifiers))
            for (field, slot), members in groups.items():
                supported = {fact.competitor.strip().casefold() for fact, _ in members}
                missing = [
                    product
                    for product in projected.plan.competitors
                    if product.strip().casefold() not in supported
                ]
                if missing:
                    incomparable.add(dimension)
                    basis_status.setdefault(dimension, "insufficient_evidence")
                    if dimension == 'pricing':
                        plans = {product: sorted({str(fact.qualifiers.get('plan') or fact.qualifiers.get('tier_name'))
                                                  for fact in view.facts if fact.dimension == dimension and fact.field == field
                                                  and fact.competitor == product}) for product in projected.plan.competitors}
                        message = (f'Not comparable: pricing / {field}; plan_alignment_unverified: {plans}; '
                                   'select plans for the shared task before ranking prices.')
                        if message not in dependency_gaps:
                            dependency_gaps.append(message)
                        continue
                    dependency_gaps.append(
                        f"Not comparable: {dimension} / {field} / {dict(slot)}; "
                        f"comparison_counterpart_missing: {', '.join(missing)}."
                    )
                    continue
                quantitative = field in {"price", "usage_limit", "capacity"}
                unknown = quantitative and any(
                    not _comparison_term_is_known(fact.unit)
                    or not _comparison_term_is_known(fact.market)
                    or (field == "price" and (
                        not _comparison_term_is_known(
                            qualifiers.get("billing_interval") or qualifiers.get("billing_cycle")
                        )
                        or not _comparison_term_is_known(qualifiers.get("tax_scope"))
                    ))
                    for fact, qualifiers in members
                )
                contexts = {
                    (fact.unit, fact.market, json.dumps(qualifiers, sort_keys=True))
                    for fact, qualifiers in members
                }
                if unknown or len(contexts) > 1:
                    incomparable.add(dimension)
                    known_market_unit_difference = (
                        all(_comparison_term_is_known(fact.unit)
                            and _comparison_term_is_known(fact.market) for fact, _ in members)
                        and len({(fact.unit, fact.market) for fact, _ in members}) > 1
                    )
                    differs = known_market_unit_difference or not unknown
                    if differs:
                        basis_status[dimension] = "not_comparable"
                    else:
                        basis_status.setdefault(dimension, "insufficient_evidence")
                    reason = "comparison_basis_differs" if differs else "comparison_basis_unknown"
                    dependency_gaps.append(
                        f"Not comparable: {dimension} / {field}; {reason}; "
                        "unit, market or time/qualifier context is unknown or differs."
                    )
        for dimension in incomparable:
            if dimension in matrix.assessments:
                matrix.winner_by_dimension.pop(dimension, None)
                assessment = matrix.assessments[dimension]
                assessment.status = basis_status[dimension]
                assessment.winner = None
                gaps = [
                    gap
                    for gap in dependency_gaps
                    if gap.startswith(f"Not comparable: {dimension} /")
                ]
                assessment.gaps.extend(gaps)
                assessment.rationale = "Comparison withheld: " + "; ".join(gaps)
            else:
                matrix.winner_by_dimension[dimension] = "tie"
        for dimension, assessment in matrix.assessments.items():
            gaps = [
                gap
                for gap in dependency_gaps
                if gap.startswith(("Analysis dependency unavailable:", "Analysis context omitted:")) and f"/ {dimension};" in gap
            ]
            if gaps and assessment.status == "comparable":
                assessment.status = "insufficient_evidence"
                assessment.winner = None
                assessment.gaps.extend(gaps)
                assessment.rationale = "Comparison withheld: " + "; ".join(gaps)
                matrix.winner_by_dimension.pop(dimension, None)
        for dimension, assessment in matrix.assessments.items():
            coverage_gaps = [issue.problem for issue in detail.qa_findings
                             if issue.target_agent == "collector" and issue.severity == "blocker"
                             and issue.target_subagent == dimension]
            if coverage_gaps:
                assessment.status = "insufficient_evidence"
                assessment.winner = None
                assessment.gaps.extend(gap for gap in coverage_gaps if gap not in assessment.gaps)
                assessment.rationale = "Comparison withheld: " + "; ".join(coverage_gaps)
                matrix.winner_by_dimension.pop(dimension, None)
        matrix.summary.extend(dependency_gaps)
        self._sync_comparison_assessment_summary(matrix)
        self._validate_evidence_use(record, use)
        if baseline != self._analysis_artifacts_hash(detail):
            raise EvidenceUseRejectedError("Comparator analysis artifacts changed before commit")
        detail.comparison_matrix = matrix
        self._refresh_swot_analyses(detail)
        detail.decision_card_bundle = build_decision_card_bundle(
            run_id=detail.id,
            claim_bundles=projected.claim_card_bundles,
            matrix=detail.comparison_matrix,
            fallback_used=bool(fallback.get("used")),
        )
        self._record_evidence_artifact(record, kind="comparator", uses=[use],
            payload=self._comparator_evidence_artifact_payload(detail))
        self._append_agent_message(
            record,
            from_agent="comparator",
            to_agent="reflector",
            message_type="comparison_matrix_ready",
            payload_schema="ComparisonMatrix",
            payload={
                "comparison_matrix": detail.comparison_matrix.model_dump(mode="json"),
                "module_status": module_status,
                "fallback": fallback,
            },
        )
        self._append_agent_message(
            record,
            from_agent="comparator",
            to_agent="reflector",
            message_type="decision_card_bundle_ready",
            payload_schema="DecisionCardBundle",
            payload={
                "bundle": detail.decision_card_bundle.model_dump(mode="json"),
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "comparator",
            None,
            (
                "Comparator completed with deterministic fallback."
                if module_status == "fallback"
                else "Comparator completed."
            ),
            {"matrix": payload, "fallback": fallback, "module_status": module_status},
        )

        self._finish_delivery_phase(record, 'comparator', None)

    async def _comparator_payload_with_retries(
        self,
        record: RunRecord,
        *,
        timeout_seconds: float,
        evidence_view=None, evidence_detail=None,
        context_max_bytes=None, evidence_use=None, question_packets=(),
    ) -> tuple[dict[str, object], dict[str, object]]:
        detail = evidence_detail or record.detail
        from packages.research.evidence.projection import analysis_fact_refs
        analysis_json = self._bounded_analysis_json(
            evidence_view,
            analysis_fact_refs(evidence_view),
            max_bytes=context_max_bytes,
        )
        evidence_json = evidence_view.to_prompt_json()
        prompt = build_comparator_prompt(
            detail, analysis_json=analysis_json, evidence_json=evidence_json,
        )
        last_error: BaseException | None = None
        last_reason = "empty_content"
        for attempt in range(1, COMPARATOR_LLM_MAX_ATTEMPTS + 1):
            try:
                payload = await asyncio.wait_for(
                    self._trace_question_llm_json(
                        record, evidence_view=evidence_view, evidence_use=evidence_use, question_packets=question_packets,
                        agent="comparator",
                        subagent=None,
                        name="comparison_matrix",
                        is_repair=attempt > 1,
                        system=prompt.system,
                        user=prompt.user,
                        schema_hint=prompt.schema_hint,
                    ),
                    timeout=timeout_seconds,
                )
                if self._comparator_payload_has_content(payload):
                    return (
                        payload,
                        {
                            "used": False,
                            "deterministic_fallback": False,
                            "attempts": attempt,
                            "max_attempts": COMPARATOR_LLM_MAX_ATTEMPTS,
                        },
                    )
                last_reason = "empty_content"
                last_error = RuntimeError("Comparator LLM returned empty content.")
            except TimeoutError as exc:
                last_reason = "timeout"
                last_error = exc
            except EvidenceUseRejectedError:
                raise
            except LLMExecutionLimitError as exc:
                last_reason, last_error = str(exc), exc
                break
            except Exception as exc:  # noqa: BLE001 - comparator can degrade after retries.
                last_reason = "llm_error"
                last_error = exc

        fallback: dict[str, object] = {
            "used": True,
            "reason": last_reason,
            "timeout_seconds": timeout_seconds,
            "attempts": attempt,
            "max_attempts": COMPARATOR_LLM_MAX_ATTEMPTS,
            "deterministic_fallback": True,
        }
        if last_error is not None and last_reason != "timeout":
            fallback["error"] = str(last_error)
        return {}, fallback

    @staticmethod
    def _comparator_evidence_artifact_payload(detail):
        return {
            "matrix": detail.comparison_matrix.model_dump(mode="json")
            if detail.comparison_matrix
            else None,
            "decision_cards": detail.decision_card_bundle.model_dump(mode="json")
            if detail.decision_card_bundle
            else None,
        }

    def _comparator_payload_has_content(self, payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        assessments = payload.get("assessments")
        if isinstance(assessments, dict) and assessments:
            return True
        summary = payload.get("matrix_summary")
        if isinstance(summary, list) and any(str(item).strip() for item in summary):
            return True
        winners = payload.get("winner_by_dimension")
        return isinstance(winners, dict) and any(
            str(value).strip() for value in winners.values()
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

    def _build_comparison_matrix(
        self,
        detail: RunDetail,
        payload: dict,
        *,
        fallback_used: bool = False,
        evidence_view=None,
    ) -> ComparisonMatrix:
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
                from packages.research.evidence.projection import matrix_fact_value
                value = (matrix_fact_value(evidence_view, competitor, dimension)
                         if evidence_view is not None else None)
                if value is None:
                    value = self._structured_matrix_value(detail, competitor, dimension)
                if not value:
                    value = "; ".join(findings[:2])
                if not value and related_sources:
                    value = related_sources[0].snippet or related_sources[0].title
                cells.append(
                    ComparisonCell(
                        competitor=competitor,
                        role=("target" if detail.plan.target_product is not None
                              and competitor == detail.plan.target_product.name else "competitor"),
                        dimension=dimension,
                        value=value or "No structured finding available.",
                        source_ids=[source.id for source in related_sources],
                        confidence=self._matrix_cell_confidence(
                            detail,
                            competitor,
                            dimension,
                            related_sources,
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
        if fallback_used:
            voted_winners, fallback_summary = self._conservative_fallback_winners(
                detail,
                cells,
                voted_winners,
            )
            vote_summary = [*vote_summary, *fallback_summary]
        assessments = self._validated_comparison_assessments(
            detail, payload, evidence_view=evidence_view
        )
        for dimension, assessment in assessments.items():
            # An explicit task assessment overrides page-count voting, including abstentions.
            voted_winners.pop(dimension, None)
            vote_summary = [
                row for row in vote_summary if not row.startswith(f"[majority-vote:{dimension}]")
            ]
            if assessment.status == "comparable" and assessment.winner:
                voted_winners[dimension] = assessment.winner
        matrix = ComparisonMatrix(
            competitors=detail.plan.competitors,
            target_product=(
                detail.plan.target_product.name if detail.plan.target_product else None
            ),
            dimensions=detail.plan.dimensions,
            cells=cells,
            winner_by_dimension=voted_winners,
            assessments=assessments,
            summary=[
                *self._matrix_standardization_summary(detail),
                *self._community_matrix_summary(detail),
                *(self._string_list(payload.get("matrix_summary")) if evidence_view is None
                  else ["矩阵单元格按当前已验证事实生成，原文及条件保持完整；模型摘要未作为正式事实发布。"]),
                *vote_summary,
            ],
        )
        self._sync_comparison_assessment_summary(matrix)
        return matrix

    @staticmethod
    def _sync_comparison_assessment_summary(matrix: ComparisonMatrix) -> None:
        matrix.summary = [row for row in matrix.summary if not row.startswith("[assessment:")]
        matrix.summary.extend(
            f"[assessment:{dimension}] {assessment.status}; {assessment.rationale}; "
            f"scenario={assessment.scenario}; tradeoffs={assessment.tradeoffs}; "
            f"gaps={assessment.gaps}"
            for dimension, assessment in matrix.assessments.items()
        )

    def _validated_comparison_assessments(
        self, detail: RunDetail, payload: dict, *, evidence_view=None
    ) -> dict[str, ComparisonAssessment]:
        raw = payload.get("assessments")
        if not isinstance(raw, dict):
            return {}
        sources = {source.id: source for source in detail.raw_sources}
        result = {}
        for dimension in detail.plan.dimensions:
            problems = []
            try:
                assessment = ComparisonAssessment.model_validate(raw.get(dimension))
            except ValidationError:
                assessment = ComparisonAssessment(
                    status="insufficient_evidence",
                    gaps=["Missing or invalid dimension assessment."],
                )
            valid_ids = [source_id for source_id in assessment.source_ids
                         if source_id in sources and sources[source_id].dimension == dimension
                         and sources[source_id].competitor in detail.plan.competitors]
            if len(valid_ids) != len(assessment.source_ids):
                problems.append("Unknown or out-of-scope citation.")
            assessment.source_ids = list(dict.fromkeys(valid_ids))
            if assessment.status == "comparable":
                cited_products = {
                    sources[source_id].competitor
                    for source_id in valid_ids
                    if sources[source_id].confidence >= 0.75
                    and sources[source_id].source_type
                    not in {"web_search_result", "llm_public_knowledge"}
                    and self._matrix_source_is_official_signal(sources[source_id])
                }
                if set(detail.plan.competitors) - cited_products:
                    problems.append("Source-backed facts are missing for a compared product.")
                if evidence_view is not None:
                    supported_products = {
                        fact.competitor for fact in evidence_view.facts
                        if fact.dimension == dimension and fact.source_id in valid_ids
                        and fact.status == "supported" and fact.confidence >= 0.75
                        and ("pricing" not in dimension.casefold() or fact.field == "price")
                    }
                    if set(detail.plan.competitors) - supported_products:
                        problems.append(
                            "Current evidence view lacks supporting facts "
                            "for each compared product."
                        )
                if assessment.winner not in [None, "tie", *detail.plan.competitors]:
                    problems.append("Winner is outside the researched product scope.")
                if not assessment.rationale.strip() or not assessment.scenario.strip():
                    problems.append("Comparable conclusion requires rationale and scenario.")
            if problems:
                assessment.status = "insufficient_evidence"
                assessment.gaps.extend(problems)
                assessment.rationale = "Comparison withheld: " + "; ".join(problems)
            if evidence_view is not None:
                # Citation IDs validate scope, not the model's restatement of
                # people, plans or prices. Originals remain in matrix cells;
                # unreviewed comparison prose stays in the model trace only.
                assessment.rationale = (
                    "功能观察按原文与完整条件保留在矩阵；模型比较主张尚未逐条审核。"
                    if dimension == 'feature' else
                    "标价按套餐与付款周期保留在矩阵；适用价格须核对币种、席位、税费和地区。"
                    if dimension == 'pricing' else
                    "原始事实保留在矩阵；模型比较主张尚未逐条审核。"
                )
                brief = detail.plan.decision_brief
                assessment.scenario = (brief.primary_job if brief else None) or detail.topic
                assessment.tradeoffs = []
                assessment.gaps = problems
            if assessment.status != "comparable":
                assessment.winner = None
            result[dimension] = assessment
        return result

    def _conservative_fallback_winners(
        self,
        detail: RunDetail,
        cells: list[ComparisonCell],
        voted_winners: dict[str, str],
    ) -> tuple[dict[str, str], list[str]]:
        source_by_id = {source.id: source for source in detail.raw_sources}
        cell_by_key = {(cell.dimension, cell.competitor): cell for cell in cells}
        winners = dict(voted_winners)
        summary: list[str] = []
        for dimension, winner in list(winners.items()):
            if winner == "tie":
                continue
            official_counts = {
                competitor: self._official_matrix_source_count(
                    self._matrix_cell(cell_by_key, dimension, competitor),
                    source_by_id,
                )
                for competitor in detail.plan.competitors
            }
            if all(count > 0 for count in official_counts.values()):
                continue
            winners[dimension] = "tie"
            summary.append(
                "[fallback-conservative:{dimension}] winner=tie; "
                "deterministic fallback had incomplete scoped official coverage "
                "({counts})".format(
                    dimension=dimension,
                    counts=", ".join(
                        f"{competitor}={count}"
                        for competitor, count in official_counts.items()
                    ),
                )
            )
        return winners, summary

    def _refresh_swot_analyses(self, detail: RunDetail) -> None:
        matrix = detail.comparison_matrix
        if matrix is None:
            return
        cells_by_competitor: dict[str, list[ComparisonCell]] = {
            competitor: [] for competitor in detail.plan.competitors
        }
        for cell in matrix.cells:
            cells_by_competitor.setdefault(cell.competitor, []).append(cell)

        for competitor in detail.plan.competitors:
            knowledge = detail.competitor_knowledge.get(competitor)
            if knowledge is None:
                continue

            valid_competitors = set(detail.plan.competitors)
            strengths: list[SWOTItem] = []
            weaknesses: list[SWOTItem] = []
            opportunities: list[SWOTItem] = []

            competitor_cells = cells_by_competitor.get(competitor, [])
            cell_by_dimension = {cell.dimension: cell for cell in competitor_cells}
            for dimension, winner in matrix.winner_by_dimension.items():
                cell = cell_by_dimension.get(dimension)
                if cell is None:
                    continue
                normalized_winner = winner.strip()
                is_tie = normalized_winner.casefold() == "tie"
                if normalized_winner == competitor:
                    strengths.append(
                        self._swot_item(
                            f"Wins {dimension} comparison: {cell.value}",
                            cell.source_ids,
                            cell.confidence,
                        )
                    )
                elif (
                    normalized_winner in valid_competitors
                    and normalized_winner != competitor
                    and not is_tie
                ):
                    weaknesses.append(
                        self._swot_item(
                            f"Loses {dimension} comparison to {normalized_winner}: "
                            f"{cell.value}",
                            cell.source_ids,
                            cell.confidence,
                        )
                    )

            review_summary = knowledge.review_summary
            for item in review_summary.praise_themes:
                strengths.append(
                    self._swot_item(item.theme, item.source_ids, item.confidence)
                )
            for item in [
                *review_summary.complaint_themes,
                *review_summary.adoption_blockers,
            ]:
                weaknesses.append(
                    self._swot_item(item.theme, item.source_ids, item.confidence)
                )
            for item in review_summary.switching_triggers:
                opportunities.append(
                    self._swot_item(item.theme, item.source_ids, item.confidence)
                )

            if not opportunities:
                persona_claim = next(
                    (
                        claim
                        for claim in knowledge.user_personas.summary_claims
                        if claim.source_ids
                    ),
                    None,
                )
                if persona_claim is not None:
                    opportunities.append(
                        self._swot_item(
                            persona_claim.claim,
                            persona_claim.source_ids,
                            persona_claim.confidence,
                        )
                    )

            threats = [
                self._swot_item(
                    "Threat requires more competitor or adjacent-workflow evidence."
                )
            ]
            all_items = [*strengths, *weaknesses, *opportunities, *threats]
            kb_sources = detail.competitor_kbs.get(competitor)
            knowledge.swot_analysis = SWOTAnalysis(
                competitor=competitor,
                strengths=strengths,
                weaknesses=weaknesses,
                opportunities=opportunities,
                threats=threats,
                source_ids=merge_ordered_refs(
                    knowledge.source_ids,
                    kb_sources.sources if kb_sources is not None else [],
                    *(cell.source_ids for cell in competitor_cells),
                    review_summary.source_ids,
                    *(item.source_ids for item in all_items),
                ),
                confidence=self._average_swot_confidence(
                    all_items,
                    [
                        self._average_cell_confidence(competitor_cells),
                        review_summary.confidence,
                        knowledge.confidence,
                    ],
                ),
            )

    def _swot_item(
        self,
        text: str,
        source_ids: Sequence[str] | None = None,
        confidence: float = 0.0,
    ) -> SWOTItem:
        merged_source_ids = merge_ordered_refs(source_ids or [])
        return SWOTItem(
            text=" ".join(text.split()),
            source_ids=merged_source_ids,
            confidence=max(0.0, min(1.0, confidence)),
            evidence_gap=not merged_source_ids,
        )

    def _average_cell_confidence(self, cells: Sequence[ComparisonCell]) -> float:
        confidences = [cell.confidence for cell in cells if cell.confidence > 0]
        if not confidences:
            return 0.0
        return max(0.0, min(1.0, sum(confidences) / len(confidences)))

    def _average_swot_confidence(
        self,
        items: Sequence[SWOTItem],
        fallback_confidences: Sequence[float] | None = None,
    ) -> float:
        confidences = [
            item.confidence
            for item in items
            if item.source_ids and not item.evidence_gap and item.confidence > 0
        ]
        if not confidences and fallback_confidences is not None:
            confidences = [value for value in fallback_confidences if value > 0]
        if not confidences:
            return 0.0
        return max(0.0, min(1.0, sum(confidences) / len(confidences)))

    def _structured_matrix_value(
        self, detail: RunDetail, competitor: str, dimension: str
    ) -> str:
        knowledge = detail.competitor_knowledge.get(competitor)
        if knowledge is None:
            return ""
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            return self._structured_pricing_cell_value(knowledge.pricing_model)
        if "persona" in dimension_key or "user" in dimension_key:
            return self._structured_persona_cell_value(knowledge.user_personas)
        if "feature" in dimension_key:
            return self._structured_feature_cell_value(knowledge.feature_tree)
        return ""

    def _structured_pricing_cell_value(self, pricing: PricingModel) -> str:
        tier_parts = [
            (
                "tier_name={name}; price={price}; billing_cycle={cycle}; limits={limits}"
            ).format(
                name=self._compact_matrix_text(tier.name or "unknown", 44),
                price=self._compact_matrix_text(tier.price or "unknown", 120),
                cycle=self._compact_matrix_text(tier.billing_cycle or "unknown", 40),
                limits=self._compact_pricing_limits_text(tier.limits, 160),
            )
            for tier in pricing.tiers[:6]
        ]
        note_parts = [
            self._compact_matrix_text(claim.claim, 180) for claim in pricing.notes[:2]
        ]
        return self._join_structured_parts(tier_parts, "notes", note_parts)

    def _structured_persona_cell_value(self, personas: UserPersonaModel) -> str:
        segment_parts = [
            (
                "segment={segment}; role={role}; company_size={size}; "
                "use_cases={use_cases}; pain_points={pain_points}"
            ).format(
                segment=self._compact_matrix_text(segment.name or "unknown", 36),
                role=self._compact_matrix_text(segment.role or "unknown", 36),
                size=self._compact_matrix_text(segment.company_size or "unknown", 32),
                use_cases=self._compact_list_text(segment.use_cases, 180),
                pain_points=self._compact_list_text(segment.pain_points, 180),
            )
            for segment in personas.segments[:3]
        ]
        summary_parts = [
            self._compact_matrix_text(claim.claim, 96)
            for claim in personas.summary_claims[:2]
        ]
        return self._join_structured_parts(segment_parts, "summary", summary_parts)

    def _structured_feature_cell_value(self, feature_tree: FeatureTree) -> str:
        feature_parts = [
            (
                "feature_name={name}; description={description}; "
                "claim_count={claim_count}; child_count={child_count}"
            ).format(
                name=self._compact_matrix_text(node.name or "unknown", 44),
                description=self._compact_matrix_text(node.description or "unknown", 120),
                claim_count=len(node.claims),
                child_count=len(node.children),
            )
            for node in self._prioritized_feature_nodes(feature_tree)[:6]
        ]
        summary_parts = [
            self._compact_matrix_text(claim.claim, 140)
            for claim in feature_tree.summary_claims[:2]
        ]
        return self._join_structured_parts(feature_parts, "summary", summary_parts)

    def _join_structured_parts(
        self, primary_parts: list[str], fallback_label: str, fallback_parts: list[str]
    ) -> str:
        parts = list(primary_parts)
        if not parts and fallback_parts:
            parts = [f"{fallback_label}={part}" for part in fallback_parts]
        return " | ".join(parts)

    def _compact_list_text(self, values: list[str], limit: int) -> str:
        cleaned = [value.strip() for value in values if value and value.strip()]
        if not cleaned:
            return "unknown"
        selected: list[str] = []
        for value in cleaned[:3]:
            candidate = ", ".join([*selected, value])
            if len(candidate) <= limit:
                selected.append(value)
                continue
            break
        if selected:
            return ", ".join(selected)
        return self._compact_matrix_text(cleaned[0], limit)

    def _compact_pricing_limits_text(self, values: list[str], limit: int) -> str:
        cleaned = [value.strip() for value in values if value and value.strip()]
        if not cleaned:
            return "not stated in collected source"
        return self._compact_matrix_text(", ".join(cleaned[:3]), limit)

    def _matrix_standardization_summary(self, detail: RunDetail) -> list[str]:
        summary: list[str] = []
        for dimension in detail.plan.dimensions:
            dimension_key = dimension.casefold()
            if "pricing" in dimension_key:
                summary.append(self._pricing_standardization_summary(detail, dimension))
            elif "persona" in dimension_key or "user" in dimension_key:
                summary.append(self._persona_standardization_summary(detail, dimension))
            elif "feature" in dimension_key:
                summary.append(self._feature_standardization_summary(detail, dimension))
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
                for tier in tiers[:6]
            ]
            profiles.append(f"{competitor} tiers={'|'.join(tier_parts)}")
        missing_note = f"; missing={','.join(missing)}" if missing else ""
        return (
            f"[pricing-standardization:{dimension}] "
            "aligned_fields=tier_name,price,billing_cycle,limits; "
            f"{'; '.join(profiles)}{missing_note}"
        )

    def _compact_pricing_tier(self, name: str, price: str, billing_cycle: str) -> str:
        compact_name = self._compact_matrix_text(name or "unknown", 36)
        compact_price = self._compact_matrix_text(price or "unknown", 72)
        compact_cycle = self._compact_matrix_text(billing_cycle or "unknown", 32)
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

    def _feature_standardization_summary(self, detail: RunDetail, dimension: str) -> str:
        profiles: list[str] = []
        missing: list[str] = []
        for competitor in detail.plan.competitors:
            knowledge = detail.competitor_knowledge.get(competitor)
            feature_tree = knowledge.feature_tree if knowledge is not None else None
            nodes = list(feature_tree.nodes) if feature_tree is not None else []
            if not nodes:
                missing.append(competitor)
                profiles.append(f"{competitor} features=missing")
                continue
            feature_parts = [
                self._compact_feature_node(
                    node.name,
                    node.description,
                    len(node.claims),
                    len(node.children),
                )
                for node in self._prioritized_feature_nodes(feature_tree)[:6]
            ]
            profiles.append(f"{competitor} features={'|'.join(feature_parts)}")
        missing_note = f"; missing={','.join(missing)}" if missing else ""
        return (
            f"[feature-standardization:{dimension}] "
            "aligned_fields=feature_name,description,claim_count,child_count; "
            f"{'; '.join(profiles)}{missing_note}"
        )

    def _prioritized_feature_nodes(self, feature_tree: FeatureTree) -> list[FeatureNode]:
        return [
            node
            for _, _, node in sorted(
                (
                    self._feature_taxonomy_rank(node.name),
                    index,
                    node,
                )
                for index, node in enumerate(feature_tree.nodes)
            )
        ]

    def _feature_taxonomy_rank(self, name: str) -> int:
        normalized = (name or "").casefold()
        if normalized == "autocomplete":
            normalized = "code completion"
        try:
            return FEATURE_TAXONOMY_ORDER.index(normalized)
        except ValueError:
            return len(FEATURE_TAXONOMY_ORDER)

    def _compact_feature_node(
        self,
        name: str,
        description: str,
        claim_count: int,
        child_count: int,
    ) -> str:
        compact_name = self._compact_matrix_text(name or "unknown", 36)
        compact_description = self._compact_matrix_text(description or "unknown", 72)
        return (
            f"{compact_name}({compact_description};claims={claim_count};"
            f"children={child_count})"
        )

    def _compact_matrix_text(self, value: str, limit: int) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        truncated = text[: max(0, limit - 1)].rstrip()
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0].rstrip()
        return f"{truncated}..."

    def _matrix_cell_confidence(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        related_sources: list[RawSource],
    ) -> float:
        source_confidence = (
            sum(source.confidence for source in related_sources) / len(related_sources)
            if related_sources
            else 0.0
        )
        claim_confidences = self._structured_claim_confidences(detail, competitor, dimension)
        if not claim_confidences:
            return self._persona_user_research_confidence_cap(
                dimension, related_sources, source_confidence
            )
        claim_confidence = sum(claim_confidences) / len(claim_confidences)
        if source_confidence <= 0:
            return self._persona_user_research_confidence_cap(
                dimension, related_sources, claim_confidence
            )
        confidence = min(source_confidence, claim_confidence)
        return self._persona_user_research_confidence_cap(
            dimension, related_sources, confidence
        )

    def _persona_user_research_confidence_cap(
        self,
        dimension: str,
        related_sources: list[RawSource],
        confidence: float,
    ) -> float:
        dimension_key = dimension.casefold()
        if "persona" not in dimension_key and "user" not in dimension_key:
            return confidence
        user_research_sources = [
            source
            for source in related_sources
            if source.source_type in {"interview_record", "survey_simulated"}
        ]
        if not user_research_sources:
            return confidence
        return min(confidence, min(source.confidence for source in user_research_sources))

    def _structured_claim_confidences(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> list[float]:
        knowledge = detail.competitor_knowledge.get(competitor)
        if knowledge is None:
            return []
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            claims = [
                *knowledge.pricing_model.notes,
                *[claim for tier in knowledge.pricing_model.tiers for claim in tier.claims],
            ]
        elif "persona" in dimension_key or "user" in dimension_key:
            claims = [
                *knowledge.user_personas.summary_claims,
                *[
                    claim
                    for segment in knowledge.user_personas.segments
                    for claim in segment.claims
                ],
            ]
        else:
            claims = [
                *knowledge.feature_tree.summary_claims,
                *[claim for node in knowledge.feature_tree.nodes for claim in node.claims],
            ]
        return [claim.confidence for claim in claims if claim.confidence > 0]

    def _matrix_majority_vote(
        self,
        detail: RunDetail,
        cells: list[ComparisonCell],
        payload_winners: dict[str, str],
    ) -> tuple[dict[str, str], list[str]]:
        winners: dict[str, str] = {}
        summary: list[str] = []
        cell_by_key = {(cell.dimension, cell.competitor): cell for cell in cells}
        source_by_id = {source.id: source for source in detail.raw_sources}
        for dimension in detail.plan.dimensions:
            signals: dict[str, str] = {}
            evidence_winner = self._winner_from_numeric_signal(
                {
                    competitor: self._official_matrix_source_count(
                        self._matrix_cell(cell_by_key, dimension, competitor),
                        source_by_id,
                    )
                    for competitor in detail.plan.competitors
                }
            )
            confidence_winner = self._winner_from_numeric_signal(
                {
                    competitor: self._official_matrix_confidence(
                        self._matrix_cell(cell_by_key, dimension, competitor),
                        source_by_id,
                    )
                    for competitor in detail.plan.competitors
                }
            )
            finding_winner = self._winner_from_numeric_signal(
                {
                    competitor: self._official_matrix_finding_count(
                        detail,
                        dimension,
                        competitor,
                        source_by_id,
                    )
                    for competitor in detail.plan.competitors
                }
            )
            if evidence_winner:
                signals["evidence"] = evidence_winner
            if confidence_winner:
                signals["cell_confidence_winner"] = confidence_winner
            if finding_winner:
                signals["findings"] = finding_winner
            llm_winner = payload_winners.get(dimension)
            if llm_winner == "tie" or (
                llm_winner in detail.plan.competitors
                and self._matrix_competitor_has_scoped_official_signal(
                    detail,
                    cell_by_key,
                    dimension,
                    llm_winner,
                    source_by_id,
                )
            ):
                signals["llm"] = llm_winner
            winner = self._winner_from_matrix_signals(dimension, signals)
            if winner is None:
                winner = "tie"
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

    def _official_matrix_source_count(
        self,
        cell: ComparisonCell,
        source_by_id: dict[str, RawSource],
    ) -> int:
        return sum(
            1
            for source_id in cell.source_ids
            if self._matrix_source_is_official_signal(source_by_id.get(source_id))
        )

    def _official_matrix_confidence(
        self,
        cell: ComparisonCell,
        source_by_id: dict[str, RawSource],
    ) -> float:
        confidences = [
            source.confidence
            for source_id in cell.source_ids
            for source in [source_by_id.get(source_id)]
            if self._matrix_source_is_official_signal(source)
        ]
        return max(confidences, default=0.0)

    def _matrix_source_is_official_signal(self, source: RawSource | None) -> bool:
        if source is None:
            return False
        if source.metadata.get("community_evidence"):
            return False
        return source.source_type not in COMMUNITY_MATRIX_SOURCE_TYPES

    def _matrix_competitor_has_scoped_official_signal(
        self,
        detail: RunDetail,
        cell_by_key: dict[tuple[str, str], ComparisonCell],
        dimension: str,
        competitor: str,
        source_by_id: dict[str, RawSource],
    ) -> bool:
        cell = self._matrix_cell(cell_by_key, dimension, competitor)
        if any(
            self._matrix_source_is_scoped_official_signal(
                source_by_id.get(source_id),
                dimension,
                competitor,
            )
            for source_id in cell.source_ids
        ):
            return True
        return (
            self._official_matrix_finding_count(
                detail,
                dimension,
                competitor,
                source_by_id,
            )
            > 0
        )

    def _community_matrix_summary(self, detail: RunDetail) -> list[str]:
        summaries: list[str] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for source in detail.raw_sources:
            if not source.metadata.get("community_evidence"):
                continue
            clusters = source.metadata.get("community_claim_clusters")
            if not isinstance(clusters, list):
                continue
            for cluster in clusters:
                if not isinstance(cluster, dict):
                    continue
                label = str(cluster.get("label") or "")
                if label not in {
                    "official_confirmed",
                    "community_triangulated",
                    "community_observed",
                    "community_contested",
                }:
                    continue
                kind = str(cluster.get("kind") or "")
                normalized_value = str(cluster.get("normalized_value") or "")
                claim = str(cluster.get("claim") or "Community observation")
                key = (source.dimension, source.competitor, kind, normalized_value, label)
                if key in seen:
                    continue
                seen.add(key)
                source_ids = [
                    str(source_id)
                    for source_id in cluster.get("source_ids", [])
                    if str(source_id).strip()
                ]
                summaries.append(
                    "[community-adjusted:{dimension}] {competitor}: {label}; "
                    "{claim} sources={sources}".format(
                        dimension=source.dimension,
                        competitor=source.competitor,
                        label=label,
                        claim=claim,
                        sources=", ".join(source_ids[:4]),
                    )
                )
        return summaries[:8]

    def _official_matrix_finding_count(
        self,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        source_by_id: dict[str, RawSource],
    ) -> int:
        kb = detail.competitor_kbs.get(competitor)
        if kb is None:
            return 0
        count = 0
        for finding in kb.slices.get(dimension, []):
            source_ids = self._matrix_finding_source_ids(finding)
            if source_ids and any(
                self._matrix_source_is_scoped_official_signal(
                    source_by_id.get(source_id),
                    dimension,
                    competitor,
                )
                for source_id in source_ids
            ):
                count += 1
        return count

    def _matrix_source_is_scoped_official_signal(
        self,
        source: RawSource | None,
        dimension: str,
        competitor: str,
    ) -> bool:
        return (
            self._matrix_source_is_official_signal(source)
            and source is not None
            and source.dimension == dimension
            and self._source_matches_competitor(source, competitor)
        )

    def _matrix_finding_source_ids(self, finding: str) -> list[str]:
        matches = re.findall(
            r"\[source:([^\]\s]+)\]|\bsource\s+id\s*:\s*([A-Za-z0-9_.:/#-]+)",
            finding,
            flags=re.IGNORECASE,
        )
        return merge_ordered_refs(value for match in matches for value in match)

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

    def _winner_from_matrix_signals(
        self, dimension: str, signals: dict[str, str]
    ) -> str | None:
        dimension_key = dimension.casefold()
        structural_winners = [
            signals[name]
            for name in ("evidence", "findings")
            if signals.get(name) and signals[name] != "tie"
        ]
        if "pricing" in dimension_key and not structural_winners:
            return "tie" if signals else None
        return self._winner_from_votes(signals)

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
