"""Verify migration 063 in an isolated nin17_contract database, never canonical data.

Requires FINAI_DATABASE_URL for finai_runtime against the isolated test database
with migrations 001 and 063 already applied. Each run uses a fresh synthetic scope.
"""

import json
import os
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

from finai_api.domain.authority import ExactScope
from finai_api.domain.journal_production import JournalProductionRequest
from finai_api.domain.review import Principal
from finai_api.services import journal_production_history as storage
from finai_api.services.entity_movement_review import digest
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError
from psycopg.errors import InsufficientPrivilege


def main():
    url = urlparse(os.environ["FINAI_DATABASE_URL"])
    assert url.hostname == "127.0.0.1" and url.path in {"/nin17_contract", "/nin17_contract_final"}
    assert url.username == "finai_runtime"
    p = Principal(
        actor_id="synthetic-maker",
        display_name="Synthetic storage verification",
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id="synthetic-nin17",
            period="2025-01",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose"),
    )
    request = JournalProductionRequest(
        request_id=uuid4(),
        invocation_id=uuid4(),
        company_id=uuid4(),
        effective_at=datetime.now(UTC),
        rationale="Synthetic retention verification",
        coordinates=["Base!S288"],
    )
    proof = {
        "contract": "source-journal-production/1",
        "rows": [
            {
                "coordinate": "Base!S288",
                "state": "EXCLUDED",
                "blockers": [{"code": "MISSING_LITERAL_POSTED_AMOUNT"}],
            }
        ],
    }
    proof["receipt_hash"] = digest(proof)
    assert storage.retain(p, request, "PREPARED", proof) == proof
    assert storage.history(p, request.request_id, "PREPARED", request) == proof
    assert storage.retain(p, request, "PREPARED", proof) == proof
    for other in (
        p.model_copy(
            update={"scope": p.scope.model_copy(update={"legal_entity_id": "other"})}
        ),
        p.model_copy(
            update={"scope": p.scope.model_copy(update={"tenant_id": uuid4()})}
        ),
    ):
        assert storage.history(other, request.request_id, "PREPARED") is None
    try:
        storage.history(
            p.model_copy(update={"actor_id": "other-maker"}),
            request.request_id,
            "PREPARED",
            request,
        )
        raise AssertionError("A different maker reused the request")
    except WorkspaceError as exc:
        assert exc.status == 409
    for command in (
        "UPDATE journal_production_attempts SET actor_id='changed'",
        "DELETE FROM journal_production_attempts",
        "TRUNCATE journal_production_attempts",
    ):
        try:
            with resource_connection(p) as conn:
                conn.execute(command)
            raise AssertionError("Immutable storage was changed")
        except InsufficientPrivilege:
            pass
    assert storage.retain(p, request, "SUBMITTED", proof) == proof
    assert storage.history(p, request.request_id) == proof
    print(
        json.dumps(
            {
                "status": "ISOLATED_POSTGRES_STORAGE_PASS",
                "migration": 63,
                "checks": [
                    "retain",
                    "reopen",
                    "retry",
                    "tenant_isolation",
                    "entity_isolation",
                    "maker_reuse_refusal",
                    "update_delete_truncate_refusal",
                    "submission_phase",
                ],
                "canonical_data_changed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
