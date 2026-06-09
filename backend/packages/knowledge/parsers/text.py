"""Plain-text parser with conservative encoding detection."""

from __future__ import annotations

from .base import ParsedDocument

PARSER_VERSION = "text-1.0"


def decode_content(content: bytes) -> tuple[str, list[str], str]:
    """Decode bytes without raising, returning text, warnings, and encoding."""
    if not content:
        return "", ["empty input"], "utf-8"

    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding), [], encoding
        except UnicodeDecodeError:
            continue

    text = content.decode("utf-8", errors="replace")
    warnings = ["input could not be decoded cleanly as utf-8/gb18030"]
    if "\ufffd" in text:
        warnings.append("replacement characters inserted during decoding")
    return text, warnings, "utf-8-replace"


def parse_text(
    content: bytes,
    mime: str = "text/plain",
    filename: str | None = None,
) -> ParsedDocument:
    text, warnings, encoding = decode_content(content)
    if not text.strip() and "empty input" not in warnings:
        warnings.append("parsed text is empty")
    return ParsedDocument(
        title=filename or "",
        text=text,
        metadata={"filename": filename, "encoding": encoding},
        parser_version=PARSER_VERSION,
        warnings=warnings,
        mime_type=mime or "text/plain",
    )
