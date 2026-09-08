"""Home composes retained authority without publishing, aggregating or guessing periods."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from finai_api.api.company_home_routes import router
from finai_api.domain.company_home import CompanyHomeRequest
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import Descriptor, Pin, Projection
from finai_api.services import company_home as service
from finai_api.services.workspace import WorkspaceError


def uid(name):
    return uuid5(NAMESPACE_URL, "company-home-test:" + name)


def resource(name, kind, attributes=None):
    return dict(
        resource_id=str(uid(name)),
        version_id=str(uid(name + ":version")),
        object_type=kind,
        identity_key=name,
        display_name=name,
        access_entity="entity-ge-001",
        schema_version_id=None,
        attributes=attributes or {},
        content_hash="a" * 64,
        valid_from="2025-01-01T00:00:00Z",
        valid_to=None,
        system_from="2025-01-01T00:00:00Z",
        authority_state="APPROVED",
        evidence_class="SOURCE_BOUND",
        proposal_id=None,
    )


def pin(node):
    return Pin.model_validate(
        {key: node[key] for key in ("resource_id", "version_id", "content_hash")}
    )


@pytest.fixture
def case(monkeypatch):
    company = resource("A company", "LegalEntity")
    pack = resource("Gas semantics", "DomainPack", {"code": "GEORGIAN_GAS", "version": "1"})
    workspace = dict(
        company=company,
        configuration=resource("Company workspace", "CompanyWorkspace"),
        enterprise=resource("Enterprise", "EnterpriseGroup"),
        domain_pack=pack,
    )
    snapshot = dict(
        context={"company": company, "relationships": []},
        workspaces=[workspace],
        valid_at="2026-08-01T00:00:00Z",
        known_at="2026-09-08T00:00:00Z",
    )
    principal = Principal(
        actor_id="home-reader",
        display_name="Home reader",
        scope={
            "tenant_id": uid("tenant"),
            "legal_entity_id": "entity-ge-001",
            "period": "2026-08",
            "currency": "GEL",
        },
        permissions=("read", "ontology_read"),
    )
    calls = []

    def resolve(*args):
        calls.append(("context", args))
        return snapshot

    def project(actor, request):
        calls.append(("analysis", actor, request))
        return Projection(
            descriptor=Descriptor(
                contract="semantic-analysis/2",
                invocation_id=request.invocation_id,
                receipt_hash="b" * 64,
                run_id="fcr_" + "c" * 64,
                function=pin(resource("Reviewed Function", "FunctionDefinition")),
                company=pin(company),
                company_label=company["display_name"],
                title="Retained source definitions",
                grain=["resource"],
                fields=[],
                measure=None,
                visual="NONE",
                authority="Source definitions only",
                coverage=[{"label": "Source records", "value": "Empty retained selection"}],
                context=[{"label": "Observed period", "value": "January 2025"}],
                valid_at="2025-01-31T00:00:00Z",
                known_at="2025-02-01T00:00:00Z",
                recorded_at="2025-02-01T00:00:00Z",
                definitions=[],
                unavailable_operations=["Financial totals are unavailable"],
            ),
            descriptor_sha256="d" * 64,
            rows=[],
            total_rows=0,
            sections=[],
            selection=None,
            request=request,
        )

    monkeypatch.setattr(service.company_context, "resolve", resolve)
    monkeypatch.setattr(service.semantic_analysis, "project", project)
    return principal, snapshot, calls


def request_for(case, **kwargs):
    return CompanyHomeRequest(company_id=case[1]["context"]["company"]["resource_id"], **kwargs)


def test_retained_period_and_receipt_remain_independent_of_home_snapshot(case):
    invocation = uid("historical run")
    request = request_for(case, invocation_ids=[invocation])
    result = service.describe(case[0], request)
    analysis = result.analyses[0]
    assert result.contract == "g8-company-home/1"
    assert analysis.descriptor.invocation_id == invocation
    assert analysis.descriptor.receipt_hash == "b" * 64
    assert analysis.descriptor.context[0].value == "January 2025"
    assert analysis.descriptor.valid_at == "2025-01-31T00:00:00Z"
    assert result.operations.valid_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert result.operations.known_at == datetime(2026, 9, 8, tzinfo=UTC)
    assert result.operations.authority == "GEOGRAPHY_CONTEXT_ONLY"
    assert not result.current_use_authorized and not result.business_effect_authorized
    assert [item.key for item in result.unavailable_financials] == [
        "profit_loss", "balance_sheet", "cash_flow", "working_capital"
    ]
    assert result.analyses[0].rows == []  # Empty source selection never becomes zero financials.


def test_no_selected_results_does_not_discover_or_execute(case):
    result = service.describe(case[0], request_for(case))
    assert result.analyses == []
    assert len(case[2]) == 1
    assert result.operations.lens == "gas_network"


def test_explicit_aware_cutoffs_reach_existing_resolver(case):
    request = request_for(
        case, valid_at="2025-01-01T04:00:00+04:00", known_at="2025-03-01T00:00:00Z"
    )
    service.describe(case[0], request)
    assert case[2][0][1] == (case[0], request.company_id, request.valid_at, request.known_at)


@pytest.mark.parametrize("field", ["valid_at", "known_at"])
def test_naive_cutoff_rejected(case, field):
    with pytest.raises(ValidationError):
        request_for(case, **{field: "2025-01-01T00:00:00"})


@pytest.mark.parametrize("ids", [[uid("same")] * 2, [uid(str(i)) for i in range(7)]])
def test_duplicate_or_unbounded_results_rejected(case, ids):
    with pytest.raises(ValidationError):
        request_for(case, invocation_ids=ids)


def test_caller_cannot_supply_a_descriptor_or_financial_period(case):
    with pytest.raises(ValidationError):
        request_for(case, descriptor={"authority": "CERTIFIED"})
    with pytest.raises(ValidationError):
        request_for(case, financial_period="2026-08")


def test_permission_checked_before_context_or_result_reads(case):
    with pytest.raises(HTTPException) as failure:
        service.describe(case[0].model_copy(update={"permissions": ("read",)}), request_for(case))
    assert failure.value.status_code == 403
    assert not case[2]


def test_cross_company_context_fails_closed(case):
    request = CompanyHomeRequest(company_id=uid("foreign company"))
    with pytest.raises(WorkspaceError) as failure:
        service.describe(case[0], request)
    assert failure.value.status == 404
    assert len(case[2]) == 1


@pytest.mark.parametrize("change", [{"evidence_class": "REFERENCE_TEMPLATE"},
                                    {"authority_state": "REVOKED"}])
def test_unaccepted_domain_pack_cannot_choose_a_lens(case, change):
    case[1]["workspaces"][0]["domain_pack"].update(change)
    with pytest.raises(WorkspaceError) as failure:
        service.describe(case[0], request_for(case))
    assert failure.value.status == 409


def test_names_do_not_select_gas_operations(case):
    case[1]["workspaces"][0]["domain_pack"]["attributes"]["code"] = "PETROLEUM"
    result = service.describe(case[0], request_for(case))
    assert result.domain_packs[0].display_name == "Gas semantics"
    assert result.operations.lens == "enterprise_assets"


def test_same_canonical_pack_is_deduplicated_without_new_identity(case):
    workspace = case[1]["workspaces"][0]
    case[1]["context"]["relationships"].append(dict(
        kind="USES_DOMAIN_PACK", record=resource("Uses pack", "Relationship"),
        source=workspace["company"], target=workspace["domain_pack"],
    ))
    result = service.describe(case[0], request_for(case))
    assert len(result.domain_packs) == 1
    assert result.operations.domain_pack_ids == [uid("Gas semantics")]


def test_conflicting_pack_version_fails_closed(case):
    second = deepcopy(case[1]["workspaces"][0])
    second["domain_pack"]["version_id"] = str(uid("different pack version"))
    case[1]["workspaces"].append(second)
    with pytest.raises(WorkspaceError) as failure:
        service.describe(case[0], request_for(case))
    assert failure.value.status == 409


def test_foreign_workspace_does_not_add_its_pack(case):
    case[1]["workspaces"][0]["company"] = resource("Foreign", "LegalEntity")
    result = service.describe(case[0], request_for(case))
    assert result.domain_packs == []
    assert result.operations.lens == "enterprise_assets"


@pytest.mark.parametrize("status", [404, 409, 422])
def test_unavailable_analysis_stops_whole_projection(case, monkeypatch, status):
    def unavailable(*args):
        raise WorkspaceError(status, "Exact retained result unavailable")

    monkeypatch.setattr(service.semantic_analysis, "project", unavailable)
    with pytest.raises(WorkspaceError) as failure:
        service.describe(case[0], request_for(case, invocation_ids=[uid("unavailable run")]))
    assert failure.value.status == status


@pytest.mark.parametrize("mismatch", ["company", "invocation", "request_company", "request_run"])
def test_projection_must_match_exact_selected_company_and_run(case, monkeypatch, mismatch):
    original = service.semantic_analysis.project

    def forged(actor, request):
        projection = original(actor, request)
        descriptor = projection.descriptor
        if mismatch == "company":
            descriptor = descriptor.model_copy(
                update={"company": pin(resource("Other", "LegalEntity"))}
            )
        elif mismatch == "invocation":
            descriptor = descriptor.model_copy(update={"invocation_id": uid("wrong run")})
        elif mismatch == "request_company":
            request = request.model_copy(update={"company_id": uid("other company")})
        else:
            request = request.model_copy(update={"invocation_id": uid("other run")})
        return projection.model_copy(update={"descriptor": descriptor, "request": request})

    monkeypatch.setattr(service.semantic_analysis, "project", forged)
    with pytest.raises(WorkspaceError) as failure:
        service.describe(case[0], request_for(case, invocation_ids=[uid("selected run")]))
    assert failure.value.status == 409


def test_http_authentication_and_permission_precede_home_reads(case):
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        body = request_for(case).model_dump(mode="json")
        assert client.post("/v1/ontology/company-home", json=body).status_code == 401
        response = client.post(
            "/v1/ontology/company-home", json=body,
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 403
    assert not case[2]


def test_related_parent_pack_does_not_change_selected_company_lens(case):
    workspace = case[1]["workspaces"].pop()
    case[1]["context"]["relationships"].append(dict(
        kind="USES_DOMAIN_PACK", record=resource("Parent uses gas", "Relationship"),
        source=resource("Parent company", "LegalEntity"), target=workspace["domain_pack"],
    ))
    result = service.describe(case[0], request_for(case))
    assert result.domain_packs == []
    assert result.operations.lens == "enterprise_assets"
