from fastapi.testclient import TestClient

from finai_api.domain.executable_enterprise_model import (
    CoverageState,
    DependencyRequirement,
    ExecutableFunctionDefinition,
    InputCoverage,
    RequirementKind,
    ResolutionState,
    resolve_function,
)
from finai_api.main import app
from finai_api.services.executable_function_registry import list_registered_functions


def fact(name: str, **kwargs: object) -> InputCoverage:
    return InputCoverage(fact_id=name, **kwargs)


def test_all_of_requires_every_fact_and_reports_missing_dependency() -> None:
    function = ExecutableFunctionDefinition(
        function_id="consolidate_group",
        domain="finance",
        version="3",
        requirements=(
            DependencyRequirement(
                requirement_id="inputs",
                kind=RequirementKind.ALL_OF,
                children=(
                    DependencyRequirement(requirement_id="ebitda", fact_type="company_ebitda"),
                    DependencyRequirement(requirement_id="fx", fact_type="closing_fx_rate"),
                ),
            ),
        ),
    )
    result = resolve_function(function, (fact("company_ebitda"),))
    assert result.state is ResolutionState.BLOCKED
    assert result.findings[0].children[1].state is CoverageState.MISSING


def test_any_of_accepts_one_governed_alternative() -> None:
    requirement = DependencyRequirement(
        requirement_id="collections",
        kind=RequirementKind.ANY_OF,
        children=(
            DependencyRequirement(requirement_id="terms", fact_type="contract_terms"),
            DependencyRequirement(
                requirement_id="profile", fact_type="approved_collection_profile"
            ),
        ),
    )
    function = ExecutableFunctionDefinition(
        function_id="forecast_liquidity",
        domain="treasury",
        version="1",
        requirements=(requirement,),
    )
    assert (
        resolve_function(function, (fact("approved_collection_profile"),)).state
        is ResolutionState.READY
    )


def test_grain_and_time_mismatch_are_incomparable_without_allocation() -> None:
    function = ExecutableFunctionDefinition(
        function_id="gross_margin",
        domain="petroleum",
        version="1",
        requirements=(
            DependencyRequirement(
                requirement_id="sales",
                fact_type="sales",
                required_dimensions=frozenset({"station", "product"}),
                valid_period="2026-04",
            ),
        ),
    )
    result = resolve_function(
        function,
        (fact("sales", dimensions=frozenset({"company"}), valid_period="2026-03"),),
    )
    assert result.state is ResolutionState.INCOMPARABLE
    assert result.findings[0].state is CoverageState.INCOMPATIBLE_GRAIN


def test_approved_allocation_is_explicit_and_preserved_in_finding() -> None:
    function = ExecutableFunctionDefinition(
        function_id="revenue",
        domain="finance",
        version="1",
        requirements=(
            DependencyRequirement(
                requirement_id="sales",
                fact_type="sales",
                required_dimensions=frozenset({"station"}),
            ),
        ),
    )
    result = resolve_function(
        function,
        (fact("sales", dimensions=frozenset(), approved_allocation=True),),
    )
    assert result.state is ResolutionState.READY
    assert result.findings[0].state is CoverageState.SATISFIED_BY_APPROVED_ALLOCATION


def test_cycle_is_blocked() -> None:
    child = DependencyRequirement(requirement_id="self")
    cyclic = child.model_copy(update={"children": (child,)})
    function = ExecutableFunctionDefinition(
        function_id="cyclic", domain="test", version="1", requirements=(cyclic,)
    )
    assert resolve_function(function).state is ResolutionState.BLOCKED


def test_executable_preflight_route_is_read_only() -> None:
    payload = {
        "function": {
            "function_id": "calculate_tax",
            "domain": "tax",
            "version": "1",
            "requirements": [
                {"requirement_id": "ledger", "fact_type": "tax_ledger"},
            ],
        },
        "available": [],
    }
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post("/v1/workspace/executable-preflight", json=payload)
    assert response.status_code == 200
    assert response.json()["preflight"]["state"] == "BLOCKED"
    assert response.json()["authority_effect"] == "NONE"


def test_registered_function_preflight_uses_server_contract() -> None:
    payload = {
        "function_id": "ReconcilePhysicalStock",
        "available": [
            {"fact_id": "OpeningInventoryBalance"},
            {"fact_id": "PhysicalReceipt"},
            {"fact_id": "PhysicalDispatch"},
            {"fact_id": "ClosingInventoryMeasurement"},
        ],
    }
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post("/v1/workspace/executable-preflight", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["registry_state"] == "AUTHORITATIVE_REGISTERED"
    assert body["function"]["function_id"] == "ReconcilePhysicalStock"
    assert body["preflight"]["state"] == "READY"
    assert body["authority_effect"] == "NONE"


def test_registered_function_catalog_is_versioned_and_read_only() -> None:
    assert len(list_registered_functions()) >= 7
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.get("/v1/workspace/executable-functions")
    assert response.status_code == 200
    body = response.json()
    assert body["contract"] == "executable-function-registry/1"
    assert {item["function_id"] for item in body["functions"]} >= {
        "ConsolidateGroup",
        "CalculateROIC",
        "ReconcilePhysicalStock",
    }
    assert body["authority_effect"] == "NONE"


def test_unknown_registered_function_is_refused() -> None:
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post(
            "/v1/workspace/executable-preflight",
            json={"function_id": "PostUnapprovedJournal", "available": []},
        )
    assert response.status_code == 404
