"""Minimal Markdown parser for knowledge ingestion."""

from __future__ import annotations

import re

from .base import ParsedDocument
from .text import decode_content

PARSER_VERSION = "markdown-1.0"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def parse_markdown(
    content: bytes,
    mime: str = "text/markdown",
    filename: str | None = None,
) -> ParsedDocument:
    raw, warnings, encoding = decode_content(content)
    headings: list[dict[str, str | int]] = []
    text_lines: list[str] = []

    for line in raw.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            heading = match.group(2).strip()
            headings.append({"level": len(match.group(1)), "text": heading})
            text_lines.append(heading)
        else:
            text_lines.append(line)

    text = "\n".join(text_lines).strip()
    if not text:
        warnings.append("parsed markdown text is empty")

    title = str(headings[0]["text"]) if headings else (filename or "")
    return ParsedDocument(
        title=title,
        text=text,
        metadata={"filename": filename, "encoding": encoding, "headings": headings},
        parser_version=PARSER_VERSION,
        warnings=warnings,
        mime_type=mime or "text/markdown",
    )
