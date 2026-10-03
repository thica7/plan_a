"""Select immutable, source-paired evidence within a stage's UTF-8 budget."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from packages.research.evidence.snapshot import _identity, _verify
from packages.research.evidence.snapshot_models import (
    EvidenceConflict,
    EvidenceFact,
    EvidenceGap,
    EvidenceSource,
    RunEvidenceSnapshot,
    StageEvidenceView,
    canonical_json,
)

_AGENTS = {
    "planner",
    "collector",
    "collect_qa",
    "analyst",
    "comparator",
    "reflector",
    "writer",
    "qa",
}
_CRITICAL_DIMENSIONS = ("pric", "价格", "定价", "version", "版本")


def _matches(value: str | None, wanted: str | None) -> bool:
    return wanted is None or (value or "").strip().casefold() == wanted.strip().casefold()


def _gap(
    reason: str,
    *,
    source: EvidenceSource | None = None,
    source_id: str | None = None,
    fact_id: str | None = None,
    competitor: str | None = None,
    dimension: str | None = None,
) -> EvidenceGap:
    identity = [reason, source.id if source else source_id, fact_id, competitor, dimension]
    return EvidenceGap(
        id=_identity("evidence-view-gap", identity),
        reason=reason,
        source_id=source.id if source else source_id,
        fact_id=fact_id,
        document_id=source.document_id if source else None,
        competitor=source.competitor if source else competitor,
        dimension=source.dimension if source else dimension,
    )


def _qualification(source: EvidenceSource, now: datetime) -> tuple[str, ...]:
    if source.status != "active":
        return ("source_inactive",)
    problems = []
    if source.role == "historical_report":
        problems.append("historical_evidence_advisory")
    elif source.material_level in {"summary", "search_summary", "historical_report"}:
        problems.append("summary_evidence_advisory")
    observed = (
        source.last_verified_at
        or source.source_updated_at
        or source.source_published_at
        or source.source_fetched_at
    )
    if observed is None:
        return (*problems, "source_date_missing")
    observed = observed.replace(tzinfo=UTC) if observed.tzinfo is None else observed.astimezone(UTC)
    if observed > now:
        return (*problems, "future_source_date")
    days = 7 if any(term in source.dimension.casefold() for term in _CRITICAL_DIMENSIONS) else 30
    if observed < now - timedelta(days=days):
        problems.append("stale_evidence")
    return tuple(problems)


def _project_source(source: EvidenceSource, facts: tuple[EvidenceFact, ...]) -> EvidenceSource:
    """Compatibility projection exposes only the facts selected in this view."""
    payload = json.loads(source.payload_json)
    originals = payload["metadata"].get("normalized_fields", [])
    rows: dict[str, dict[str, object]] = {}
    for fact in facts:
        kind = next(
            (
                row.get("kind")
                for row in originals
                if row.get("competitor") == fact.competitor
                and fact.field in row
                and canonical_json(row[fact.field]) == fact.value_json
            ),
            "",
        )
        quote_key = "source_quote" if kind == "pricing" else "evidence_quote"
        row_key = canonical_json(
            [
                kind,
                fact.competitor,
                fact.dimension,
                fact.unit,
                fact.market,
                fact.quote,
                fact.evidence_item_ids,
                fact.qualifiers_json,
                fact.confidence,
            ]
        )
        row = rows.setdefault(
            row_key,
            {
                "kind": kind,
                "competitor": fact.competitor,
                "dimension": fact.dimension,
                "confidence": fact.confidence,
                "evidence_item_ids": list(fact.evidence_item_ids),
                quote_key: fact.quote,
                "source_url": source.url,
                "unit": fact.unit,
                "market": fact.market,
                "qualifiers": fact.qualifiers,
            },
        )
        row[fact.field] = fact.value
    payload["metadata"]["normalized_fields"] = [rows[key] for key in sorted(rows)]
    return source.model_copy(update={"payload_json": canonical_json(payload)})


def _build_view(
    snapshot: RunEvidenceSnapshot,
    *,
    agent: str,
    competitor: str | None,
    dimension: str | None,
    requested_ids: tuple[str, ...] | None,
    max_bytes: int,
    sources: tuple[EvidenceSource, ...],
    facts: tuple[EvidenceFact, ...],
    conflicts: tuple[EvidenceConflict, ...],
    gaps: tuple[EvidenceGap, ...],
) -> StageEvidenceView:
    dependencies = {
        "run_id": snapshot.run_id,
        "workspace_id": snapshot.workspace_id,
        "project_id": snapshot.project_id,
        "agent": agent,
        "competitor": competitor.strip().casefold() if competitor else None,
        "dimension": dimension.strip().casefold() if dimension else None,
        "requested_source_ids": requested_ids,
        "max_bytes": max_bytes,
        "sources": [source.model_dump(mode="json") for source in sources],
        "facts": [fact.model_dump(mode="json") for fact in facts],
        "conflicts": [conflict.model_dump(mode="json") for conflict in conflicts],
        "gaps": [gap.model_dump(mode="json") for gap in gaps],
    }
    dependency_hash = hashlib.sha256(canonical_json(dependencies).encode("utf-8")).hexdigest()
    view = StageEvidenceView(
        agent=agent,
        run_id=snapshot.run_id,
        workspace_id=snapshot.workspace_id,
        project_id=snapshot.project_id,
        snapshot_id=snapshot.id,
        snapshot_version=snapshot.version,
        content_hash=snapshot.content_hash,
        competitor=competitor,
        dimension=dimension,
        sources=sources,
        source_ids=tuple(source.id for source in sources),
        facts=facts,
        fact_ids=tuple(fact.id for fact in facts),
        conflicts=conflicts,
        gaps=gaps,
        dependency_hash=dependency_hash,
        max_bytes=max_bytes,
    )
    # The estimate fields themselves consume JSON bytes; converge their digit lengths.
    for _ in range(8):
        actual = len(view.to_prompt_json().encode("utf-8"))
        if view.estimated_bytes == actual and view.estimated_tokens == actual + 256:
            return view
        view = view.model_copy(update={"estimated_bytes": actual, "estimated_tokens": actual + 256})
    raise ValueError("evidence view byte budget estimate did not converge")


def select_evidence_view(
    snapshot: RunEvidenceSnapshot,
    *,
    agent: str,
    competitor: str | None = None,
    dimension: str | None = None,
    source_ids: Iterable[str] | None = None,
    max_bytes: int = 8192,
) -> StageEvidenceView:
    _verify(snapshot)
    if agent not in _AGENTS:
        raise ValueError("unsupported evidence agent")
    if max_bytes < 1:
        raise ValueError("evidence view byte budget must be positive")
    requested_ids = tuple(sorted(set(source_ids))) if source_ids is not None else None
    allowed_sources = {
        source.id: source
        for source in snapshot.sources
        if (requested_ids is None or source.id in requested_ids)
        and _matches(source.dimension, dimension)
        and (
            competitor is None
            or any(
                _matches(name, competitor)
                for name in (source.competitor, *source.covered_competitors)
            )
        )
    }
    gaps = [
        gap
        for gap in snapshot.gaps
        if _matches(gap.competitor, competitor)
        and _matches(gap.dimension, dimension)
        and (requested_ids is None or gap.source_id in requested_ids)
    ]
    if requested_ids is not None:
        gaps.extend(
            _gap(
                "source_not_in_snapshot",
                source_id=source_id,
                competitor=competitor,
                dimension=dimension,
            )
            for source_id in requested_ids
            if source_id not in allowed_sources
        )
    problems = {}
    for source in allowed_sources.values():
        source_problems = _qualification(source, datetime.now(UTC))
        if source_problems:
            gaps.extend(_gap(problem, source=source) for problem in source_problems)
            problems[source.id] = source_problems
    facts = {}
    for fact in snapshot.facts:
        if (
            fact.source_id not in allowed_sources
            or not _matches(fact.competitor, competitor)
            or not _matches(fact.dimension, dimension)
        ):
            continue
        if "source_inactive" in problems.get(fact.source_id, ()):
            continue
        status = "signal" if fact.source_id in problems else fact.status
        facts[fact.id] = fact.model_copy(update={"status": status})
    conflicts = []
    groups: list[set[str]] = []
    grouped = set()
    for conflict in snapshot.conflicts:
        present = set(conflict.fact_ids) & facts.keys()
        if not present:
            continue
        for fact_id in present:
            if facts[fact_id].status == "supported":
                facts[fact_id] = facts[fact_id].model_copy(update={"status": "unknown"})
        if set(conflict.fact_ids) <= facts.keys():
            conflicts.append(conflict)
            groups.append(set(conflict.fact_ids))
            grouped.update(conflict.fact_ids)
        else:
            gaps.append(
                _gap(
                    "conflict_context_incomplete",
                    fact_id=min(present),
                    competitor=competitor,
                    dimension=dimension,
                )
            )
    groups.extend({fact_id} for fact_id in sorted(facts) if fact_id not in grouped)
    groups.sort(
        key=lambda group: min(
            (
                facts[fact_id].competitor,
                facts[fact_id].dimension,
                facts[fact_id].source_id,
                facts[fact_id].field,
                fact_id,
            )
            for fact_id in group
        )
    )
    gap_records = tuple(sorted(set(gaps), key=lambda gap: gap.id))
    budget_gap = _gap("context_budget_exceeded", competitor=competitor, dimension=dimension)
    selected_facts: set[str] = set()
    selected_sources: set[str] = set()
    has_budget_gap = False

    def build(fact_selection, source_selection, extra_gap):
        picked = tuple(
            sorted((facts[fact_id] for fact_id in fact_selection), key=lambda item: item.id)
        )
        projected = tuple(
            _project_source(
                allowed_sources[source_id],
                tuple(fact for fact in picked if fact.source_id == source_id),
            )
            for source_id in sorted(source_selection)
        )
        chosen_conflicts = tuple(
            conflict for conflict in conflicts if set(conflict.fact_ids) <= fact_selection
        )
        chosen_gaps = tuple(
            sorted((*gap_records, *((budget_gap,) if extra_gap else ())), key=lambda gap: gap.id)
        )
        return _build_view(
            snapshot,
            agent=agent,
            competitor=competitor,
            dimension=dimension,
            requested_ids=requested_ids,
            max_bytes=max_bytes,
            sources=projected,
            facts=picked,
            conflicts=chosen_conflicts,
            gaps=chosen_gaps,
        )

    # Reserve a complete diagnostic record before filling the evidence portion.
    view = build(set(), set(), True)
    for group in groups:
        candidate_facts = selected_facts | group
        candidate_sources = selected_sources | {facts[fact_id].source_id for fact_id in group}
        try:
            candidate = build(candidate_facts, candidate_sources, True)
        except ValueError:
            has_budget_gap = True
            continue
        selected_facts, selected_sources, view = candidate_facts, candidate_sources, candidate
    source_has_facts = {fact.source_id for fact in snapshot.facts}
    for source_id in sorted(allowed_sources):
        if source_id in source_has_facts or "source_inactive" in problems.get(source_id, ()):
            continue
        try:
            candidate = build(selected_facts, selected_sources | {source_id}, True)
        except ValueError:
            has_budget_gap = True
            continue
        selected_sources.add(source_id)
        view = candidate
    return view if has_budget_gap else build(selected_facts, selected_sources, False)
