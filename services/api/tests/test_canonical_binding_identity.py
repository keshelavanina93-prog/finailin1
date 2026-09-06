"""Bindings reuse declared canonical identities; synthetic fixtures prove no source authenticity."""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest

from finai_api.domain.object_sets import ObjectSetQuery, ObjectSetResult
from finai_api.domain.ontology_definitions import BindingDefinition
from finai_api.domain.resources import ResourceMutation
from finai_api.services import ontology_definitions as definitions
from finai_api.services.ontology_definition_validation import validate_definition
from finai_api.services.workspace import WorkspaceError


def spec(mode="CANONICAL_REFERENCE"):
    return {
        "identity_mode": mode,
        "identity_field": "company_id",
        "display_field": "label",
        "fields": [{"source_field": "label", "target_field": "jurisdiction"}],
    }


@pytest.mark.parametrize(
    "identity_spec",
    [
        {"kind": "identifier", "required": True},
        {"kind": "reference", "required": True, "target_type": "LocalAccount"},
        {"kind": "reference", "required": False, "target_type": "LegalEntity"},
    ],
)
def test_binding_identity_requires_a_required_reference_to_the_destination(identity_spec):
    source_id, target_id = str(uuid4()), str(uuid4())
    item = ResourceMutation(
        object_type="ObjectBinding",
        identity_key="synthetic:" + uuid4().hex,
        display_name="SYNTHETIC binding",
        valid_from=datetime.now(UTC),
        attributes={
            "source_schema_id": source_id,
            "target_schema_id": target_id,
            "definition": spec(),
        },
    )
    schemas = {
        source_id: {
            "attributes": {
                "fields": {"company_id": identity_spec, "label": {"kind": "text", "required": True}}
            }
        },
        target_id: {
            "identity_key": "LegalEntity",
            "attributes": {"fields": {"jurisdiction": {"kind": "text", "required": False}}},
        },
    }
    with pytest.raises(WorkspaceError, match="required reference"):
        validate_definition(item, {}, {}, lambda identity, *_: schemas[identity])
    schemas[source_id]["attributes"]["fields"]["company_id"] = {
        "kind": "reference",
        "required": True,
        "target_type": "LegalEntity",
    }
    validate_definition(item, {}, {}, lambda identity, *_: schemas[identity])


@pytest.fixture
def prepared(monkeypatch):
    company, current_version = uuid4(), uuid4()
    source = {"relation": "FIELD:source_schema_id", "resource_id": uuid4(), "version_id": uuid4()}
    target = {
        "relation": "FIELD:target_schema_id",
        "resource_id": uuid4(),
        "version_id": uuid4(),
        "identity_key": "LegalEntity",
    }
    binding = {
        "resource_id": uuid4(),
        "version_id": uuid4(),
        "object_type": "ObjectBinding",
        "display_name": "SYNTHETIC binding",
        "attributes": {"definition": spec()},
        "dependencies": [source, target],
    }
    current = {
        "resource_id": str(company),
        "version_id": str(current_version),
        "object_type": "LegalEntity",
        "identity_key": "company:canonical-existing",
    }
    row = {
        "resource_id": str(uuid4()),
        "version_id": str(uuid4()),
        "schema_version_id": str(source["version_id"]),
        "evidence_class": "SOURCE_BOUND",
        "attributes": {"company_id": str(company), "label": "SYNTHETIC mocked source"},
    }
    query = ObjectSetQuery(object_type="SourceJournalMovement")
    result = ObjectSetResult(
        query=query, total=1, counts_by_type={}, objects=[row], next_offset=None
    )
    monkeypatch.setattr(definitions, "definition", lambda *_: binding)
    monkeypatch.setattr(definitions, "query_objects", lambda *_: result)
    monkeypatch.setattr(definitions.resources, "get_resource", lambda *_: {"resource": current})
    resolved = {"canonical_id": str(company), "version_id": str(current_version)}
    monkeypatch.setattr(definitions.resources, "resolve_identity", lambda *_: resolved)
    principal = SimpleNamespace(scope=SimpleNamespace(legal_entity_id="synthetic-company"))

    def prepare():
        return definitions.prepare_binding(
            principal, binding["resource_id"], query, "Synthetic mocked source identity acceptance"
        )

    return SimpleNamespace(
        prepare=prepare,
        binding=binding,
        current=current,
        row=row,
        result=result,
        resolved=resolved,
        company=company,
    )


