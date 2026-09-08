"""Read-only, company-bound composition of canonical context and retained analyses."""

from typing import Any
from uuid import UUID

from finai_api.domain.company_home import (
    CompanyHomeDescriptor,
    CompanyHomeRequest,
    HomeOperations,
    MissingFinancial,
)
from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import ProjectionRequest
from finai_api.security import require_permission
from finai_api.services import company_context, semantic_analysis
from finai_api.services.workspace import WorkspaceError


def _accepted(value: Any, kind: str) -> CanonicalResource:
    resource = CanonicalResource.model_validate(value)
    if (
        resource.object_type != kind
        or resource.authority_state != "APPROVED"
        or resource.evidence_class == "REFERENCE_TEMPLATE"
    ):
        raise WorkspaceError(409, "Company Home requires accepted canonical context")
    return resource


def describe(principal: Principal, request: CompanyHomeRequest) -> CompanyHomeDescriptor:
    require_permission(principal, "ontology_read")
    # This resolver preserves ExactScope, accepted dependency pins and snapshot cutoffs.
    snapshot = company_context.resolve(
        principal, request.company_id, request.valid_at, request.known_at
    )
    context = snapshot.get("context")
    if not context:
        raise WorkspaceError(404, "Company Home is unavailable for this company")
    company = _accepted(context["company"], "LegalEntity")
    if company.resource_id != request.company_id:
        raise WorkspaceError(404, "Company Home is unavailable for this company")

    packs: dict[UUID, CanonicalResource] = {}

    def retain_pack(value: Any) -> None:
        pack = _accepted(value, "DomainPack")
        prior = packs.get(pack.resource_id)
        if prior is not None and prior != pack:
            raise WorkspaceError(409, "Company Home has conflicting domain-pack versions")
        packs[pack.resource_id] = pack

    for workspace in snapshot["workspaces"]:
        if workspace["company"]["resource_id"] != str(company.resource_id):
            continue
        owner = _accepted(workspace["company"], "LegalEntity")
        if owner != company:
            raise WorkspaceError(409, "Company workspace differs from the selected snapshot")
        _accepted(workspace["configuration"], "CompanyWorkspace")
        _accepted(workspace["enterprise"], "EnterpriseGroup")
        retain_pack(workspace["domain_pack"])
    for relationship in context["relationships"]:
        if (
            relationship["kind"] == "USES_DOMAIN_PACK"
            and relationship["source"]["resource_id"] == str(company.resource_id)
        ):
            _accepted(relationship["record"], "Relationship")
            retain_pack(relationship["target"])

    analyses = []
    for invocation_id in request.invocation_ids:
        # The retained result has its own company version, financial context and time
        # cutoffs. Never substitute this Home snapshot's date for its financial period.
        projection = semantic_analysis.project(
            principal,
            ProjectionRequest(company_id=request.company_id, invocation_id=invocation_id),
        )
        if (
            projection.descriptor.company.resource_id != request.company_id
            or projection.descriptor.invocation_id != invocation_id
            or projection.request.company_id != request.company_id
            or projection.request.invocation_id != invocation_id
        ):
            raise WorkspaceError(409, "Retained analysis differs from the Home selection")
        analyses.append(projection)

    domain_packs = sorted(packs.values(), key=lambda pack: str(pack.resource_id))
    # Pack codes select a supported geography view, never a live operating assertion.
    gas = any(pack.attributes.get("code") == "GEORGIAN_GAS" for pack in domain_packs)
    return CompanyHomeDescriptor(
        company=company,
        company_label=company.display_name,
        valid_at=snapshot["valid_at"],
        known_at=snapshot["known_at"],
        domain_packs=domain_packs,
        analyses=analyses,
        operations=HomeOperations(
            lens="gas_network" if gas else "enterprise_assets",
            valid_at=snapshot["valid_at"],
            known_at=snapshot["known_at"],
            domain_pack_ids=[pack.resource_id for pack in domain_packs],
            limitation="Accepted geography only; positions do not establish connectivity, "
            "live operating condition or performance. Each retained analysis keeps its "
            "own financial context and time cutoffs.",
        ),
        unavailable_financials=[
            MissingFinancial(
                key="profit_loss",
                label="Profit and loss",
                reason="A retained statement with reviewed account classification and "
                "complete period coverage is not connected to Home.",
            ),
            MissingFinancial(
                key="balance_sheet",
                label="Balance sheet",
                reason="Retained opening and closing balances with reviewed statement "
                "classification are not connected to Home.",
            ),
            MissingFinancial(
                key="cash_flow",
                label="Cash flow",
                reason="A reviewed cash-flow result and cash reconciliation are not "
                "connected to Home.",
            ),
            MissingFinancial(
                key="working_capital",
                label="Working capital",
                reason="Reviewed receivables, payables and inventory balances at a shared "
                "financial cutoff are not connected to Home.",
            ),
        ],
    )
