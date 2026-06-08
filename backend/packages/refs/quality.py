from __future__ import annotations

from collections.abc import Iterable

from packages.identity import stable_digest


def quality_finding_key(
    *,
    source: str,
    severity: str | None = None,
    rule_id: str | None = None,
    message: str | None = None,
    evidence_ids: Iterable[str] = (),
    claim_ids: Iterable[str] = (),
) -> str:
    return "quality:" + stable_digest(
        source,
        severity or "",
        rule_id or "",
        _message_fingerprint(message),
        sorted(evidence_ids),
        sorted(claim_ids),
        length=20,
    )


def quality_entry_keys(
    *,
    agent_name: str,
    blocker_count: int,
    warn_count: int,
    evidence_ids: Iterable[str],
    claim_ids: Iterable[str],
    summary: str,
) -> list[str]:
    if blocker_count == 0 and warn_count == 0:
        return []
    return [
        quality_finding_key(
            source=agent_name,
            severity="blocker" if blocker_count else "warn",
            message=summary,
            evidence_ids=evidence_ids,
            claim_ids=claim_ids,
        )
    ]


def _message_fingerprint(message: str | None) -> str:
    return " ".join(str(message or "").casefold().split())[:240]
