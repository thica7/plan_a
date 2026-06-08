from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx


def _load_collect_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "collect_real_sources.py"
    spec = importlib.util.spec_from_file_location("collect_real_sources", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_limit_seed_sources_zero_means_all_sources() -> None:
    collect = _load_collect_module()
    sources = [
        {"competitor": "A", "dimension": "docs", "url": "https://a.example"},
        {"competitor": "B", "dimension": "pricing", "url": "https://b.example"},
    ]

    assert collect.limit_seed_sources(sources, 0) == sources
    assert collect.limit_seed_sources(sources, -1) == sources
    assert collect.limit_seed_sources(sources, 1) == sources[:1]


def test_filter_sources_respects_competitor_and_existing_url_filters() -> None:
    collect = _load_collect_module()
    sources = [
        {"competitor": "Codeium", "dimension": "pricing", "url": "https://codeium.com/pricing"},
        {"competitor": "Coda", "dimension": "docs", "url": "https://coda.io/docs"},
        {"competitor": "Obsidian", "dimension": "docs", "url": "https://obsidian.md/docs"},
    ]

    selected, skipped = collect.filter_sources(
        sources,
        include_competitors=["Codeium", "Coda"],
        exclude_competitors=["Coda"],
        existing_urls={"https://codeium.com/pricing"},
    )

    assert selected == []
    assert [item["reason"] for item in skipped] == [
        "already ingested",
        "excluded competitor",
        "not in include filter",
    ]


def test_codeium_sources_stay_on_codeium_or_windsurf_plugin_domains() -> None:
    collect = _load_collect_module()

    codeium_sources = [
        source for source in collect.SOURCES
        if source["competitor"] == "Codeium"
    ]

    assert codeium_sources
    assert not any("docs.devin.ai" in source["url"] for source in codeium_sources)
    assert all(
        "codeium.com" in source["url"] or "docs.windsurf.com" in source["url"]
        for source in codeium_sources
    )


def test_sitemap_path_filter_limits_codeium_to_plugin_pages() -> None:
    collect = _load_collect_module()

    assert collect._sitemap_entry_matches_competitor(
        "Codeium",
        "https://docs.windsurf.com/plugins/getting-started",
    )
    assert collect._sitemap_entry_matches_competitor(
        "Codeium",
        "https://docs.windsurf.com/command/plugins-overview",
    )
    assert not collect._sitemap_entry_matches_competitor(
        "Codeium",
        "https://docs.windsurf.com/windsurf/cascade",
    )


def test_verify_url_accepts_markdown_responses() -> None:
    collect = _load_collect_module()

    class _Response:
        headers = {"content-type": "text/markdown; charset=utf-8"}
        status_code = 200
        text = "# Markdown"

    class _Client:
        def get(self, url, timeout, follow_redirects):  # noqa: ANN001, ANN202
            return _Response()

    ok, reason = collect.verify_url(_Client(), "https://example.com/doc.md", 1.0)

    assert ok is True
    assert reason.startswith("HTTP 200")


def test_verify_url_via_backend_accepts_successful_fetch() -> None:
    collect = _load_collect_module()

    class _Response:
        status_code = 200

        def json(self):  # noqa: ANN202
            return {
                "ok": True,
                "details": {
                    "status_code": 200,
                    "title": "Official docs",
                    "text_chars": 1200,
                },
            }

    class _Client:
        def post(self, path, json):  # noqa: ANN001, ANN202
            assert path == "/api/smoke/fetch"
            assert json == {"url": "https://example.com/docs"}
            return _Response()

    ok, reason = collect.verify_url_via_backend(_Client(), "https://example.com/docs")

    assert ok is True
    assert "backend fetch HTTP 200" in reason


def test_verify_url_via_backend_rejects_failed_or_empty_fetches() -> None:
    collect = _load_collect_module()

    class _FailedResponse:
        status_code = 200

        def json(self):  # noqa: ANN202
            return {
                "ok": False,
                "details": {
                    "status_code": 403,
                    "error": "forbidden",
                    "text_chars": 0,
                },
            }

    class _TinyResponse:
        status_code = 200

        def json(self):  # noqa: ANN202
            return {
                "ok": True,
                "details": {
                    "status_code": 200,
                    "title": "Too small",
                    "text_chars": 20,
                },
            }

    class _Client:
        def __init__(self, response):  # noqa: ANN001
            self._response = response

        def post(self, path, json):  # noqa: ANN001, ANN202
            return self._response

    failed_ok, failed_reason = collect.verify_url_via_backend(
        _Client(_FailedResponse()),
        "https://example.com/blocked",
    )
    tiny_ok, tiny_reason = collect.verify_url_via_backend(
        _Client(_TinyResponse()),
        "https://example.com/tiny",
    )

    assert failed_ok is False
    assert "backend fetch failed" in failed_reason
    assert tiny_ok is False
    assert "too little text" in tiny_reason


def test_create_crawl_job_auto_falls_back_to_knowledge_api() -> None:
    collect = _load_collect_module()

    class _FailedResponse:
        status_code = 500
        request = httpx.Request("POST", "http://test/api/crawl/jobs")

    class _SuccessResponse:
        def raise_for_status(self):  # noqa: ANN202
            return None

        def json(self):  # noqa: ANN202
            return {"id": "job-1"}

    class _Client:
        def __init__(self):  # noqa: ANN204
            self.paths = []

        def post(self, path, json):  # noqa: ANN001, ANN202
            self.paths.append(path)
            if path == "/api/crawl/jobs":
                raise httpx.HTTPStatusError(
                    "boom",
                    request=_FailedResponse.request,
                    response=_FailedResponse(),
                )
            assert path == "/api/knowledge/crawl-jobs"
            assert json == {"url": "https://example.com/docs"}
            return _SuccessResponse()

    client = _Client()

    job, path = collect.create_crawl_job(
        client,
        {"url": "https://example.com/docs"},
        job_api="auto",
    )

    assert job == {"id": "job-1"}
    assert path == "/api/knowledge/crawl-jobs"
    assert client.paths == ["/api/crawl/jobs", "/api/knowledge/crawl-jobs"]


def test_list_crawl_jobs_auto_falls_back_to_knowledge_api() -> None:
    collect = _load_collect_module()

    class _FailedResponse:
        status_code = 500
        request = httpx.Request("GET", "http://test/api/crawl/jobs")

    class _Client:
        def __init__(self):  # noqa: ANN204
            self.paths = []

        def get(self, path, params):  # noqa: ANN001, ANN202
            self.paths.append(path)
            if path == "/api/crawl/jobs":
                raise httpx.HTTPStatusError(
                    "boom",
                    request=_FailedResponse.request,
                    response=_FailedResponse(),
                )
            assert path == "/api/knowledge/crawl-jobs"
            assert params == {"limit": 200, "offset": 0}
            return httpx.Response(
                200,
                request=httpx.Request("GET", "http://test/api/knowledge/crawl-jobs"),
                json=[{"id": "job-1"}],
            )

    client = _Client()

    jobs = collect.list_crawl_jobs(client, job_api="auto")

    assert jobs == [{"id": "job-1"}]
    assert client.paths == ["/api/crawl/jobs", "/api/knowledge/crawl-jobs"]
