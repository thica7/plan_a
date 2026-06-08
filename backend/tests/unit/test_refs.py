from datetime import datetime, timedelta

from packages.refs import (
    CompetitorRef,
    CompetitorResolver,
    audit_relationship_resource_id,
    merge_ordered_refs,
    normalize_competitor_key,
    normalize_dimension_refs,
    select_report_version,
    sort_report_versions,
)
from packages.schema.enterprise import ReportVersionRecord


def test_competitor_resolver_maps_ids_names_and_aliases_to_canonical_id() -> None:
    resolver = CompetitorResolver(
        [
            CompetitorRef(
                id="competitor-cursor",
                name="Cursor",
                aliases=("cursor.sh", "Anysphere Cursor"),
            )
        ]
    )

    assert normalize_competitor_key("Anysphere Cursor") == "anysphere-cursor"
    assert resolver.resolve_id("Cursor") == "competitor-cursor"
    assert resolver.resolve_id("cursor.sh") == "competitor-cursor"
    assert resolver.resolve_id("Unknown Vendor") == "unknown-vendor"
    assert resolver.display_name("competitor-cursor") == "Cursor"


def test_dimension_refs_normalize_against_allowed_skill_names() -> None:
    assert normalize_dimension_refs(
        ["Pricing", "pricing", "Security & Trust", "unknown"],
        allowed=["pricing", "security_trust", "feature"],
        fallback=["feature"],
        require=["pricing", "feature"],
    ) == ["pricing", "security_trust", "feature"]


def test_report_resolver_sorts_latest_and_selects_published_when_requested() -> None:
    base = datetime(2026, 6, 1, 12, 0, 0)
    draft = _version("report-draft", 3, "draft", base + timedelta(minutes=3))
    published = _version(
        "report-published",
        2,
        "published",
        base + timedelta(minutes=2),
        published_at=base + timedelta(minutes=4),
    )
    approved = _version("report-approved", 1, "approved", base + timedelta(minutes=1))

    assert [item.id for item in sort_report_versions([approved, published, draft])] == [
        "report-draft",
        "report-published",
        "report-approved",
    ]
    assert select_report_version([approved, published, draft], role="published") == published


def test_audit_relationship_resource_id_is_stable_and_typed() -> None:
    first = audit_relationship_resource_id("project-competitor", "project-1", "competitor-1")
    second = audit_relationship_resource_id("project-competitor", "project-1", "competitor-1")

    assert first == second
    assert first.startswith("project-competitor-")


def test_merge_ordered_refs_preserves_first_seen_order() -> None:
    assert merge_ordered_refs(
        ["source-b", "source-a"],
        ["source-a", "", None, "source-c"],
    ) == ["source-b", "source-a", "source-c"]


def _version(
    version_id: str,
    version_number: int,
    status: str,
    created_at: datetime,
    *,
    published_at: datetime | None = None,
) -> ReportVersionRecord:
    return ReportVersionRecord(
        id=version_id,
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=version_number,
        topic_normalized="topic",
        competitor_layer="L1",
        competitor_set_hash="set",
        status=status,  # type: ignore[arg-type]
        created_at=created_at,
        published_at=published_at,
    )
