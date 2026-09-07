"""Retained calculation → reviewed canonical update, with synthetic source evidence only."""

# ruff: noqa: F811

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from test_definition_history import item, retained  # noqa: F401

from finai_api.domain.function_execution import FunctionInvocation, RetainedResultInput
from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.ontology_definitions import BindingDefinition, BindingField
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import (
    calculated_bindings,
    function_execution,
    function_invocations,
    ontology_definitions,
    ontology_operations,
    resources,
    source_documents,
)
from finai_api.services.workspace import WorkspaceError


def test_legacy_binding_serialization_and_explicit_calculated_union():
    old = {
        "identity_mode": "SOURCE_KEY",
        "identity_field": "code",
        "display_field": "name",
        "fields": [{"source_field": "name", "target_field": "name"}],
    }
    assert BindingDefinition.model_validate(old).model_dump(mode="json") == old
    ref = {"resource_id": str(uuid4()), "version_id": str(uuid4())}
    new = {
        "identity_mode": "CANONICAL_REFERENCE",
        "identity_field": "dimension_id",
        "display_property": ref,
        "fields": [],
    }
    assert BindingDefinition.model_validate(new).model_dump(mode="json") == new
    for bad in (
        {"target_field": "name"},
        {"target_field": "name", "source_field": "name", "derived_property": ref},
    ):
        with pytest.raises(ValidationError):
            BindingField.model_validate(bad)
    with pytest.raises(ValidationError):
        BindingDefinition.model_validate({**new, "display_field": "name"})
    with pytest.raises(ValidationError):
        BindingDefinition.model_validate({**new, "identity_mode": "SOURCE_KEY"})


def test_mapping_uses_retained_value_preserves_attributes_and_refuses_missing_or_duplicate():
    oid, vid, pid, pvid = [str(uuid4()) for _ in range(4)]
    spec = {
        "identity_mode": "CANONICAL_REFERENCE",
        "identity_field": "dimension_id",
        "display_property": {"resource_id": pid, "version_id": pvid},
        "fields": [],
    }
    row = {"resource_id": oid, "version_id": vid, "attributes": {"code": "raw"}}
    current = {"attributes": {"code": "unchanged", "evidence_id": str(uuid4())}}
    value = {
        "object_id": oid,
        "object_version_id": vid,
        "definition_id": pid,
        "definition_version_id": pvid,
        "status": "AVAILABLE",
        "value": "Retained label",
    }
    assert calculated_bindings.mapped(spec, row, current, [value]) == (
        "Retained label",
        current["attributes"],
    )
    for bad in (
        [],
        [value, value],
        [{**value, "status": "MISSING_INPUT"}],
        [{**value, "definition_version_id": str(uuid4())}],
    ):
        with pytest.raises(WorkspaceError):
            calculated_bindings.mapped(spec, row, current, bad)


