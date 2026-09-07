"""Business API over the shared reviewed account analytical-rule authority."""

from datetime import UTC, datetime
from uuid import UUID

from psycopg.rows import dict_row
from pydantic import Field, RootModel, field_validator

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.journal_dimensions import PolicyDefinition, Reasoned
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import (
    CanonicalResource,
    ProposalRequestBinding,
    ResourceMutation,
    ResourceProposal,
)
from finai_api.security import require_permission
from finai_api.services import journal_dimensions as core
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


class ProposalRequest(Reasoned):
    request_id: UUID
    expected_version_id: UUID | None
    company: VersionReference
    chart: VersionReference
    account: VersionReference
    rules: list[VersionReference] = Field(max_length=32)

    @field_validator("rules")
    @classmethod
    def distinct_rules(cls, values):
        return PolicyDefinition.unique(values)


def _canonical(node):
    return CanonicalResource.model_validate(node).model_dump(mode="json")


def _reader(conn, principal, at):
    cache = {}

    def target(identity, *_):
        key = str(identity)
        if key not in cache:
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.execute(
                    "SELECT v.*,i.identity_key FROM resource_versions v "
                    "JOIN canonical_identities i USING(tenant_id,resource_id) "
                    "WHERE v.tenant_id=%s AND v.resource_id=%s "
                    "AND v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,%s)",
                    (principal.scope.tenant_id, UUID(key), at),
                ).fetchone()
            if row is None:
                raise WorkspaceError(404, "Current account policy context is unavailable")
            cache[key] = _canonical(row)
        return cache[key]

    return target


def _context(conn, principal, company_id, account_id, at, target):
    account = core.require_node(conn, principal, target(account_id), "LocalAccount", at)
    chart = core.require_node(
        conn, principal, target(account["attributes"]["chart_id"]), "LocalChartOfAccounts", at
    )
    company = core.require_node(conn, principal, target(company_id), "LegalEntity", at)
    core.edge(conn, principal, account, "chart_id", chart)
    core.edge(conn, principal, chart, "legal_entity_id", company)
    return company, chart, account


def read(principal, company_id: UUID, account_id: UUID):
    require_permission(principal, "ontology_read")
    with resources.resource_connection(principal) as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
            (f"canonical:{principal.scope.tenant_id}",),
        )
        at = datetime.now(UTC)
        target = _reader(conn, principal, at)
        company, chart, account = _context(conn, principal, company_id, account_id, at, target)
        identity, _ = core.policy_identity(principal.scope.tenant_id, account_id)
        try:
            policy = target(identity)
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            policy = None
        rows = conn.execute(
            "SELECT v.resource_id,v.version_id FROM resource_versions v "
            "WHERE v.tenant_id=%s AND v.object_type='AccountDimensionRule' "
            "AND v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,%s) "
            "AND v.attributes->>'account_id'=%s AND v.authority_state='APPROVED' "
            "ORDER BY v.resource_id LIMIT 33",
            (principal.scope.tenant_id, at, str(account_id)),
        ).fetchall()
        refs = [VersionReference(resource_id=row[0], version_id=row[1]) for row in rows]
        complete = False
        rules = []
        state = "UNESTABLISHED" if policy is None else "STALE"
        reason = "No reviewed completeness policy is established for this account"
        try:
            candidate = {
                "resource_id": str(identity),
                "attributes": {
                    "account_id": str(account_id),
                    "chart_id": chart["resource_id"],
                    "legal_entity_id": str(company_id),
                    "definition": PolicyDefinition(
                        contract="account-dimension-policy/1",
                        rules=refs,
                        reason="Current rule-set discovery; not a reviewed policy",
                    ).model_dump(mode="json"),
                },
            }
            discovered = core.inspect_policy(conn, principal, candidate, account, target, at)
            rules = [
                {"rule": _canonical(rule), "dimension": _canonical(dimension)}
                for rule, dimension in discovered.values()
            ]
            complete = True
            if policy:
                core.require_node(conn, principal, policy, "AccountDimensionPolicy", at)
                core.inspect_policy(conn, principal, policy, account, target, at)
                state = "CURRENT"
                reason = policy["attributes"]["definition"]["reason"]
        except WorkspaceError as exc:
            if exc.status not in (404, 409, 422):
                raise
            reason = str(exc.detail)
        except ValueError:
            reason = "Account rule set or policy exceeds its typed contract"
        return {
            "company": company,
            "chart": chart,
            "account": account,
            "policy": policy,
            "state": state,
            "reason": reason,
            "rules_complete": complete,
            "rules": rules,
            "checked_at": at.isoformat(),
            "current_use_authorized": False,
        }


def propose(principal, request: ProposalRequest):
    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    binding = ProposalRequestBinding(
        operation="account-dimension-policy/1",
        content_sha256=canonical_sha256(
            RootModel(
                {
                    "scope": principal.scope.model_dump(mode="json"),
                    "request": request.model_dump(mode="json"),
                }
            )
        ),
    )
    with resources.resource_connection(principal) as conn:
        old = conn.execute(
            "SELECT submitted_by,payload FROM resource_proposals "
            "WHERE tenant_id=%s AND proposal_id=%s",
            (principal.scope.tenant_id, request.request_id),
        ).fetchone()
        if old:
            proposal = ResourceProposal.model_validate(old[1]["request"])
            if old[0] != principal.actor_id or proposal.request_binding != binding:
                raise WorkspaceError(
                    409, "Account policy request identity was reused for different content"
                )
        else:
            at = datetime.now(UTC)
            target = _reader(conn, principal, at)
            company, chart, account = _context(
                conn,
                principal,
                request.company.resource_id,
                request.account.resource_id,
                at,
                target,
            )
            for node, ref in [
                (company, request.company),
                (chart, request.chart),
                (account, request.account),
            ]:
                if core.pin(node) != ref.model_dump(mode="json"):
                    raise WorkspaceError(409, "Account context changed; refresh before review")
            identity, key = core.policy_identity(
                principal.scope.tenant_id, request.account.resource_id
            )
            definition = PolicyDefinition(
                contract="account-dimension-policy/1", rules=request.rules, reason=request.reason
            )
            proposal = ResourceProposal(
                proposal_id=request.request_id,
                title="Review account analytical requirements",
                rationale=request.reason,
                access_entity=account["access_entity"],
                request_binding=binding,
                source_versions={
                    identity: {
                        ref.resource_id: ref.version_id
                        for ref in [request.company, request.chart, request.account]
                    }
                },
                mutations=[
                    ResourceMutation(
                        resource_id=identity,
                        identity_key=key,
                        object_type="AccountDimensionPolicy",
                        display_name="Analytical policy: " + account["display_name"][:170],
                        expected_version_id=request.expected_version_id,
                        valid_from=at,
                        evidence_class="USER_ASSERTED",
                        attributes={
                            "account_id": account["resource_id"],
                            "chart_id": chart["resource_id"],
                            "legal_entity_id": company["resource_id"],
                            "definition": definition.model_dump(mode="json"),
                        },
                    )
                ],
            )
    detail = (
        resources.proposal_detail(principal, request.request_id)
        if old
        else resources.propose(principal, proposal)
    )
    return {
        "proposal_id": str(proposal.proposal_id),
        "policy_id": str(proposal.mutations[0].resource_id),
        "decision": detail.decision,
        "review_required": detail.decision is None,
    }
