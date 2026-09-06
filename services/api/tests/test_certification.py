# ruff: noqa: F811
"""Synthetic native proof of structural certification, not financial certification."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ValidationError
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.certification import CertificationContract, CertificationEvaluationRequest
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import certification, resources
from finai_api.services.workspace import WorkspaceError


def attributes(kind="ObjectSetDefinition", schema=None):
    result = {
        "definition": {
            "claim": "CANONICAL_DEFINITION_CONFORMANCE",
            "evaluator": "canonical-structural-contract/v1",
            "subject_type": kind,
            "required_checks": [
                "schema compatibility",
                "identity cycles",
                "dependency version pins",
                "impact",
            ],
            "meaning": "Exact definition passed canonical structural promotion checks.",
            "limitations": "No accounting, authenticity or financial certification is asserted.",
        }
    }
    if schema:
        result["subject_schema_id"] = str(schema)
    return result


def ref(resource):
    return VersionReference(resource_id=resource["resource_id"], version_id=resource["version_id"])


def fixture(retained):
    reader, publish = retained
    subject = item("ObjectSetDefinition", {"definition": {"object_type": "LegalEntity"}})
    contract = item(
        "CertificationContract",
        attributes(
            schema=canonical_id(reader.scope.tenant_id, "SchemaDefinition", "ObjectSetDefinition")
        ),
    )
    subject_row, contract_row = publish(subject, contract)
    return (
        reader,
        publish,
        subject,
        contract,
        CertificationEvaluationRequest(subject=ref(subject_row), contract=ref(contract_row)),
    )


def test_contract_never_accepts_caller_pass_or_financial_claim():
    valid = attributes("SemanticContract")
    CertificationContract.model_validate(valid)
    for changed in [
        {**valid, "status": "PASS"},
        attributes("LegalEntity"),
        attributes("ObjectSetDefinition"),
    ]:
        with pytest.raises(ValidationError):
            CertificationContract.model_validate(changed)
    with pytest.raises(ValidationError):
        CertificationEvaluationRequest(
            subject={"resource_id": uuid4(), "version_id": uuid4()},
            contract={"resource_id": uuid4(), "version_id": uuid4()},
            status="PASS",
        )


@DB
def test_retained_receipt_replay_conflict_and_current_check(retained):
    reader, publish, subject, _contract, request = fixture(retained)
    result = certification.evaluate(reader, request)
    assert result["proof"]["status"] == "PASS"
    assert result["current_use_authorized"] is False
    assert result == certification.evaluate(reader, request)
    assert result == certification.history(reader, request.request_id)
    with resources.resource_connection(reader) as conn, conn.cursor(row_factory=dict_row) as c:
        assert certification.receipt_for_current_use(
            c, reader, request.request_id, request.subject
        )["current_use_authorized"]
    with pytest.raises(WorkspaceError, match="already used differently"):
        certification.evaluate(reader, request.model_copy(update={"subject": request.contract}))
    publish(
        subject.model_copy(
            update={
                "expected_version_id": request.subject.version_id,
                "authority_state": "REVOKED",
                "valid_from": datetime.now(UTC) - timedelta(seconds=1),
            }
        )
    )
    assert result == certification.evaluate(
        reader, request
    )  # Historical replay, not authorization.
    with (
        resources.resource_connection(reader) as conn,
        conn.cursor(row_factory=dict_row) as c,
        pytest.raises(WorkspaceError, match="current use"),
    ):
        certification.receipt_for_current_use(c, reader, request.request_id, request.subject)
    assert result == certification.history(reader, request.request_id)


@DB
def test_database_rejects_forged_lineage_and_receipt_is_immutable(retained):
    reader, _, _, _, request = fixture(retained)
    result = certification.evaluate(reader, request)
    proof = deepcopy(result["proof"])
    assert proof["subject_upstream"]
    proof["subject_upstream"] = []
    with (
        pytest.raises(psycopg.Error, match="Incomplete certification lineage"),
        resources.resource_connection(reader) as conn,
    ):
        conn.execute(
            "INSERT INTO certification_receipts SELECT tenant_id,%s,"
            "subject_resource_id,subject_version_id,contract_resource_id,contract_version_id,"
            "access_entity,actor_id,request_hash,%s,%s,recorded_at FROM certification_receipts "
            "WHERE tenant_id=%s AND receipt_id=%s",
            (
                uuid4(),
                certification._digest(proof),
                Jsonb(proof),
                reader.scope.tenant_id,
                request.request_id,
            ),
        )
    with pytest.raises(psycopg.Error), resources.resource_connection(reader) as conn:
        conn.execute(
            "UPDATE certification_receipts SET proof_hash=%s WHERE receipt_id=%s",
            ("0" * 64, request.request_id),
        )
    other = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(
                update={"legal_entity_id": "different-synthetic-" + uuid4().hex}
            )
        }
    )
    with pytest.raises(WorkspaceError, match="unavailable"):
        certification.history(other, request.request_id)


@DB
def test_contract_type_mismatch_and_future_contract_fail_closed(retained):
    reader, publish, _, contract, request = fixture(retained)
    wrong = item("CertificationContract", attributes("SemanticContract"))
    wrong_row = publish(wrong)[0]
    with pytest.raises(WorkspaceError, match="Subject type"):
        certification.evaluate(reader, request.model_copy(update={"contract": ref(wrong_row)}))
    future = publish(
        contract.model_copy(
            update={
                "expected_version_id": request.contract.version_id,
                "valid_from": datetime.now(UTC) + timedelta(days=10),
            }
        )
    )[0]
    assert certification.evaluate(reader, request)["proof"][
        "contract"
    ] == request.contract.model_dump(mode="json")
    with pytest.raises(WorkspaceError, match="current use"):
        certification.evaluate(
            reader, request.model_copy(update={"request_id": uuid4(), "contract": ref(future)})
        )


@DB
def test_platform_bootstrap_contract_is_reviewed_and_excludes_financial_facts(retained):
    reader, _ = retained
    operator = reader.model_copy(
        update={
            "permissions": (
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
            )
        }
    )
    subject = item("SemanticContract", {"kind": "identifier"})
    contract = item("CertificationContract", attributes("SemanticContract"))
    proposal = ResourceProposal(
        title="SYNTHETIC bootstrap conformance contract",
        rationale="Structural bootstrap acceptance; no financial certification",
        access_entity="__PLATFORM__",
        mutations=[subject, contract],
    )
    resources.propose(operator, proposal)
    resources.review(
        operator.model_copy(update={"actor_id": "synthetic-certification-reviewer"}),
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED", rationale="Review exact synthetic bootstrap structural contract"
        ),
    )
    request = CertificationEvaluationRequest(
        subject=ref(resources.get_resource(operator, subject.resource_id)["resource"]),
        contract=ref(resources.get_resource(operator, contract.resource_id)["resource"]),
    )
    result = certification.evaluate(operator, request)
    assert result["proof"]["subject_schema"] is None
    assert result["proof"]["access_entity"] == "__PLATFORM__"
    assert certification.history(reader, request.request_id) == result
    with pytest.raises(WorkspaceError):
        resources.propose(
            operator,
            proposal.model_copy(
                update={"proposal_id": uuid4(), "mutations": [item("LegalEntity", {})]}
            ),
        )
