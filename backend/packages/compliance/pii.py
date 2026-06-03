from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CompliancePolicy:
    redaction_enabled: bool = True
    redact_api_keys: bool = True
    redact_emails: bool = True
    redact_phones: bool = True


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)
    policy: CompliancePolicy = field(default_factory=CompliancePolicy)

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
            r"(?i)\b(?:"
            r"sk-or-v1-[A-Za-z0-9_-]{16,}|"
            r"sk-proj-[A-Za-z0-9_-]{16,}|"
            r"sk-ant-api03-[A-Za-z0-9_-]{16,}|"
            r"sk-[A-Za-z0-9_-]{16,}|"
            r"pplx-[A-Za-z0-9_-]{16,}|"
            r"AIza[0-9A-Za-z_-]{20,}|"
            r"AKIA[0-9A-Z]{16}|"
            r"(?:ak|rk|pk|xoxb|ghp|github_pat|hf|glpat)_[A-Za-z0-9_-]{16,}"
            r")\b"
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


def redact_text(text: str, policy: CompliancePolicy | None = None) -> RedactionResult:
    policy = policy or CompliancePolicy()
    if not policy.redaction_enabled:
        return RedactionResult(text=text, policy=policy)

    redacted = text
    counts: dict[str, int] = {}
    for label, pattern in _REDACTION_PATTERNS:
        if not _pattern_enabled(label, policy):
            continue
        redacted, count = pattern.subn(f"[redacted:{label}]", redacted)
        if count:
            counts[label] = count
    return RedactionResult(text=redacted, counts=counts, policy=policy)


def compliance_policy_from_settings(settings: object) -> CompliancePolicy:
    return CompliancePolicy(
        redaction_enabled=bool(getattr(settings, "compliance_redaction_enabled", True)),
        redact_api_keys=bool(getattr(settings, "compliance_redact_api_keys", True)),
        redact_emails=bool(getattr(settings, "compliance_redact_emails", True)),
        redact_phones=bool(getattr(settings, "compliance_redact_phones", True)),
    )


def _pattern_enabled(label: str, policy: CompliancePolicy) -> bool:
    if label in {"api_key", "bearer_token"}:
        return policy.redact_api_keys
    if label == "email":
        return policy.redact_emails
    if label == "phone":
        return policy.redact_phones
    return True
