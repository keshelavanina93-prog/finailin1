"""Opt-in native import/review of synthetic retained RDF in a unique entity scope.

These fixtures do not establish authentic external-source, financial, reasoning or
constraint-validation acceptance. They exercise the shared canonical review path,
retained document storage and offline RDF engine without fetching a publisher URL.
"""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from pydantic import ValidationError
from test_definition_history import DB, retained  # noqa: F401

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.external_ontology import ImportRequest, SourceDefinition
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import LifecycleRequest, LifecycleReview, VersionReference
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import Pin
from finai_api.main import app
from finai_api.services import ontology_import as imports
from finai_api.services import resource_lifecycle, resources, source_documents
from finai_api.services.workspace import WorkspaceError

REASON = "Review synthetic offline external meaning only; no enterprise facts or reasoning."


def approve(checker, proposal_id):
    return resources.review(
        checker, UUID(str(proposal_id)), ResourceReview(decision="APPROVED", rationale=REASON)
    )


def resource_pin(row):
    return Pin.model_validate(
        {key: row[key] for key in ("resource_id", "version_id", "content_hash")}
    )


def source_definition(namespace):
    return SourceDefinition(
        publisher="Synthetic offline ontology publisher",
        source_url=namespace + "publisher",
        namespaces=[namespace],
        license="Synthetic fixture declaration; not an external licensing determination",
        supported_formats=["TURTLE"],
    )


