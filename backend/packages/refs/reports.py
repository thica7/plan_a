from __future__ import annotations

from typing import Literal

from packages.schema.enterprise import ReportVersionRecord

ReportVersionRole = Literal["latest", "published", "approved", "reviewable"]

_STATUS_RANK = {
    "published": 0,
    "approved": 1,
    "in_review": 2,
    "draft": 3,
    "rejected": 4,
    "archived": 5,
}


def sort_report_versions(
    versions: list[ReportVersionRecord],
    *,
    role: ReportVersionRole = "latest",
) -> list[ReportVersionRecord]:
    if role == "published":
        filtered = [item for item in versions if item.status == "published"]
    elif role == "approved":
        filtered = [item for item in versions if item.status in {"published", "approved"}]
    elif role == "reviewable":
        filtered = [
            item
            for item in versions
            if item.status in {"draft", "in_review", "approved", "published"}
        ]
    else:
        filtered = list(versions)
    return sorted(
        filtered,
        key=lambda item: (
            item.version_number,
            item.published_at or item.created_at,
            -_STATUS_RANK.get(item.status, 99),
        ),
        reverse=True,
    )


def select_report_version(
    versions: list[ReportVersionRecord],
    *,
    role: ReportVersionRole = "latest",
) -> ReportVersionRecord | None:
    sorted_versions = sort_report_versions(versions, role=role)
    return sorted_versions[0] if sorted_versions else None
