"""Organization labels cannot acquire legal identity through generic source review."""

from unittest.mock import Mock

import pytest
from test_source_document_http_edges import actors  # noqa: F401

from finai_api.config import get_settings
from finai_api.services import company_source


@pytest.mark.parametrize("mode", ["company_column", "1c_tb_title"])
def test_source_company_creation_is_retired_before_read_or_proposal(actors, monkeypatch, mode):  # noqa: F811
    _, clients = actors
    read = Mock(side_effect=AssertionError("Retired identity path must not read source stores"))
    monkeypatch.setattr(company_source, "inspect_companies", read)
    try:
        response = clients["writer"].post(
            "/v1/ontology/source-documents/doc_" + "a" * 64 + "/companies/proposal",
            json={"sheet": "Source", "mode": mode},
        )
        assert response.status_code == 410
        assert "Source labels cannot create legal entities" in response.json()["detail"]
        read.assert_not_called()
    finally:
        get_settings.cache_clear()