def request_for(source, definition, document, namespace, *, release="fixture-release-1"):
    return ImportRequest.model_validate(
        {
            "source": source.model_dump(mode="json"),
            "release_label": release,
            "publication_status": "DEVELOPMENT",
            "modules": [
                {
                    "source": source.model_dump(mode="json"),
                    "artifact_iri": namespace + "artifact",
                    "document": document,
                    "format": "TURTLE",
                    "owned_namespaces": [namespace],
                    "permitted_import_iris": [],
                    "source_url": namespace + "artifact.ttl",
                    "license": definition.license,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
            ],
        }
    )


@pytest.fixture
def native_import(retained):  # noqa: F811
    reader, publish = retained
    maker = reader.model_copy(
        update={
            "permissions": (
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
                "ingest",
            )
        }
    )
    checker = maker.model_copy(update={"actor_id": "synthetic-external-import-checker"})
    namespace = "https://example.invalid/g8-fixture/" + uuid4().hex + "/"
    definition = source_definition(namespace)
    source_proposal = imports.propose_source(maker, definition)
    assert source_proposal.decision is None
    source_id = source_proposal.proposal.mutations[0].resource_id
    with pytest.raises(WorkspaceError) as self_review:
        approve(maker, source_proposal.proposal.proposal_id)
    assert self_review.value.status == 403
    approve(checker, source_proposal.proposal.proposal_id)
    source_row = resources.get_resource(reader, source_id)["resource"]
    raw = (
        f"@prefix ex: <{namespace}> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "ex:artifact a owl:Ontology .\n"
        'ex:Concept a owl:Class ; rdfs:label "Synthetic concept" .\n'
    ).encode()
    document = imports.retained(maker, "synthetic-external-ontology.ttl", raw)
    request = request_for(
        resource_pin(source_row), definition, document.model_dump(mode="json"), namespace
    )
    return SimpleNamespace(
        reader=reader,
        maker=maker,
        checker=checker,
        publish=publish,
        namespace=namespace,
        definition=definition,
        source_id=source_id,
        source_row=source_row,
        raw=raw,
        document=document,
        request=request,
    )


def dependency_rows(principal, version_id):
    with (
        resources.resource_connection(principal) as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        return cursor.execute(
            "SELECT d.relation,d.target_resource_id,d.target_version_id,v.object_type,v.attributes "
            "FROM resource_dependencies d JOIN resource_versions v "
            "ON v.tenant_id=d.tenant_id AND v.version_id=d.target_version_id "
            "WHERE d.tenant_id=%s AND d.version_id=%s",
            (principal.scope.tenant_id, UUID(str(version_id))),
        ).fetchall()


def scoped_versions(principal):
    with resources.resource_connection(principal) as connection:
        return connection.execute(
            "SELECT resource_id,version_id FROM resource_versions "
            "WHERE tenant_id=%s AND access_entity=%s ORDER BY resource_id,version_id",
            (principal.scope.tenant_id, principal.scope.legal_entity_id),
        ).fetchall()


def proposal_from(response):
    assert response["status"] == "REVIEW_REQUIRED", response
    return ResourceProposal.model_validate(response["proposal"]["proposal"])


def no_release(case, release_id):
    with pytest.raises(WorkspaceError) as missing:
        resources.get_resource(case.reader, UUID(str(release_id)))
    assert missing.value.status == 404


@DB
def test_retained_turtle_review_replay_and_exact_canonical_lineage(native_import):
    case = native_import
    prepared = imports.prepare(case.maker, case.request)
    proposal = proposal_from(prepared)
    assert prepared["business_effect_authorized"] is False
    assert prepared["constraint_validation"] == "NOT_PERFORMED"
    no_release(case, prepared["release_id"])
    replay = imports.prepare(case.maker, case.request)
    assert replay["proposal"] == prepared["proposal"]
    assert replay["canonical_dataset"] == prepared["canonical_dataset"]
    assert replay["report"] == prepared["report"]
    assert {mutation.object_type for mutation in proposal.mutations} == {
        "SourceEvidence",
        "ExternalOntologyRelease",
        "ExternalOntologyModule",
        "OntologyImportRun",
    }
    with pytest.raises(WorkspaceError) as self_review:
        approve(case.maker, proposal.proposal_id)
    assert self_review.value.status == 403
    no_release(case, prepared["release_id"])
    approved = approve(case.checker, proposal.proposal_id)
    assert approved.decision == "APPROVED"
    approved_rows = {
        mutation.resource_id: resources.get_resource(case.reader, mutation.resource_id)["resource"]
        for mutation in proposal.mutations
    }
    release = approved_rows[UUID(prepared["release_id"])]
    definition = release["attributes"]["definition"]
    assert definition["interpretation"] == "EXTERNAL_MEANING_ONLY"
    assert definition["reasoning"] == "NONE"
    assert definition["constraint_validation"] == "NOT_PERFORMED"
    dependencies = dependency_rows(case.reader, release["version_id"])
    publisher_pins = [
        row for row in dependencies if row["relation"].startswith("EXTERNAL_ONTOLOGY_SOURCE:")
    ]
    assert publisher_pins
    assert {
        (str(row["target_resource_id"]), str(row["target_version_id"])) for row in publisher_pins
    } == {(str(case.source_id), str(case.source_row["version_id"]))}
    for mutation in proposal.mutations:
        row = approved_rows[mutation.resource_id]
        if row["object_type"] == "SourceEvidence":
            assert mutation.resource_id == canonical_id(
                case.maker.scope.tenant_id, "SourceEvidence", row["attributes"]["sha256"]
            )
            assert row["evidence_class"] == "SOURCE_BOUND"
            continue
        references = dependency_rows(case.reader, row["version_id"])
        evidence = [ref for ref in references if ref["relation"] == "FIELD:evidence_id"]
        assert len(evidence) == 1
        assert evidence[0]["object_type"] == "SourceEvidence"
        assert str(evidence[0]["target_resource_id"]) == row["attributes"]["evidence_id"]
        if row["object_type"] in {"ExternalOntologyModule", "OntologyImportRun"}:
            parents = [ref for ref in references if ref["relation"] == "EXTERNAL_ONTOLOGY_RELEASE"]
            assert len(parents) == 1
            assert str(parents[0]["target_resource_id"]) == prepared["release_id"]
            assert str(parents[0]["target_version_id"]) == str(release["version_id"])
    metadata, original = source_documents.document_bytes(case.maker, case.document.document_id)
    assert original == case.raw
    assert metadata["source_sha256"] == sha256(case.raw).hexdigest()
    _, dataset = source_documents.document_bytes(
        case.maker, prepared["canonical_dataset"]["document_id"]
    )
    _, report_bytes = source_documents.document_bytes(case.maker, prepared["report"]["document_id"])
    report = json.loads(report_bytes)
    assert sha256(dataset).hexdigest() == prepared["canonical_dataset"]["sha256"]
    assert report["canonical_sha256"] == sha256(dataset).hexdigest()
    assert report["artifacts"][0]["sha256"] == sha256(case.raw).hexdigest()
    assert report["outcome"] == "PARSED_ONLY"
    assert report["business_effect_authorized"] is False
    assert case.namespace.encode() in dataset
    before = scoped_versions(case.maker)
    replay = imports.prepare(case.maker, case.request)
    assert replay["status"] == "ALREADY_RETAINED"
    assert replay["release_id"] == prepared["release_id"]
    assert scoped_versions(case.maker) == before


@DB
@pytest.mark.parametrize("different_scope", ["tenant", "entity", "currency"])
def test_external_import_cannot_resolve_publisher_or_bytes_from_another_scope(
    native_import, different_scope
):
    case = native_import
    update = (
        {"tenant_id": uuid4()}
        if different_scope == "tenant"
        else {"legal_entity_id": "other-synthetic-" + uuid4().hex}
        if different_scope == "entity"
        else {"currency": "USD"}
    )
    outsider = case.maker.model_copy(update={"scope": case.maker.scope.model_copy(update=update)})
    before = scoped_versions(case.maker)
    with pytest.raises(WorkspaceError) as refused:
        imports.prepare(outsider, case.request)
    assert refused.value.status == 404
    assert scoped_versions(case.maker) == before
    with pytest.raises(WorkspaceError) as document:
        source_documents.document_bytes(outsider, case.document.document_id)
    assert document.value.status == 404


@DB
@pytest.mark.parametrize("artifact", ["canonical_dataset", "import_report"])
def test_forged_dataset_or_report_cannot_become_a_reviewable_release(native_import, artifact):
    case = native_import
    prepared = imports.prepare(case.maker, case.request)
    original = proposal_from(prepared)
    forged_bytes = ("Synthetic forged " + artifact + " " + uuid4().hex).encode()
    forged_ref = imports.retained(case.maker, "synthetic-forgery.txt", forged_bytes)
    changes = []
    for candidate in original.mutations:
        if candidate.object_type == "ExternalOntologyRelease":
            attributes = deepcopy(candidate.attributes)
            attributes["definition"][artifact] = forged_ref.model_dump(mode="json")
            candidate = candidate.model_copy(update={"attributes": attributes})
        changes.append(candidate)
    forged = original.model_copy(update={"proposal_id": uuid4(), "mutations": changes})
    before = scoped_versions(case.maker)
    with pytest.raises(WorkspaceError) as refused:
        resources.propose(case.maker, forged)
    assert refused.value.status == 409
    assert any(
        word in refused.value.detail.lower()
        for word in ("dataset", "report", "replay", "evidence", "artifact")
    )
    assert scoped_versions(case.maker) == before
    no_release(case, prepared["release_id"])
    assert resources.proposal_detail(case.maker, original.proposal_id).decision is None


def lifecycle_change(case, state, availability="AVAILABLE", expected=None):
    request = LifecycleRequest(
        subject=VersionReference(
            resource_id=case.source_id, version_id=case.source_row["version_id"]
        ),
        expected_event_id=expected,
        target_state=state,
        epistemic_state="OBSERVED",
        business_state="PROVISIONAL",
        availability_state=availability,
        reason=REASON,
    )
    resource_lifecycle.request_transition(case.maker, request)
    resource_lifecycle.review_transition(
        case.checker,
        request.request_id,
        LifecycleReview(
            decision="APPROVED",
            reason=REASON,
        ),
    )
    return resource_lifecycle.history(case.maker, request.subject)["events"][-1]["event_id"]


@DB
@pytest.mark.parametrize(
    "fault", ["stale", "registry_revoked", "lifecycle_revoked", "unavailable", "future"]
)
def test_import_refuses_stale_revoked_unavailable_or_future_publisher(native_import, fault):
    case = native_import
    if fault in {"stale", "registry_revoked"}:
        changed = case.definition.model_copy(update={"publisher": "Reviewed successor publisher"})
        item = imports.mutation(case.maker, "ExternalOntologySource", changed).model_copy(
            update={
                "expected_version_id": UUID(str(case.source_row["version_id"])),
                "authority_state": "REVOKED" if fault == "registry_revoked" else "APPROVED",
            }
        )
        case.publish(item)
    elif fault == "lifecycle_revoked":
        event = lifecycle_change(case, "OBSERVED")
        lifecycle_change(case, "REVOKED", expected=event)
    elif fault == "unavailable":
        lifecycle_change(case, "OBSERVED", availability="UNAVAILABLE")
    else:
        # A future-only publisher identity is editable metadata, not current import authority.
        definition = source_definition(case.namespace + "future/")
        item = imports.mutation(case.maker, "ExternalOntologySource", definition).model_copy(
            update={
                "valid_from": datetime.now(UTC) + timedelta(days=30),
            }
        )
        future = case.publish(item)[0]
        request_data = case.request.model_dump(mode="json")
        future_pin = resource_pin(future).model_dump(mode="json")
        request_data["source"] = future_pin
        request_data["modules"][0].update(
            source=future_pin,
            owned_namespaces=[case.namespace + "future/"],
            source_url=definition.source_url,
        )
        case.request = ImportRequest.model_validate(request_data)
    before = scoped_versions(case.maker)
    with pytest.raises(WorkspaceError) as refused:
        imports.prepare(case.maker, case.request)
    assert refused.value.status in {404, 409}
    assert scoped_versions(case.maker) == before


@DB
def test_source_withdrawal_after_preparation_blocks_review_and_preserves_pending_proposal(
    native_import,
):
    case = native_import
    prepared = imports.prepare(case.maker, case.request)
    proposal = proposal_from(prepared)
    lifecycle_change(case, "OBSERVED", availability="UNAVAILABLE")
    before = scoped_versions(case.maker)
    with pytest.raises(WorkspaceError) as refused:
        approve(case.checker, proposal.proposal_id)
    assert refused.value.status == 409
    assert resources.proposal_detail(case.maker, proposal.proposal_id).decision is None
    no_release(case, prepared["release_id"])
    assert scoped_versions(case.maker) == before


@DB
def test_reviewed_release_cannot_be_rewritten_under_its_existing_identity(native_import):
    case = native_import
    prepared = imports.prepare(case.maker, case.request)
    proposal = proposal_from(prepared)
    approve(case.checker, proposal.proposal_id)
    original = next(
        item for item in proposal.mutations if item.object_type == "ExternalOntologyRelease"
    )
    current = resources.get_resource(case.reader, original.resource_id)["resource"]
    attributes = deepcopy(original.attributes)
    attributes["definition"]["request"]["publication_status"] = "PRODUCTION"
    attributes["definition"]["request_sha256"] = imports.digest(attributes["definition"]["request"])
    # Make the attempted successor internally replayable so refusal proves release
    # immutability, rather than merely detecting an outdated report hash.
    changed_request = ImportRequest.model_validate(attributes["definition"]["request"])
    _, changed_report = imports.compile_retained(case.maker, changed_request)
    attributes["definition"]["import_report"] = imports.retained(
        case.maker, "synthetic-successor-report.json", imports.encoded(changed_report)
    ).model_dump(mode="json")
    successor = original.model_copy(
        update={
            "expected_version_id": UUID(str(current["version_id"])),
            "attributes": attributes,
        }
    )
    before = scoped_versions(case.maker)
    with pytest.raises(WorkspaceError, match="immutable") as refused:
        resources.propose(
            case.maker,
            ResourceProposal(
                title="Synthetic forbidden release rewrite",
                rationale=REASON,
                access_entity=case.maker.scope.legal_entity_id,
                mutations=[successor],
            ),
        )
    assert refused.value.status == 409
    assert scoped_versions(case.maker) == before
    assert resources.get_resource(case.reader, original.resource_id)["resource"] == current


@DB
def test_external_identity_forgery_cannot_fork_shared_canonical_resources(native_import):
    case = native_import
    source = imports.mutation(case.maker, "ExternalOntologySource", case.definition).model_copy(
        update={"resource_id": uuid4()}
    )
    before = scoped_versions(case.maker)
    with pytest.raises(WorkspaceError) as refused:
        resources.propose(
            case.maker,
            ResourceProposal(
                title="Synthetic forged external publisher identity",
                rationale=REASON,
                access_entity=case.maker.scope.legal_entity_id,
                mutations=[source],
            ),
        )
    assert refused.value.status == 422
    assert "identity" in refused.value.detail.lower()
    assert scoped_versions(case.maker) == before


@DB
def test_engine_refusal_is_retained_without_releasing_any_canonical_ontology(native_import):
    case = native_import
    malformed = imports.retained(case.maker, "synthetic-invalid.ttl", b"This is not valid Turtle {")
    request = case.request.model_copy(
        update={
            "modules": [case.request.modules[0].model_copy(update={"document": malformed})],
        }
    )
    before = scoped_versions(case.maker)
    result = imports.prepare(case.maker, request)
    assert result["status"] == "REFUSED"
    assert result["code"] == "MALFORMED_RDF"
    assert "release_id" not in result and "proposal" not in result
    _, content = source_documents.document_bytes(case.maker, result["report"]["document_id"])
    refusal = json.loads(content)
    assert refusal["outcome"] == "REFUSED" and refusal["code"] == "MALFORMED_RDF"
    assert refusal["business_effect_authorized"] is False
    assert refusal["request"]["modules"][0]["document"]["sha256"] == malformed.sha256
    assert sha256(content).hexdigest() == result["report"]["sha256"]
    assert scoped_versions(case.maker) == before


@pytest.mark.parametrize("missing_permission", ["ontology_propose", "ingest", "ontology_read"])
def test_import_api_permission_refusal_precedes_source_and_parser_access(
    monkeypatch, missing_permission
):
    namespace = "https://example.invalid/permission-fixture/" + uuid4().hex + "/"
    definition = source_definition(namespace)
    source = Pin(resource_id=uuid4(), version_id=uuid4(), content_hash="a" * 64)
    request = request_for(
        source,
        definition,
        {
            "document_id": "doc_" + "b" * 64,
            "sha256": "c" * 64,
            "byte_length": 10,
        },
        namespace,
    )
    principal = Principal(
        actor_id="synthetic-import-limited",
        display_name="Synthetic limited importer",
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id="synthetic-import-permissions",
            period="2026-09",
            currency="GEL",
        ),
        permissions=tuple(
            permission
            for permission in ("ontology_propose", "ingest", "ontology_read")
            if permission != missing_permission
        ),
    )
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS", json.dumps({"synthetic-limited": principal.model_dump(mode="json")})
    )
    get_settings.cache_clear()
    forbidden = Mock(side_effect=AssertionError("Permission refusal reached source storage"))
    monkeypatch.setattr(imports, "current_sources", forbidden)
    with TestClient(app, headers={"Authorization": "Bearer synthetic-limited"}) as client:
        response = client.post(
            "/v1/ontology/external/imports/proposals", json=request.model_dump(mode="json")
        )
        assert response.status_code == 403, response.text
        assert missing_permission in response.json()["detail"]
        anonymous = client.post(
            "/v1/ontology/external/imports/proposals",
            headers={"Authorization": "Bearer invalid"},
            json=request.model_dump(mode="json"),
        )
        assert anonymous.status_code == 401
    forbidden.assert_not_called()
    with pytest.raises(HTTPException) as refused:
        imports.prepare(principal, request)
    assert refused.value.status_code == 403


