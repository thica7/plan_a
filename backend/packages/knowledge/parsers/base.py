"""Common parser models for knowledge documents."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ParsedDocument(BaseModel):
    """Normalised document content returned by all knowledge parsers."""

    title: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    parser_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    mime_type: str = "text/plain"
    language: str | None = None
