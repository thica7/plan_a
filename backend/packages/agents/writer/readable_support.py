"""Restore readable Writer references only from complete dispatched originals."""

import re
from collections import Counter

from packages.research.evidence.snapshot_models import canonical_json


def single_reference_tasks(payload):
    """Present ranked refs as alternatives without merging facts or conditions.

    The complete catalog remains available. Verified exception pairs and all
    original publication checks still apply independently of these hints.
    """
    dangling_modal = re.compile(
        r"\b(?:can|could|may|might|must|should|would|shall|will)(?:\s+not)?$"
        r"|(?:可以|能够|必须|应当|应该)$", re.I,
    )
    calendar_may = re.compile(
        r"\b(?:in|during|since|until|through|before|after|by|from|for|on|this|next|last|"
        r"early|late|mid|is|was)\s+May$|\b[0-9]{1,2}\s+May$", re.I,
    )
    rejected, rows = set(), []
    for row in payload["evidence_view"]["facts"]:
        candidates = []
        for span in row.get("source_span_candidates", ()):
            tail = span["quote"].rstrip().rstrip(".!?;:。！？；：").rstrip()
            if dangling_modal.search(tail) and not calendar_may.search(tail):
                rejected.add(span["support_ref"])
            else:
                candidates.append(span)
        rows.append(dict(row, source_span_candidates=candidates))
    tasks = []
    for task in payload["generation_tasks"]:
        refs = [ref for ref in task["support_refs"] if ref not in rejected]
        projected = dict(task, support_refs=refs)
        if len(refs) > 1:
            projected["support_ref_options"] = [[ref] for ref in refs]
        tasks.append(projected)
    return dict(
        payload, generation_projection_version=3,
        evidence_view=dict(payload["evidence_view"], facts=rows), generation_tasks=tasks,
        generation_support_gaps=[task["task_id"] for task in tasks
                                 if task.get("state") == "planned" and not task["support_refs"]],
    )


def _resolve_span(item, spans):
    bare = {key: value for key, value in item.items() if key != "support_ref"}
    if set(bare) == {"quote"} and isinstance(bare["quote"], str):
        # The canonical generator deduplicates equal text, preferring quote,
        # then value members in source order. Reject any future ambiguity.
        matches = [span for span in spans if span["quote"] == bare["quote"]]
        return matches[0] if len(matches) == 1 else None
    if set(bare) == {"span_id", "source_path", "start", "end"}:
        return next((span for span in spans if bare == {key: span[key] for key in bare}), None)
    return None


def _catalogs(payload, source_facts, sent_fact_ids):
    from packages.research.evidence.operations import operation_binding, operation_observations
    from packages.research.evidence.source_spans import source_span_candidates

    view = payload.get("evidence_view") if isinstance(payload, dict) else None
    rows = view.get("facts") if isinstance(view, dict) else None
    if not isinstance(rows, list):
        return {}, {}
    rows = [row for row in rows if isinstance(row, dict)]
    counts = Counter(row["id"] for row in rows if isinstance(row.get("id"), str))
    # Count even malformed duplicates before validating bindings: a valid entry
    # must never make another entry with the same alias harmless.
    ref_counts = Counter()
    for row in rows:
        refs = row.get("operation_support_refs", ())
        if isinstance(refs, (list, tuple)):
            ref_counts.update(ref for ref in refs if isinstance(ref, str))
        choices = row.get("source_span_candidates", ())
        if isinstance(choices, (list, tuple)):
            ref_counts.update(
                item["support_ref"]
                for item in choices
                if isinstance(item, dict) and isinstance(item.get("support_ref"), str)
            )
    originals = {fact.id: fact for fact in source_facts if fact.id in sent_fact_ids}
    catalog, selected_spans = {}, {}
    for row in rows:
        if not isinstance(row.get("id"), str) or counts[row["id"]] != 1:
            continue
        original = originals.get(row["id"])
        if (
            original is None
            or row.get("competitor") != payload.get("segment_competitor")
            or row.get("dimension") != payload.get("dimension")
        ):
            continue
        expected = dict(
            id=original.id,
            source_id=original.source_id,
            competitor=original.competitor,
            dimension=original.dimension,
            field=original.field,
            quote=original.quote,
            value=original.value,
            qualifiers={
                key: value for key, value in original.qualifiers.items() if key != "operations"
            },
        )
        try:
            if any(key not in row for key in expected) or canonical_json(
                {key: row[key] for key in expected}
            ) != canonical_json(expected):
                continue
        except (TypeError, ValueError):
            continue
        operations = {
            item["observation_id"]: item
            for item in (operation_binding(op) for op in operation_observations(original))
        }
        spans = source_span_candidates(original)
        operation_rows = row.get("operation_observations", ())
        operation_refs = row.get("operation_support_refs", ())
        annotated_operations = (
            [
                dict(item, support_ref=ref)
                for item, ref in zip(operation_rows, operation_refs, strict=True)
                if isinstance(item, dict)
            ]
            if isinstance(operation_rows, list)
            and isinstance(operation_refs, list)
            and len(operation_rows) == len(operation_refs)
            else []
        )
        for kind, choices in (
            ("o", annotated_operations),
            ("s", row.get("source_span_candidates", ())),
        ):
            for item in choices if isinstance(choices, (list, tuple)) else ():
                if not isinstance(item, dict):
                    continue
                ref = item.get("support_ref")
                legacy = kind == "s" and "support_ref" not in item and "span_id" in item
                if not legacy and (
                    not isinstance(ref, str)
                    or not re.fullmatch(kind + r"[1-9][0-9]*", ref)
                    or ref_counts[ref] != 1
                ):
                    continue
                if kind == "o":
                    if not isinstance(item.get("observation_id"), str):
                        continue
                    bound = operations.get(item["observation_id"])
                    if bound != {key: value for key, value in item.items() if key != "support_ref"}:
                        continue
                    binding = dict(observation_id=bound["observation_id"])
                else:
                    bound = _resolve_span(item, spans)
                    if bound is None:
                        continue
                    selected_spans[bound["span_id"]] = bound
                    binding = dict(source_span_ids=[bound["span_id"]])
                if not legacy:
                    catalog[ref] = dict(
                        competitor=original.competitor,
                        dimension=original.dimension,
                        fact_ids=[original.id],
                        source_ids=[original.source_id],
                        **binding,
                    )
    return catalog, selected_spans


def support_ref_catalog(payload, source_facts, sent_fact_ids):
    return _catalogs(payload, source_facts, sent_fact_ids)[0]


def dispatched_span_candidates(payload, source_facts, sent_fact_ids):
    """The actual sent whitelist uses the same checks as short alias expansion."""
    return _catalogs(payload, source_facts, sent_fact_ids)[1]


def dispatched_support_choices(payload, source_facts, sent_fact_ids):
    """Readable, complete choices from the same verified transport catalog."""
    from packages.research.evidence.operations import operation_binding, operation_observations

    catalog, spans = _catalogs(payload, source_facts, sent_fact_ids)
    if not catalog:
        return {}
    operations = {
        (fact.id, item["observation_id"]): item
        for fact in source_facts if fact.id in sent_fact_ids
        for item in (operation_binding(op) for op in operation_observations(fact))
    }
    result = {}
    for ref, binding in catalog.items():
        if "observation_id" in binding:
            result[ref] = dict(
                support_ref=ref, binding_kind="operation",
                operation_binding=operations[(binding["fact_ids"][0], binding["observation_id"])],
            )
        else:
            span = spans[binding["source_span_ids"][0]]
            result[ref] = dict(support_ref=ref, binding_kind="span", quote=span["quote"])
    return result
