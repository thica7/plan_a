from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from packages.identity.source_resolver import (
    SOURCE_TOKEN_RE,
    source_token_match_value,
    source_tokens,
)
from packages.schema.api_dto import RunDetail

_INTERNAL_TERMS = (
    "Segment Evidence Pack",
    "Writer Evidence Pack",
    "Writer Report Brief",
    "Writer Repair Context",
    "report_brief",
    "writer_constraints",
    "source_registry",
    "allowed_source_ids",
    "represented_by",
)
_GAP_MARKERS = (
    "evidence gap",
    "no cited swot",
    "no cited item",
    "no cited user-review",
    "\u8bc1\u636e\u7f3a\u53e3",
    "\u5c1a\u65e0\u53ef\u5f15\u7528",
)


@dataclass(frozen=True)
class ReportSanitizer:
    label_aliases: Callable[..., Iterable[str]]
    heading_matches: Callable[[str, str], bool]
    localize_heading: Callable[[RunDetail, str], str]

    def sanitize_report_hygiene(self, detail: RunDetail, markdown: str) -> str:
        lines = markdown.splitlines()
        sanitized_lines: list[str] = []
        evidence_appendix_aliases = list(self.label_aliases("evidence_appendix"))
        in_evidence_appendix = False
        for index, line in enumerate(lines):
            if self.line_contains_writer_internal_terms(line):
                continue
            sanitized = self.localize_heading(detail, line)
            stripped = sanitized.strip()
            h2_match = re.match(r"^\s*##\s+(.+?)\s*#*\s*$", stripped)
            if h2_match is not None:
                in_evidence_appendix = any(
                    self.heading_matches(h2_match.group(1), alias)
                    for alias in evidence_appendix_aliases
                )
            if stripped.startswith("#"):
                sanitized = SOURCE_TOKEN_RE.sub("", sanitized).rstrip()
            elif self.table_header_line_has_citation(lines, index):
                sanitized = SOURCE_TOKEN_RE.sub("", sanitized).rstrip()
            elif in_evidence_appendix and stripped.startswith("-"):
                sanitized = SOURCE_TOKEN_RE.sub("", sanitized).rstrip()
            sanitized_lines.append(sanitized)
        return "\n".join(sanitized_lines).strip()

    @staticmethod
    def line_contains_writer_internal_terms(line: str) -> bool:
        return any(term in line for term in _INTERNAL_TERMS)

    @staticmethod
    def table_header_line_has_citation(lines: Sequence[str], index: int) -> bool:
        line = lines[index].strip()
        if not line.startswith("|") or "[source:" not in line.casefold():
            return False
        return CitationGuard.report_table_header_line(lines, index)


@dataclass(frozen=True)
class CitationGuard:
    source_ids_for_line: Callable[[RunDetail, str], list[str]]
    claim_line_tokens: Sequence[str]
    cjk_text_re: re.Pattern[str]

    @staticmethod
    def extract_cited_source_ids(report_md: str) -> set[str]:
        cited = set(source_tokens(report_md))
        for pattern in (
            r"(?<![-\w])source(?:\s+id)?\s*:\s*([A-Za-z0-9_.:-]+)",
            r"\[source(?:\s+id)?\s+([A-Za-z0-9_.:-]+)\]",
        ):
            cited.update(re.findall(pattern, report_md, flags=re.IGNORECASE))
        return cited

    def repair_report_source_tokens(self, detail: RunDetail, markdown: str) -> str:
        valid_source_ids = {source.id for source in detail.raw_sources}
        if not valid_source_ids:
            return markdown

        repaired_lines: list[str] = []
        for line in markdown.splitlines():
            repaired_lines.append(
                SOURCE_TOKEN_RE.sub(
                    lambda match, current_line=line: self.repair_report_source_token(
                        detail,
                        current_line,
                        source_token_match_value(match),
                        valid_source_ids,
                    ),
                    line,
                )
            )
        return "\n".join(repaired_lines)

    def repair_report_source_token(
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
        replacement_ids = dimension_match or self.source_ids_for_line(detail, line)
        if not replacement_ids:
            return f"[source:{token}]"
        return f"[source:{replacement_ids[0]}]"

    def ensure_report_claim_citations(self, detail: RunDetail, markdown: str) -> str:
        lines = markdown.splitlines()
        hardened_lines: list[str] = []
        for index, line in enumerate(lines):
            if not self.report_line_needs_citation(line):
                hardened_lines.append(line)
                continue
            if self.report_table_header_line(lines, index):
                hardened_lines.append(line)
                continue
            if self.extract_cited_source_ids(line):
                hardened_lines.append(line)
                continue
            source_ids = self.source_ids_for_line(detail, line)
            if not source_ids:
                hardened_lines.append(line)
                continue
            citation_text = " ".join(
                f"[source:{source_id}]" for source_id in source_ids[:2]
            )
            stripped = line.rstrip()
            if stripped.startswith("|") and stripped.endswith("|"):
                hardened_lines.append(f"{stripped[:-1].rstrip()} {citation_text} |")
            else:
                hardened_lines.append(f"{stripped} {citation_text}")
        return "\n".join(hardened_lines)

    @staticmethod
    def report_table_header_line(lines: Sequence[str], index: int) -> bool:
        line = lines[index].strip()
        if not line.startswith("|"):
            return False
        next_line = ""
        for candidate in lines[index + 1 :]:
            if candidate.strip():
                next_line = candidate.strip()
                break
        return (
            bool(next_line)
            and re.fullmatch(r"\|?[\s|\-:]+\|?", next_line) is not None
        )

    def report_line_needs_citation(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.startswith("#"):
            return False
        if set(stripped) <= {"-", " ", "|", ":"}:
            return False
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", stripped):
            return False
        if self.report_line_is_explicit_gap_statement(stripped):
            return False
        if self.cjk_text_re.search(stripped):
            normalized = stripped.casefold()
            if len(stripped) >= 12 and any(
                token in normalized for token in self.claim_line_tokens
            ):
                return True
        return bool(re.search(r"[A-Za-z0-9]", stripped)) and len(stripped) >= 24

    @staticmethod
    def report_line_is_explicit_gap_statement(line: str) -> bool:
        normalized = line.casefold()
        return any(marker in normalized for marker in _GAP_MARKERS)