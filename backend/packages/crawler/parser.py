"""HTML -> structured text/markdown parser using trafilatura."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from trafilatura import extract as trafilatura_extract
from trafilatura.metadata import extract_metadata

from .models import ParsedPage


def parse_html(page: ParsedPage) -> ParsedPage:
    """Parse raw HTML into structured text and metadata using trafilatura."""
    if not page.html:
        return page

    # Extract main text content
    text = trafilatura_extract(
        page.html,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        url=page.url,
    ) or ""

    # Extract markdown (trafilatura returns plain text; we wrap it minimally)
    markdown = text  # trafilatura output is already clean text

    # Extract metadata
    try:
        meta = extract_metadata(page.html, default_url=page.url)
        title = _normalise_title(meta.title, page)
        description = meta.description or page.meta_description or ""
        keywords = (meta.keywords or "").split(",") if meta.keywords else []
        keywords = [k.strip() for k in keywords if k.strip()]
    except Exception:
        title = page.title or _extract_title_tag(page.html)
        description = page.meta_description or ""
        keywords = []

    # Extract links for further crawling
    links = _extract_links(page.html, page.url)

    return page.model_copy(update={
        "title": title,
        "text": text,
        "markdown": markdown,
        "meta_description": description,
        "meta_keywords": keywords,
        "links": links,
    })


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)


def _extract_title_tag(html: str) -> str:
    parser = _TitleParser()
    parser.feed(html)
    return " ".join("".join(parser.parts).split())


def _normalise_title(candidate: str | None, page: ParsedPage) -> str:
    title = (candidate or "").strip()
    if title and title != page.url:
        return title
    return page.title or _extract_title_tag(page.html)


def _extract_links(html: str, base_url: str) -> list[str]:
    """Extract unique absolute URLs from <a href> tags."""
    import re
    href_pattern = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
    seen: set[str] = set()
    links: list[str] = []

    for match in href_pattern.finditer(html):
        href = match.group(1)
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme in ("http", "https") and absolute not in seen:
            seen.add(absolute)
            links.append(absolute)

    return links[:100]  # limit to 100 links per page
