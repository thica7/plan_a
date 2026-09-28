from __future__ import annotations

from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from packages.crawler.policy import SSRFGuard
from packages.tools.fetch_page import fetch_page


def _public_resolver(_host: str, port: int, *_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.215.14", port))]


def _text_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
    })
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 40 250 Td (Product price is 19 dollars.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.asyncio
async def test_pdf_product_document_is_extracted_as_text() -> None:
    pdf = _text_pdf()
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, content=pdf, headers={"Content-Type": "application/pdf"}, request=request,
    ))
    result = await fetch_page(
        "https://example.com/product.pdf", guard=SSRFGuard(resolver=_public_resolver),
        transport=transport,
    )
    assert result.ok is True
    assert result.content_type == "application/pdf"
    assert "Product price is 19 dollars" in result.text


@pytest.mark.asyncio
async def test_unsupported_binary_is_reported_without_false_text() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, content=b"\x89PNG\r\n\x1a\n", headers={"Content-Type": "image/png"}, request=request,
    ))
    result = await fetch_page(
        "https://example.com/product.png", guard=SSRFGuard(resolver=_public_resolver),
        transport=transport,
    )
    assert result.ok is False
    assert result.text == ""
    assert "content type" in (result.error or "").lower()
