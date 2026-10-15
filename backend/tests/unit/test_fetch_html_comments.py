from packages.tools.fetch_page import _html_to_text


def test_html_comments_in_headings_do_not_break_article_extraction():
    body = (
        "<article><h1>Collaborate<!-- --> with people</h1>"
        "<p>You can share documents and edit shared pages together with your team.</p>"
        "</article>"
    )
    text = _html_to_text(body)
    assert "share documents" in text
    assert "edit shared pages" in text


def test_capture_keeps_structural_headings_separate_from_plain_text():
    from packages.tools.fetch_page import _document_headings
    body = '<article><h1>Product guide</h1><h2>Comments</h2><p>Users can leave comments.</p><h2>Access rules</h2><p>Requires edit access.</p></article>'
    assert _document_headings(body) == ((1, 'Product guide'), (2, 'Comments'), (2, 'Access rules'))
