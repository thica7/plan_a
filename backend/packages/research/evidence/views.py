"""Select immutable, source-paired evidence within a stage's UTF-8 budget."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from packages.research.evidence.snapshot import _identity, _verify
from packages.research.evidence.capabilities import capability_keys
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
    "analyst_qa",
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
    snippet = "\n".join(dict.fromkeys(fact.quote for fact in facts if fact.quote)) or source.snippet
    payload["snippet"] = snippet
    return source.model_copy(update={"snippet": snippet, "payload_json": canonical_json(payload)})


def _build_view(
    snapshot: RunEvidenceSnapshot,
    *,
    agent: str,
    competitor: str | None,
    dimension: str | None,
    requested_ids: tuple[str, ...] | None,
    requested_fact_ids: tuple[str, ...] | None,
    max_bytes: int,
    sources: tuple[EvidenceSource, ...],
    facts: tuple[EvidenceFact, ...],
    conflicts: tuple[EvidenceConflict, ...],
    gaps: tuple[EvidenceGap, ...],
) -> StageEvidenceView:
    products = tuple(sorted(set(snapshot.competitors) | {fact.competitor for fact in snapshot.facts} |
                            {name for source in snapshot.sources
                             for name in (source.competitor, *source.covered_competitors)}))
    dependencies = {
        "run_id": snapshot.run_id,
        "workspace_id": snapshot.workspace_id,
        "project_id": snapshot.project_id,
        "agent": agent,
        "competitor": competitor.strip().casefold() if competitor else None,
        "dimension": dimension.strip().casefold() if dimension else None,
        "comparison_products": products,
        "requested_source_ids": requested_ids,
        "max_bytes": max_bytes,
        "sources": [source.model_dump(mode="json") for source in sources],
        "facts": [fact.model_dump(mode="json") for fact in facts],
        "conflicts": [conflict.model_dump(mode="json") for conflict in conflicts],
        "gaps": [gap.model_dump(mode="json") for gap in gaps],
    }
    if requested_fact_ids is not None:
        dependencies['requested_fact_ids'] = requested_fact_ids
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
        comparison_products=products,
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
    fact_ids: Iterable[str] | None = None,
    max_bytes: int = 8192,
) -> StageEvidenceView:
    _verify(snapshot)
    if agent not in _AGENTS:
        raise ValueError("unsupported evidence agent")
    if max_bytes < 1:
        raise ValueError("evidence view byte budget must be positive")
    requested_ids = tuple(sorted(set(source_ids))) if source_ids is not None else None
    requested_fact_ids = tuple(dict.fromkeys(fact_ids)) if fact_ids is not None else None
    requested_fact_rank = {fact_id: index for index, fact_id in enumerate(requested_fact_ids or ())}
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
    def observation_key(fact):
        return (fact.source_id, fact.competitor, fact.dimension, fact.unit,
                fact.market, fact.qualifiers_json, fact.quote, fact.evidence_item_ids)

    requested_observations = ({observation_key(fact) for fact in snapshot.facts
                               if fact.id in requested_fact_ids}
                              if requested_fact_ids is not None else None)
    if requested_fact_ids is not None:
        known = {fact.id for fact in snapshot.facts}
        gaps.extend(_gap('fact_not_in_snapshot', fact_id=fact_id, competitor=competitor, dimension=dimension)
                    for fact_id in requested_fact_ids if fact_id not in known)
    facts = {}
    for fact in snapshot.facts:
        if (
            fact.source_id not in allowed_sources
            or (requested_observations is not None and observation_key(fact) not in requested_observations)
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
        else:
            gaps.append(
                _gap(
                    "conflict_context_incomplete",
                    fact_id=min(present),
                    competitor=competitor,
                    dimension=dimension,
                )
            )
    # Keep an observation's value, support status and complete condition text
    # together. Conflict components also carry each participant's full observation.
    observations = defaultdict(set)
    for fact in facts.values():
        key = (fact.source_id, fact.competitor, fact.dimension, fact.unit,
               fact.market, fact.qualifiers_json, fact.quote, fact.evidence_item_ids)
        observations[key].add(fact.id)
    for observation in observations.values():
        overlapping = [group for group in groups if group & observation]
        merged = set(observation).union(*overlapping)
        groups = [group for group in groups if not group & merged]
        groups.append(merged)
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
    # A small first observation from every product/dimension precedes another
    # observation from an already represented branch. Names never consume a quota.
    branches = defaultdict(list)
    for group in groups:
        branch = min((facts[item].competitor, facts[item].dimension) for item in group)
        branches[branch].append(group)
    capability_products = defaultdict(set)
    fact_capabilities = {}
    for fact in snapshot.facts:
        if fact.field == 'evidence_terms':
            from packages.research.evidence.operations import operation_observations
            keys = (*capability_keys(fact, snapshot.competitors), *('operation.' + row['operation'] for row in operation_observations(fact, snapshot.competitors)))
            fact_capabilities[fact.id] = keys if fact.id in facts and facts[fact.id].status == 'supported' else ()
            for key in keys:
                capability_products[key].add(fact.competitor)

    def coverage_priority(group):
        axes = {'shared_editing', 'comments', 'permissions', 'operation.read', 'operation.comment',
                'operation.edit', 'operation.create', 'operation.share', 'operation.manage_access'}
        branch = min((facts[item].competitor, facts[item].dimension) for item in group)
        seen = {key for item in selected_facts if (facts[item].competitor, facts[item].dimension) == branch
                and facts[item].field == 'evidence_terms'
                for key in fact_capabilities.get(item, ())}
        keys = {key for item in group if facts[item].field == 'evidence_terms'
                for key in fact_capabilities.get(item, ())}
        return -100 * len((keys & axes) - seen) - max(
            (len(capability_products[key]) for key in keys), default=0)

    def requested_priority(group):
        return min(requested_fact_rank.get(item, len(requested_fact_rank)) for item in group)

    queues = {branch: deque(sorted(items, key=lambda group: (
        any(facts[item].status != "supported" for item in group),
        sum(len(facts[item].value_json.encode("utf-8")) + len(facts[item].quote.encode("utf-8")) for item in group),
        min(group),
    ))) for branch, items in branches.items()}
    # Reserve branch-specific omission records. They describe view capacity,
    # not collection quality, and do not require extra retrieval.
    budget_gaps = tuple(_gap("context_budget_exceeded", competitor=product, dimension=dim)
                        for product, dim in sorted(branches))
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
        omitted_branches = {(facts[item].competitor, facts[item].dimension)
                            for item in facts.keys() - fact_selection}
        scoped_gaps = tuple(gap for gap in budget_gaps
                            if (gap.competitor, gap.dimension) in omitted_branches)
        chosen_gaps = tuple(sorted((*gap_records, *scoped_gaps,
                                   *((budget_gap,) if extra_gap else ())), key=lambda gap: gap.id))
        return _build_view(
            snapshot,
            agent=agent,
            competitor=competitor,
            dimension=dimension,
            requested_ids=requested_ids,
            requested_fact_ids=requested_fact_ids,
            max_bytes=max_bytes,
            sources=projected,
            facts=picked,
            conflicts=chosen_conflicts,
            gaps=chosen_gaps,
        )

    # Reserve a complete diagnostic record before filling the evidence portion.
    view = build(set(), set(), True)
    while any(queues.values()):
        represented_products = {facts[item].competitor for item in selected_facts}
        represented_branches = {(facts[item].competitor, facts[item].dimension) for item in selected_facts}
        # Try an unrepresented product/branch's alternative sources before
        # allocating more observations to an already represented branch.
        branch = min((key for key, queue in queues.items() if queue), key=lambda key: (
            min(requested_priority(group) for group in queues[key]),
            key[0] in represented_products, key in represented_branches,
            len(branches[key]) - len(queues[key]), key,
        ))
        candidates = []
        reserve_coverage = len(branches) > 1 and branch not in represented_branches
        for group in tuple(queues[branch]):
            candidate_facts = selected_facts | group
            candidate_sources = selected_sources | {facts[fact_id].source_id for fact_id in group}
            try:
                candidate = build(candidate_facts, candidate_sources, True)
            except ValueError:
                has_budget_gap = True
                queues[branch].remove(group)
                continue
            candidates.append((any(facts[item].status != "supported" for item in group),
                               candidate.estimated_bytes if reserve_coverage else 0,
                               coverage_priority(group), -min(facts[item].confidence for item in group),
                               candidate.estimated_bytes, min(group), group,
                               candidate_facts, candidate_sources, candidate))
        if candidates:
            # Measure the whole source-paired prompt: a shorter quote can have
            # a much larger page header than another equally valid observation.
            _, _, _, _, _, _, group, selected_facts, selected_sources, view = min(
                candidates, key=lambda item: (requested_priority(item[6]), *item[:6])
            )
            queues[branch].remove(group)
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
