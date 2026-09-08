"""Opt-in authorized inspection of disposable RDF indexes over retained releases.

Synthetic isolated entity fixtures use real review, storage and index workers.
Historical inspection is explicitly distinguished from current publication use.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_definition_history import DB, retained  # noqa: F401
from test_external_ontology_import import (
    REASON,
    approve,
    lifecycle_change,
    native_import,  # noqa: F401
    proposal_from,
    resource_pin,
    scoped_versions,
)

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.external_ontology import ReleaseInspectionRequest, TermInspectionRequest
from finai_api.domain.resource_lifecycle import LifecycleRequest, LifecycleReview, VersionReference
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import Pin
from finai_api.main import app
from finai_api.services import external_ontology_queries as queries
from finai_api.services import ontology_import as imports
from finai_api.services import resource_lifecycle, resources
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def release_case(native_import):  # noqa: F811
    case = native_import
    prepared = imports.prepare(case.maker, case.request)
    approve(case.checker, proposal_from(prepared).proposal_id)
    case.release_row = resources.get_resource(case.reader, UUID(prepared["release_id"]))["resource"]
    case.release_pin = resource_pin(case.release_row)
    case.inspect_request = ReleaseInspectionRequest(release=case.release_pin)
    case.term_request = TermInspectionRequest(
        release=case.release_pin, subject_iri=case.namespace + "Concept", limit=1
    )
    case.known = datetime.now(UTC)
    case.dataset_hash = prepared["canonical_dataset"]["sha256"]
    return case


def access_headers(monkeypatch, principal):
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS", json.dumps({"synthetic-query": principal.model_dump(mode="json")})
    )
    get_settings.cache_clear()
    return {"Authorization": "Bearer synthetic-query"}


def assert_inspection_boundary(result, case, mode="CURRENT_RELEASE"):
    assert result["release"] == case.release_pin.model_dump(mode="json")
    assert result["mode"] == mode
    assert result["business_effect_authorized"] is False
    assert result["current_use_authorized"] is False


@DB
def test_real_release_rebuild_and_bounded_term_read_through_authenticated_routes(
    release_case, monkeypatch
):
    case = release_case
    before = scoped_versions(case.maker)
    headers = access_headers(monkeypatch, case.maker)
    with TestClient(app, headers=headers) as client:
        metadata = client.post(
            "/v1/ontology/external/releases/inspect",
            json=case.inspect_request.model_dump(mode="json"),
        )
        assert metadata.status_code == 200, metadata.text
        assert_inspection_boundary(metadata.json(), case)
        assert metadata.json()["definition"]["canonical_dataset"]["sha256"] == case.dataset_hash
        rebuilt = client.post(
            "/v1/ontology/external/index/rebuild", json=case.inspect_request.model_dump(mode="json")
        )
        assert rebuilt.status_code == 200, rebuilt.text
        assert_inspection_boundary(rebuilt.json(), case)
        expected_scope = {
            "tenant_id": str(case.maker.scope.tenant_id),
            "legal_entity_id": case.maker.scope.legal_entity_id,
            "release_id": str(case.release_pin.resource_id),
            "release_version_id": str(case.release_pin.version_id),
            "release_content_hash": case.release_pin.content_hash,
            "dataset_sha256": case.dataset_hash,
        }
        assert rebuilt.json()["projection"]["scope"] == expected_scope
        assert rebuilt.json()["projection"]["graph_iris"] == [case.namespace + "artifact"]
        assert rebuilt.json()["projection"]["quad_count"] == 3
        bounded = client.post(
            "/v1/ontology/external/terms/inspect", json=case.term_request.model_dump(mode="json")
        )
        assert bounded.status_code == 200, bounded.text
        result = bounded.json()
        assert_inspection_boundary(result, case)
        assert result["reasoning"] == "NONE"
        assert result["constraint_validation"] == "NOT_PERFORMED"
        projection = result["projection"]
        assert projection["scope"] == expected_scope
        assert projection["subject_iri"] == case.namespace + "Concept"
        assert projection["derived_only"] is True
        assert projection["truncated"] is True
        assert len(projection["quads"]) == 1
        assert projection["quads"][0]["graph_iri"] == case.namespace + "artifact"
        assert projection["quads"][0]["subject"] == "<" + case.namespace + "Concept>"
        capture_path = os.getenv("G8_ONTOLOGY_CAPTURE_PATH")
        if capture_path:
            target = Path(capture_path)
            assert target.is_absolute() and target.drive.lower() == "d:"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    {
                        "evidence_class": "SYNTHETIC_NATIVE_WIRE_CONTRACT",
                        "request": {
                            "release": case.inspect_request.model_dump(mode="json"),
                            "term": case.term_request.model_dump(mode="json"),
                        },
                        "metadata": metadata.json(),
                        "rebuild": rebuilt.json(),
                        "term": result,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    # Indexing and inspection must not create versions in canonical business truth.
    assert scoped_versions(case.maker) == before


@DB
def test_wrong_exact_pin_hash_scope_and_prepublication_time_refuse_before_index(
    release_case, monkeypatch
):
    from finai_api.services import ontology_index

    case = release_case
    forbidden = Mock(side_effect=AssertionError("Unauthorized release reached index worker"))
    monkeypatch.setattr(ontology_index, "inspect_subject", forbidden)
    for field in ("resource_id", "version_id", "content_hash"):
        value = "0" * 64 if field == "content_hash" else uuid4()
        request = case.term_request.model_copy(
            update={"release": case.release_pin.model_copy(update={field: value})}
        )
        with pytest.raises(WorkspaceError) as refused:
            queries.project(case.reader, request, rebuild=False)
        assert refused.value.status == (409 if field == "content_hash" else 404)
    outsider = case.reader.model_copy(
        update={
            "scope": case.reader.scope.model_copy(
                update={
                    "legal_entity_id": "synthetic-other-query-" + uuid4().hex,
                }
            )
        }
    )
    with pytest.raises(WorkspaceError) as hidden:
        queries.project(outsider, case.term_request, rebuild=False)
    assert hidden.value.status == 404
    before = datetime.fromisoformat(str(case.release_row["system_from"])) - timedelta(
        microseconds=1
    )
    request = case.term_request.model_copy(
        update={"mode": "HISTORICAL_INSPECTION", "known_at": before}
    )
    with pytest.raises(WorkspaceError) as unborn:
        queries.project(case.reader, request, rebuild=False)
    assert unborn.value.status == 404
    forbidden.assert_not_called()


def withdraw_release(case):
    request = LifecycleRequest(
        subject=VersionReference(
            resource_id=case.release_pin.resource_id, version_id=case.release_pin.version_id
        ),
        target_state="OBSERVED",
        epistemic_state="OBSERVED",
        business_state="PROVISIONAL",
        availability_state="UNAVAILABLE",
        reason=REASON,
    )
    resource_lifecycle.request_transition(case.maker, request)
    resource_lifecycle.review_transition(
        case.checker, request.request_id, LifecycleReview(decision="APPROVED", reason=REASON)
    )


@DB
@pytest.mark.parametrize(
    "change", ["publisher_upgrade", "publisher_withdrawal", "release_withdrawal"]
)
def test_current_authority_change_denies_use_but_exact_historical_inspection_keeps_old_bytes(
    release_case, change
):
    case = release_case
    queries.project(case.maker, case.inspect_request, rebuild=True)
    before = queries.project(case.reader, case.term_request, rebuild=False)
    if change == "publisher_upgrade":
        successor = imports.mutation(
            case.maker,
            "ExternalOntologySource",
            case.definition.model_copy(
                update={
                    "publisher": "Synthetic successor metadata",
                }
            ),
        ).model_copy(update={"expected_version_id": UUID(str(case.source_row["version_id"]))})
        case.publish(successor)
    elif change == "publisher_withdrawal":
        lifecycle_change(case, "OBSERVED", availability="UNAVAILABLE")
    else:
        withdraw_release(case)
    with pytest.raises(WorkspaceError) as current:
        queries.project(case.reader, case.term_request, rebuild=False)
    assert current.value.status == 409
    historical = case.term_request.model_copy(
        update={"mode": "HISTORICAL_INSPECTION", "known_at": case.known}
    )
    result = queries.project(case.reader, historical, rebuild=False)
    assert_inspection_boundary(result, case, "HISTORICAL_INSPECTION")
    assert result["known_at"] == case.known
    assert result["projection"] == before["projection"]
    metadata = queries.release_metadata(
        case.reader,
        ReleaseInspectionRequest(
            release=case.release_pin,
            mode="HISTORICAL_INSPECTION",
            known_at=case.known,
        ),
    )
    assert metadata["definition"]["canonical_dataset"]["sha256"] == case.dataset_hash
    assert metadata["definition"]["request"]["source"] == resource_pin(case.source_row).model_dump(
        mode="json"
    )


@DB
def test_cached_index_still_requires_original_retained_bytes_before_worker_access(
    release_case, monkeypatch
):
    from finai_api.services import ontology_index

    case = release_case
    queries.project(case.maker, case.inspect_request, rebuild=True)
    read_document = imports.read_document
    inspect_subject = ontology_index.inspect_subject
    events = []

    def read(principal, reference):
        assert principal == case.reader
        assert reference.sha256 == case.dataset_hash
        events.append("retained-bytes")
        return read_document(principal, reference)

    def inspect(*args, **kwargs):
        events.append("index-worker")
        return inspect_subject(*args, **kwargs)

    monkeypatch.setattr(imports, "read_document", read)
    monkeypatch.setattr(ontology_index, "inspect_subject", inspect)
    queries.project(case.reader, case.term_request, rebuild=False)
    assert events == ["retained-bytes", "index-worker"]
    monkeypatch.setattr(
        imports, "read_document", Mock(side_effect=WorkspaceError(409, "Retained artifact changed"))
    )
    forbidden = Mock(side_effect=AssertionError("Index substituted for unavailable retained bytes"))
    monkeypatch.setattr(ontology_index, "inspect_subject", forbidden)
    with pytest.raises(WorkspaceError, match="Retained artifact changed"):
        queries.project(case.reader, case.term_request, rebuild=False)
    forbidden.assert_not_called()


@DB
def test_withdrawal_during_worker_denies_result_after_revalidation(release_case, monkeypatch):
    from finai_api.services import ontology_index

    case = release_case
    queries.project(case.maker, case.inspect_request, rebuild=True)
    inspect_subject = ontology_index.inspect_subject
    finished = []

    def inspect_then_withdraw(*args, **kwargs):
        result = inspect_subject(*args, **kwargs)
        finished.append(result)
        lifecycle_change(case, "OBSERVED", availability="UNAVAILABLE")
        return result

    monkeypatch.setattr(ontology_index, "inspect_subject", inspect_then_withdraw)
    with pytest.raises(WorkspaceError) as denied:
        queries.project(case.reader, case.term_request, rebuild=False)
    assert denied.value.status == 409
    assert len(finished) == 1  # A completed projection cannot outrun current authority withdrawal.


@pytest.mark.parametrize(
    "path,permissions,missing",
    [
        ("releases/inspect", (), "ontology_read"),
        ("terms/inspect", (), "ontology_read"),
        ("index/rebuild", ("ontology_read",), "ontology_propose"),
        ("index/rebuild", ("ontology_propose",), "ontology_read"),
    ],
)
def test_external_query_api_permissions_precede_any_release_or_index_read(
    monkeypatch, path, permissions, missing
):
    principal = Principal(
        actor_id="synthetic-index-limited",
        display_name="Synthetic limited analyst",
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id="synthetic-index-permission",
            period="2026-09",
            currency="GEL",
        ),
        permissions=permissions,
    )
    request = TermInspectionRequest(
        release=Pin(resource_id=uuid4(), version_id=uuid4(), content_hash="a" * 64),
        subject_iri="https://example.invalid/fixture/Concept",
    )
    payload = (
        request.model_dump(mode="json")
        if path == "terms/inspect"
        else ReleaseInspectionRequest(release=request.release).model_dump(mode="json")
    )
    forbidden = Mock(side_effect=AssertionError("Permission refusal reached resource storage"))
    monkeypatch.setattr(resources, "resource_connection", forbidden)
    with TestClient(app, headers=access_headers(monkeypatch, principal)) as client:
        response = client.post("/v1/ontology/external/" + path, json=payload)
        assert response.status_code == 403, response.text
        assert missing in response.json()["detail"]
        anonymous = client.post(
            "/v1/ontology/external/" + path,
            headers={"Authorization": "Bearer invalid"},
            json=payload,
        )
        assert anonymous.status_code == 401
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"subject_iri": "relative-identifier"},
        {"mode": "HISTORICAL_INSPECTION"},
        {"mode": "HISTORICAL_INSPECTION", "known_at": "2026-09-08T00:00:00"},
        {"known_at": "2026-09-08T00:00:00Z"},
        {"query": "SELECT * WHERE {?s ?p ?o}"},
    ],
)
def test_query_contract_refuses_unbounded_untyped_or_ambiguous_time_requests(changes):
    payload = {
        "release": {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "content_hash": "a" * 64,
        },
        "subject_iri": "https://example.invalid/fixture/Concept",
        **changes,
    }
    with pytest.raises(ValidationError):
        TermInspectionRequest.model_validate(payload)
