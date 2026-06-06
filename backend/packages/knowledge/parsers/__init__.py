"""Dispatcher for knowledge document parsers."""

from __future__ import annotations

import mimetypes

from .base import ParsedDocument
from .csv import parse_csv
from .json import parse_json
from .markdown import parse_markdown
from .text import parse_text

__all__ = ["ParsedDocument", "parse_document"]

_MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}


def parse_document(content: bytes, mime: str = "", filename: str | None = None) -> ParsedDocument:
    """Parse bytes into a normalised knowledge document without raising."""
    detected_mime = _detect_mime(content, mime, filename)
    try:
        if detected_mime in {"text/html", "application/xhtml+xml"}:
            from .html import parse_html

            return parse_html(content, detected_mime, filename)
        if detected_mime in {"text/markdown", "text/x-markdown"}:
            return parse_markdown(content, detected_mime, filename)
        if detected_mime in {"application/json", "text/json"} or detected_mime.endswith("+json"):
            return parse_json(content, detected_mime, filename)
        if detected_mime in {"text/csv", "application/csv"}:
            return parse_csv(content, detected_mime, filename)
        return parse_text(content, detected_mime, filename)
    except Exception as exc:
        parsed = parse_text(content, detected_mime, filename)
        parsed.warnings.append(f"parser dispatch failed: {exc}")
        return parsed


def _detect_mime(content: bytes, mime: str = "", filename: str | None = None) -> str:
    normalised = (mime or "").split(";", 1)[0].strip().lower()
    if normalised and normalised != "application/octet-stream":
        return normalised

    if filename:
        guessed, _ = mimetypes.guess_type(filename)
        if guessed:
            guessed = guessed.lower()
            if guessed == "text/plain" and _filename_has_markdown_extension(filename):
                return "text/markdown"
            return guessed

    sample = content[:256].lstrip()
    lower = sample.lower()
    if lower.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "text/html"
    if lower.startswith((b"{", b"[")):
        return "application/json"
    if lower.startswith((b"# ", b"## ", b"---\n")):
        return "text/markdown"
    if b"," in sample and b"\n" in sample:
        return "text/csv"
    return "text/plain"


def _filename_has_markdown_extension(filename: str) -> bool:
    lowered = filename.lower()
    return any(lowered.endswith(extension) for extension in _MARKDOWN_EXTENSIONS)
