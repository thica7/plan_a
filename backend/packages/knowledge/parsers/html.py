"""HTML parser adapter for the crawler parser."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from .base import ParsedDocument
from .text import decode_content

PARSER_VERSION = "html-1.0"


def parse_html(
    content: bytes,
    mime: str = "text/html",
    filename: str | None = None,
) -> ParsedDocument:
    html, warnings, encoding = decode_content(content)
    if not html.strip():
        return ParsedDocument(
            title=filename or "",
            text="",
            metadata={"filename": filename, "encoding": encoding},
            parser_version=PARSER_VERSION,
            warnings=warnings,
            mime_type=mime or "text/html",
        )

    try:
        from packages.crawler.models import ParsedPage
        from packages.crawler.parser import parse_html as parse_crawler_html

        page = ParsedPage(
            url=filename or "",
            html=html,
            fetched_at=datetime.now(UTC),
            content_hash=hashlib.sha256(content).hexdigest()[:16],
            content_length=len(content),
            content_type=mime or "text/html",
        )
        parsed = parse_crawler_html(page)
    except Exception as exc:
        return ParsedDocument(
            title=filename or "",
            text=html,
            metadata={"filename": filename, "encoding": encoding},
            parser_version=PARSER_VERSION,
            warnings=[*warnings, f"html parser failed: {exc}"],
            mime_type=mime or "text/html",
        )

    if not parsed.text.strip():
        warnings.append("parsed html text is empty")

    return ParsedDocument(
        title=parsed.title or filename or "",
        text=parsed.text,
        metadata={
            "filename": filename,
            "encoding": encoding,
            "markdown": parsed.markdown,
            "meta_description": parsed.meta_description,
            "meta_keywords": parsed.meta_keywords,
            "links": parsed.links,
        },
        tables=parsed.tables,
        parser_version=PARSER_VERSION,
        warnings=warnings,
        mime_type=mime or "text/html",
    )
