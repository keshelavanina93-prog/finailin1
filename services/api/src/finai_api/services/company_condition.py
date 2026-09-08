"""Company connections are explicit accepted pins; current work is never historical fact."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import OperationalError
from psycopg.errors import QueryCanceled
from psycopg.rows import dict_row

from finai_api.domain.company_condition import (
    CompanyConditionDescriptor,
    CompanyWork,
    CompanyWorkItem,
    Connection,
    LicenceEvidence,
    ResourceGroup,
    UnavailableCondition,
)
from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import (
    company_context,
    company_journal_reviews,
    ontology_operations,
    operator_workbench,
    resources,
)
from finai_api.services.operations_map import ASSET_TYPES
from finai_api.services.workspace import WorkspaceError

ASSETS = ASSET_TYPES - {"Location"} | {
    "AssetPortfolio", "BusinessUnit", "LicensedOperator", "ServiceCompany"
}
PARTIES = {"Party", "Customer", "Supplier", "Counterparty"}
# Product is the registered canonical type; no family or industry-specific identity is inferred.
PRODUCTS = {"Product"}
TARGETS = ASSETS | PARTIES | PRODUCTS | {"Contract"}
KINDS = sorted(TARGETS | {"LegalEntity", "Relationship", "LinkType"})
SCAN_LIMIT = 5000


def connection_snapshot(
    principal: Principal, valid_at: datetime, known_at: datetime
) -> tuple[list[CanonicalResource], dict[tuple[str, str], str]]:
    """Reuse canonical RLS and dependency authority with an explicit finite scan bound."""
    try:
        with resources.resource_connection(principal) as conn, conn.cursor(
            row_factory=dict_row
        ) as cursor:
            cursor.execute("SELECT set_config('statement_timeout','10000',true)")
            rows = cursor.execute(
                "SELECT * FROM (SELECT DISTINCT ON(v.resource_id) v.*,i.identity_key "
                "FROM resource_versions v JOIN canonical_identities i USING(tenant_id,resource_id) "
                "WHERE v.tenant_id=%s AND v.object_type=ANY(%s) AND v.system_from<=%s "
                "AND v.valid_from<=%s AND (v.valid_to IS NULL OR v.valid_to>%s) "
                "ORDER BY v.resource_id,v.system_from DESC,v.version_id) snapshot "
                "WHERE authority_state='APPROVED' AND evidence_class<>'REFERENCE_TEMPLATE' "
                "ORDER BY resource_id LIMIT %s",
                (principal.scope.tenant_id, KINDS, known_at, valid_at, valid_at, SCAN_LIMIT + 1),
            ).fetchall()
            if len(rows) > SCAN_LIMIT:
                raise WorkspaceError(409, "Company connection snapshot exceeds its resource bound")
            nodes = [CanonicalResource.model_validate(row) for row in rows]
            deps = cursor.execute(
                "SELECT version_id,relation,target_version_id FROM resource_dependencies "
                "WHERE tenant_id=%s AND version_id=ANY(%s::uuid[]) "
                "AND relation IN ('FIELD:source_id','FIELD:target_id','FIELD:relation_id') "
                "LIMIT 15001",
                (principal.scope.tenant_id, [row.version_id for row in nodes]),
            ).fetchall()
            if len(deps) > 15000:
                raise WorkspaceError(409, "Company connection snapshot exceeds its pin bound")
    except QueryCanceled as exc:
        raise WorkspaceError(409, "Company connections exceeded their bounded read budget") from exc
    return nodes, {
        (str(row["version_id"]), row["relation"].removeprefix("FIELD:")): str(
            row["target_version_id"]
        ) for row in deps
    }


def connected(
    company: CanonicalResource,
    nodes: list[CanonicalResource],
    pins: dict[tuple[str, str], str],
) -> list[Connection]:
    by_id = {str(node.resource_id): node for node in nodes}
    if by_id.get(str(company.resource_id)) != company:
        raise WorkspaceError(409, "Company connection root differs from the exact company snapshot")

    def linked(node: CanonicalResource, field: str) -> CanonicalResource | None:
        target = by_id.get(str(node.attributes.get(field)))
        if (
            target is not None
            and target.authority_state == "APPROVED"
            and target.evidence_class != "REFERENCE_TEMPLATE"
            and pins.get((str(node.version_id), field)) == str(target.version_id)
        ):
            return target
        return None

    edges = []
    for node in nodes:
        if (
            node.object_type != "Relationship" or node.authority_state != "APPROVED"
            or node.evidence_class == "REFERENCE_TEMPLATE"
        ):
            continue
        source, target, relation = [linked(node, field) for field in (
            "source_id", "target_id", "relation_id"
        )]
        if source and target and relation and relation.object_type == "LinkType":
            edges.append(Connection(record=node, relation=relation, source=source, target=target))
    frontier = {company.resource_id}
    selected: dict[UUID, Connection] = {}
    for _ in range(2):
        following = set()
        for edge in edges:
            if edge.source.resource_id not in frontier or edge.target.object_type not in TARGETS:
                continue
            selected[edge.record.resource_id] = edge
            # An associated party, sibling company or asset does not confer company scope.
            if edge.target.object_type in {"BusinessUnit", "LicensedOperator", "ServiceCompany"}:
                following.add(edge.target.resource_id)
        frontier = following
    return sorted(selected.values(), key=lambda edge: str(edge.record.resource_id))


def current_work(principal: Principal, company_id: UUID) -> CompanyWork:
    queue = operator_workbench.listing(principal, company_id, include_unbound=False)
    candidates = []
    for row in queue["items"]:
        if (
            row.get("company_id") != str(company_id)
            or row.get("company_binding") != "EXPLICIT_INVOCATION"
        ):
            raise WorkspaceError(409, "Company work contains an unbound or foreign invocation")
        if row["family"] == "ontology":
            candidates.append(row)
    items = []
    for row in candidates[:25]:
        operation = ontology_operations.read(principal, row["workflow_id"])  # type: ignore[no-untyped-call]
        if operation["operation_id"] != row["workflow_id"]:
            raise WorkspaceError(409, "Company work differs from its retained operation")
        proposal = operation["proposal"]
        proposal_id = operation["prepared_proposal_id"]
        if proposal and proposal["proposal"]["proposal_id"] != proposal_id:
            raise WorkspaceError(409, "Company work differs from its retained proposal")
        items.append(CompanyWorkItem(
            workflow_id=row["workflow_id"], proposal_id=proposal_id,
            company_id=company_id, title=row["title"], state=operation["state"],
            created_at=row["created_at"],
            reason=proposal["proposal"]["rationale"] if proposal else
            "Company workflow retained a proposal; submission for review is not established.",
        ))
    return CompanyWork(
        observed_at=datetime.now(UTC), items=items,
        truncated=queue["truncated"] or len(candidates) > 25,
    )


def describe(
    principal: Principal, company_id: UUID, valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> CompanyConditionDescriptor:
    require_permission(principal, "ontology_read")
    require_permission(principal, "read")
    snapshot = company_context.resolve(principal, company_id, valid_at, known_at)
    context = snapshot.get("context")
    if not context:
        raise WorkspaceError(404, "Selected company context is unavailable")
    company = CanonicalResource.model_validate(context["company"])
    if (
        company.resource_id != company_id or company.object_type != "LegalEntity"
        or company.authority_state != "APPROVED" or company.evidence_class == "REFERENCE_TEMPLATE"
    ):
        raise WorkspaceError(404, "Selected company context is unavailable")
    valid, known = [datetime.fromisoformat(snapshot[key]) for key in ("valid_at", "known_at")]
    nodes, pins = connection_snapshot(principal, valid, known)
    connections = connected(company, nodes, pins)
    targets = {edge.target.resource_id: edge.target for edge in connections}

    def group(kinds: set[str] | frozenset[str]) -> ResourceGroup:
        members = sorted(
            [node for node in targets.values() if node.object_type in kinds],
            key=lambda node: (node.display_name, str(node.resource_id)),
        )
        return ResourceGroup(
            state="AVAILABLE" if members else "EMPTY", resources=members,
            reason="Only accepted version-pinned outgoing relationships from this company or "
            "one connected operating unit are included. Association does not establish ownership, "
            "contract performance, product availability, asset condition or complete business "
            "coverage.",
        )

    unavailable: list[dict[str, Any]] = [
        {"key": "financial_performance", "label": "Financial performance",
         "reason": "No accepted statement result is composed here. Source and ledger "
         "configuration do not establish financial performance."},
        {"key": "live_operations", "label": "Live operating condition",
         "reason": "Connected resource definitions do not establish live telemetry or condition."},
        {"key": "findings", "label": "Findings",
         "reason": "A shared company-bound Findings contract is not connected."},
        {"key": "investigations", "label": "Investigations",
         "reason": "A shared company-bound Investigations contract is not connected."},
        {"key": "regulatory_compliance", "label": "Regulatory compliance",
         "reason": "Retained licence evidence is available for inspection; an operating "
         "compliance determination is not established by this descriptor."},
    ]
    try:
        work = current_work(principal, company_id)
    except (OperationalError, QueryCanceled):
        work = CompanyWork(
            state="UNAVAILABLE", reason="Current company work storage is unavailable. "
            "No empty-queue or approval-state conclusion is established.",
            observed_at=datetime.now(UTC), items=[], truncated=False,
        )
    except WorkspaceError as exc:
        if exc.status != 503:
            raise
        work = CompanyWork(
            state="UNAVAILABLE", reason="Current company work could not be observed. "
            "Retained company resources remain available at their displayed snapshot.",
            observed_at=datetime.now(UTC), items=[], truncated=False,
        )
    return CompanyConditionDescriptor(
        company=company, valid_at=valid, known_at=known, connections=connections,
        assets=group(ASSETS), parties=group(PARTIES), contracts=group({"Contract"}),
        products=group(PRODUCTS),
        licence_evidence=[
            LicenceEvidence.model_validate(row) for row in context["licence_evidence"]
        ],
        work=work,
        journal_reviews=company_journal_reviews.observe(principal, company_id),
        unavailable=[UnavailableCondition.model_validate(row) for row in unavailable],
    )
