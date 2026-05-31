from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_count(self) -> int:
        return sum(self.counts.values())


_REDACTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "bearer_token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    ),
    (
        "api_key",
        re.compile(
            r"(?i)\b(?:sk-or-v1-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{16,}|"
            r"(?:ak|rk|pk|xoxb|ghp)_[A-Za-z0-9_-]{16,})\b"
        ),
    ),
    (
        "email",
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ),
    (
        "phone",
        re.compile(
            r"(?<!\w)(?:\+?86[-.\s]?)?1[3-9]\d{9}(?!\w)|"
            r"(?<!\w)(?:\+?1[-.\s]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})"
            r"[-.\s]?[2-9]\d{2}[-.\s]?\d{4}(?!\w)"
        ),
    ),
)


def redact_text(text: str) -> RedactionResult:
    redacted = text
    counts: dict[str, int] = {}
    for label, pattern in _REDACTION_PATTERNS:
        redacted, count = pattern.subn(f"[redacted:{label}]", redacted)
        if count:
            counts[label] = count
    return RedactionResult(text=redacted, counts=counts)
