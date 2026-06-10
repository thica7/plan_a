from __future__ import annotations

from packages.knowledge.parsers import parse_document


def test_parse_markdown_extracts_headings() -> None:
    parsed = parse_document(
        b"# Product\n\n## Pricing\n\nStarts at $10.",
        "text/markdown",
        "pricing.md",
    )

    assert parsed.title == "Product"
    assert "Pricing" in parsed.text
    assert parsed.metadata["headings"] == [
        {"level": 1, "text": "Product"},
        {"level": 2, "text": "Pricing"},
    ]
    assert parsed.warnings == []


def test_parse_json_flattens_dot_paths() -> None:
    parsed = parse_document(
        b'{"title":"Plan","items":[{"name":"Pro","price":20}]}',
        "application/json",
        "plans.json",
    )

    assert parsed.title == "Plan"
    assert "items[0].name: Pro" in parsed.text
    assert "items[0].price: 20" in parsed.text
    assert parsed.metadata["root_type"] == "dict"


def test_parse_csv_renders_pipe_delimited_rows() -> None:
    parsed = parse_document(b"name,price\nPro,20\nTeam,50\n", "text/csv", "plans.csv")

    assert parsed.text.splitlines() == ["name | price", "Pro | 20", "Team | 50"]
    assert parsed.metadata["headers"] == ["name", "price"]
    assert parsed.metadata["row_count"] == 2
    assert parsed.tables[0]["rows"] == [["Pro", "20"], ["Team", "50"]]


def test_parse_html_uses_crawler_parser() -> None:
    parsed = parse_document(
        b"<html><head><title>Acme</title></head><body><main>Acme pricing page</main></body></html>",
        "text/html",
        "https://example.com/pricing",
    )

    assert "Acme pricing page" in parsed.text
    if not parsed.warnings:
        assert parsed.title == "Acme"
        assert parsed.metadata["links"] == []


def test_parse_garbled_text_returns_warning_without_raising() -> None:
    parsed = parse_document(b"\xff\xfe\x00\x81", "text/plain", "bad.txt")

    assert isinstance(parsed.text, str)
    assert parsed.warnings
