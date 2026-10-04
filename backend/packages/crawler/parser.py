"""HTML -> structured text/markdown parser using trafilatura."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from lxml import html as lxml_html
from lxml.etree import ParserError
from trafilatura import extract as trafilatura_extract
from trafilatura.metadata import extract_metadata

from .models import ParsedPage


def parse_html(page: ParsedPage) -> ParsedPage:
    """Parse raw HTML into structured text and metadata using trafilatura."""
    if not page.html:
        return page

    structured = _extract_explicit_main(page.html)
    if structured is not None:
        text, markdown, tables = structured
    else:
        text = trafilatura_extract(
            page.html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            url=page.url,
        ) or ""
        markdown = text
        tables = []

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
        "tables": tables,
        "meta_description": description,
        "meta_keywords": keywords,
        "links": links,
    })


def _extract_explicit_main(html: str) -> tuple[str, str, list[dict]] | None:
    """Keep source order and real HTML semantics when an article boundary exists."""
    try:
        root = lxml_html.fromstring(html)
    except ValueError:
        # lxml rejects a Unicode string with an XML encoding declaration.
        without_declaration = re.sub(r"^\ufeff?\s*<\?xml[^>]*\?>", "", html)
        try:
            root = lxml_html.fromstring(without_declaration)
        except (ParserError, ValueError):
            return None
    except ParserError:
        return None
    def visible(node) -> bool:
        return all(
            ancestor.get("hidden") is None and ancestor.get("aria-hidden") != "true"
            for ancestor in (node, *node.iterancestors())
        )

    mains = [node for node in root.xpath("//main") if visible(node)]
    candidates = mains or [node for node in root.xpath("//article") if visible(node)]
    containers = [
        node for node in candidates
        if not any(parent in candidates for parent in node.iterancestors())
    ]
    if not containers:
        return None
    for container in containers:
        for unwanted in container.xpath(
            ".//nav | .//footer | .//script | .//style | .//noscript | .//template | "
            ".//*[@hidden] | .//*[@aria-hidden='true'] | "
            ".//*[@role='navigation']"
        ):
            unwanted.drop_tree()

    blocks: list[str] = []
    markdown_blocks: list[str] = []
    tables: list[dict] = []

    def clean(node) -> str:
        return " ".join(node.text_content().split())

    def add_plain(value: str) -> None:
        value = " ".join(value.split())
        if value:
            blocks.append(value)
            markdown_blocks.append(value)

    def visit(node) -> None:
        if not isinstance(node.tag, str):
            return
        tag = node.tag.lower()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            value = clean(node)
            if value:
                blocks.append(value)
                markdown_blocks.append(f"{'#' * int(tag[1])} {value}")
            return
        if tag == "table":
            rows = []
            header: list[str] = []
            merged_cells = False
            caption_nodes = node.xpath("./caption")
            caption = clean(caption_nodes[0]) if caption_nodes else ""
            for tr in node.xpath(".//tr"):
                cells = tr.xpath("./th | ./td")
                merged_cells |= any(
                    cell.get("colspan", "1") != "1" or cell.get("rowspan", "1") != "1"
                    for cell in cells
                )
                values = [clean(cell) for cell in cells]
                if not values:
                    continue
                if not header and all(
                    cell.tag.lower() == "th" and cell.get("scope", "").lower() != "row"
                    for cell in cells
                ):
                    header = values
                else:
                    rows.append(values)
            lines = ([header] if header else []) + rows
            if lines:
                table_text = "\n".join(
                    ([caption] if caption else []) + [" | ".join(row) for row in lines]
                )
                blocks.append(table_text)
                markdown_lines = ["| " + " | ".join(row) + " |" for row in lines]
                if header:
                    markdown_lines.insert(1, "| " + " | ".join("---" for _ in header) + " |")
                if caption:
                    markdown_lines.insert(0, caption)
                markdown_blocks.append("\n".join(markdown_lines))
                gaps = (["missing_header"] if not header else [])
                if merged_cells:
                    gaps.append("merged_cells")
                table = {"headers": header, "rows": rows, "text": table_text}
                if caption:
                    table["caption"] = caption
                if gaps:
                    table["structure_gap"] = gaps[-1]
                    table["structure_gaps"] = gaps
                tables.append(table)
            return
        if tag in {"p", "pre"} or (
            tag in {"li", "blockquote"}
            and not node.xpath(".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6 | .//table")
        ):
            add_plain(clean(node))
            return
        if not len(node):
            add_plain(clean(node))
            return
        if node.text:
            add_plain(node.text)
        for child in node:
            visit(child)
            if child.tail:
                add_plain(child.tail)

    for container in containers:
        visit(container)
    if not blocks:
        return None
    return "\n\n".join(blocks), "\n\n".join(markdown_blocks), tables


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
