"""Atomic mixed-policy definition acceptance, not execution of Functions or Reports."""

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

import psycopg
import pytest

from finai_api.domain.authority import ExactScope, canonical_sha256
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


def mutation(
    kind: str, policy: str | None, attributes: dict, identity: str | None = None
) -> ResourceMutation:
    return ResourceMutation(
        object_type=kind,
        access_entity=policy,
        identity_key=identity or "synthetic:" + uuid4().hex,
        display_name="SYNTHETIC " + kind,
        attributes=attributes,
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
    )


def test_omitted_policy_preserves_legacy_mutation_and_proposal_hashes() -> None:
    item = mutation("LegalEntity", None, {})
    old = item.model_dump(mode="json")
    assert "access_entity" not in old
    assert old["expected_version_id"] is None and old["valid_to"] is None
    assert (
        canonical_sha256(item)
        == sha256(json.dumps(old, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    proposal = ResourceProposal(
        title="Synthetic legacy payload",
        rationale="Legacy serialization preservation",
        access_entity="company-a",
        mutations=[item],
    )
    legacy = proposal.model_dump(mode="json")
    assert "access_entity" not in legacy["mutations"][0]
    parsed = ResourceProposal.model_validate(legacy)
    assert (
        canonical_sha256(parsed)
        == sha256(json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )


@pytest.fixture
def identities() -> tuple[Principal, Principal]:
    operator = Principal(
        actor_id="synthetic-mixed-proposer",
        display_name="Synthetic mixed proposer",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="synthetic-mixed-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_admin", "ontology_propose", "ontology_review", "ontology_read"),
    )
    return operator, operator.model_copy(update={"actor_id": "synthetic-mixed-reviewer"})


def approve(principal: Principal, proposal: ResourceProposal) -> None:
    resources.review(
        principal,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED", rationale="Independent synthetic atomic definition review"
        ),
    )


@pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained PostgreSQL acceptance"
)
def test_atomic_definitions_retain_each_policy_and_exact_pins(
    identities: tuple[Principal, Principal],
) -> None:
    operator, reviewer = identities
    tenant, company_a = operator.scope.tenant_id, operator.scope.legal_entity_id
    company_b = company_a + "-b"
    semantic = mutation("SemanticContract", "__PLATFORM__", {"kind": "identifier"})
    reference = str(canonical_id(tenant, "SemanticContract", "CanonicalReference"))
    function_type, report_type = "FunctionDef" + uuid4().hex[:10], "ReportDef" + uuid4().hex[:10]

    def field(semantic_id: str, kind: str, target: str | None = None) -> dict:
        return {
            "field_id": str(uuid4()),
            "semantic_id": semantic_id,
            "kind": kind,
            "required": True,
            "target_type": target,
        }

    function_schema = mutation(
        "SchemaDefinition",
        "__PLATFORM__",
        {
            "additional_fields": False,
            "fields": {
                "code": field(str(semantic.resource_id), "identifier"),
                "company_id": field(reference, "reference", "LegalEntity"),
            },
        },
        function_type,
    )
    report_schema = mutation(
        "SchemaDefinition",
        "__PLATFORM__",
        {
            "additional_fields": False,
            "fields": {
                "code": field(str(semantic.resource_id), "identifier"),
                "function_a_id": field(reference, "reference", function_type),
                "function_b_id": field(reference, "reference", function_type),
            },
        },
        report_type,
    )
    entity_a, entity_b = (
        mutation("LegalEntity", company_a, {}),
        mutation("LegalEntity", company_b, {}),
    )
    function_a = mutation(
        function_type,
        company_a,
        {"code": "SYNTHETIC-definition-a", "company_id": str(entity_a.resource_id)},
    )
    function_b = mutation(
        function_type,
        company_b,
        {"code": "SYNTHETIC-definition-b", "company_id": str(entity_b.resource_id)},
    )
    report = mutation(
        report_type,
        None,
        {
            "code": "SYNTHETIC-report-definition",
            "function_a_id": str(function_a.resource_id),
            "function_b_id": str(function_b.resource_id),
        },
    )
    items = [
        semantic,
        function_schema,
        report_schema,
        entity_a,
        entity_b,
        function_a,
        function_b,
        report,
    ]
    proposal = ResourceProposal(
        title="SYNTHETIC mixed definition transaction",
        rationale="Shared schema and company definition identity acceptance; no execution claims",
        access_entity="__TENANT__",
        mutations=items,
    )
    detail = resources.propose(operator, proposal)
    assert detail.validation["resource_scopes"][str(function_a.resource_id)] == company_a
    for item in items:
        with pytest.raises(WorkspaceError) as absent:
            resources.get_resource(operator, item.resource_id)
        assert absent.value.status == 404
    with pytest.raises(WorkspaceError, match="separate"):
        approve(operator, proposal)
    approve(reviewer, proposal)
    for item in items:
        resource = resources.get_resource(operator, item.resource_id)["resource"]
        assert resource["access_entity"] == (item.access_entity or "__TENANT__")
        assert resource["version_id"] == str(uuid5(proposal.proposal_id, str(item.resource_id)))
    with resources.resource_connection(operator) as conn:
        pins = conn.execute(
            "SELECT target_resource_id,target_version_id,access_entity FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=%s AND relation LIKE 'FIELD:%%'",
            (tenant, uuid5(proposal.proposal_id, str(report.resource_id))),
        ).fetchall()
    assert {(str(row[0]), str(row[1]), row[2]) for row in pins} == {
        (
            str(item.resource_id),
            str(uuid5(proposal.proposal_id, str(item.resource_id))),
            "__TENANT__",
        )
        for item in (function_a, function_b)
    }
    scoped = operator.model_copy(
        update={"permissions": ("ontology_read", "ontology_propose", "ontology_review")}
    )
    assert (
        resources.get_resource(scoped, function_a.resource_id)["resource"]["access_entity"]
        == company_a
    )
    assert (
        resources.get_resource(scoped, function_schema.resource_id)["resource"]["access_entity"]
        == "__PLATFORM__"
    )
    for hidden_id in (function_b.resource_id, report.resource_id):
        with pytest.raises(WorkspaceError) as hidden:
            resources.get_resource(scoped, hidden_id)
        assert hidden.value.status == 404
    for scope_name in (company_a, "__TENANT__", "__TENANT_RESTRICTED__"):
        reader = scoped.model_copy(
            update={"scope": scoped.scope.model_copy(update={"legal_entity_id": scope_name})}
        )
        with pytest.raises(WorkspaceError) as hidden:
            resources.proposal_detail(reader, proposal.proposal_id)
        assert hidden.value.status == 404
    with pytest.raises(WorkspaceError, match="administrator"):
        resources.propose(scoped, proposal.model_copy(update={"proposal_id": uuid4()}))
    with pytest.raises(WorkspaceError, match="policy overrides"):
        resources.propose(
            operator,
            proposal.model_copy(update={"proposal_id": uuid4(), "access_entity": company_a}),
        )
    cross_company = mutation(
        function_type,
        company_a,
        {"code": "SYNTHETIC-illegal", "company_id": str(entity_b.resource_id)},
    )
    with pytest.raises(WorkspaceError, match="access boundary"):
        resources.propose(
            operator,
            ResourceProposal(
                title="SYNTHETIC rejected broadening",
                rationale="Cross-company source policy must remain enforced",
                access_entity="__TENANT__",
                mutations=[cross_company],
            ),
        )
    # Even a valid decision cannot authorize arbitrary extra version content.
    with (
        resources.resource_connection(operator) as conn,
        pytest.raises(psycopg.errors.RaiseException, match="content"),
    ):
        conn.execute(
            "INSERT INTO resource_versions (tenant_id,resource_id,version_id,access_entity,"
            "object_type,display_name,schema_version_id,attributes,content_hash,valid_from,"
            "valid_to,authority_state,evidence_class,proposal_id) SELECT tenant_id,resource_id,"
            "%s,access_entity,object_type,display_name,schema_version_id,"
            "attributes || jsonb_build_object('forged',true),content_hash,valid_from,valid_to,"
            "authority_state,evidence_class,proposal_id FROM resource_versions "
            "WHERE tenant_id=%s AND version_id=%s",
            (uuid4(), tenant, uuid5(proposal.proposal_id, str(function_a.resource_id))),
        )


@pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained PostgreSQL acceptance"
)
def test_mid_promotion_failure_rolls_back_all_and_old_payload_replays(
    identities: tuple[Principal, Principal],
) -> None:
    operator, reviewer = identities
    # A natural-identity collision on the second insert must roll back the first version.
    key = "synthetic:collision:" + uuid4().hex
    first = mutation("SemanticContract", "__PLATFORM__", {"kind": "text"}, key)
    second = mutation("SemanticContract", "__PLATFORM__", {"kind": "text"}, key)
    proposal = ResourceProposal(
        title="SYNTHETIC rollback acceptance",
        rationale="Database natural identity collision must roll back the complete transaction",
        access_entity="__TENANT__",
        mutations=[first, second],
    )
    resources.propose(operator, proposal)
    with pytest.raises(psycopg.errors.UniqueViolation):
        approve(reviewer, proposal)
    assert resources.proposal_detail(operator, proposal.proposal_id).decision is None
    for item in (first, second):
        with pytest.raises(WorkspaceError):
            resources.get_resource(operator, item.resource_id)
    legacy = ResourceProposal(
        title="SYNTHETIC legacy pending proposal",
        rationale="Legacy absent mutation policy fields retain their original request hash",
        access_entity=operator.scope.legal_entity_id,
        mutations=[mutation("LegalEntity", None, {})],
    )
    original = resources.propose(operator, legacy)
    with resources.resource_connection(operator) as conn:
        request_hash, payload = conn.execute(
            "SELECT request_hash,payload->'request' FROM resource_proposals "
            "WHERE tenant_id=%s AND proposal_id=%s",
            (operator.scope.tenant_id, legacy.proposal_id),
        ).fetchone()
    assert "access_entity" not in payload["mutations"][0]
    assert (
        request_hash
        == sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    assert resources.propose(operator, ResourceProposal.model_validate(payload)) == original
    approve(reviewer, legacy)
