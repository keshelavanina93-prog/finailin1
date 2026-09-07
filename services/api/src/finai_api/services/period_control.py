"""Reviewed current posting permission; not financial close or ERP execution."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ProposalRequestBinding, ResourceMutation, ResourceProposal
from finai_api.security import require_permission
from finai_api.services import company_journals, resources
from finai_api.services.workspace import WorkspaceError

FIELDS = {
    "legal_entity_id": "LegalEntity",
    "ledger_id": "Ledger",
    "book_id": "AccountingBook",
    "period_id": "FiscalPeriod",
    "chart_id": "LocalChartOfAccounts",
    "currency_id": "Currency",
    "calendar_id": "FiscalCalendar",
}


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract: Literal["period-posting-control/1"] = "period-posting-control/1"
    state: Literal["OPEN", "LOCKED"]
    reason: str = Field(min_length=10, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if value != value.strip():
            raise ValueError("Posting control reason cannot be empty or padded")
        return value


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    selection: dict[str, VersionReference]
    request_id: UUID
    expected_version_id: UUID | None
    state: Literal["OPEN", "LOCKED"]
    reason: str = Field(min_length=10, max_length=2000)

    @field_validator("selection")
    @classmethod
    def exact_context(cls, value):
        if set(value) != set(FIELDS):
            raise ValueError("Posting control requires all seven explicit accounting context pins")
        return value

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        return Definition(state="OPEN", reason=value).reason


def identity(tenant, attrs):
    key = (
        f"company:{attrs['legal_entity_id']}:ledger:{attrs['ledger_id']}:"
        f"book:{attrs['book_id']}:period:{attrs['period_id']}"
    )
    return canonical_id(tenant, "PeriodControl", key), key


def pin(node):
    return {key: str(node[key]) for key in ["resource_id", "version_id"]}


def current_pins(conn, principal, selected):
    at = datetime.now(UTC)
    for field, pin in selected.items():
        row = conn.execute(
            "SELECT v.version_id,v.object_type,v.authority_state,v.valid_from,v.valid_to,"
            "v.evidence_class,g8_effective_version_id(v.tenant_id,v.resource_id,%s) "
            "FROM resource_heads h JOIN resource_versions v "
            "USING(tenant_id,resource_id,version_id) "
            "WHERE h.tenant_id=%s AND h.resource_id=%s",
            (at, principal.scope.tenant_id, UUID(pin["resource_id"])),
        ).fetchone()
        if (
            not row
            or str(row[0]) != pin["version_id"]
            or row[1] != FIELDS[field]
            or row[2] != "APPROVED"
            or row[3] > at
            or (row[4] is not None and row[4] <= at)
            or row[5] == "REFERENCE_TEMPLATE"
            or row[6] != row[0]
        ):
            raise WorkspaceError(
                409, "Posting control context is stale or unavailable; refresh selection"
            )
        available(conn, principal, pin["version_id"])


def available(conn, principal, version_id):
    latest = conn.execute(
        "SELECT payload FROM resource_lifecycle_events WHERE tenant_id=%s "
        "AND version_id=%s ORDER BY recorded_at DESC,event_id DESC LIMIT 1",
        (principal.scope.tenant_id, UUID(version_id)),
    ).fetchone()
    if latest and (
        latest[0].get("target_state") in {"REVOKED", "SUPERSEDED"}
        or latest[0].get("availability_state") != "AVAILABLE"
    ):
        raise WorkspaceError(
            409, "Posting control or accounting context has recorded withdrawal or unavailability"
        )


def check_control(conn, principal, control, selected):
    control = {**control, **pin(control)}
    at = datetime.now(UTC)
    if (
        control["object_type"] != "PeriodControl"
        or control["authority_state"] != "APPROVED"
        or datetime.fromisoformat(str(control["valid_from"])) > at
        or control["valid_to"] is not None
        or control["evidence_class"] == "REFERENCE_TEMPLATE"
    ):
        raise WorkspaceError(409, "Posting control has no immediate reviewed state")
    row = conn.execute(
        "SELECT version_id FROM resource_heads WHERE tenant_id=%s AND resource_id=%s",
        (principal.scope.tenant_id, UUID(control["resource_id"])),
    ).fetchone()
    if not row or str(row[0]) != control["version_id"]:
        raise WorkspaceError(409, "Posting control version is no longer current")
    available(conn, principal, control["version_id"])
    edges = conn.execute(
        "SELECT relation,target_resource_id,target_version_id FROM resource_dependencies "
        "WHERE tenant_id=%s AND version_id=%s AND relation=ANY(%s)",
        (principal.scope.tenant_id, UUID(control["version_id"]), ["FIELD:" + f for f in FIELDS]),
    ).fetchall()
    pins = {row[0][6:]: {"resource_id": str(row[1]), "version_id": str(row[2])} for row in edges}
    if (
        len(edges) != 7
        or pins != selected
        or any(control["attributes"].get(f) != p["resource_id"] for f, p in selected.items())
    ):
        raise WorkspaceError(
            409, "Posting control pins do not match the current accounting selection"
        )
    current_pins(conn, principal, selected)
    try:
        return Definition.model_validate(control["attributes"]["definition"])
    except ValueError as exc:
        raise WorkspaceError(409, "Posting control definition is unavailable or invalid") from exc


def read(principal, company_id, ledger_id, book_id, period_id):
    at = datetime.now(UTC)
    selected = company_journals.selection(principal, company_id, ledger_id, book_id, period_id, at)
    attrs = {f: p["resource_id"] for f, p in selected.items()}
    control_id, _ = identity(principal.scope.tenant_id, attrs)
    control = resources.current_resources(principal, [control_id]).get(str(control_id))
    state = "UNESTABLISHED"
    reason = "No current reviewed posting control is established"
    if control:
        try:
            with resources.resource_connection(principal) as conn:
                conn.execute(
                    "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
                    (f"canonical:{principal.scope.tenant_id}",),
                )
                definition = check_control(conn, principal, control, selected)
            state = definition.state
            reason = definition.reason
        except WorkspaceError as exc:
            reason = str(exc.detail)
    return {
        "selection": selected,
        "control": control,
        "state": state,
        "reason": reason,
        "checked_at": datetime.now(UTC).isoformat(),
        "current_use_authorized": False,
        "financial_close_certified": False,
        "erp_posted": False,
    }


def validate(conn, principal, item, target, proposal):
    attrs = item.attributes
    owner = str(item.resource_id)
    try:
        Definition.model_validate(attrs.get("definition"))
    except ValueError as exc:
        raise WorkspaceError(
            422, "PeriodControl requires OPEN or LOCKED and a meaningful reason"
        ) from exc
    if (
        item.authority_state != "APPROVED"
        or item.valid_to is not None
        or item.valid_from > datetime.now(UTC)
    ):
        raise WorkspaceError(
            422,
            "Posting controls require immediate reviewed state; use LOCKED instead of revocation",
        )
    expected, key = identity(principal.scope.tenant_id, attrs)
    if item.resource_id != expected or item.identity_key != key:
        raise WorkspaceError(
            422, "PeriodControl identity must match its immutable company/ledger/book/period tuple"
        )
    if any(m.object_type in {"JournalEntry", "JournalLine"} for m in proposal.mutations):
        raise WorkspaceError(422, "Review posting controls separately from journal publication")
    if any(str(m.resource_id) in {attrs[f] for f in FIELDS} for m in proposal.mutations):
        raise WorkspaceError(422, "Posting controls require previously reviewed accounting context")
    nodes = {f: target(attrs[f], owner, "PERIOD_CONTROL_CONTEXT:" + f) for f in FIELDS}
    selected = {f: pin(n) for f, n in nodes.items()}
    current_pins(conn, principal, selected)
    relations = [
        ("ledger_id", "legal_entity_id"),
        ("ledger_id", "chart_id"),
        ("ledger_id", "currency_id"),
        ("ledger_id", "calendar_id"),
        ("book_id", "ledger_id"),
        ("period_id", "calendar_id"),
        ("chart_id", "legal_entity_id"),
    ]
    for source, field in relations:
        if nodes[source]["attributes"].get(field) != attrs[field]:
            raise WorkspaceError(422, "Posting control accounting context relationships disagree")
        edge = conn.execute(
            "SELECT target_resource_id,target_version_id FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=%s AND relation=%s",
            (principal.scope.tenant_id, UUID(str(nodes[source]["version_id"])), "FIELD:" + field),
        ).fetchone()
        if (
            not edge
            or str(edge[0]) != selected[field]["resource_id"]
            or str(edge[1]) != selected[field]["version_id"]
        ):
            raise WorkspaceError(409, "Posting control context has stale exact relationships")


def require_open(conn, principal, item, binding, target, proposal):
    if any(m.object_type == "PeriodControl" for m in proposal.mutations):
        raise WorkspaceError(
            422, "Posting controls and journals require separate independent reviews"
        )
    owner = str(item.resource_id)
    config = binding["attributes"]
    scope = target(config["scope_id"], owner, "PERIOD_CONTROL_SOURCE_SCOPE")
    ledger = target(config["ledger_id"], owner, "PERIOD_CONTROL_LEDGER")
    attrs = {f: config[f] for f in ["ledger_id", "book_id", "period_id", "currency_id"]}
    attrs.update(
        legal_entity_id=scope["attributes"]["legal_entity_id"],
        chart_id=scope["attributes"]["chart_id"],
        calendar_id=ledger["attributes"]["calendar_id"],
    )
    selected = {f: pin(target(value, owner, "PERIOD_CONTEXT:" + f)) for f, value in attrs.items()}
    control_id, _ = identity(principal.scope.tenant_id, attrs)
    try:
        control = target(str(control_id), owner, "PERIOD_POSTING_CONTROL")
        definition = check_control(conn, principal, control, selected)
    except WorkspaceError as exc:
        raise WorkspaceError(
            409,
            "Posting control is unestablished or stale; "
            "review an OPEN control before publishing journals",
        ) from exc
    if definition.state != "OPEN":
        raise WorkspaceError(
            409, "Posting is LOCKED for this company, ledger, book and fiscal period"
        )


def propose(principal, request: ProposalRequest):
    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    binding = ProposalRequestBinding(
        operation="period-posting-control/1",
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
                409, "Posting-control request identity was reused for different content"
            )
        detail = resources.proposal_detail(principal, request.request_id)
    else:
        pins = {f: p.model_dump(mode="json") for f, p in request.selection.items()}
        expected = company_journals.selection(
            principal,
            request.selection["legal_entity_id"].resource_id,
            request.selection["ledger_id"].resource_id,
            request.selection["book_id"].resource_id,
            request.selection["period_id"].resource_id,
            datetime.now(UTC),
        )
        if pins != expected:
            raise WorkspaceError(
                409, "Accounting selection changed; refresh before proposing posting control"
            )
        attrs = {f: p["resource_id"] for f, p in pins.items()}
        control_id, key = identity(principal.scope.tenant_id, attrs)
        definition = Definition(state=request.state, reason=request.reason)
        proposal = ResourceProposal(
            proposal_id=request.request_id,
            title="Change period posting control",
            rationale=request.reason,
            access_entity=principal.scope.legal_entity_id,
            request_binding=binding,
            source_versions={
                control_id: {
                    UUID(pin["resource_id"]): UUID(pin["version_id"]) for pin in pins.values()
                }
            },
            mutations=[
                ResourceMutation(
                    resource_id=control_id,
                    expected_version_id=request.expected_version_id,
                    object_type="PeriodControl",
                    identity_key=key,
                    display_name="Period posting control",
                    attributes={**attrs, "definition": definition.model_dump(mode="json")},
                    valid_from=datetime.now(UTC),
                    evidence_class="USER_ASSERTED",
                )
            ],
        )
        detail = resources.propose(principal, proposal)
    return {
        "proposal_id": str(proposal.proposal_id),
        "control_id": str(proposal.mutations[0].resource_id),
        "decision": detail.decision,
        "review_required": detail.decision is None,
    }
