from __future__ import annotations

from difflib import SequenceMatcher

from packages.schema.enterprise import ReportDiffLine, ReportVersionDiff, ReportVersionRecord


def build_report_version_diff(
    target_version: ReportVersionRecord,
    *,
    base_version: ReportVersionRecord | None = None,
) -> ReportVersionDiff:
    """Build a compact line diff for report history review."""
    base_lines = base_version.report_md.splitlines() if base_version else []
    target_lines = target_version.report_md.splitlines()
    matcher = SequenceMatcher(a=base_lines, b=target_lines, autojunk=False)
    lines: list[ReportDiffLine] = []

    for tag, base_start, base_end, target_start, target_end in matcher.get_opcodes():
        if tag == "equal":
            lines.extend(
                ReportDiffLine(kind="unchanged", text=line)
                for line in target_lines[target_start:target_end]
            )
        elif tag == "delete":
            lines.extend(
                ReportDiffLine(kind="removed", text=line)
                for line in base_lines[base_start:base_end]
            )
        elif tag == "insert":
            lines.extend(
                ReportDiffLine(kind="added", text=line)
                for line in target_lines[target_start:target_end]
            )
        elif tag == "replace":
            lines.extend(
                ReportDiffLine(kind="removed", text=line)
                for line in base_lines[base_start:base_end]
            )
            lines.extend(
                ReportDiffLine(kind="added", text=line)
                for line in target_lines[target_start:target_end]
            )

    return ReportVersionDiff(
        base_version=base_version,
        target_version=target_version,
        added_lines=sum(1 for line in lines if line.kind == "added"),
        removed_lines=sum(1 for line in lines if line.kind == "removed"),
        unchanged_lines=sum(1 for line in lines if line.kind == "unchanged"),
        lines=lines,
    )
