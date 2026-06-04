from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from packages.schema.enterprise import EvidenceRecord

RAW_SOURCE_ALIASES_KEY = "raw_source_aliases"
RUN_RAW_SOURCE_ID_KEY = "run_raw_source_id"
SOURCE_TOKEN_RE = re.compile(r"\[source:([A-Za-z0-9_.:#-]+)\]")


def raw_source_alias_metadata(
    raw_source_id: str,
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result = dict(metadata or {})
    result[RUN_RAW_SOURCE_ID_KEY] = raw_source_id
    result[RAW_SOURCE_ALIASES_KEY] = merge_source_aliases(
        result.get(RAW_SOURCE_ALIASES_KEY),
        raw_source_id,
    )
    return result


def merge_evidence_source_metadata(
    existing: EvidenceRecord | None,
    incoming: EvidenceRecord,
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if existing is not None:
        metadata.update(existing.metadata)
    metadata.update(incoming.metadata)

    aliases: list[str] = []
    if existing is not None:
        aliases.extend(string_list(existing.metadata.get(RAW_SOURCE_ALIASES_KEY)))
        aliases.append(existing.raw_source_id)
    aliases.extend(string_list(incoming.metadata.get(RAW_SOURCE_ALIASES_KEY)))
    aliases.append(incoming.raw_source_id)
    metadata[RAW_SOURCE_ALIASES_KEY] = merge_source_aliases(aliases)
    return metadata


def build_source_reconciliation(
    report_md: str,
    evidence: Iterable[EvidenceRecord],
    *,
    scoped_evidence_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    scoped_ids = set(scoped_evidence_ids or [])
    scoped_evidence = [item for item in evidence if not scoped_ids or item.id in scoped_ids]
    report_tokens = dedupe_strings(
        normalize_source_token(token) for token in SOURCE_TOKEN_RE.findall(report_md)
    )
    scoped_tokens: set[str] = set()
    evidence_aliases: dict[str, list[str]] = {}
    for item in scoped_evidence:
        tokens = evidence_source_tokens(item)
        scoped_tokens.update(tokens)
        aliases = sorted(token for token in tokens if token != item.id)
        if aliases:
            evidence_aliases[item.id] = aliases

    unresolved = [token for token in report_tokens if token not in scoped_tokens]
    return {
        "report_source_tokens": report_tokens,
        "report_source_token_count": len(report_tokens),
        "scoped_evidence_ids": [item.id for item in scoped_evidence],
        "scoped_evidence_count": len(scoped_evidence),
        "scoped_source_token_count": len(scoped_tokens),
        "unresolved_report_source_tokens": unresolved,
        "unresolved_report_source_token_count": len(unresolved),
        "evidence_source_aliases": evidence_aliases,
    }


def evidence_by_source_token(
    evidence: Iterable[EvidenceRecord],
) -> dict[str, EvidenceRecord]:
    result: dict[str, EvidenceRecord] = {}
    for item in evidence:
        for token in evidence_source_tokens(item):
            result[token] = item
    return result


def evidence_source_tokens(evidence: EvidenceRecord) -> set[str]:
    tokens = {evidence.id, evidence.raw_source_id}
    tokens.update(string_list(evidence.metadata.get(RAW_SOURCE_ALIASES_KEY)))
    return {token for token in tokens if token}


def normalize_source_token(token: str) -> str:
    return token.split("#", 1)[0].strip()


def merge_source_aliases(*values: object) -> list[str]:
    aliases: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            aliases.extend(string_list(list(value)))
        else:
            aliases.extend(string_list([value]))
    return dedupe_strings(aliases)


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if item is not None and str(item).strip()]


def dedupe_strings(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
