from finai_api.services.regulatory_sources import parse


def test_original_capture_with_later_publications_never_claims_current_law():
    html = """<body class="page-document-view-123"><h1>Act title</h1>
    <table><tr><td>დოკუმენტის ნომერი</td><td>81</td></tr></table>
    <a href="/ka/document/view/123?publication=2">Later publication</a>
    <script>publication_id=0</script><div id="maindoc"><p>Original legal text</p></div></body>"""
    result = parse(html.encode())
    assert result["completeness"] == "OLDER_PUBLICATION_ONLY"
    assert result["current_law_verified"] is False
    assert result["attachments_retained"] is False
    assert result["text"] == "Original legal text"
    restricted = html.replace(
        '<div id="maindoc">', 'კონსოლიდირებული ვარიანტის ნახვა <b>ფასიანია</b><div id="maindoc">'
    )
    assert parse(restricted.encode())["completeness"] == "RESTRICTED_CONSOLIDATION"