def test_publisher_proposal_requires_explicit_proposal_permission(monkeypatch):
    principal = Principal(
        actor_id="synthetic-publisher-reader",
        display_name="Synthetic publisher reader",
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id="synthetic-publisher-read",
            period="2026-09",
            currency="GEL",
        ),
        permissions=("ontology_read",),
    )
    forbidden = Mock(side_effect=AssertionError("Read-only publisher reached canonical storage"))
    monkeypatch.setattr(resources, "current_resources", forbidden)
    with pytest.raises(HTTPException) as refused:
        imports.propose_source(principal, source_definition("https://example.invalid/fixture/"))
    assert refused.value.status_code == 403
    forbidden.assert_not_called()


@DB
def test_future_publisher_editing_head_keeps_current_exact_source_usable(native_import):
    case = native_import
    future_definition = case.definition.model_copy(
        update={"publisher": "Future synthetic publisher metadata"}
    )
    future = imports.mutation(case.maker, "ExternalOntologySource", future_definition).model_copy(
        update={
            "expected_version_id": UUID(str(case.source_row["version_id"])),
            "valid_from": datetime.now(UTC) + timedelta(days=30),
        }
    )
    future_row = case.publish(future)[0]
    assert str(future_row["version_id"]) != str(case.source_row["version_id"])
    assert datetime.fromisoformat(str(future_row["valid_from"])) > datetime.now(UTC)
    prepared = imports.prepare(case.maker, case.request)
    proposal = proposal_from(prepared)
    approve(case.checker, proposal.proposal_id)
    release = resources.get_resource(case.reader, UUID(prepared["release_id"]))["resource"]
    publishers = [
        row
        for row in dependency_rows(case.reader, release["version_id"])
        if row["relation"].startswith("EXTERNAL_ONTOLOGY_SOURCE:")
    ]
    assert publishers
    assert {str(row["target_version_id"]) for row in publishers} == {
        str(case.source_row["version_id"])
    }