def test_distinct_bindings_reuse_one_canonical_identity_and_retain_exact_lineage(prepared):
    first = prepared.prepare()
    first_binding = prepared.binding["resource_id"]
    prepared.binding["resource_id"] = uuid4()
    prepared.binding["version_id"] = uuid4()
    second = prepared.prepare()
    for proposal in (first, second):
        mutation = proposal.mutations[0]
        assert mutation.resource_id == prepared.company
        assert str(mutation.expected_version_id) == prepared.current["version_id"]
        assert mutation.identity_key == "company:canonical-existing"
        assert proposal.source_versions[prepared.company][
            UUID(prepared.row["resource_id"])
        ] == UUID(prepared.row["version_id"])
    assert first_binding in first.source_versions[prepared.company]
    assert prepared.binding["resource_id"] in second.source_versions[prepared.company]


@pytest.mark.parametrize(
    "failure", ["missing", "wrong_type", "redirected", "changed_version", "invalid_uuid"]
)
def test_missing_wrong_or_changed_canonical_target_cannot_be_bound(prepared, monkeypatch, failure):
    if failure == "missing":

        def missing(*_):
            raise WorkspaceError(404, "Target unavailable")

        monkeypatch.setattr(definitions.resources, "get_resource", missing)
    elif failure == "wrong_type":
        prepared.current["object_type"] = "LocalAccount"
    elif failure == "redirected":
        prepared.resolved["canonical_id"] = str(uuid4())
    elif failure == "changed_version":
        prepared.resolved["version_id"] = str(uuid4())
    else:
        prepared.row["attributes"]["company_id"] = "source-local-company-code"
    with pytest.raises(WorkspaceError):
        prepared.prepare()


def test_duplicate_canonical_target_and_unbacked_source_remain_rejected(prepared):
    prepared.result.objects.append({**prepared.row, "resource_id": str(uuid4())})
    with pytest.raises(WorkspaceError, match="same target identity"):
        prepared.prepare()
    prepared.result.objects.pop()
    prepared.result.objects[0]["evidence_class"] = "REFERENCE_TEMPLATE"
    with pytest.raises(WorkspaceError, match="source-backed"):
        prepared.prepare()


def test_legacy_source_key_identity_remains_stable(prepared, monkeypatch):
    prepared.binding["attributes"]["definition"].pop("identity_mode")
    assert (
        BindingDefinition.model_validate(prepared.binding["attributes"]["definition"]).identity_mode
        == "SOURCE_KEY"
    )

    def missing(*_):
        raise WorkspaceError(404, "New source key")

    monkeypatch.setattr(definitions.resources, "get_resource", missing)
    first, second = prepared.prepare(), prepared.prepare()
    expected = uuid5(prepared.binding["resource_id"], str(prepared.company))
    assert first.mutations[0].resource_id == second.mutations[0].resource_id == expected
    assert first.mutations[0].expected_version_id is None


@pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained DB acceptance"
)
def test_promotion_validation_refuses_new_identity_and_redirected_canonical_target(monkeypatch):
    from finai_api.domain.authority import ExactScope
    from finai_api.domain.ontology_catalog import canonical_id
    from finai_api.domain.resources import ResourceProposal, ResourceReview
    from finai_api.domain.review import Principal
    from finai_api.services import resources

    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    operator = Principal(
        actor_id="synthetic-canonical-binding-proposer",
        display_name="Synthetic binding",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="synthetic-canonical-binding-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_admin", "ontology_propose", "ontology_review"),
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-canonical-binding-reviewer"})

    def item(kind, attrs):
        return ResourceMutation(
            object_type=kind,
            identity_key="synthetic:" + uuid4().hex,
            display_name="SYNTHETIC binding guard",
            attributes=attrs,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            evidence_class="REFERENCE_TEMPLATE",
        )

    def proposal(items, lineage=None):
        return ResourceProposal(
            title="SYNTHETIC canonical binding guard acceptance",
            rationale="Non-authentic isolated canonical identity guard acceptance",
            access_entity=operator.scope.legal_entity_id,
            mutations=items,
            source_versions=lineage or {},
        )

    def approve(value):
        resources.review(
            reviewer,
            value.proposal_id,
            ResourceReview(
                decision="APPROVED", rationale="Retain synthetic canonical binding guard acceptance"
            ),
        )

    binding_spec = spec()
    binding_spec.update(
        identity_field="legal_entity_id",
        display_field="document_reference",
        fields=[{"source_field": "document_reference", "target_field": "jurisdiction"}],
    )
    binding = item(
        "ObjectBinding",
        {
            "source_schema_id": str(
                canonical_id(tenant, "SchemaDefinition", "SourceJournalMovement")
            ),
            "target_schema_id": str(canonical_id(tenant, "SchemaDefinition", "LegalEntity")),
            "definition": binding_spec,
        },
    )
    company, master = item("LegalEntity", {}), item("LegalEntity", {})
    initial = proposal([binding, company, master])
    resources.propose(operator, initial)
    approve(initial)
    binding_version = UUID(
        resources.get_resource(operator, binding.resource_id)["resource"]["version_id"]
    )
    new = item("LegalEntity", {})
    with pytest.raises(WorkspaceError, match="cannot create identities"):
        resources.propose(
            operator, proposal([new], {new.resource_id: {binding.resource_id: binding_version}})
        )
    current = resources.get_resource(operator, company.resource_id)["resource"]
    update = company.model_copy(
        update={
            "expected_version_id": UUID(current["version_id"]),
            "attributes": {"jurisdiction": "SYNTHETIC"},
        }
    )
    pending = proposal([update], {company.resource_id: {binding.resource_id: binding_version}})
    resources.propose(operator, pending)
    redirect = item(
        "IdentityResolution",
        {
            "source_id": str(company.resource_id),
            "target_id": str(master.resource_id),
            "active": True,
            "survivorship": "Synthetic canonical master survives",
        },
    ).model_copy(update={"identity_key": f"identity:{company.resource_id}"})
    redirect_proposal = proposal([redirect])
    resources.propose(operator, redirect_proposal)
    approve(redirect_proposal)
    with pytest.raises(WorkspaceError, match="redirected"):
        approve(pending)

    # A later inactive head takes effect next month; it cannot erase today's active redirect.
    redirect_head = resources.get_resource(operator, redirect.resource_id)["resource"]
    inactive = redirect.model_copy(
        update={
            "expected_version_id": UUID(redirect_head["version_id"]),
            "valid_from": datetime.now(UTC) + timedelta(days=30),
            "attributes": {**redirect.attributes, "active": False},
        }
    )
    inactive_proposal = proposal([inactive])
    resources.propose(operator, inactive_proposal)
    approve(inactive_proposal)
    assert not resources.get_resource(operator, redirect.resource_id)["resource"]["attributes"][
        "active"
    ]
    with pytest.raises(WorkspaceError, match="redirected"):
        approve(pending)
    with pytest.raises(WorkspaceError, match="redirected"):
        resources.propose(
            operator,
            proposal(
                [update],
                {
                    company.resource_id: {binding.resource_id: binding_version},
                },
            ),
        )

    # Expiration advances valid time without changing the retained target head.
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    expiring = item("LegalEntity", {}).model_copy(update={"valid_to": expires_at})
    expiring_proposal = proposal([expiring])
    resources.propose(operator, expiring_proposal)
    approve(expiring_proposal)
    expiring_head = resources.get_resource(operator, expiring.resource_id)["resource"]
    expiring_update = expiring.model_copy(
        update={
            "expected_version_id": UUID(expiring_head["version_id"]),
            "attributes": {"jurisdiction": "SYNTHETIC proposed before expiration"},
        }
    )
    expiring_pending = proposal(
        [expiring_update],
        {
            expiring.resource_id: {binding.resource_id: binding_version},
        },
    )
    resources.propose(operator, expiring_pending)

    class AfterExpiration(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = expires_at + timedelta(seconds=1)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    with monkeypatch.context() as clock:
        clock.setattr(resources, "datetime", AfterExpiration)
        with pytest.raises(WorkspaceError, match="no longer effective"):
            approve(expiring_pending)
    assert (
        resources.get_resource(operator, expiring.resource_id)["resource"]["version_id"]
        == expiring_head["version_id"]
    )


@pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1",
    reason="Opt-in retained DB and object-store acceptance",
)
def test_retained_synthetic_document_binds_twice_to_one_existing_company():
    from psycopg.rows import dict_row

    from finai_api.domain.authority import ExactScope
    from finai_api.domain.ontology_catalog import canonical_id
    from finai_api.domain.resources import ResourceProposal, ResourceReview
    from finai_api.domain.review import Principal
    from finai_api.services import resources, source_documents

    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    operator = Principal(
        actor_id="synthetic-binding-retention-proposer",
        display_name="Synthetic retention operator",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="synthetic-binding-retention-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=(
            "ingest",
            "ontology_read",
            "ontology_admin",
            "ontology_propose",
            "ontology_review",
        ),
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-binding-retention-reviewer"})
    content = b"SYNTHETIC fixture: registration code SYNTHETIC-001. Not authentic company evidence."
    document = source_documents.retain_document(
        operator, "SYNTHETIC-binding-acceptance.txt", content
    )
    assert source_documents.document_bytes(operator, document["document_id"])[1] == content

    def item(kind, attrs, evidence_class="REFERENCE_TEMPLATE"):
        return ResourceMutation(
            object_type=kind,
            identity_key="synthetic:" + uuid4().hex,
            display_name="SYNTHETIC retained binding fixture",
            attributes=attrs,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            evidence_class=evidence_class,
        )

    def promote(value):
        resources.propose(operator, value)
        resources.review(
            reviewer,
            value.proposal_id,
            ResourceReview(
                decision="APPROVED",
                rationale="Synthetic retained bytes prove local binding mechanics only",
            ),
        )

    company = item("LegalEntity", {})
    evidence = item(
        "SourceEvidence",
        {"sha256": document["sha256"], "source_system": "SYNTHETIC_FIXTURE"},
        "SOURCE_BOUND",
    )
    chart = item(
        "LocalChartOfAccounts",
        {
            "legal_entity_id": str(company.resource_id),
            "code": "SYNTHETIC-001",
            "evidence_id": str(evidence.resource_id),
        },
        "SOURCE_BOUND",
    )
    binding_attributes = {
        "source_schema_id": str(canonical_id(tenant, "SchemaDefinition", "LocalChartOfAccounts")),
        "target_schema_id": str(canonical_id(tenant, "SchemaDefinition", "LegalEntity")),
        "definition": {
            "identity_mode": "CANONICAL_REFERENCE",
            "identity_field": "legal_entity_id",
            "display_field": "code",
            "fields": [
                {"source_field": "code", "target_field": "registration_code"},
                {"source_field": "evidence_id", "target_field": "evidence_id"},
            ],
        },
    }
    bindings = [item("ObjectBinding", binding_attributes) for _ in range(2)]
    promote(
        ResourceProposal(
            title="SYNTHETIC retained canonical binding fixtures",
            rationale="Retained synthetic document exercises persistence; no authenticity claimed",
            access_entity=operator.scope.legal_entity_id,
            mutations=[company, evidence, chart, *bindings],
        )
    )
    initial = resources.get_resource(operator, company.resource_id)["resource"]
    source_version = UUID(
        resources.get_resource(operator, chart.resource_id)["resource"]["version_id"]
    )
    previous_version = initial["version_id"]
    promoted_versions = []
    for binding in bindings:
        prepared = definitions.prepare_binding(
            operator,
            binding.resource_id,
            ObjectSetQuery(object_type="LocalChartOfAccounts", resource_ids=[chart.resource_id]),
            "SYNTHETIC retained source proposal; no authentic company evidence claimed",
        )
        mutation = prepared.mutations[0]
        assert len(prepared.mutations) == 1
        assert mutation.resource_id == company.resource_id
        assert mutation.identity_key == company.identity_key
        assert str(mutation.expected_version_id) == previous_version
        assert prepared.source_versions[company.resource_id][chart.resource_id] == source_version
        assert binding.resource_id in prepared.source_versions[company.resource_id]
        promote(prepared)
        accepted = resources.get_resource(operator, company.resource_id)["resource"]
        assert accepted["identity_key"] == company.identity_key
        assert accepted["attributes"] == {
            "registration_code": "SYNTHETIC-001",
            "evidence_id": str(evidence.resource_id),
        }
        assert accepted["version_id"] != previous_version
        with (
            resources.resource_connection(operator) as conn,
            conn.cursor(row_factory=dict_row) as cursor,
        ):
            pins = cursor.execute(
                "SELECT target_resource_id,target_version_id FROM resource_dependencies "
                "WHERE tenant_id=%s AND version_id=%s AND relation LIKE 'BOUND_SOURCE:%%'",
                (tenant, UUID(accepted["version_id"])),
            ).fetchall()
        assert {
            pin["target_resource_id"]: pin["target_version_id"] for pin in pins
        } == prepared.source_versions[company.resource_id]
        previous_version = accepted["version_id"]
        promoted_versions.append(previous_version)
    history = resources.get_resource(operator, company.resource_id)
    assert {row["version_id"] for row in history["versions"]} == {
        initial["version_id"],
        *promoted_versions,
    }
    assert {row["resource_id"] for row in history["versions"]} == {str(company.resource_id)}

    # Only retained-version lineage may be excluded from live cycle topology.
    # Mutually bound versions in this same publication remain a genuine dependency cycle.
    left, right = item("LegalEntity", {}), item("LegalEntity", {})
    cycle_id = uuid4()
    cyclic = ResourceProposal(
        proposal_id=cycle_id,
        title="SYNTHETIC co-proposed source lineage cycle",
        rationale="Mutually proposed versions must not bypass the live dependency cycle guard",
        access_entity=operator.scope.legal_entity_id,
        mutations=[left, right],
        source_versions={
            left.resource_id: {right.resource_id: uuid5(cycle_id, str(right.resource_id))},
            right.resource_id: {left.resource_id: uuid5(cycle_id, str(left.resource_id))},
        },
    )
    with pytest.raises(WorkspaceError, match="cycle"):
        resources.propose(operator, cyclic)
