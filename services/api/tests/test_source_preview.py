from hashlib import sha256

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from finai_api.api import workspace_routes
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.services.source_preview import preview


def test_source_text_and_record_positions_survive_search_and_pagination() -> None:
    content = b'\xef\xbb\xbfid,label,label\r\n001,"First, account","two\nlines"\r\n002,,0\r\n'
    result = preview(content)
    assert result["columns"] == ["id", "label", "label"]
    assert result["rows"][0]["values"] == ["001", "First, account", "two\nlines"]
    assert result["rows"][1]["values"] == ["002", "", "0"]
    assert result["sha256"] == sha256(content).hexdigest()
    assert preview(content, search="ACCOUNT")["rows"][0]["source_row"] == 2
    many = ("id\n" + "\n".join(f"{i:04}" for i in range(205))).encode()
    page = preview(many, offset=100)
    assert page["rows"][0] == {
        "source_row": 102, "values": ["0100"], "width_matches_header": True,
    }
    assert len(page["rows"]) == 100 and page["has_more"]
    assert len(preview(many, offset=200)["rows"]) == 5
    assert preview(b"a,b\n1,2,3\n")["rows"][0]["width_matches_header"] is False


def test_preview_requires_source_permission_and_uses_scoped_integrity_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    path = "/v1/workspace/constructions/retained/preview"
    assert TestClient(app).get(path).status_code == 401
    seen = []

    def source(principal: Principal, receipt_id: str) -> bytes:
        seen.append((principal.scope.legal_entity_id, receipt_id))
        return b"id,value\n001,2.00\n"

    monkeypatch.setattr(workspace_routes.workspace, "source_bytes", source)
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert seen == [("entity-ge-001", "retained")]
    assert response.json()["rows"][0]["values"] == ["001", "2.00"]
    assert client.get(path + "?offset=-1").status_code == 422
    principal = Principal.model_validate(client.get("/v1/workspace/session").json())
    app.dependency_overrides[workspace_routes.reader] = lambda: principal.model_copy(
        update={"permissions": ("read",)}
    )
    try:
        assert client.get(path).status_code == 403
        assert len(seen) == 1
    finally:
        app.dependency_overrides.clear()

    def unavailable(principal: Principal, receipt_id: str) -> bytes:
        raise HTTPException(404, "Construction not found in this scope")

    monkeypatch.setattr(workspace_routes.workspace, "source_bytes", unavailable)
    assert client.get(path).status_code == 404


def test_column_profile_is_whole_source_and_preserves_text_distinctions() -> None:
    result = preview(b"id,name\n001,\n1,A\n001\n2,B,extra\n", search="extra")
    assert result["matching_rows"] == 1
    assert result["total_rows"] == 4
    assert result["profile_scope"] == "ENTIRE_SOURCE"
    assert result["extra_width_rows"] == 1
    assert result["profile"] == [
        {"column_index": 0, "empty_cells": 0, "missing_cells": 0,
         "distinct_nonempty_values": 3},
        {"column_index": 1, "empty_cells": 1, "missing_cells": 1,
         "distinct_nonempty_values": 2},
    ]
