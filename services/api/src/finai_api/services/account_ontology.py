"""Publish observed account definitions with retained source coordinates; no inferred company."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid5

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.account_source import profile_accounts
from finai_api.services.workbook_source import read_workbook
from finai_api.services.workspace import WorkspaceError, source_bytes


def inspect_accounts(principal: Principal, receipt_id: str) -> dict[str, Any]:
    content = source_bytes(principal, receipt_id)
    book = read_workbook(content)
    catalogs = [result for sheet in book["sheets"] if (result := profile_accounts(sheet))]
    if not catalogs:
        raise WorkspaceError(
            422, "Retained source does not contain a recognized account configuration table"
        )
    return {"receipt_id": receipt_id, "sha256": sha256(content).hexdigest(), "catalogs": catalogs}


def propose_accounts(principal: Principal, receipt_id: str, offset: int, limit: int) -> Any:
    inspection = inspect_accounts(principal, receipt_id)
    accounts = [account for catalog in inspection["catalogs"] for account in catalog["accounts"]]
    selected = accounts[offset : offset + limit]
    if not selected:
        raise WorkspaceError(422, "No account definitions in the requested range")
    selected_coordinates = {account["coordinate"] for account in selected}
    if any(
        selected_coordinates.intersection(finding["coordinates"])
        for catalog in inspection["catalogs"]
        for finding in catalog["findings"]
    ):
        raise WorkspaceError(422, "Selected account definitions have unresolved source findings")
    tenant = principal.scope.tenant_id
    evidence_id = canonical_id(tenant, "SourceEvidence", inspection["sha256"])
    mutations = []
    now = datetime.now(UTC)
    object_ids = [
        uuid5(uuid5(evidence_id, account["coordinate"]), "SourceAccountDefinition")
        for account in selected
    ]
    with resources.resource_connection(principal) as conn:
        published_ids = {
            row[0]
            for row in conn.execute(
                "SELECT resource_id FROM resource_heads WHERE tenant_id=%s "
                "AND resource_id=ANY(%s::uuid[])",
                (tenant, object_ids),
            ).fetchall()
        }
    try:
        with resources.resource_connection(principal) as conn:
            existing = resources._get(conn, tenant, evidence_id)
        if existing["attributes"]["sha256"] != inspection["sha256"]:
            raise WorkspaceError(409, "Source evidence identity has incompatible content")
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
        mutations.append(
            ResourceMutation(
                resource_id=evidence_id,
                object_type="SourceEvidence",
                identity_key=inspection["sha256"],
                display_name="Retained 1C account configuration",
                attributes={"sha256": inspection["sha256"], "source_system": "1C"},
                valid_from=now,
                evidence_class="SOURCE_BOUND",
            )
        )
    for account in selected:
        record_id = uuid5(evidence_id, account["coordinate"])
        object_id = uuid5(record_id, "SourceAccountDefinition")
        if object_id in published_ids:
            continue
        if not account["account_code"] or not account["source_name"]:
            raise WorkspaceError(422, "Account code/name is missing; review source findings")
        mutations.extend(
            [
                ResourceMutation(
                    resource_id=record_id,
                    object_type="SourceRecord",
                    identity_key=f"{inspection['sha256']}:{account['coordinate']}",
                    display_name=account["coordinate"],
                    attributes={
                        "evidence_id": str(evidence_id),
                        "coordinate": account["coordinate"],
                    },
                    valid_from=now,
                    evidence_class="SOURCE_BOUND",
                ),
                ResourceMutation(
                    resource_id=object_id,
                    object_type="SourceAccountDefinition",
                    identity_key=f"{inspection['sha256']}:{account['coordinate']}:account",
                    display_name=f"{account['account_code']} · {account['source_name']}"[:200],
                    attributes={
                        "account_code": account["account_code"],
                        "source_name": account["source_name"],
                        "source_record_id": str(record_id),
                        "evidence_id": str(evidence_id),
                        "definition": account,
                    },
                    valid_from=now,
                    evidence_class="SOURCE_BOUND",
                ),
            ]
        )
    if not mutations:
        raise WorkspaceError(409, "Selected source account definitions are already published")
    proposal = ResourceProposal(
        title="Publish source account definitions",
        rationale=(
            f"Observed 1C configuration from retained source {receipt_id}; "
            "company and reporting mappings remain unestablished"
        ),
        access_entity=principal.scope.legal_entity_id,
        mutations=mutations,
    )
    return resources.propose(principal, proposal)
