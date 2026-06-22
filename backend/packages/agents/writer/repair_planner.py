from __future__ import annotations

from dataclasses import dataclass

from packages.agents.writer.repair import (
    WriterRepairPlan,
    apply_line_repair,
    build_writer_repair_plan,
    replace_markdown_section,
    report_regression_problem,
    section_regression_problem,
)
from packages.schema.api_dto import RunDetail
from packages.schema.models import QCIssue


@dataclass(frozen=True)
class WriterRepairPlanner:
    def plan(
        self,
        detail: RunDetail,
        issues: list[QCIssue],
        *,
        upstream_data_changed: bool,
    ) -> WriterRepairPlan:
        return build_writer_repair_plan(
            detail,
            issues,
            upstream_data_changed=upstream_data_changed,
        )

    def apply_line_repair(
        self,
        markdown: str,
        issues: list[QCIssue],
    ) -> str:
        return apply_line_repair(markdown, issues)

    def replace_section(
        self,
        markdown: str,
        target_section: str,
        output_language: str,
        replacement_markdown: str,
    ) -> str:
        return replace_markdown_section(
            markdown,
            target_section,
            output_language,
            replacement_markdown,
        )

    def section_regression_problem(
        self,
        previous: RunDetail,
        candidate: RunDetail,
        *,
        protected_sections: list[str],
    ) -> str | None:
        return section_regression_problem(
            previous,
            candidate,
            protected_sections=protected_sections,
        )

    def report_regression_problem(
        self,
        previous: RunDetail,
        candidate: RunDetail,
        *,
        protected_sections: list[str],
    ) -> str | None:
        return report_regression_problem(
            previous,
            candidate,
            protected_sections=protected_sections,
        )
