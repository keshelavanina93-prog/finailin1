"""A safe synthetic schema evolution plus immutable-head rejection in PostgreSQL."""

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


@pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained PostgreSQL acceptance"
)
def test_optional_evolution_and_narrowing_refusal_preserve_schema_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    operator = Principal(
        actor_id="synthetic-schema-proposer",
        display_name="Synthetic schema proposer",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="synthetic-schema-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_admin", "ontology_propose", "ontology_review"),
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-schema-reviewer"})
    attributes = {
        "additional_fields": True,
        "fields": {
            "code": {
                "field_id": str(uuid4()),
                "semantic_id": str(canonical_id(tenant, "SemanticContract", "Identifier")),
                "kind": "identifier",
                "required": True,
            }
        },
    }
    mutation = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key="SYNTHETIC / წყარო " + uuid4().hex,
        display_name="SYNTHETIC source schema compatibility",
        attributes=attributes,
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
    )

    def proposed(item: ResourceMutation) -> ResourceProposal:
        return ResourceProposal(
            title="SYNTHETIC schema compatibility acceptance",
            rationale="Isolated non-authentic backward compatibility evidence",
            access_entity="__PLATFORM__",
            mutations=[item],
        )

    first = proposed(mutation)
    resources.propose(operator, first)
    resources.review(
        reviewer,
        first.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic schema review"),
    )
    initial_head = resources.get_resource(operator, mutation.resource_id)["resource"]["version_id"]
    expanded = deepcopy(attributes)
    expanded["fields"]["ქართული სახელი"] = {
        "field_id": str(uuid4()),
        "semantic_id": str(canonical_id(tenant, "SemanticContract", "Text")),
        "kind": "text",
        "required": False,
    }
    expanded["fields"]["code"].update(required=False, deprecated=True)
    update = mutation.model_copy(
        update={"expected_version_id": UUID(initial_head), "attributes": expanded}
    )
    second = proposed(update)
    detail = resources.propose(operator, second)
    impact = detail.validation["impact"][0]
    assert impact["compatibility"] == "BACKWARD_COMPATIBLE"
    assert {row["change"] for row in impact["semantic_changes"]} == {
        "FIELD_ADDED",
        "DEPRECATED",
        "REQUIRED_LOOSENED",
    }
    resources.review(
        reviewer,
        second.proposal_id,
        ResourceReview(
            decision="APPROVED", rationale="Independent optional field evolution review"
        ),
    )
    accepted = resources.get_resource(operator, mutation.resource_id)["resource"]
    assert accepted["version_id"] != initial_head
    narrow = update.model_copy(
        update={
            "expected_version_id": UUID(accepted["version_id"]),
            "attributes": {**expanded, "additional_fields": False},
        }
    )
    with pytest.raises(WorkspaceError, match="unknown-field narrowing") as rejected:
        resources.propose(operator, proposed(narrow))
    assert rejected.value.status == 409
    assert resources.get_resource(operator, mutation.resource_id)["resource"] == accepted
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS", json.dumps({"operator": operator.model_dump(mode="json")})
    )
    get_settings.cache_clear()
    client = TestClient(app, headers={"Authorization": "Bearer operator"})
    malformed = deepcopy(expanded)
    malformed["fields"]["code"]["semantic_id"] = 7
    invalid = proposed(
        update.model_copy(
            update={"expected_version_id": UUID(accepted["version_id"]), "attributes": malformed}
        )
    )
    response = client.post("/v1/ontology/proposals", json=invalid.model_dump(mode="json"))
    assert response.status_code == 422 and "UUID" in response.text
    assert resources.get_resource(operator, mutation.resource_id)["resource"] == accepted
