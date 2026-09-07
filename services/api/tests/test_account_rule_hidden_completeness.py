"""A private rule dependency cannot make a visible account's empty rule set complete."""

# ruff: noqa: F811
from datetime import UTC, datetime
from uuid import UUID, uuid4

from test_definition_history import DB, retained  # noqa: F401
from test_journal_dimensions import dimension_case

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.services import account_dimension_policy, resources


@DB
def test_hidden_rule_dependency_refuses_visible_empty_set(retained):
    low, publish, resource, company, _chart, account, nodes = dimension_case(retained)
    high = low.model_copy(
        update={
            "actor_id": "synthetic-hidden-rule-author",
            "permissions": (
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
                "restricted_read",
            ),
        }
    )
    checker = high.model_copy(update={"actor_id": "synthetic-hidden-rule-checker"})
    tenant = low.scope.tenant_id
    kind = "PrivateRuleWitness" + uuid4().hex[:10]
    schema = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key=kind,
        display_name="SYNTHETIC private witness schema",
        valid_from=datetime.now(UTC),
        access_entity="__PLATFORM__",
        attributes={
            "additional_fields": False,
            "fields": {
                "witness": {
                    "field_id": str(uuid4()),
                    "semantic_id": str(canonical_id(tenant, "SemanticContract", "Text")),
                    "kind": "text",
                    "required": False,
                    "read_permissions": ["restricted_read"],
                }
            },
        },
    )

    def reviewed(item, scope, source_versions=None):
        proposal = ResourceProposal(
            title="SYNTHETIC hidden rule witness",
            rationale=(
                "Isolated synthetic completeness refusal with a unique private witness schema"
            ),
            access_entity=scope,
            mutations=[item],
            source_versions=source_versions or {},
        )
        resources.propose(high, proposal)
        resources.review(
            checker,
            proposal.proposal_id,
            ResourceReview(
                decision="APPROVED", rationale="Independent synthetic hidden lineage acceptance"
            ),
        )
        return resources.get_resource(high, item.resource_id)["resource"]

    reviewed(schema, "__PLATFORM__")
    witness = resource(kind, {"witness": "SYNTHETIC RESTRICTED WITNESS"})
    saved_witness = reviewed(witness, low.scope.legal_entity_id)
    dimension = resource("DimensionDefinition", {"code": "SYNTHETIC_" + uuid4().hex})
    publish(dimension)
    key = f"account-dimension:{account.resource_id}:{dimension.resource_id}"
    rule = resource(
        "AccountDimensionRule",
        {
            "account_id": str(account.resource_id),
            "dimension_id": str(dimension.resource_id),
            "required": True,
        },
        resource_id=canonical_id(tenant, "AccountDimensionRule", key),
    ).model_copy(update={"identity_key": key})
    saved_rule = reviewed(
        rule,
        low.scope.legal_entity_id,
        {rule.resource_id: {witness.resource_id: UUID(saved_witness["version_id"])}},
    )
    assert (
        resources.get_resource(low, account.resource_id)["resource"]["version_id"]
        == nodes[2]["version_id"]
    )
    for principal, refs, expected in [
        (low, [], False),
        (high, [UUID(saved_rule["version_id"])], True),
    ]:
        with resources.resource_connection(principal) as conn:
            result = conn.execute(
                "SELECT g8_account_rule_set_complete(%s,%s,%s,%s::uuid[],%s)",
                (
                    tenant,
                    account.resource_id,
                    UUID(nodes[2]["version_id"]),
                    refs,
                    datetime.now(UTC),
                ),
            ).fetchone()
            assert result[0] is expected
    hidden = account_dimension_policy.read(low, company.resource_id, account.resource_id)
    assert hidden["rules"] == [] and hidden["rules_complete"] is False
    visible = account_dimension_policy.read(high, company.resource_id, account.resource_id)
    assert visible["rules_complete"] is True
    assert [row["rule"]["version_id"] for row in visible["rules"]] == [saved_rule["version_id"]]
