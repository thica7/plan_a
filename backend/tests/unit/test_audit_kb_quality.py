from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx


def _load_audit_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "audit_kb_quality.py"
    spec = importlib.util.spec_from_file_location("audit_kb_quality", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_documents_flags_quality_signals() -> None:
    audit = _load_audit_module()
    documents = [
        {
            "id": "doc-1",
            "title": "Good pricing",
            "url": "https://cursor.com/pricing",
            "canonical_url": "https://cursor.com/pricing",
            "competitor": "Cursor",
            "dimension": "pricing",
            "source_type": "webpage_verified",
            "text": "Pricing starts at $10.",
            "last_seen_at": "2026-06-07T00:00:00Z",
        },
        {
            "id": "doc-2",
            "title": "Bad dimension",
            "url": "https://cursor.com",
            "canonical_url": "https://cursor.com",
            "competitor": "Cursor",
            "dimension": "Cursor",
            "source_type": "webpage_verified",
            "text": "Official overview.",
            "last_seen_at": "2026-06-07T00:00:00Z",
        },
        {
            "id": "doc-3",
            "title": "Broken " + "\u00e2" + " title",
            "url": "",
            "canonical_url": "",
            "competitor": "",
            "dimension": "",
            "source_type": "manual",
            "text": "Missing metadata.",
            "last_seen_at": "2026-06-07T00:00:00Z",
        },
    ]

    result = audit.audit_documents(
        documents,
        competitors=["Cursor", "Codeium"],
        min_docs_per_competitor=2,
        stale_days=30,
    )

    assert result["document_count"] == 3
    assert result["competitor_counts"]["Cursor"] == 2
    assert result["low_coverage"] == [{"competitor": "Codeium", "count": 0}]
    assert result["suspicious_dimensions_count"] == 1
    assert result["suspicious_dimensions"][0]["id"] == "doc-2"
    assert result["missing_metadata_count"] == 1
    assert result["non_http_documents_count"] == 1
    assert result["mojibake_documents_count"] == 1
    assert result["suspicious_source_domains_count"] == 0


def test_audit_documents_allows_codeium_rebrand_domains() -> None:
    audit = _load_audit_module()
    documents = [
        {
            "id": "doc-1",
            "title": "Allowed Devin docs",
            "url": "https://docs.devin.ai/desktop/getting-started",
            "canonical_url": "https://docs.devin.ai/desktop/getting-started",
            "competitor": "Codeium",
            "dimension": "docs",
            "source_type": "webpage_verified",
            "text": "Official docs.",
            "last_seen_at": "2026-06-07T00:00:00Z",
        },
        {
            "id": "doc-2",
            "title": "Allowed plugin docs",
            "url": "https://docs.windsurf.com/plugins/getting-started",
            "canonical_url": "https://docs.windsurf.com/plugins/getting-started",
            "competitor": "Codeium",
            "dimension": "docs",
            "source_type": "webpage_verified",
            "text": "Official plugin docs.",
            "last_seen_at": "2026-06-07T00:00:00Z",
        },
    ]

    result = audit.audit_documents(
        documents,
        competitors=["Codeium"],
        min_docs_per_competitor=1,
        stale_days=30,
    )

    assert result["suspicious_source_domains_count"] == 0


def test_audit_documents_flags_competitor_domain_mismatches() -> None:
    audit = _load_audit_module()
    documents = [
        {
            "id": "doc-1",
            "title": "Wrong source",
            "url": "https://example.com/desktop/getting-started",
            "canonical_url": "https://example.com/desktop/getting-started",
            "competitor": "Codeium",
            "dimension": "docs",
            "source_type": "webpage_verified",
            "text": "Unofficial docs.",
            "last_seen_at": "2026-06-07T00:00:00Z",
        },
    ]

    result = audit.audit_documents(
        documents,
        competitors=["Codeium"],
        min_docs_per_competitor=1,
        stale_days=30,
    )

    assert result["suspicious_source_domains_count"] == 1
    assert result["suspicious_source_domains"][0]["id"] == "doc-1"


def test_audit_failed_jobs_groups_errors() -> None:
    audit = _load_audit_module()

    result = audit.audit_failed_jobs([
        {"status": "failed", "error": "HTTP 403", "url": "https://blocked.example"},
        {"status": "failed", "error": "HTTP 403", "url": "https://blocked.example/2"},
        {"status": "failed", "error": "database is locked", "url": "https://ok.example"},
        {"status": "success", "error": None, "url": "https://ok.example/2"},
    ])

    assert result["status_counts"] == {"failed": 3, "success": 1}
    assert result["error_counts"] == {"HTTP 403": 2, "database is locked": 1}
    assert len(result["samples"]) == 3


def test_failed_jobs_falls_back_to_knowledge_route_when_crawl_route_errors() -> None:
    audit = _load_audit_module()

    class _Response:
        status_code = 500

        request = httpx.Request("GET", "http://test/api/crawl/jobs")

    class _Client:
        def get(self, path, params):  # noqa: ANN001, ANN202
            if path == "/api/crawl/jobs":
                raise httpx.HTTPStatusError(
                    "boom",
                    request=_Response.request,
                    response=_Response(),
                )
            assert path == "/api/knowledge/crawl-jobs"
            assert params == {"status": "failed", "limit": 3, "offset": 0}
            return httpx.Response(
                200,
                request=httpx.Request("GET", "http://test/api/knowledge/crawl-jobs"),
                json=[{"status": "failed", "error": "HTTP 403"}],
            )

    jobs, warnings = audit.failed_jobs(_Client(), limit=3)

    assert jobs == [{"status": "failed", "error": "HTTP 403"}]
    assert warnings == [
        "/api/crawl/jobs failed with HTTP 500; "
        "falling back to /api/knowledge/crawl-jobs"
    ]


def test_quality_gate_reports_blockers_and_passes_when_thresholds_allow() -> None:
    audit = _load_audit_module()
    quality = {
        "low_coverage": [{"competitor": "Codeium", "count": 1}],
        "suspicious_dimensions_count": 2,
        "missing_metadata_count": 1,
        "mojibake_documents_count": 1,
        "non_http_documents_count": 1,
        "suspicious_source_domains_count": 1,
    }

    blocked = audit.quality_gate(
        quality,
        max_suspicious_dimensions=0,
        max_missing_metadata=0,
        max_mojibake_documents=0,
        max_non_http_documents=0,
    )

    assert blocked["passed"] is False
    assert blocked["blockers"] == [
        "low_coverage: Codeium=1",
        "suspicious_dimensions: 2 > 0",
        "missing_metadata: 1 > 0",
        "mojibake_documents: 1 > 0",
        "non_http_documents: 1 > 0",
        "suspicious_source_domains: 1 > 0",
    ]

    quality["low_coverage"] = []
    passed = audit.quality_gate(
        quality,
        max_suspicious_dimensions=2,
        max_missing_metadata=1,
        max_mojibake_documents=1,
        max_non_http_documents=1,
        max_suspicious_source_domains=1,
    )

    assert passed["passed"] is True
    assert passed["blockers"] == []
