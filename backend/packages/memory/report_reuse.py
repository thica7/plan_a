"""Bounded, advisory history and original URLs; never current report evidence."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import ValidationError

from packages.enterprise.store import EnterpriseStore
from packages.identity import compute_competitor_id, normalize_url
from packages.research.models import SourceCandidate
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import ClaimRecord, EvidenceRecord, ReportVersionRecord
from packages.schema.models import (
    AnalysisPlan,
    HistoricalReportSelection,
    HistoricalReportSkip,
    HistoricalSourceLineage,
    ReportReuseContext,
)

MAX_REPORTS = 3
MAX_FACTS = 6
MAX_BRANCH_URLS = 2
MAX_CONTEXT_CHARS = 12_000
MAX_LINEAGES = 12
MAX_SKIPS = 24
PRICE_VERSION_TTL_DAYS = 7
FACT_TTL_DAYS = 30


def _key(value: str) -> str:
    # Product numbers are identity, so retain every digit and decimal component.
    return re.sub(r"[^\w.]+", "", value.casefold())


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _safe_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"https", "http"} or not host or parsed.username or parsed.password:
        return False
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host


def _relevance(current: AnalysisPlan, old: AnalysisPlan) -> str:
    current_product, old_product = current.target_product, old.target_product
    if current_product and old_product:
        for field in ("market", "category"):
            left, right = getattr(current_product, field), getattr(old_product, field)
            if left and right and _key(left) != _key(right):
                return f"{field}_conflict"
        left, right = current_product.name, old_product.name
        if re.sub(r"[\d.]+", "", _key(left)) == re.sub(r"[\d.]+", "", _key(right)) and _key(
            left
        ) != _key(right):
            return "version_conflict"
    names = {_key(name) for name in current.competitors}
    old_names = {_key(name) for name in old.competitors}
    if current_product:
        names.add(_key(current_product.name))
    if old_product:
        old_names.add(_key(old_product.name))
    shared = names & old_names
    if not shared:
        return "product_identity_missing"
    # Cross-project recall requires product identity plus an explicit category or
    # the same scoped topic. A generic topic on its own is never sufficient.
    same_category = bool(
        current_product
        and old_product
        and current_product.category
        and old_product.category
        and _key(current_product.category) == _key(old_product.category)
    )
    if not same_category and _key(current.topic) != _key(old.topic):
        return "category_unconfirmed"
    if not set(current.dimensions) & set(old.dimensions):
        return "dimension_mismatch"
    return "related_product_scope"


def build_report_reuse_context(
    store: EnterpriseStore | None,
    *,
    workspace_id: str,
    project_id: str,
    plan: AnalysisPlan,
    historical_runs: Iterable[RunDetail] = (),
    now: datetime | None = None,
) -> ReportReuseContext:
    context = ReportReuseContext()
    now = _utc(now or datetime.utcnow())
    current_names = [*plan.competitors]
    if plan.target_product is not None:
        current_names.append(plan.target_product.name)
    current_product_keys = {_key(name) for name in current_names}
    current_product_bases = {re.sub(r"[\d.]+", "", key) for key in current_product_keys}
    runs = {detail.id: detail for detail in historical_runs if detail.workspace_id == workspace_id}
    # Each bundle keeps evidence and claims in its own validated project scope.
    bundles: dict[
        str, tuple[ReportVersionRecord, list[EvidenceRecord], list[ClaimRecord], dict[str, str]]
    ] = {}

    def skip(report_id: str, reason: str, evidence_id: str | None = None) -> None:
        item = HistoricalReportSkip(report_id=report_id, evidence_id=evidence_id, reason=reason)
        if len(context.skipped) < MAX_SKIPS:
            context.skipped.append(item)
            if len(context.model_dump_json()) > MAX_CONTEXT_CHARS:
                context.skipped.pop()

    if store is not None:
        current_project = store.get_project(project_id)
        if current_project is not None and current_project.workspace_id != workspace_id:
            skip("", "scope_mismatch")
            return context
        for project in store.list_projects(workspace_id=workspace_id):
            if project.workspace_id != workspace_id:
                continue
            names = {
                item.id: item.name
                for item in store.list_competitors(workspace_id=workspace_id, project_id=project.id)
                if item.workspace_id == workspace_id
            }
            evidence = store.list_evidence(project_id=project.id)
            claims = store.list_claims(project_id=project.id)
            for report in store.list_report_versions(project_id=project.id):
                if report.workspace_id != workspace_id or report.project_id != project.id:
                    skip(report.id, "scope_mismatch")
                    continue
                bundles[report.id] = (report, evidence, claims, names)

    # Read-only journal fallback. No replay/reprojection or QA state changes.
    for detail in runs.values():
        projection = detail.enterprise_projection
        if projection is None:
            continue
        report = projection.report_version
        if (
            projection.workspace_id != workspace_id
            or projection.project_id != detail.project_id
            or projection.run_id != detail.id
            or report.workspace_id != workspace_id
            or report.project_id != projection.project_id
            or report.run_id != detail.id
        ):
            skip(report.id, "scope_mismatch")
            continue
        persisted_names = [*detail.plan.competitors]
        if detail.plan.target_product:
            persisted_names.append(detail.plan.target_product.name)
        names = {compute_competitor_id(workspace_id, name): name for name in persisted_names}
        bundles.setdefault(
            report.id, (report, projection.evidence_records, projection.claim_records, names)
        )

    seen_runs: set[str] = set()
    seen_urls: set[tuple[str, str, str]] = set()
    facts_count = 0
    for report, evidence, claims, names in sorted(
        bundles.values(),
        key=lambda item: (_utc(item[0].created_at), item[0].version_number, item[0].id),
        reverse=True,
    ):
        group = report.run_id or report.id
        if group in seen_runs:
            skip(report.id, "superseded_report")
            continue
        seen_runs.add(group)
        if len(context.selected) >= MAX_REPORTS:
            skip(report.id, "report_limit")
            continue
        detail = runs.get(report.run_id or "")
        if detail is not None and detail.project_id != report.project_id:
            skip(report.id, "scope_mismatch")
            continue
        mode = report.quality_metadata.get("execution_mode")
        if mode is None and detail is not None:
            mode = detail.execution_mode
        if mode != "real" or (detail is not None and detail.execution_mode != "real"):
            skip(report.id, "not_explicit_real")
            continue
        if report.status == "rejected":
            skip(report.id, "rejected")
            continue
        old_plan_data = report.quality_metadata.get("analysis_plan")
        try:
            old_plan = (
                AnalysisPlan.model_validate(old_plan_data)
                if isinstance(old_plan_data, dict)
                else (detail.plan if detail else None)
            )
        except ValidationError:
            old_plan = None
        if old_plan is None:
            skip(report.id, "product_identity_missing")
            continue
        reason = _relevance(plan, old_plan)
        if reason != "related_product_scope":
            skip(report.id, reason)
            continue
        selection = HistoricalReportSelection(
            report_id=report.id, run_id=report.run_id, project_id=report.project_id, reason=reason
        )
        links: list[HistoricalSourceLineage] = []
        fresh_ids: set[str] = set()
        for item in evidence:
            if item.id not in report.evidence_ids:
                continue
            if item.workspace_id != workspace_id or item.project_id != report.project_id:
                skip(report.id, "scope_mismatch", item.id)
                continue
            competitor = names.get(item.competitor_id)
            if not competitor:
                skip(report.id, "product_identity_missing", item.id)
                continue
            if _key(competitor) not in current_product_keys:
                reason = (
                    "version_conflict"
                    if re.sub(r"[\d.]+", "", _key(competitor)) in current_product_bases
                    else "product_identity_missing"
                )
                skip(report.id, reason, item.id)
                continue
            if "simulated" in item.source_type.casefold() or item.metadata.get(
                "execution_mode"
            ) in {"demo", "simulated"}:
                skip(report.id, "simulated_source", item.id)
                continue
            source_type = item.source_type.casefold()
            if source_type == "llm_public_knowledge" or "demo" in source_type:
                skip(report.id, "non_fetched_source", item.id)
                continue
            if item.quality_label == "rejected":
                skip(report.id, "rejected", item.id)
                continue
            url = str(item.url) if item.url else ""
            if not url or not _safe_url(url):
                skip(report.id, "missing_url" if not url else "unsafe_url", item.id)
                continue
            key = (_key(competitor), item.dimension, normalize_url(url))
            if key in seen_urls:
                skip(report.id, "duplicate_url", item.id)
                continue
            ttl = (
                PRICE_VERSION_TTL_DAYS
                if any(
                    word in item.dimension.casefold()
                    for word in ("pric", "version", "版本", "价格")
                )
                else FACT_TTL_DAYS
            )
            age = (now - _utc(item.captured_at)).total_seconds() / 86400
            reason = (
                "unreviewed"
                if item.quality_label == "unreviewed"
                else "stale"
                if item.quality_label == "stale"
                else "expired"
                if age > ttl
                else "future_capture"
                if age < 0
                else "current_fetch_required"
            )
            if reason == "current_fetch_required" and (
                source_type != "webpage_verified"
                or ("execution_mode" in item.metadata and item.metadata["execution_mode"] != "real")
            ):
                reason = "provenance_unknown"
            if reason != "current_fetch_required":
                skip(report.id, reason, item.id)
            link = HistoricalSourceLineage(
                report_id=report.id,
                evidence_id=item.id,
                competitor=competitor,
                dimension=item.dimension,
                url=url,
                title=item.title[:160],
                captured_at=item.captured_at,
                source_published_at=_date_metadata(item, "source_published_at"),
                source_updated_at=_date_metadata(item, "source_updated_at"),
                freshness="fresh"
                if reason == "current_fetch_required"
                else "unreviewed"
                if reason in {"unreviewed", "provenance_unknown"}
                else "stale",
                reason=reason,
            )
            if len(context.refresh_required) + len(links) >= MAX_LINEAGES:
                skip(report.id, "context_limit", item.id)
                continue
            links.append(link)
            if reason == "current_fetch_required":
                fresh_ids.add(item.id)
        if not links:
            continue
        for claim in claims:
            if claim.id not in report.claim_ids:
                continue
            if claim.workspace_id != workspace_id or claim.project_id != report.project_id:
                skip(report.id, "scope_mismatch")
                continue
            if (
                claim.status != "accepted"
                or not set(claim.evidence_ids).issubset(fresh_ids)
                or facts_count >= MAX_FACTS
            ):
                continue
            if any(
                word in claim.claim_type.casefold()
                for word in (
                    "pric",
                    "version",
                    "版本",
                    "价格",
                )
            ) and any(
                (now - _utc(item.captured_at)).total_seconds() / 86400 > PRICE_VERSION_TTL_DAYS
                for item in evidence
                if item.id in claim.evidence_ids
            ):
                skip(report.id, "expired", claim.evidence_ids[0])
                continue
            fact = re.sub(
                r"\[\s*(?:source|来源)\s*[:：][^\]]*\]", "", claim.claim_text, flags=re.I
            ).strip()[:240]
            if fact:
                selection.advisory_facts.append(fact)
                facts_count += 1
        context.selected.append(selection)
        context.refresh_required.extend(links)
        if len(context.model_dump_json()) > MAX_CONTEXT_CHARS:
            context.selected.pop()
            del context.refresh_required[-len(links) :]
            facts_count -= len(selection.advisory_facts)
            skip(report.id, "context_limit")
        else:
            seen_urls.update(
                (_key(link.competitor), link.dimension, normalize_url(link.url)) for link in links
            )
    return context


def _date_metadata(item: EvidenceRecord, key: str) -> str | None:
    value = item.metadata.get(key)
    return str(value) if isinstance(value, (str, datetime)) else None


def report_reuse_candidates(
    plan: AnalysisPlan, competitor: str, dimension: str
) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    seen: set[str] = set()
    for link in plan.report_reuse_context.refresh_required:
        if _key(link.competitor) != _key(competitor) or link.dimension != dimension:
            continue
        url_key = normalize_url(link.url)
        if url_key in seen or not _safe_url(link.url):
            continue
        seen.add(url_key)
        candidates.append(
            SourceCandidate(
                title=link.title,
                url=link.url,
                origin="manual",
                competitor=competitor,
                dimension=dimension,
                rank=len(candidates),
                confidence=0.6,
                reason="Historical URL requires a current fetch and evidence admission.",
                date=link.source_published_at,
                last_updated=link.source_updated_at,
                metadata={
                    "history_report_id": link.report_id,
                    "history_evidence_id": link.evidence_id,
                    "history_captured_at": link.captured_at.isoformat(),
                    "history_source_published_at": link.source_published_at,
                    "history_source_updated_at": link.source_updated_at,
                    "history_refresh_reason": link.reason,
                },
            )
        )
        if len(candidates) >= MAX_BRANCH_URLS:
            break
    return candidates
