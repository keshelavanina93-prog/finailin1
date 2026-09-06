"""Source observations traced through the shared accepted dependency authority."""

from datetime import UTC, datetime
from uuid import UUID

from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.security import require_permission
from finai_api.services import regulatory_sources, resources
from finai_api.services.dependency_impact import current_impact
from finai_api.services.fact_runs import retain_run


class ImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{64}$")


def assess(principal, request: ImpactRequest):
    require_permission(principal, "ontology_read")
    metadata, observed = regulatory_sources.inspect(principal, request.document_id)
    act_id = canonical_id(
        principal.scope.tenant_id, "RegulatoryAct", "GE:MATSNE:" + observed["matsne_id"]
    )
    with resources.resource_connection(principal, repeatable_read=True) as conn:
        act = resources._get(conn, principal.scope.tenant_id, act_id)
        impact = current_impact(conn, principal, {str(act_id): str(act["version_id"])})
        contexts = []
        for affected in impact["affected"]:
            if affected["object_type"] != "RegulatoryRule":
                continue
            with conn.cursor(row_factory=dict_row) as cursor:
                refs = cursor.execute(
                    "SELECT d.relation,v.resource_id,v.version_id,v.object_type,v.display_name "
                    "FROM resource_dependencies d JOIN resource_versions v "
                    "ON v.tenant_id=d.tenant_id AND v.version_id=d.target_version_id "
                    "WHERE d.tenant_id=%s AND d.version_id=%s "
                    "AND d.relation LIKE 'FIELD:%%' ORDER BY d.relation",
                    (principal.scope.tenant_id, UUID(affected["version_id"])),
                ).fetchall()
            contexts.append({"rule": affected, "references": refs})
    return retain_run(
        principal,
        {
            "contract": "regulatory-dependency-impact/1",
            "observed_at": datetime.now(UTC).isoformat(),
            "source": {
                "document_id": request.document_id,
                "sha256": metadata["source_sha256"],
                "matsne_id": observed["matsne_id"],
                "publication": observed["publication"],
                "completeness": observed["completeness"],
            },
            "act": {
                "resource_id": str(act_id),
                "version_id": str(act["version_id"]),
                "display_name": act["display_name"],
            },
            "dependency_impact": impact,
            "rule_contexts": contexts,
            "financial_impact": {
                "state": "UNAVAILABLE",
                "amount": None,
                "reason": "No affected executable financial calculation evaluated",
            },
            "legal_change_verified": False,
            "accounting_effects": False,
            "limitations": [
                "Dependency reachability is potential impact, not legal applicability",
                "Only registered accepted dependencies are covered; missing bindings are not "
                "no-impact",
                "Current dependency heads are traced; historical legal applicability is "
                "assessed separately",
                "Source review, complete legal versions and activation conditions remain required",
            ],
        },
        runtime="regulatory-dependency-impact/1",
    )
