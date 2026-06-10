"""CSV parser using the Python standard library."""

from __future__ import annotations

import csv
from io import StringIO

from .base import ParsedDocument
from .text import decode_content

PARSER_VERSION = "csv-1.0"


def parse_csv(
    content: bytes,
    mime: str = "text/csv",
    filename: str | None = None,
) -> ParsedDocument:
    raw, warnings, encoding = decode_content(content)
    if not raw.strip():
        return ParsedDocument(
            title=filename or "",
            text="",
            metadata={"filename": filename, "encoding": encoding, "headers": [], "row_count": 0},
            parser_version=PARSER_VERSION,
            warnings=warnings,
            mime_type=mime or "text/csv",
        )

    try:
        sample = raw[:2048]
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel

    try:
        reader = csv.reader(StringIO(raw), dialect)
        rows = [row for row in reader]
    except Exception as exc:
        return ParsedDocument(
            title=filename or "",
            text=raw,
            metadata={"filename": filename, "encoding": encoding, "headers": [], "row_count": 0},
            parser_version=PARSER_VERSION,
            warnings=[*warnings, f"invalid csv: {exc}"],
            mime_type=mime or "text/csv",
        )

    if not rows:
        warnings.append("csv contained no rows")
        headers: list[str] = []
        body_rows: list[list[str]] = []
    else:
        headers = [cell.strip() for cell in rows[0]]
        body_rows = rows[1:]

    rendered = [" | ".join(cell.strip() for cell in row) for row in rows]
    text = "\n".join(rendered).strip()
    if not text:
        warnings.append("parsed csv text is empty")

    return ParsedDocument(
        title=filename or "",
        text=text,
        metadata={
            "filename": filename,
            "encoding": encoding,
            "headers": headers,
            "row_count": len(body_rows),
        },
        tables=[{"headers": headers, "rows": body_rows}],
        parser_version=PARSER_VERSION,
        warnings=warnings,
        mime_type=mime or "text/csv",
    )
