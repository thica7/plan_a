"""Canonical source/evidence identity resolver.

Reports cite `RawSource.id` tokens. Enterprise storage scopes use
`EvidenceRecord.id`. This module owns the deterministic alias resolver between
those identities so report rendering, release gates, source snapshots, and QA
checks do not each invent their own source-token rules.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from packages.schema.enterprise import EvidenceRecord, ReportVersionRecord

RAW_SOURCE_ALIASES_KEY = "raw_source_aliases"
RUN_RAW_SOURCE_ID_KEY = "run_raw_source_id"
SOURCE_TOKEN_RE = re.compile(r"\[source:([A-Za-z0-9_.:#-]+)\]")
ANY_SOURCE_TOKEN_RE = re.compile(r"\[source:([^\]]+)\]")
VALID_SOURCE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:#-]+$")

SourceResolutionStatus = Literal["resolved", "alias", "out_of_scope", "missing", "malformed"]


@dataclass(frozen=True)
class SourceResolution:
    token: str
    normalized_token: str
    status: SourceResolutionStatus
    evidence_id: str | None = None
    raw_source_id: str | None = None
    canonical_token: str | None = None
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.status in {"resolved", "alias"}

    def as_dict(self) -> dict[str, object]:
        return {
            "token": self.token,
            "normalized_token": self.normalized_token,
            "status": self.status,
            "evidence_id": self.evidence_id,
            "raw_source_id": self.raw_source_id,
            "canonical_token": self.canonical_token,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SourceTokenNormalization:
    report_md: str
    evidence_ids: list[str]
    resolutions: list[SourceResolution] = field(default_factory=list)
    changed: bool = False

    def reconciliation(self, evidence: Iterable[EvidenceRecord]) -> dict[str, object]:
        evidence_list = list(evidence)
        return build_source_reconciliation(
            self.report_md,
            evidence_list,
            scoped_evidence_ids=self.evidence_ids,
            precomputed_resolutions=self.resolutions,
            canonical_report_md_changed=self.changed,
        )


class SourceResolutionIndex:
    def __init__(
        self,
        evidence: Iterable[EvidenceRecord],
        *,
        scoped_evidence_ids: Iterable[str] | None = None,
    ) -> None:
        self._evidence = list(evidence)
        self._all_by_token: dict[str, EvidenceRecord] = {}
        self._scoped_by_token: dict[str, EvidenceRecord] = {}
        self._scope_was_provided = scoped_evidence_ids is not None
        self._scoped_ids = set(scoped_evidence_ids or [])
        for item in self._evidence:
            for token in evidence_source_tokens(item):
                normalized = normalize_source_token(token)
                self._all_by_token[normalized] = item
                if not self._scope_was_provided or item.id in self._scoped_ids:
                    self._scoped_by_token[normalized] = item

    @property
    def scoped_evidence(self) -> list[EvidenceRecord]:
        if not self._scope_was_provided:
            return list(self._evidence)
        return [item for item in self._evidence if item.id in self._scoped_ids]

    def resolve(self, token: str) -> SourceResolution:
        normalized = normalize_source_token(token)
        scoped = self._scoped_by_token.get(normalized)
        if scoped is not None:
            return _resolution_for(token, normalized, scoped)
        unscoped = self._all_by_token.get(normalized)
        if unscoped is not None:
            return SourceResolution(
                token=token,
                normalized_token=normalized,
                status="out_of_scope",
                evidence_id=unscoped.id,
                raw_source_id=unscoped.raw_source_id,
                canonical_token=_canonical_report_token(unscoped),
                reason="Token resolves to evidence outside the scoped report version.",
            )
        return SourceResolution(
            token=token,
            normalized_token=normalized,
            status="missing",
            reason="Token does not resolve to an EvidenceRecord id, RawSource id, or alias.",
        )

    def evidence_by_token(self) -> dict[str, EvidenceRecord]:
        return dict(self._scoped_by_token)


def normalize_report_version_sources(
    version: ReportVersionRecord,
    evidence: Iterable[EvidenceRecord],
) -> ReportVersionRecord:
    normalization = normalize_report_source_tokens(
        version.report_md,
        evidence,
        scoped_evidence_ids=version.evidence_ids,
    )
    metadata = dict(version.quality_metadata)
    metadata["source_reconciliation"] = normalization.reconciliation(evidence)
    return version.model_copy(
        update={
            "report_md": normalization.report_md,
            "evidence_ids": normalization.evidence_ids,
            "quality_metadata": metadata,
        }
    )


def normalize_report_source_tokens(
    report_md: str,
    evidence: Iterable[EvidenceRecord],
    *,
    scoped_evidence_ids: Iterable[str] | None = None,
) -> SourceTokenNormalization:
    evidence_list = list(evidence)
    scope_was_provided = scoped_evidence_ids is not None
    scoped_ids = list(scoped_evidence_ids) if scoped_evidence_ids is not None else []
    index = SourceResolutionIndex(
        evidence_list,
        scoped_evidence_ids=scoped_ids if scope_was_provided else None,
    )
    canonical_ids: list[str] = []
    resolutions: list[SourceResolution] = []
    changed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        token = match.group(1)
        if not is_valid_source_token(token):
            resolutions.append(
                SourceResolution(
                    token=token,
                    normalized_token=normalize_source_token(token),
                    status="malformed",
                    reason="Token does not match the canonical source token grammar.",
                )
            )
            changed = True
            return ""
        resolution = index.resolve(token)
        if resolution.status == "out_of_scope" and resolution.evidence_id:
            resolution = SourceResolution(
                token=resolution.token,
                normalized_token=resolution.normalized_token,
                status="alias",
                evidence_id=resolution.evidence_id,
                raw_source_id=resolution.raw_source_id,
                canonical_token=resolution.canonical_token
                or resolution.raw_source_id
                or resolution.evidence_id,
                reason=(
                    "Token resolved outside the initial report scope and was added "
                    "to the normalized report evidence scope."
                ),
            )
        resolutions.append(resolution)
        if resolution.resolved and resolution.evidence_id:
            canonical_ids.append(resolution.evidence_id)
            report_token = (
                resolution.canonical_token
                or resolution.raw_source_id
                or resolution.evidence_id
            )
            replacement = f"[source:{report_token}]"
            if replacement != match.group(0):
                changed = True
            return replacement
        return match.group(0)

    normalized_report_md = ANY_SOURCE_TOKEN_RE.sub(replace, report_md)
    resolved_ids = dedupe_strings(canonical_ids)
    if scope_was_provided:
        evidence_ids = _merge_ids(scoped_ids, resolved_ids)
    elif resolved_ids:
        evidence_ids = resolved_ids
    else:
        evidence_ids = [item.id for item in evidence_list]
    return SourceTokenNormalization(
        report_md=normalized_report_md,
        evidence_ids=evidence_ids,
        resolutions=resolutions,
        changed=changed,
    )


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
    precomputed_resolutions: Iterable[SourceResolution] | None = None,
    canonical_report_md_changed: bool = False,
) -> dict[str, object]:
    evidence_list = list(evidence)
    scope_was_provided = scoped_evidence_ids is not None
    scoped_ids = set(scoped_evidence_ids or [])
    index = SourceResolutionIndex(
        evidence_list,
        scoped_evidence_ids=scoped_ids if scope_was_provided else None,
    )
    report_tokens = dedupe_strings(
        normalize_source_token(token) for token in ANY_SOURCE_TOKEN_RE.findall(report_md)
    )
    resolutions = list(
        precomputed_resolutions
        or [
            index.resolve(token)
            if is_valid_source_token(token)
            else SourceResolution(
                token=token,
                normalized_token=normalize_source_token(token),
                status="malformed",
                reason="Token does not match the canonical source token grammar.",
            )
            for token in report_tokens
        ]
    )
    scoped_evidence = index.scoped_evidence

    evidence_aliases: dict[str, list[str]] = {}
    scoped_tokens: set[str] = set()
    for item in scoped_evidence:
        tokens = evidence_source_tokens(item)
        scoped_tokens.update(tokens)
        canonical_token = _canonical_report_token(item)
        aliases = sorted(token for token in tokens if token != canonical_token)
        if aliases:
            evidence_aliases[item.id] = aliases

    unresolved = [
        resolution.normalized_token
        for resolution in resolutions
        if resolution.status in {"missing", "out_of_scope", "malformed"}
    ]
    return {
        "report_source_tokens": report_tokens,
        "canonical_report_source_tokens": dedupe_strings(
            resolution.canonical_token or resolution.normalized_token for resolution in resolutions
        ),
        "report_source_token_count": len(report_tokens),
        "canonical_report_md_changed": canonical_report_md_changed,
        "scoped_evidence_ids": [item.id for item in scoped_evidence],
        "scoped_evidence_count": len(scoped_evidence),
        "scoped_source_token_count": len(scoped_tokens),
        "unresolved_report_source_tokens": dedupe_strings(unresolved),
        "unresolved_report_source_token_count": len(dedupe_strings(unresolved)),
        "evidence_source_aliases": evidence_aliases,
        "source_resolutions": [resolution.as_dict() for resolution in resolutions],
    }


def evidence_by_source_token(
    evidence: Iterable[EvidenceRecord],
) -> dict[str, EvidenceRecord]:
    return SourceResolutionIndex(evidence).evidence_by_token()


def source_token_alias_map(
    *,
    raw_sources: Iterable[Any] = (),
    evidence: Iterable[EvidenceRecord] = (),
    scoped_evidence_ids: Iterable[str] | None = None,
) -> dict[str, str]:
    """Return every accepted report token mapped to canonical RawSource identity."""

    aliases: dict[str, str] = {}
    for source in raw_sources:
        source_id = normalize_source_token(str(getattr(source, "id", "") or ""))
        if source_id:
            aliases[source_id] = source_id
    for token, item in SourceResolutionIndex(
        evidence,
        scoped_evidence_ids=scoped_evidence_ids,
    ).evidence_by_token().items():
        aliases[token] = _canonical_report_token(item)
    return aliases


def resolve_source_token(
    token: str,
    alias_map: Mapping[str, str],
) -> str | None:
    if not is_valid_source_token(token):
        return None
    return alias_map.get(normalize_source_token(token))


def source_tokens(markdown: str, *, include_malformed: bool = False) -> list[str]:
    pattern = ANY_SOURCE_TOKEN_RE if include_malformed else SOURCE_TOKEN_RE
    return [match.group(1) for match in pattern.finditer(markdown)]


def malformed_source_tokens(markdown: str) -> list[str]:
    return dedupe_strings(
        token
        for token in source_tokens(markdown, include_malformed=True)
        if not is_valid_source_token(token)
    )


def evidence_source_tokens(evidence: EvidenceRecord) -> set[str]:
    tokens = {evidence.id, evidence.raw_source_id}
    tokens.update(string_list(evidence.metadata.get(RAW_SOURCE_ALIASES_KEY)))
    return {normalize_source_token(token) for token in tokens if token}


def normalize_source_token(token: str) -> str:
    return token.split("#", 1)[0].strip()


def is_valid_source_token(token: str) -> bool:
    return bool(VALID_SOURCE_TOKEN_RE.fullmatch(token.strip()))


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


def _resolution_for(
    token: str,
    normalized: str,
    evidence: EvidenceRecord,
) -> SourceResolution:
    canonical_token = _canonical_report_token(evidence)
    status: SourceResolutionStatus = "resolved" if normalized == canonical_token else "alias"
    return SourceResolution(
        token=token,
        normalized_token=normalized,
        status=status,
        evidence_id=evidence.id,
        raw_source_id=evidence.raw_source_id,
        canonical_token=canonical_token,
        reason="Token resolved directly."
        if status == "resolved"
        else "Token resolved through alias.",
    )


def _canonical_report_token(evidence: EvidenceRecord) -> str:
    return normalize_source_token(evidence.raw_source_id) or normalize_source_token(evidence.id)


def _merge_ids(primary: Iterable[str], secondary: Iterable[str]) -> list[str]:
    return dedupe_strings([*list(primary), *list(secondary)])
