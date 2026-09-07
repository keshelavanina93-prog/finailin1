"""Native private document intake and analytical proposal permissions remain separate."""

import asyncio
import json
import os
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import xlwt
from fastapi import HTTPException
from fastapi.testclient import TestClient

from finai_api.api import source_document_routes as routes
from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def actors(monkeypatch):
    writer = Principal(
        actor_id="synthetic-document-maker",
        display_name="Synthetic document maker",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="document-fixture", period="2026-08", currency="GEL"
        ),
        permissions=("ontology_read", "ontology_propose", "ingest", "export"),
    )
    reader = writer.model_copy(update={"actor_id": "reader", "permissions": ("ontology_read",)})
    outsider = writer.model_copy(
        update={"scope": writer.scope.model_copy(update={"currency": "USD"})}
    )
    grants = {"writer": writer, "reader": reader, "outsider": outsider}
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps({name: actor.model_dump(mode="json") for name, actor in grants.items()}),
    )
    get_settings.cache_clear()
    return writer, {
        name: TestClient(app, headers={"Authorization": f"Bearer {name}"}) for name in grants
    }


@pytest.mark.skipif(
    os.getenv("G8_BINDING_DB_TEST") != "1" or not os.getenv("FINAI_DATABASE_URL"),
    reason="Explicit disposable PostgreSQL acceptance opt-in required",
)
def test_native_document_roundtrip_scope_preview_and_duplicate_source_identity(actors):
    _, clients = actors
    client = clients["writer"]
    book = xlwt.Workbook()
    sheet = book.add_sheet("Source")
    sheet.write(0, 0, "Code")
    sheet.write(0, 1, "Observed quantity")
    sheet.write(1, 0, "001")
    sheet.write(1, 1, 0)
    content = BytesIO()
    book.save(content)
    raw = content.getvalue()
    path = "/v1/ontology/source-documents"
    uploaded = client.post(path, params={"filename": "synthetic-observations.xls"}, content=raw)
    assert uploaded.status_code == 200, uploaded.text
    identity = uploaded.json()["document_id"]
    repeated = client.post(path, params={"filename": "renamed.xls"}, content=raw)
    assert repeated.json()["document_id"] == identity
    assert repeated.json()["filename"] == "synthetic-observations.xls"
    listed = client.get(path).json()
    assert [row["document_id"] for row in listed] == [identity]
    assert client.get(path, params={"offset": 1}).json() == []
    original = client.get(path + f"/{identity}/content")
    assert (
        original.content == raw and original.headers["x-source-sha256"] == sha256(raw).hexdigest()
    )
    assert original.headers["cache-control"] == "no-store"
    preview = client.get(path + f"/{identity}/preview", params={"sheet": "Source", "offset": 1})
    assert preview.status_code == 200, preview.text
    assert preview.json()["sha256"] == sha256(raw).hexdigest()
    assert [cell["value"] for cell in preview.json()["rows"][0]["cells"]] == ["001", 0]
    assert (
        clients["reader"].post(path, params={"filename": "x.xlsx"}, content=raw).status_code == 403
    )
    assert clients["reader"].get(path + f"/{identity}/content").status_code == 403
    assert clients["outsider"].get(path + f"/{identity}/content").status_code == 404
    assert clients["outsider"].get(path).json() == []


@pytest.mark.parametrize("endpoint", ["accounts", "dimensions", "facts", "companies"])
def test_observer_cannot_create_analytical_proposals_before_service_dispatch(
    actors, monkeypatch, endpoint
):
    _, clients = actors
    forbidden = Mock(side_effect=AssertionError("Read-only actor reached proposal service"))
    targets = {
        "accounts": routes.source_account_binding,
        "dimensions": routes.source_dimensions,
        "facts": routes.source_financial_facts,
    }
    if endpoint == "companies":
        monkeypatch.setattr(routes, "propose_companies", forbidden)
        payload = {"sheet": "Source", "mode": "company_column"}
    else:
        monkeypatch.setattr(targets[endpoint], "propose", forbidden)
        payload = {"sheet": "Source", "profile": "1c_journal", "company_id": str(uuid4())}
    response = clients["reader"].post(
        f"/v1/ontology/source-documents/fixture/{endpoint}/proposal",
        json=payload,
    )
    assert response.status_code == 403
    forbidden.assert_not_called()


def test_stream_bound_and_unsupported_dimension_profile_refuse_before_storage(actors, monkeypatch):
    writer, _ = actors
    retain = Mock(side_effect=AssertionError("Oversized content was retained"))
    monkeypatch.setattr(routes, "retain_document", retain)

    async def stream():
        yield b"x" * 16_000_000
        yield b"x" * 16_000_001

    with pytest.raises(WorkspaceError) as rejected:
        asyncio.run(routes.upload(writer, SimpleNamespace(stream=stream), "oversized.csv"))
    assert rejected.value.status == 413
    retain.assert_not_called()
    request = routes.AccountBinding(sheet="Source", profile="1c_tb", company_id=uuid4())
    for function in (routes.inspect_dimensions, routes.propose_dimensions):
        with pytest.raises(WorkspaceError, match="journal analytical columns"):
            function(writer, "fixture", request)
    query = routes.DimensionQuery(**request.model_dump(), member_id=uuid4())
    with pytest.raises(WorkspaceError, match="journal analytical columns"):
        routes.dimension_movements(writer, "fixture", query)
    reader = writer.model_copy(update={"permissions": ("ontology_read",)})
    with pytest.raises(HTTPException) as denied:
        asyncio.run(routes.upload(reader, SimpleNamespace(stream=stream), "oversized.csv"))
    assert denied.value.status_code == 403