@DB
@pytest.mark.parametrize("authority", ["APPROVED", "REVOKED"])
def test_import_proposal_cannot_mutate_its_own_pinned_publisher(native_import, authority):
    case = native_import
    prepared = imports.prepare(case.maker, case.request)
    retained_proposal = proposal_from(prepared)
    changed = imports.mutation(
        case.maker,
        "ExternalOntologySource",
        case.definition.model_copy(
            update={"publisher": "Same-proposal synthetic publisher change"}
        ),
    ).model_copy(
        update={
            "expected_version_id": UUID(str(case.source_row["version_id"])),
            "authority_state": authority,
        }
    )
    combined = retained_proposal.model_copy(
        update={
            "proposal_id": uuid4(),
            "mutations": [*retained_proposal.mutations, changed],
        }
    )
    before = scoped_versions(case.maker)
    with pytest.raises(WorkspaceError) as refused:
        resources.propose(case.maker, combined)
    assert refused.value.status in {409, 422}
    assert "publisher" in refused.value.detail.lower()
    assert scoped_versions(case.maker) == before
    assert resources.get_resource(case.reader, case.source_id)["resource"] == case.source_row
    no_release(case, prepared["release_id"])


def test_generic_proposal_limits_external_releases_before_any_parser_or_storage_access():
    from finai_api.domain.resources import ResourceMutation

    releases = [
        ResourceMutation(
            resource_id=uuid4(),
            object_type="ExternalOntologyRelease",
            identity_key="fixture:" + uuid4().hex,
            display_name="Synthetic release placeholder",
            attributes={},
            valid_from=datetime.now(UTC),
            evidence_class="SOURCE_BOUND",
        )
        for _ in range(2)
    ]
    with pytest.raises(ValidationError, match="only one release"):
        ResourceProposal(
            title="Synthetic oversized release proposal",
            rationale=REASON,
            access_entity="synthetic-max-release",
            mutations=releases,
        )


