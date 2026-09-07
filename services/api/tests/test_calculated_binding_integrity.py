"""SQL publication guard remains decisive when calculated-binding Python validation is bypassed."""

import os
from uuid import uuid4

import pytest
from psycopg.errors import RaiseException
from test_calculated_bindings import calculated_binding_case
from test_definition_history import retained  # noqa: F401

from finai_api.domain.resources import ResourceReview
from finai_api.services import calculated_bindings, ontology_definitions, resources


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Native isolated DB proof")
def test_database_refuses_forged_display_and_missing_calculated_metadata(retained, monkeypatch):  # noqa: F811
    author, reviewer, dimension, binding, _, action = calculated_binding_case(retained)
    original = resources.get_resource(author, dimension.resource_id)["resource"]
    prepared = ontology_definitions.prepare_binding(
        author,
        binding.resource_id,
        action.query,
        action.rationale,
        action.binding_version_id,
        input_result=action.input_result,
    )
    # Only the application-specific validator is bypassed. Normal proposal validation,
    # independent review, database roles, RLS and all publication triggers remain active.
    monkeypatch.setattr(calculated_bindings, "validate_proposal", lambda *args, **kwargs: None)
    cases = [
        (
            prepared.model_copy(
                update={
                    "proposal_id": uuid4(),
                    "mutations": [
                        prepared.mutations[0].model_copy(
                            update={"display_name": "SYNTHETIC forged display"}
                        )
                    ],
                }
            ),
            "Calculated binding display differs from the retained value",
        ),
        (
            prepared.model_copy(update={"proposal_id": uuid4(), "calculated_bindings": {}}),
            "Calculated binding promotion requires retained calculation evidence",
        ),
    ]
    for proposal, expected in cases:
        resources.propose(author, proposal)
        with pytest.raises(RaiseException, match=expected):
            resources.review(
                reviewer,
                proposal.proposal_id,
                ResourceReview(
                    decision="APPROVED", rationale="Independent synthetic SQL refusal witness"
                ),
            )
        assert resources.get_resource(author, dimension.resource_id)["resource"] == original
        # Failed publication rolls back its attempted review decision as well.
        assert resources.proposal_detail(author, proposal.proposal_id).decision is None
