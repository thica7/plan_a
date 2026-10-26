"""Canonical, exact-content sharing for independent final question review only.

The codec has no evidentiary authority. Callers must reconstruct ``expected``
from the current server state and bind the canonical wire to actual transport.
"""

from __future__ import annotations

from collections import Counter

from packages.research.evidence.snapshot_models import canonical_json

CODEC_VERSION = 1


def _literal(value):
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError("Review object keys must be strings")
        if "" in value:
            return {"": [[key, _literal(value[key])] for key in sorted(value)]}
        return {key: _literal(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_literal(item) for item in value]
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ValueError("Review context must be JSON")


def _nodes(value):
    # Reserved objects are references or escaped literals; leave their complete
    # literal representation alone rather than sharing its structural markers.
    if isinstance(value, dict) and "" in value:
        return
    if isinstance(value, (dict, list, str)):
        yield value
    children = (
        value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    )
    for child in children:
        yield from _nodes(child)


def _replace(value, key, reference):
    if isinstance(value, dict) and "" in value:
        return value
    if isinstance(value, (dict, list, str)) and canonical_json(value) == key:
        return reference
    if isinstance(value, dict):
        return {name: _replace(child, key, reference) for name, child in value.items()}
    if isinstance(value, list):
        return [_replace(child, key, reference) for child in value]
    return value


def encode(value):
    """Share exact subtrees/strings only when the complete wire gets smaller."""
    wire = dict(c=CODEC_VERSION, p=_literal(value), t=[])
    while True:
        values = {}
        counts = Counter()
        for root in [wire["p"], *wire["t"]]:
            for node in _nodes(root):
                key = canonical_json(node)
                counts[key] += 1
                values[key] = node
        reference = {"": len(wire["t"])}
        ref_bytes = len(canonical_json(reference).encode())
        # Exact byte delta: replace all occurrences, append one complete member
        # and its separating comma. Existing table references keep their IDs.
        choices = [
            ((count - 1) * len(key.encode()) - count * ref_bytes - int(bool(wire["t"])), key)
            for key, count in counts.items()
            if count > 1
        ]
        if not choices:
            break
        saving, key = min(choices, key=lambda item: (-item[0], item[1]))
        if saving <= 0:
            break
        before = len(canonical_json(wire).encode())
        proposed = dict(
            c=CODEC_VERSION,
            p=_replace(wire["p"], key, reference),
            t=[_replace(item, key, reference) for item in wire["t"]] + [values[key]],
        )
        if len(canonical_json(proposed).encode()) >= before:
            raise ValueError("Invalid review sharing byte accounting")
        wire = proposed
    return wire


def decode(wire):
    """Reject ambiguous markers, foreign versions, cycles and unused tables."""
    if (
        not isinstance(wire, dict)
        or set(wire) != {"c", "p", "t"}
        or type(wire["c"]) is not int
        or wire["c"] != CODEC_VERSION
        or not isinstance(wire["t"], list)
    ):
        raise ValueError("Review codec version or envelope changed")
    active, used = set(), set()

    def expand(value):
        if isinstance(value, dict):
            if "" not in value:
                return {key: expand(child) for key, child in value.items()}
            if set(value) != {""}:
                raise ValueError("Review reference type disguise")
            marker = value[""]
            if type(marker) is int:
                if marker < 0 or marker >= len(wire["t"]) or marker in active:
                    raise ValueError("Missing or cyclic review reference")
                active.add(marker)
                used.add(marker)
                result = expand(wire["t"][marker])
                active.remove(marker)
                return result
            if isinstance(marker, list):
                result = {}
                for pair in marker:
                    if (
                        not isinstance(pair, list)
                        or len(pair) != 2
                        or type(pair[0]) is not str
                        or pair[0] in result
                    ):
                        raise ValueError("Invalid escaped review object")
                    result[pair[0]] = expand(pair[1])
                if "" not in result:
                    raise ValueError("Unnecessary escaped review object")
                return result
            raise ValueError("Invalid review reference type")
        if isinstance(value, list):
            return [expand(item) for item in value]
        if value is None or type(value) in (str, int, float, bool):
            return value
        raise ValueError("Invalid review value type")

    try:
        result = expand(wire["p"])
    except RecursionError as exc:
        raise ValueError("Review reference nesting exceeded") from exc
    if used != set(range(len(wire["t"]))):
        raise ValueError("Unused review table member")
    if canonical_json(encode(result)) != canonical_json(wire):
        raise ValueError("Noncanonical review encoding")
    return result


def dumps(value):
    return canonical_json(encode(value))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate review JSON key")
        result[key] = value
    return result


def loads(raw, *, expected=None):
    import json

    wire = json.loads(
        raw,
        object_pairs_hook=_unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    value = decode(wire)
    if expected is not None and (
        canonical_json(value) != canonical_json(expected) or raw != dumps(expected)
    ):
        raise ValueError("Review payload differs from server reconstruction")
    return value


def final_review_batches(candidates, basis_hash, *, max_bytes, max_batches):
    """Admit complete findings using the bytes of their full canonical wire."""
    from packages.agents.qa.question_reconciliation import MAX_FINDINGS

    def payload(rows):
        return dict(version=1, basis_hash=basis_hash, findings=rows)

    def fits(rows):
        return (
            len(rows) <= MAX_FINDINGS
            and len(("\nJSON:\n" + dumps(payload(rows))).encode()) <= max_bytes
        )

    groups, omitted = [], []
    for row in candidates:
        for group in groups:
            if fits([*group, row]):
                group.append(row)
                break
        else:
            if len(groups) < max_batches and fits([row]):
                groups.append([row])
            else:
                omitted.append(row["issue_id"])
    return [payload(group) for group in groups], omitted