@DB
def test_expensive_rdf_replay_happens_before_tenant_publication_lock(native_import, monkeypatch):
    case = native_import
    real_compile = imports.compile_retained
    checks = []

    def compile_without_publication_lock(principal, request):
        # A distinct PostgreSQL transaction must acquire the publication lock
        # immediately while the real engine replays the retained source.
        with resources.resource_connection(principal) as connection:
            acquired = connection.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))",
                (f"canonical:{principal.scope.tenant_id}",),
            ).fetchone()[0]
            checks.append(acquired)
            assert acquired is True, "RDF replay held the tenant publication lock"
        return real_compile(principal, request)

    monkeypatch.setattr(imports, "compile_retained", compile_without_publication_lock)
    prepared = imports.prepare(case.maker, case.request)
    proposal = proposal_from(prepared)
    after_propose = len(checks)
    assert after_propose >= 2  # Preparation and generic publication preflight.
    approve(case.checker, proposal.proposal_id)
    assert len(checks) > after_propose  # Independent approval replays the exact bytes again.
    assert all(checks)


@DB
def test_same_bytes_in_second_company_return_private_identity_conflict_without_partial_release(
    native_import, monkeypatch
):
    case = native_import
    first = imports.prepare(case.maker, case.request)
    approve(case.checker, proposal_from(first).proposal_id)
    evidence_id = canonical_id(case.maker.scope.tenant_id, "SourceEvidence", case.document.sha256)
    original_evidence = resources.get_resource(case.reader, evidence_id)["resource"]

    second_maker = case.maker.model_copy(
        update={
            "actor_id": "synthetic-second-company-maker",
            "scope": case.maker.scope.model_copy(
                update={
                    "legal_entity_id": "synthetic-second-import-" + uuid4().hex,
                }
            ),
            "permissions": ("ontology_read", "ontology_propose", "ontology_review", "ingest"),
        }
    )
    second_checker = second_maker.model_copy(
        update={"actor_id": "synthetic-second-company-checker"}
    )
    source_proposal = imports.propose_source(second_maker, case.definition)
    approve(second_checker, source_proposal.proposal.proposal_id)
    second_source = resources.get_resource(
        second_maker, source_proposal.proposal.mutations[0].resource_id
    )["resource"]
    second_document = imports.retained(second_maker, "synthetic-same-bytes.ttl", case.raw)
    assert second_document.sha256 == case.document.sha256
    assert second_document.document_id != case.document.document_id
    assert resources.current_resources(second_maker, [evidence_id]) == {}
    second_request = request_for(
        resource_pin(second_source),
        case.definition,
        second_document.model_dump(mode="json"),
        case.namespace,
    )
    prepared = imports.prepare(second_maker, second_request)
    proposal = proposal_from(prepared)
    assert any(item.resource_id == evidence_id for item in proposal.mutations)
    before = scoped_versions(second_maker)
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "synthetic-second-reviewer": second_checker.model_dump(mode="json"),
            }
        ),
    )
    get_settings.cache_clear()
    with TestClient(app, headers={"Authorization": "Bearer synthetic-second-reviewer"}) as client:
        response = client.post(
            f"/v1/ontology/proposals/{proposal.proposal_id}/decision",
            json={
                "decision": "APPROVED",
                "rationale": REASON,
            },
        )
    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": "Canonical identity or access boundary conflict; steward review required",
    }
    for private_identifier in (
        str(case.maker.scope.tenant_id),
        case.maker.scope.legal_entity_id,
        second_maker.scope.legal_entity_id,
        str(evidence_id),
    ):
        assert private_identifier not in response.text
    assert resources.proposal_detail(second_maker, proposal.proposal_id).decision is None
    assert scoped_versions(second_maker) == before
    with pytest.raises(WorkspaceError) as unpublished:
        resources.get_resource(second_maker, UUID(prepared["release_id"]))
    assert unpublished.value.status == 404
    assert resources.get_resource(case.reader, evidence_id)["resource"] == original_evidence
    admin = second_maker.model_copy(
        update={
            "actor_id": "synthetic-second-company-steward",
            "permissions": (*second_maker.permissions, "ontology_admin"),
        }
    )
    with pytest.raises(WorkspaceError, match="dependency's entity access boundary") as denied:
        imports.prepare(admin, second_request)
    assert denied.value.status == 403
