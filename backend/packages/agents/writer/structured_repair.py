from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from packages.agents.writer.structured_report import StructuredReport
from packages.schema.models import RedoScope


_SOURCE_TOKEN_RE = re.compile(r"\[source:[^\]]+\]")
_RECOMMENDATION_MARKER_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:recommendation|推荐|建议|采购建议|推荐决策)\s*[:：]\s*(.+)$",
    re.IGNORECASE,
)


def scoped_structured_section_keys(scopes: Iterable[RedoScope]) -> set[str]:
    keys: set[str] = set()
    for scope in scopes:
        dimension = _normalize(scope.target_subagent)
        competitors = _scope_competitors(scope)

        if dimension in {"persona", "review", "customer", "user"}:
            keys.add("user_review_themes")
            _add_competitor_deep_dive_keys(keys, competitors)
        elif dimension == "pricing":
            keys.add("decision_matrix")
            _add_competitor_deep_dive_keys(keys, competitors)
        elif dimension == "feature":
            _add_competitor_deep_dive_keys(keys, competitors)
        elif competitors:
            _add_competitor_deep_dive_keys(keys, competitors)
        else:
            keys.add("competitive_findings")

        keys.add("support")
    return keys


def merge_scoped_structured_report(
    *,
    previous: StructuredReport,
    candidate: StructuredReport,
    scopes: Iterable[RedoScope],
) -> StructuredReport:
    affected = scoped_structured_section_keys(scopes)
    if not affected:
        return candidate

    merged = previous.model_copy(deep=True)
    merged.metadata = candidate.metadata

    if "competitive_findings" in affected:
        merged.core.competitive_findings = candidate.core.competitive_findings
    if "user_review_themes" in affected:
        merged.core.user_review_themes = candidate.core.user_review_themes
    if "decision_matrix" in affected:
        merged.core.decision_matrix = candidate.core.decision_matrix
    if "support" in affected:
        merged.support = candidate.support

    if "competitor_deep_dives" in affected:
        merged.core.competitor_deep_dives = candidate.core.competitor_deep_dives
    else:
        candidate_by_competitor = {
            item.competitor: item for item in candidate.core.competitor_deep_dives
        }
        merged_deep_dives = []
        seen_competitors: set[str] = set()
        for previous_item in previous.core.competitor_deep_dives:
            candidate_item = candidate_by_competitor.get(previous_item.competitor)
            key = f"competitor_deep_dive::{previous_item.competitor}"
            if key in affected and candidate_item is not None:
                merged_deep_dives.append(candidate_item)
            else:
                merged_deep_dives.append(previous_item)
            seen_competitors.add(previous_item.competitor)
        for candidate_item in candidate.core.competitor_deep_dives:
            key = f"competitor_deep_dive::{candidate_item.competitor}"
            if key in affected and candidate_item.competitor not in seen_competitors:
                merged_deep_dives.append(candidate_item)
        merged.core.competitor_deep_dives = merged_deep_dives

    return merged


def structured_scoped_regression_problem(
    *,
    previous: StructuredReport,
    merged: StructuredReport,
    affected_keys: set[str],
) -> str | None:
    for key in sorted(affected_keys):
        if key == "support":
            continue
        previous_section = _section_for_key(previous, key)
        merged_section = _section_for_key(merged, key)
        if previous_section is None or merged_section is None:
            continue
        previous_metrics = _section_metrics(previous_section)
        merged_metrics = _section_metrics(merged_section)
        if (
            previous_metrics["text_chars"] >= 80
            and merged_metrics["text_chars"] < int(previous_metrics["text_chars"] * 0.6)
        ):
            return (
                f"{key} scoped structured section regressed: text_chars "
                f"{previous_metrics['text_chars']} -> {merged_metrics['text_chars']}"
            )
        if (
            previous_metrics["claim_count"] >= 3
            and merged_metrics["claim_count"] < int(previous_metrics["claim_count"] * 0.6)
        ):
            return (
                f"{key} scoped structured section regressed: claim_count "
                f"{previous_metrics['claim_count']} -> {merged_metrics['claim_count']}"
            )
        if (
            previous_metrics["source_id_count"] >= 2
            and merged_metrics["source_id_count"] < previous_metrics["source_id_count"]
        ):
            return (
                f"{key} scoped structured section regressed: source_id_count "
                f"{previous_metrics['source_id_count']} -> "
                f"{merged_metrics['source_id_count']}"
            )
        previous_claims = _text_claims_by_path(previous_section)
        merged_claims = _text_claims_by_path(merged_section)
        for path, previous_text in previous_claims.items():
            merged_text = merged_claims.get(path)
            if merged_text is None:
                continue
            if len(previous_text) >= 80 and len(merged_text) < int(len(previous_text) * 0.6):
                return (
                    f"{key} scoped structured section regressed at {path}: text_chars "
                    f"{len(previous_text)} -> {len(merged_text)}"
                )
    return None


