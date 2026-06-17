from __future__ import annotations

from dataclasses import dataclass
import re

from packages.agents.writer.segment_contract import (
    CORE_HEADING_KEYS,
    SUPPORT_HEADING_KEYS,
    heading_key_for,
)
from packages.schema.api_dto import RunDetail

REQUIRED_CORE_KEYS: tuple[str, ...] = (
    "decision_summary",
    "competitive_findings",
    "review_theme_summary",
    "competitor_deep_dives",
    "side_by_side_matrix",
    "swot_analysis",
)

_H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")


@dataclass(frozen=True)
class WriterQualityPreflightResult:
    passed: bool
    failure_reasons: list[str]
    duplicate_section_count: int
    missing_core_sections: list[str]
    core_sections_after_support: list[str]
    first_support_key: str | None
    h2_keys: list[str]

    def telemetry_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failure_reasons": list(self.failure_reasons),
            "duplicate_section_count": self.duplicate_section_count,
            "missing_core_sections": list(self.missing_core_sections),
            "core_sections_after_support": list(self.core_sections_after_support),
            "first_support_key": self.first_support_key,
            "h2_keys": list(self.h2_keys),
        }


def run_writer_quality_preflight(
    detail: RunDetail,
    markdown: str,
) -> WriterQualityPreflightResult:
    h2_keys = [
        key
        for key in (
            heading_key_for(match.group(1).strip(), detail.output_language)
            for match in _H2_RE.finditer(markdown)
        )
        if key is not None
    ]
    first_support_index = next(
        (index for index, key in enumerate(h2_keys) if key in SUPPORT_HEADING_KEYS),
        None,
    )
    first_support_key = (
        h2_keys[first_support_index] if first_support_index is not None else None
    )
    if first_support_index is None:
        before_support_keys = h2_keys
        after_support_keys: list[str] = []
    else:
        before_support_keys = h2_keys[:first_support_index]
        after_support_keys = h2_keys[first_support_index + 1 :]

    duplicate_section_count = _duplicate_known_key_count(h2_keys)
    missing_core_sections = [
        key for key in REQUIRED_CORE_KEYS if key not in before_support_keys
    ]
    core_sections_after_support = [
        key for key in after_support_keys if key in CORE_HEADING_KEYS
    ]

    failure_reasons: list[str] = []
    if duplicate_section_count:
        failure_reasons.append("duplicate_sections")
    if missing_core_sections:
        failure_reasons.append("missing_core_sections")
    if core_sections_after_support:
        failure_reasons.append("core_sections_after_support")

    return WriterQualityPreflightResult(
        passed=not failure_reasons,
        failure_reasons=failure_reasons,
        duplicate_section_count=duplicate_section_count,
        missing_core_sections=missing_core_sections,
        core_sections_after_support=core_sections_after_support,
        first_support_key=first_support_key,
        h2_keys=h2_keys,
    )


def _duplicate_known_key_count(h2_keys: list[str]) -> int:
    counts: dict[str, int] = {}
    for key in h2_keys:
        counts[key] = counts.get(key, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)
