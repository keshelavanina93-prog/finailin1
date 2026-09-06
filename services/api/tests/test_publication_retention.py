"""Published execution records retain their scope without acquiring finance authority."""

import pytest
from test_execution_publication import retained_run  # noqa: F401

from finai_api.domain.artifact_retention import RetentionEvaluationRequest
from finai_api.services import artifact_retention, execution_publication
from finai_api.services.workspace import WorkspaceError


def test_published_record_preservation_and_exact_generation(retained_run):  # noqa: F811
    principal, workflow_id = retained_run({"observations": "synthetic-observation/1"})
    principal = principal.model_copy(
        update={"permissions": (*principal.permissions, "ontology_read")}
    )
    execution_publication.stage(
        principal, workflow_id, 0, "observations", "synthetic-observation/1", {"synthetic": True}
    )
    manifest = execution_publication.publish(principal, workflow_id, 0)
    request = RetentionEvaluationRequest(
        artifact={
            "kind": "PUBLICATION_MANIFEST",
            "workflow_id": workflow_id,
            "generation": 0,
            "publication_id": manifest["publication_id"],
        }
    )
    result = artifact_retention.evaluate(principal, request)
    assert result["proof"]["artifact"]["artifact_class"] == "AUTHORITATIVE_RECORD"
    assert result["proof"]["artifact"]["authority_scope"] == "EXECUTION_ONLY"
    assert result["execution_authorized"] is False
    assert artifact_retention.history(principal, request.request_id) == result
    with pytest.raises(WorkspaceError, match="unavailable"):
        artifact_retention.evaluate(
            principal,
            RetentionEvaluationRequest(
                artifact=request.artifact.model_copy(update={"generation": 1})
            ),
        )