def previous_recommendation_posture(
    *,
    previous_structured_report: StructuredReport | None,
    previous_report: str,
) -> str:
    if previous_structured_report is not None:
        return previous_structured_report.core.executive_summary.recommendation.text
    return _extract_markdown_recommendation(previous_report)


def recommendation_delta_problem(
    *,
    previous_recommendation: str,
    candidate_recommendation: str,
    scoped_competitors: set[str],
    scoped_dimensions: set[str],
    candidate_rationale: str,
) -> str | None:
    previous = _normalize(previous_recommendation)
    candidate = _normalize(candidate_recommendation)
    if not previous or not candidate or previous == candidate:
        return None
    if not scoped_competitors and not scoped_dimensions:
        return None

    rationale = _normalize(candidate_rationale)
    candidate_mentions_scoped_competitor = not scoped_competitors or any(
        _contains_name(candidate, competitor) for competitor in scoped_competitors
    )
    rationale_mentions_scoped_competitor = not scoped_competitors or any(
        _contains_name(rationale, competitor) for competitor in scoped_competitors
    )
    rationale_mentions_scoped_dimension = not scoped_dimensions or any(
        dimension and dimension.casefold() in rationale
        for dimension in scoped_dimensions
    )
    if (
        candidate_mentions_scoped_competitor
        and rationale_mentions_scoped_competitor
        and rationale_mentions_scoped_dimension
    ):
        return None

    return (
        "recommendation changed outside scoped redo evidence; preserve previous "
        "recommendation or provide scoped new-evidence justification"
    )


def _scope_competitors(scope: RedoScope) -> list[str]:
    competitors: list[str] = []
    if scope.target_competitor:
        competitors.append(scope.target_competitor)
    competitors.extend(scope.target_competitors)
    return list(dict.fromkeys(competitor for competitor in competitors if competitor))


def _add_competitor_deep_dive_keys(keys: set[str], competitors: list[str]) -> None:
    if competitors:
        for competitor in competitors:
            keys.add(f"competitor_deep_dive::{competitor}")
    else:
        keys.add("competitor_deep_dives")


def _normalize(text: str | None) -> str:
    return " ".join((text or "").casefold().split())


def _contains_name(text: str, name: str) -> bool:
    normalized_name = _normalize(name)
    if not normalized_name:
        return False
    return bool(re.search(rf"(^|\W){re.escape(normalized_name)}($|\W)", text))


def _section_for_key(report: StructuredReport, key: str) -> object | None:
    if key == "competitive_findings":
        return report.core.competitive_findings
    if key == "user_review_themes":
        return report.core.user_review_themes
    if key == "decision_matrix":
        return report.core.decision_matrix
    if key == "support":
        return report.support
    if key == "competitor_deep_dives":
        return report.core.competitor_deep_dives
    if key.startswith("competitor_deep_dive::"):
        competitor = key.split("::", 1)[1]
        return [
            item
            for item in report.core.competitor_deep_dives
            if item.competitor == competitor
        ]
    return None


def _section_metrics(section: object) -> dict[str, int]:
    text_chars = 0
    claim_count = 0
    source_ids: set[str] = set()

    def visit(value: Any) -> None:
        nonlocal text_chars, claim_count
        if hasattr(value, "model_dump"):
            visit(value.model_dump())
            return
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str) and text.strip():
                claim_count += 1
                text_chars += len(text.strip())
            source_list = value.get("source_ids")
            if isinstance(source_list, list):
                source_ids.update(
                    source_id.strip()
                    for source_id in source_list
                    if isinstance(source_id, str) and source_id.strip()
                )
            source_id = value.get("source_id")
            if isinstance(source_id, str) and source_id.strip():
                source_ids.add(source_id.strip())
            for child in value.values():
                visit(child)
            return
        if isinstance(value, list):
            for child in value:
                visit(child)

    visit(section)
    return {
        "text_chars": text_chars,
        "claim_count": claim_count,
        "source_id_count": len(source_ids),
    }


def _text_claims_by_path(section: object) -> dict[str, str]:
    claims: dict[str, str] = {}

    def visit(value: Any, path: str) -> None:
        if hasattr(value, "model_dump"):
            visit(value.model_dump(), path)
            return
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str) and text.strip():
                claims[path] = text.strip()
            for key, child in value.items():
                visit(child, f"{path}.{key}" if path else str(key))
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(section, "")
    return claims


def _extract_markdown_recommendation(markdown: str) -> str:
    in_summary = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("<!--") and "report-section:" in stripped:
            in_summary = "executive_summary" in stripped or "key=executive_summary" in stripped
            continue
        if stripped.startswith("## "):
            heading = stripped.lstrip("#").strip().casefold()
            in_summary = any(
                token in heading
                for token in (
                    "executive summary",
                    "执行摘要",
                    "决策摘要",
                    "決策摘要",
                    "decision summary",
                )
            )
            continue
        if not in_summary:
            continue
        match = _RECOMMENDATION_MARKER_RE.match(stripped)
        if not match:
            continue
        return _SOURCE_TOKEN_RE.sub("", match.group(1)).strip(" .。")
    return ""
