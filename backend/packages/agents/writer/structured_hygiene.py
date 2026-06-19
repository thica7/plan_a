from __future__ import annotations

import re


SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_.:#-]+$")
SOURCE_TOKEN_RE = re.compile(r"\[source:[^\]]+\]", re.IGNORECASE)
SOURCE_TOKEN_ATTEMPT_RE = re.compile(
    r"(?:\[[^\]\n]*\]|【[^】\n]*】)",
    re.IGNORECASE,
)
SOURCE_TOKEN_ATTEMPT_BODY_RE = re.compile(r"^\s*source\s*:", re.IGNORECASE)
SOURCE_TOKEN_MARKER = "[source:"


def has_source_token(text: str) -> bool:
    return bool(SOURCE_TOKEN_RE.search(text))


def find_malformed_source_token_attempts(text: str) -> list[str]:
    malformed: list[str] = []
    malformed_spans: list[tuple[int, int]] = []
    canonical_starts = {match.start() for match in SOURCE_TOKEN_RE.finditer(text)}
    lowered = text.casefold()
    search_from = 0

    while True:
        marker_start = lowered.find(SOURCE_TOKEN_MARKER, search_from)
        if marker_start == -1:
            break
        if marker_start not in canonical_starts:
            closing_bracket = text.find("]", marker_start)
            end = closing_bracket + 1 if closing_bracket != -1 else len(text)
            malformed.append(text[marker_start:end])
            malformed_spans.append((marker_start, end))
        search_from = marker_start + len(SOURCE_TOKEN_MARKER)

    for match in SOURCE_TOKEN_ATTEMPT_RE.finditer(text):
        token = match.group(0)
        if SOURCE_TOKEN_RE.fullmatch(token):
            continue
        if any(_spans_overlap(match.span(), span) for span in malformed_spans):
            continue
        body = token[1:-1]
        if SOURCE_TOKEN_ATTEMPT_BODY_RE.match(body):
            malformed.append(token)

    return malformed


def is_valid_source_id(source_id: str) -> bool:
    return bool(SOURCE_ID_RE.fullmatch(source_id))


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]
