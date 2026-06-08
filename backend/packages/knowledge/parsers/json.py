"""JSON parser that flattens values into searchable dot-path text."""

from __future__ import annotations

import json
from typing import Any

from .base import ParsedDocument
from .text import decode_content

PARSER_VERSION = "json-1.0"


def parse_json(
    content: bytes,
    mime: str = "application/json",
    filename: str | None = None,
) -> ParsedDocument:
    raw, warnings, encoding = decode_content(content)
    if not raw.strip():
        return ParsedDocument(
            title=filename or "",
            text="",
            metadata={"filename": filename, "encoding": encoding},
            parser_version=PARSER_VERSION,
            warnings=warnings,
            mime_type=mime or "application/json",
        )

    try:
        data = json.loads(raw)
    except Exception as exc:
        return ParsedDocument(
            title=filename or "",
            text=raw,
            metadata={"filename": filename, "encoding": encoding},
            parser_version=PARSER_VERSION,
            warnings=[*warnings, f"invalid json: {exc}"],
            mime_type=mime or "application/json",
        )

    lines = list(_flatten(data))
    text = "\n".join(lines).strip()
    if not text:
        warnings.append("json contained no scalar values")

    metadata: dict[str, Any] = {
        "filename": filename,
        "encoding": encoding,
        "root_type": type(data).__name__,
    }
    if isinstance(data, list):
        metadata["record_count"] = len(data)
        metadata["array_of_records"] = all(isinstance(item, dict) for item in data)
    elif isinstance(data, dict):
        title = data.get("title") or data.get("name")
        if isinstance(title, str):
            metadata["title_field"] = title

    return ParsedDocument(
        title=str(metadata.get("title_field") or filename or ""),
        text=text,
        metadata=metadata,
        parser_version=PARSER_VERSION,
        warnings=warnings,
        mime_type=mime or "application/json",
    )


def _flatten(value: Any, path: str = "") -> list[str]:
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            lines.extend(_flatten(item, next_path))
        return lines
    if isinstance(value, list):
        lines = []
        for index, item in enumerate(value):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            lines.extend(_flatten(item, next_path))
        return lines
    if value is None:
        return [f"{path}: null"] if path else ["null"]
    return [f"{path}: {value}"] if path else [str(value)]
