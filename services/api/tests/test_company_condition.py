"""Company condition never turns visible neighbors or current proposals into historical facts."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg import OperationalError
from psycopg.errors import QueryCanceled
from test_company_home import resource, uid

from finai_api.api.company_condition_routes import router
from finai_api.domain.company_condition import CompanyJournalReviews
from finai_api.domain.ontology_catalog import TYPE_FIELDS
from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import company_condition as service
from finai_api.services.workspace import WorkspaceError

read_connections = service.connection_snapshot


@pytest.fixture
def case(monkeypatch):
    company = CanonicalResource.model_validate(resource("Company", "LegalEntity"))
    principal = Principal(
        actor_id="condition-reader", display_name="Company reader",
        scope={"tenant_id": uid("tenant"), "legal_entity_id": "entity-ge-001",
               "period": "2026-08", "currency": "GEL"},
        permissions=("read", "ontology_read"),
    )
    snapshot = {
        "context": {"company": company.model_dump(mode="json"), "licence_evidence": []},
        "valid_at": "2025-01-31T00:00:00.123456+00:00",
        "known_at": "2025-02-01T00:00:00.654321+00:00",
    }
    nodes, pins, calls = [company], {}, []
    queue = {"items": [], "truncated": False}
    operations = {}

    def resolve(*args):
        calls.append(("company", args))
        return snapshot

    def connection_snapshot(*args):
        calls.append(("connections", args))
        return nodes, pins

    def listing(actor, company_id, include_unbound):
        assert actor == principal and company_id == company.resource_id
        assert include_unbound is False
        calls.append(("work", datetime.now(UTC)))
        return queue

    def read(actor, identity):
        assert actor == principal
        return operations[identity]

    monkeypatch.setattr(service.company_context, "resolve", resolve)
    monkeypatch.setattr(service, "connection_snapshot", connection_snapshot)
    monkeypatch.setattr(service.operator_workbench, "listing", listing)
    monkeypatch.setattr(service.ontology_operations, "read", read)
    monkeypatch.setattr(
        service.company_journal_reviews, "observe", lambda *_: CompanyJournalReviews(
            observed_at=datetime.now(UTC), items=[], truncated=False,
        ),
    )
    return dict(company=company, principal=principal, snapshot=snapshot, nodes=nodes,
                pins=pins, calls=calls, queue=queue, operations=operations)


def node(case, name, kind):
    value = CanonicalResource.model_validate(resource(name, kind))
    case["nodes"].append(value)
    return value


def link(case, source, target, name="Association"):
    relation = node(case, name + " type", "LinkType")
    edge = node(case, name, "Relationship")
    edge.attributes.update(source_id=str(source.resource_id), target_id=str(target.resource_id),
                           relation_id=str(relation.resource_id))
    for field, value in (("source_id", source), ("target_id", target), ("relation_id", relation)):
        case["pins"][(str(edge.version_id), field)] = str(value.version_id)
    return edge


def describe(case):
    return service.describe(case["principal"], case["company"].resource_id)


def test_journal_observer_unavailable_does_not_replace_company_snapshot_or_work(case, monkeypatch):
    missing = CompanyJournalReviews(
        state="UNAVAILABLE", reason="Canonical decisions unavailable",
        observed_at=datetime.now(UTC), items=[], truncated=False,
    )
    monkeypatch.setattr(service.company_journal_reviews, "observe", lambda *_: missing)
    result = describe(case)
    assert result.journal_reviews == missing
    assert result.company == case["company"] and result.work.state == "AVAILABLE"
    assert result.known_at.isoformat() == case["snapshot"]["known_at"]


def test_only_explicit_accepted_connections_establish_groups(case):
    connected = node(case, "Accepted supplier", "Supplier")
    node(case, "Unconnected supplier", "Supplier")
    edge = link(case, case["company"], connected)
    result = describe(case)
    assert result.parties.resources == [connected]
    assert result.parties.state == "AVAILABLE"
    assert result.connections[0].record == edge
    assert result.assets.state == "EMPTY" and result.assets.resources == []
    assert not result.current_use_authorized and not result.business_effect_authorized


@pytest.mark.parametrize("field", ["source_id", "target_id", "relation_id"])
def test_unpinned_or_stale_relationship_endpoints_never_enter_company(case, field):
    target = node(case, "Contract", "Contract")
    edge = link(case, case["company"], target)
    case["pins"][(str(edge.version_id), field)] = str(uid("stale version"))
    assert describe(case).contracts.resources == []


@pytest.mark.parametrize("which", ["edge", "target", "relation"])
@pytest.mark.parametrize("change", [{"authority_state": "REVOKED"},
                                    {"evidence_class": "REFERENCE_TEMPLATE"}])
def test_rejected_or_reference_only_nodes_do_not_confer_operating_presence(case, which, change):
    target = node(case, "Asset", "Facility")
    edge = link(case, case["company"], target)
    chosen = edge if which == "edge" else target if which == "target" else case["nodes"][-2]
    index = case["nodes"].index(chosen)
    case["nodes"][index] = chosen.model_copy(update=change)
    assert describe(case).assets.resources == []


def test_one_operating_unit_hop_is_allowed_but_party_and_company_bridges_are_not(case):
    unit = node(case, "Operating unit", "BusinessUnit")
    facility = node(case, "Unit asset", "Facility")
    supplier = node(case, "Supplier", "Supplier")
    foreign = node(case, "Other company", "LegalEntity")
    inaccessible = node(case, "Other contract", "Contract")
    link(case, case["company"], unit, "Unit link")
    link(case, unit, facility, "Unit asset link")
    link(case, case["company"], supplier, "Supplier link")
    link(case, supplier, inaccessible, "Supplier contract")
    link(case, case["company"], foreign, "Other company link")
    link(case, foreign, inaccessible, "Other company contract")
    result = describe(case)
    assert {row.resource_id for row in result.assets.resources} == {
        unit.resource_id, facility.resource_id
    }
    assert result.contracts.resources == []
    assert len(result.connections) == 3


def test_reversed_relationship_does_not_imply_ownership(case):
    asset = node(case, "Reversed asset", "Facility")
    link(case, asset, case["company"])
    assert describe(case).assets.resources == []


def test_products_use_only_registered_type_and_exact_company_or_unit_connections(case):
    assert service.PRODUCTS == {"Product"} <= TYPE_FIELDS.keys()
    direct = node(case, "Direct product", "Product")
    unit = node(case, "Product operating unit", "BusinessUnit")
    unit_product = node(case, "Unit product", "Product")
    node(case, "Unconnected product", "Product")
    link(case, case["company"], direct, "Company product")
    link(case, case["company"], unit, "Company unit")
    link(case, unit, unit_product, "Unit product relationship")
    result = describe(case)
    assert result.products.state == "AVAILABLE"
    assert result.products.resources == [direct, unit_product]
    assert result.products.coverage == "EXPLICIT_CONNECTED_RESOURCE_SNAPSHOT"
    assert "product availability" in result.products.reason
    assert "Product" in service.KINDS
    assert not result.current_use_authorized and not result.business_effect_authorized


@pytest.mark.parametrize("field", ["source_id", "target_id", "relation_id"])
@pytest.mark.parametrize("pin", ["missing", "stale"])
def test_products_require_every_exact_accepted_relationship_pin(case, field, pin):
    product = node(case, "Pinned product", "Product")
    edge = link(case, case["company"], product)
    key = (str(edge.version_id), field)
    if pin == "missing":
        del case["pins"][key]
    else:
        case["pins"][key] = str(uid("stale product link"))
    result = describe(case)
    assert result.products.state == "EMPTY" and result.products.resources == []


@pytest.mark.parametrize("bridge", ["LegalEntity", "Supplier", "Product"])
def test_product_connections_do_not_expand_through_foreign_company_party_or_product(case, bridge):
    intermediary = node(case, "Foreign bridge", bridge)
    foreign_product = node(case, "Foreign product", "Product")
    link(case, case["company"], intermediary, "Bridge")
    link(case, intermediary, foreign_product, "Foreign product")
    assert foreign_product not in describe(case).products.resources


@pytest.mark.parametrize("change", [{"authority_state": "REVOKED"},
                                    {"evidence_class": "REFERENCE_TEMPLATE"}])
def test_unaccepted_product_definitions_are_excluded(case, change):
    product = node(case, "Unaccepted product", "Product")
    link(case, case["company"], product)
    case["nodes"][case["nodes"].index(product)] = product.model_copy(update=change)
    assert describe(case).products.resources == []


def test_product_family_and_reverse_links_do_not_establish_company_products(case):
    family = node(case, "Unsupported family", "ProductFamily")
    reverse = node(case, "Reverse product", "Product")
    link(case, case["company"], family, "Family")
    link(case, reverse, case["company"], "Reverse")
    assert describe(case).products.resources == []


def test_snapshot_company_version_mismatch_fails_closed(case):
    case["nodes"][0] = case["company"].model_copy(update={"version_id": uid("new company")})
    with pytest.raises(WorkspaceError) as failure:
        describe(case)
    assert failure.value.status == 409


def test_historical_snapshot_and_current_work_times_remain_distinct(case):
    result = describe(case)
    assert result.valid_at.isoformat() == case["snapshot"]["valid_at"]
    assert result.known_at.microsecond == 654321
    assert result.work.observed_at > result.known_at
    assert result.work.authority == "CURRENT_RETAINED_WORK"
    passed = case["calls"][1][1]
    assert passed[0] == case["principal"]
    assert passed[1:] == (result.valid_at, result.known_at)
    assert {row.key for row in result.unavailable} == {
        "financial_performance", "live_operations", "findings", "investigations",
        "regulatory_compliance",
    }


def add_work(case, suffix="one", state="PENDING_REVIEW"):
    identity = "opa_" + suffix
    proposal_id = str(uid("proposal " + suffix))
    case["queue"]["items"].append({
        "workflow_id": identity, "family": "ontology", "title": "Review company change",
        "company_id": str(case["company"].resource_id), "company_binding": "EXPLICIT_INVOCATION",
        "created_at": "2026-08-01T00:00:00Z",
    })
    case["operations"][identity] = dict(
        operation_id=identity, state=state, prepared_proposal_id=proposal_id,
        proposal={"proposal": {"proposal_id": proposal_id, "rationale": "Actual retained reason"}},
    )
    return identity


@pytest.mark.parametrize("state", ["PREPARED", "PENDING_REVIEW", "PUBLISHED", "REJECTED"])
def test_company_work_uses_shared_retained_decision_and_proposal(case, state):
    identity = add_work(case, state=state)
    if state == "PREPARED":
        case["operations"][identity]["proposal"] = None
    result = describe(case)
    item = result.work.items[0]
    assert item.state == state and item.workflow_id == identity
    assert str(item.proposal_id) == case["operations"][identity]["prepared_proposal_id"]
    assert item.basis == "EXPLICIT_INVOCATION"


def test_retained_exception_work_preserves_missing_publication_and_company(case):
    identity = add_work(case, state="PUBLICATION_UNAVAILABLE")
    case["queue"]["items"][0]["company_binding"] = "EXPLICIT_RETAINED_EXCEPTION"
    operation = case["operations"][identity]
    operation["definition"] = {
        "kind": "SOURCE_EXCEPTION_INVESTIGATION", "company_id": str(case["company"].resource_id)
    }
    operation["publication_limitation"] = "Exact published versions are unavailable"
    item = describe(case).work.items[0]
    assert item.state == "PUBLICATION_UNAVAILABLE"
    assert item.basis == "EXPLICIT_RETAINED_EXCEPTION"
    assert item.reason == operation["publication_limitation"]
    operation["definition"]["company_id"] = str(uid("foreign"))
    with pytest.raises(WorkspaceError):
        describe(case)


@pytest.mark.parametrize("change", [
    {"company_id": str(uid("foreign"))}, {"company_id": None}, {"company_binding": "UNBOUND"},
])
def test_unbound_or_foreign_work_fails_closed(case, change):
    add_work(case)
    case["queue"]["items"][0].update(change)
    with pytest.raises(WorkspaceError) as failure:
        describe(case)
    assert failure.value.status == 409


@pytest.mark.parametrize("field", ["operation_id", "prepared_proposal_id"])
def test_swapped_work_or_proposal_is_rejected(case, field):
    identity = add_work(case)
    case["operations"][identity][field] = str(uid("swapped"))
    with pytest.raises(WorkspaceError) as failure:
        describe(case)
    assert failure.value.status == 409


def test_current_work_is_bounded_and_reports_truncation(case):
    for index in range(26):
        add_work(case, str(index))
    result = describe(case)
    assert len(result.work.items) == 25
    assert result.work.truncated and result.work.limit == 25


def test_underlying_work_queue_truncation_is_retained(case):
    case["queue"]["truncated"] = True
    assert describe(case).work.truncated is True


@pytest.mark.parametrize("permissions", [("read",), ("ontology_read",), ()])
def test_permissions_precede_company_or_work_reads(case, permissions):
    with pytest.raises(HTTPException) as failure:
        service.describe(case["principal"].model_copy(update={"permissions": permissions}),
                         case["company"].resource_id)
    assert failure.value.status_code == 403
    assert not case["calls"]


def test_http_anonymous_and_ambiguous_time_are_rejected(case):
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/v1/ontology/company-condition", params={
            "company_id": str(case["company"].resource_id)
        }).status_code == 401
        app.dependency_overrides[authenticated_principal] = lambda: case["principal"]
        response = client.get("/v1/ontology/company-condition", params={
            "company_id": str(case["company"].resource_id), "valid_at": "2026-08-01T00:00:00"
        })
        assert response.status_code == 422
    assert not case["calls"]


def test_licence_evidence_preserves_shared_company_projection_without_compliance_claim(case):
    evidence = {"binding": resource("Notice binding", "LicenceNoticeBinding"),
                "notice": resource("Retained notice", "SourceLicenceNotice"), "licence": None}
    case["snapshot"]["context"]["licence_evidence"].append(deepcopy(evidence))
    result = describe(case)
    assert result.licence_evidence[0].binding.resource_id == uid("Notice binding")
    assert result.licence_evidence[0].licence is None
    assert any(row.key == "regulatory_compliance" for row in result.unavailable)


def test_foreign_company_root_rejected_before_connection_or_work_reads(case):
    with pytest.raises(WorkspaceError) as failure:
        service.describe(case["principal"], uid("foreign root"))
    assert failure.value.status == 404
    assert len(case["calls"]) == 1


@pytest.mark.parametrize("error", [OperationalError("unreachable"), QueryCanceled(),
                                   WorkspaceError(503, "Not observed")])
def test_work_outage_preserves_retained_context_without_empty_claim(case, monkeypatch, error):
    def unavailable(*args, **kwargs):
        raise error

    monkeypatch.setattr(service.operator_workbench, "listing", unavailable)
    result = describe(case)
    assert result.company == case["company"]
    assert result.work.state == "UNAVAILABLE" and result.work.reason
    assert result.work.items == []


def fake_connection_reader(case, monkeypatch, rows=None, dependencies=None, error=None):
    queries = []
    context_principals = []

    class Cursor:
        statement = ""

        def execute(self, statement, params=None):
            self.statement = statement
            queries.append((statement, params))
            if error is not None:
                raise error
            return self

        def fetchall(self):
            if "resource_dependencies" in self.statement:
                return dependencies or []
            return rows if rows is not None else [case["company"].model_dump(mode="json")]

    class Connection:
        def cursor(self, **kwargs):
            return nullcontext(Cursor())

    def connection(principal):
        context_principals.append(principal)
        return nullcontext(Connection())

    monkeypatch.setattr(service.resources, "resource_connection", connection)
    return queries, context_principals


def test_connection_reader_uses_rls_principal_tenant_and_both_snapshot_cutoffs(case, monkeypatch):
    queries, principals = fake_connection_reader(case, monkeypatch)
    valid = datetime(2025, 1, 31, 0, 0, 0, 123456, tzinfo=UTC)
    known = datetime(2025, 2, 1, 0, 0, 0, 654321, tzinfo=UTC)
    nodes, pins = read_connections(case["principal"], valid, known)
    assert nodes == [case["company"]] and pins == {}
    assert principals == [case["principal"]]
    statement, params = queries[1]
    assert "v.tenant_id=%s" in statement and "v.system_from<=%s" in statement
    assert "v.valid_from<=%s" in statement and "v.valid_to>%s" in statement
    assert "authority_state='APPROVED'" in statement
    assert "evidence_class<>'REFERENCE_TEMPLATE'" in statement
    assert params == (case["principal"].scope.tenant_id, service.KINDS, known, valid, valid, 5001)
    assert queries[2][1] == (case["principal"].scope.tenant_id, [case["company"].version_id])


@pytest.mark.parametrize("overflow", ["resources", "pins"])
def test_connection_reader_fails_closed_at_declared_bounds(case, monkeypatch, overflow):
    fake_connection_reader(
        case, monkeypatch,
        rows=[case["company"].model_dump(mode="json")] * 5001 if overflow == "resources" else None,
        dependencies=[{}] * 15001 if overflow == "pins" else None,
    )
    with pytest.raises(WorkspaceError) as failure:
        read_connections(case["principal"], datetime.now(UTC), datetime.now(UTC))
    assert failure.value.status == 409


def test_connection_timeout_does_not_return_partial_company(case, monkeypatch):
    fake_connection_reader(case, monkeypatch, error=QueryCanceled())
    with pytest.raises(WorkspaceError) as failure:
        read_connections(case["principal"], datetime.now(UTC), datetime.now(UTC))
    assert failure.value.status == 409
