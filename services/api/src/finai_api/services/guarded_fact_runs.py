"""Execute fact analysis against an accepted consumer's material authority contract."""

from datetime import date
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.resource_lifecycle import ConsumptionRequest, VersionReference
from finai_api.domain.review import Principal
from finai_api.services.fact_aggregation import aggregate_facts
from finai_api.services.fact_runs import retain_run
from finai_api.services.resource_lifecycle import consume
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def aggregate_guarded(
    principal: Principal,
    identity: UUID,
    consumer: VersionReference,
    query: ObjectSetQuery,
    group_by: list[str],
    as_of: date | None,
) -> dict[str, Any]:
    result = aggregate_facts(principal, identity, query, group_by, as_of)
    used = {
        (UUID(str(result["contract_id"])), UUID(str(result["contract_version_id"]))),
        (UUID(str(result["schema_id"])), UUID(str(result["schema_version_id"]))),
        *(
            (UUID(str(item["resource_id"])), UUID(str(item["version_id"])))
            for group in result["groups"]
            for item in group["inputs"]
        ),
    }
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT DISTINCT target_resource_id,target_version_id FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=%s",
            (principal.scope.tenant_id, consumer.version_id),
        ).fetchall()
    pins = {(row["target_resource_id"], row["target_version_id"]) for row in rows}
    if not used.issubset(pins):
        raise WorkspaceError(
            409,
            "Calculation contract, schema and facts must match accepted consumer dependency pins",
        )
    if len(pins) > 1000:
        raise WorkspaceError(422, "Guarded calculation supports 1000 dependency pins; narrow scope")
    # The guard rechecks current versions and lifecycle under the canonical tenant lock.
    # Every accepted direct dependency is checked, including dependencies beyond this query.
    # OBSERVED is only the protocol floor; the accepted consumer sets the actual minimum.
    proof = consume(
        principal,
        ConsumptionRequest(
            consumer=consumer,
            inputs=[
                VersionReference(resource_id=resource_id, version_id=version_id)
                for resource_id, version_id in sorted(pins)
            ],
            minimum_state="OBSERVED",
        ),
    )
    # Full proof values live in the immutable consumption receipt. Retain its hash and
    # typed evidence metadata here, without duplicating arbitrary source attributes.
    authority_check = {
        **proof,
        "purpose": "RETAINED_CONSUMPTION_REFERENCE",
        "inputs": [
            {key: value for key, value in item.items() if key != "attributes"}
            for item in proof["inputs"]
        ],
    }
    return retain_run(
        principal,
        {
            **result,
            "authority_check": authority_check,
            "current_use_authorized": False,
            "evidence_purpose": "HISTORICAL_GUARDED_CALCULATION",
        },
        runtime="guarded-accounting-contracts/1",
    )
