from finai_api.domain.executable_enterprise_model import (
    CoverageState,
    DependencyRequirement,
    ExecutableFunctionDefinition,
    InputCoverage,
    RequirementKind,
    ResolutionState,
    resolve_function,
)


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
