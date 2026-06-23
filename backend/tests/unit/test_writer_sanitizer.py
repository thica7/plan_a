from __future__ import annotations

import re

from packages.agents.writer.sanitizer import CitationGuard, ReportSanitizer
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource


def _detail() -> RunDetail:
    return RunDetail(
        id="run-writer-sanitizer",
        topic="AI coding agent",
        status="running",
        execution_mode="demo",
        created_at="2026-06-20T00:00:00",
        updated_at="2026-06-20T00:00:00",
        output_language="en-US",
        plan=AnalysisPlan(
            topic="AI coding agent",
            competitors=["Acme"],
            dimensions=["pricing"],
        ),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="Acme",
                dimension="pricing",
                source_type="webpage_verified",
                title="Acme pricing",
                snippet="Acme pricing is public.",
                content_hash="pricing-hash",
                confidence=0.9,
            )
        ],
    )


def test_report_sanitizer_removes_writer_internals_and_header_citations() -> None:
    sanitizer = ReportSanitizer(
        label_aliases=lambda key: ["Evidence Appendix"] if key == "evidence_appendix" else [],
        heading_matches=lambda heading, alias: heading.casefold() == alias.casefold(),
        localize_heading=lambda detail, line: line,
    )

    markdown = "\n".join(
        [
            "## Decision Summary [source:pricing-1]",
            "Writer Evidence Pack: internal payload should not leak.",
            "| Claim [source:pricing-1] | Evidence |",
            "| --- | --- |",
            "| Acme has public pricing [source:pricing-1] | pricing page |",
            "## Evidence Appendix",
            "- Acme pricing page [source:pricing-1]",
        ]
    )

    result = sanitizer.sanitize_report_hygiene(_detail(), markdown)

    assert "Writer Evidence Pack" not in result
    assert "## Decision Summary" in result
    assert "## Decision Summary [source:pricing-1]" not in result
    assert "| Claim" in result and "| Evidence |" in result
    assert "| Acme has public pricing [source:pricing-1] | pricing page |" in result
    assert "- Acme pricing page [source:pricing-1]" not in result


def test_citation_guard_repairs_dimension_tokens_and_adds_missing_claim_citations() -> None:
    guard = CitationGuard(
        source_ids_for_line=lambda detail, line: ["pricing-1"],
        claim_line_tokens=("pricing", "price", "cost"),
        cjk_text_re=re.compile(r"[\u3400-\u9fff]"),
    )
    detail = _detail()

    repaired = guard.repair_report_source_tokens(
        detail,
        "Acme pricing is public [source:pricing].",
    )
    hardened = guard.ensure_report_claim_citations(
        detail,
        "Acme pricing is public and has enough context for a cited claim.",
    )

    assert repaired == "Acme pricing is public [source:pricing-1]."
    assert hardened.endswith("[source:pricing-1]")