def calculated_binding_case(retained):
    from finai_api.domain.ontology_catalog import canonical_id

    reader, publish = retained
    author = reader.model_copy(
        update={"permissions": ("read", "ontology_read", "ontology_propose", "ingest")}
    )
    reviewer = author.model_copy(
        update={
            "actor_id": "synthetic-calculated-binding-reviewer",
            "permissions": ("read", "ontology_read", "ontology_review"),
        }
    )
    doc = source_documents.retain_document(
        author, "SYNTHETIC binding bytes.txt", b"Synthetic canonical label fixture"
    )
    evidence = item(
        "SourceEvidence", {"sha256": doc["sha256"], "source_system": "SYNTHETIC"}
    ).model_copy(update={"evidence_class": "SOURCE_BOUND"})
    dimension = item(
        "DimensionDefinition", {"code": "SYNTHETIC", "evidence_id": str(evidence.resource_id)}
    ).model_copy(update={"evidence_class": "SOURCE_BOUND"})
    member = item(
        "DimensionMember",
        {
            "dimension_id": str(dimension.resource_id),
            "code": "fixture",
            "evidence_id": str(evidence.resource_id),
        },
    ).model_copy(update={"evidence_class": "SOURCE_BOUND"})
    publish(evidence, dimension, member)
    schema = canonical_id(reader.scope.tenant_id, "SchemaDefinition", "DimensionMember")
    derived = item(
        "DerivedProperty",
        {
            "schema_id": str(schema),
            "definition": {
                "name": "bound_label",
                "result_kind": "text",
                "expression": {
                    "op": "concat",
                    "args": [
                        {"op": "literal", "value": "SYNTHETIC retained "},
                        {"op": "field", "field": "code"},
                    ],
                },
            },
        },
    )
    derived_row = publish(derived)[0]
    binding = item(
        "ObjectBinding",
        {
            "source_schema_id": str(schema),
            "target_schema_id": str(
                canonical_id(reader.scope.tenant_id, "SchemaDefinition", "DimensionDefinition")
            ),
            "definition": {
                "identity_mode": "CANONICAL_REFERENCE",
                "identity_field": "dimension_id",
                "display_property": {
                    "resource_id": str(derived.resource_id),
                    "version_id": derived_row["version_id"],
                },
                "fields": [],
            },
        },
    )
    binding_row = publish(binding)[0]
    selected = item(
        "ObjectSetDefinition",
        {
            "definition": {
                "object_type": "DimensionMember",
                "resource_ids": [str(member.resource_id)],
            }
        },
    )
    publish(selected)
    manifest = function_execution.manifest()
    function = item(
        "FunctionDefinition",
        {
            "object_set_id": str(selected.resource_id),
            "definition": {
                **{
                    k: manifest[k]
                    for k in (
                        "implementation_id",
                        "determinism",
                        "code_sha256",
                        "dependency_sha256",
                    )
                },
                "derived_property_ids": [str(derived.resource_id)],
            },
        },
    )
    function_row = publish(function)[0]
    now = datetime.now(UTC)
    request = FunctionInvocation(
        function={"resource_id": function.resource_id, "version_id": function_row["version_id"]},
        valid_at=now,
        known_at=now,
        limit=10,
    )
    receipt = function_invocations.invoke(author, request)
    assert receipt["status"] == "SUCCEEDED"
    action = ontology_operations.BindingAction(
        request_id=uuid4(),
        binding_id=binding.resource_id,
        binding_version_id=binding_row["version_id"],
        query=ObjectSetQuery.model_validate(receipt["output"]["query"]),
        rationale="Synthetic retained calculation proposes display only, no authentic source claim",
        input_result=RetainedResultInput(invocation_id=request.request_id),
    )
    return author, reviewer, dimension, binding, receipt, action


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Native isolated DB proof")
def test_retained_calculated_binding_review_replay_and_tamper_refusal(retained, monkeypatch):
    author, reviewer, dimension, binding, receipt, action = calculated_binding_case(retained)
    original = resources.get_resource(author, dimension.resource_id)["resource"]
    monkeypatch.setattr(
        ontology_definitions,
        "query_objects",
        lambda *_: pytest.fail("retained binding must not requery"),
    )
    with pytest.raises(WorkspaceError, match="explicit retained"):
        ontology_definitions.prepare_binding(
            author, binding.resource_id, action.query, action.rationale, action.binding_version_id
        )
    prepared = ontology_definitions.prepare_binding(
        author,
        binding.resource_id,
        action.query,
        action.rationale,
        action.binding_version_id,
        input_result=action.input_result,
    )
    assert prepared.mutations[0].resource_id == dimension.resource_id
    assert prepared.mutations[0].attributes == original["attributes"]
    assert prepared.mutations[0].display_name == "SYNTHETIC retained fixture"
    assert "calculated_bindings" in prepared.model_dump(mode="json")
    for changes in (
        {"display_name": "forged"},
        {"attributes": {**original["attributes"], "code": "forged"}},
    ):
        forged = prepared.model_copy(
            update={
                "proposal_id": uuid4(),
                "mutations": [prepared.mutations[0].model_copy(update=changes)],
            }
        )
        with pytest.raises(WorkspaceError, match="differs"):
            resources.propose(author, forged)
    with pytest.raises(WorkspaceError, match="metadata"):
        resources.propose(
            author, prepared.model_copy(update={"proposal_id": uuid4(), "calculated_bindings": {}})
        )
    other = author.model_copy(
        update={
            "scope": author.scope.model_copy(update={"legal_entity_id": "synthetic-other-binding"})
        }
    )
    with pytest.raises(WorkspaceError):
        ontology_definitions.prepare_binding(
            other,
            binding.resource_id,
            action.query,
            action.rationale,
            action.binding_version_id,
            input_result=action.input_result,
        )
    outcome = ontology_operations.invoke(author, action)
    proposal_id = UUID(outcome["prepared_proposal_id"])
    resources.review(
        reviewer,
        proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Independent synthetic display-only calculated binding verification",
        ),
    )
    current = resources.get_resource(author, dimension.resource_id)["resource"]
    assert (
        current["resource_id"] == original["resource_id"]
        and current["attributes"] == original["attributes"]
    )
    assert current["display_name"] == "SYNTHETIC retained fixture"
    assert ontology_operations.invoke(author, action)["prepared_proposal_id"] == str(proposal_id)
    with pytest.raises(WorkspaceError, match="different content"):
        ontology_operations.invoke(
            author, action.model_copy(update={"rationale": "Changed retry must be rejected"})
        )
    # Old source/receipt remains immutable after the independently reviewed target update.
    assert (
        function_invocations.history(author, UUID(receipt["invocation_id"]))["receipt_hash"]
        == receipt["receipt_hash"]
    )
    with pytest.raises(WorkspaceError):
        resources.propose(author, prepared.model_copy(update={"proposal_id": uuid4()}))
    plain = ResourceProposal(
        title="SYNTHETIC legacy serialization",
        rationale=action.rationale,
        access_entity=author.scope.legal_entity_id,
        mutations=[dimension],
    )
    assert "calculated_bindings" not in plain.model_dump(mode="json")
