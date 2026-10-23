"""Whole source blocks for question-focused proposals, never sentence fragments."""

from __future__ import annotations

import re

_END = re.compile(r"^\s*(?:Was this helpful\?|Related pages|On this page)\s*$", re.I | re.M)
_MODAL = re.compile(r"^\s*(?:can|could|must|may|is|are|should|does|do|will|would)\b", re.I)
_MENU = re.compile(r"^\s*(?:Navigation menu|Open menu|Search docs|Show more)\s*$", re.I | re.M)
_LIMITING = re.compile(
    r"\b(?:exceptions?|restrictions?|conditions?|requirements?|eligibility|"
    r"limitations?|warnings?|notes?)\b|限制|例外|条件|要求|注意",
    re.I,
)
_PROCEDURE = re.compile(
    r"^(?:Add|Change|Create|Delete|Remove|Invite|Configure|Manage|Edit|"
    r"Export|Import)\s+\S",
    re.I,
)
_SUBJECT = re.compile(
    r"\b(?:members?|users?|guests?|observers?|visitors?|editors?|viewers?|"
    r"admins?|owners?|teams?|workspaces?|plans?|accounts?)\b",
    re.I,
)
_INVERTED_SUBJECT = re.compile(r"\s*(?:all|every|an?|the|our|your|we|I|you|they|it|he|she)\b", re.I)
_LATE_RULE = re.compile(
    r"\b(?:can(?:not)?|must|may|excluded?|except|not available|not possible)\b"
    r"|不能|仅限|除外|排除|必须",
    re.I,
)


def _is_question(block, heading_titles):
    lines = block.splitlines()
    for index, line in enumerate(lines):
        modal = _MODAL.match(line)
        if modal is None:
            continue
        following = line[modal.end() :]
        previous = lines[index - 1].strip() if index else ""
        # Inline link wrapping may put 'can add' on its own physical line.
        # It is not an inverted question only when its prior unfinished phrase
        # supplies a subject and the verb is not followed by a new subject.
        prefix = re.split(r"[.!?。！？]", "\n".join(lines[:index]))[-1]
        continuation = (
            index > 0
            and line.lstrip()[:1].islower()
            and previous not in heading_titles
            and _SUBJECT.search(prefix)
            and not _SUBJECT.match(following.strip())
            and not _INVERTED_SUBJECT.match(following)
        )
        if not continuation:
            return True
    return False


def native_question_blocks(brief, page):
    """Use heading scope, preserving child restrictions and every original byte."""
    from packages.research.extraction.semantic import (
        _active_questions,
        _heading_resolution,
        semantic_body_window,
    )

    if brief.dimension != "feature" or not _active_questions(brief):
        return []
    body = page.text or page.markdown or page.snippet
    window = semantic_body_window(brief, page)
    if not window or "|" in window or body.count(window) != 1:
        return []
    start = body.index(window)
    end = start + len(window)
    resolution = _heading_resolution(body, page)
    headings = resolution["headings"] if resolution["valid"] else []
    borders, active_level = {0, len(body)}, None
    for position, level, title in headings:
        if _LIMITING.search(title):
            continue
        if active_level is None or level <= active_level or _PROCEDURE.match(title):
            borders.add(position)
            active_level = level
    borders = sorted(borders)
    sections = (
        [
            (lower, upper)
            for lower, upper in zip(borders[:-1], borders[1:], strict=True)
            if start <= lower < upper <= end
        ]
        if headings
        else [(0, len(body))]
    )
    blocks = []
    for lower, upper in sections:
        if lower < start or upper > end:
            continue
        block = body[lower:upper].strip()
        footer = _END.search(block)
        if footer:
            # A footer label cannot hide a real later exception or rule.
            if _LATE_RULE.search(block[footer.end() :]):
                continue
            block = block[: footer.start()].rstrip()
        limit = 1600 if headings else 800
        if (
            18 <= len(block) <= limit
            and not _is_question(block, {title for _, _, title in headings})
            and not _MENU.search(block)
            and "?" not in block
            and "？" not in block
        ):
            blocks.append(block)
    return list(dict.fromkeys(blocks))
