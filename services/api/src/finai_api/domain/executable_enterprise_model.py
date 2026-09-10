"""Typed executable-domain contracts and a deterministic dependency resolver.

This module is deliberately side-effect free. It answers whether a governed
function *may* run; it never promotes facts, posts accounting entries, or
executes an external action.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RequirementKind(StrEnum):
    ALL_OF = "ALL_OF"
    ANY_OF = "ANY_OF"
    ONE_OF = "ONE_OF"
    OPTIONAL = "OPTIONAL"
    CONDITIONAL = "CONDITIONAL"


class CoverageState(StrEnum):
    SATISFIED = "SATISFIED"
    SATISFIED_BY_AGGREGATION = "SATISFIED_BY_AGGREGATION"
    SATISFIED_BY_APPROVED_ALLOCATION = "SATISFIED_BY_APPROVED_ALLOCATION"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    INCOMPATIBLE_GRAIN = "INCOMPATIBLE_GRAIN"
    INCOMPATIBLE_TIME = "INCOMPATIBLE_TIME"
    UNAPPROVED = "UNAPPROVED"
    STALE = "STALE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CYCLE = "CYCLE"


class ResolutionState(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    REFUSED = "REFUSED"
    INCOMPARABLE = "INCOMPARABLE"


class InputCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str = Field(min_length=1)
    dimensions: frozenset[str] = frozenset()
    unit: str | None = None
    currency: str | None = None
    valid_period: str | None = None
    authority_state: str = "OBSERVED"
    evidence_complete: bool = True
    approved_allocation: bool = False
    stale: bool = False


class DependencyRequirement(BaseModel):
    """A composable requirement node in a function's dependency contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1)
    kind: RequirementKind = RequirementKind.ALL_OF
    fact_type: str | None = None
    children: tuple[DependencyRequirement, ...] = ()
    required_dimensions: frozenset[str] = frozenset()
    unit: str | None = None
    currency: str | None = None
    valid_period: str | None = None
    condition: str | None = None
    optional: bool = False


class ExecutableFunctionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    function_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    version: str = Field(min_length=1)
    requirements: tuple[DependencyRequirement, ...] = ()
    required_authority: str | None = None
    deterministic: bool = True
    approval_required: bool = False


class RequirementFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    fact_type: str | None
    state: CoverageState
    message: str
    children: tuple[RequirementFinding, ...] = ()


class ResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    function_id: str
    function_version: str
    state: ResolutionState
    findings: tuple[RequirementFinding, ...]
    cycle_path: tuple[str, ...] = ()


def resolve_function(
    function: ExecutableFunctionDefinition,
    available: tuple[InputCoverage, ...] = (),
    *,
    applicable_facts: frozenset[str] | None = None,
    active_requirements: tuple[str, ...] = (),
) -> ResolutionResult:
    """Resolve one function without guessing missing enterprise inputs.

    A fact is eligible only when its type, scope, period, unit, currency and
    authority are compatible. A coarser fact may satisfy a requirement only
    through an explicitly approved allocation; aggregation is reported rather
    than silently materialized.
    """

    facts = tuple(available)
    applicable = applicable_facts
    findings = tuple(
        _resolve_requirement(item, facts, applicable, active_requirements)
        for item in function.requirements
    )
    states = {finding.state for finding in findings}
    cycle = next((finding for finding in findings if finding.state is CoverageState.CYCLE), None)
    if cycle:
        return ResolutionResult(
            function_id=function.function_id,
            function_version=function.version,
            state=ResolutionState.BLOCKED,
            findings=findings,
            cycle_path=(cycle.requirement_id,),
        )
    if CoverageState.INCOMPATIBLE_GRAIN in states or CoverageState.INCOMPATIBLE_TIME in states:
        result_state = ResolutionState.INCOMPARABLE
    elif any(
        state in states
        for state in (CoverageState.MISSING, CoverageState.UNAPPROVED, CoverageState.STALE)
    ):
        result_state = ResolutionState.BLOCKED
    elif CoverageState.PARTIAL in states:
        result_state = ResolutionState.PARTIAL
    else:
        result_state = ResolutionState.READY
    return ResolutionResult(
        function_id=function.function_id,
        function_version=function.version,
        state=result_state,
        findings=findings,
    )


def _resolve_requirement(
    requirement: DependencyRequirement,
    facts: tuple[InputCoverage, ...],
    applicable: frozenset[str] | None,
    active: tuple[str, ...],
) -> RequirementFinding:
    if requirement.requirement_id in active:
        return RequirementFinding(
            requirement_id=requirement.requirement_id,
            fact_type=requirement.fact_type,
            state=CoverageState.CYCLE,
            message="Dependency cycle detected; execution is blocked",
        )
    if requirement.fact_type and applicable is not None and requirement.fact_type not in applicable:
        return RequirementFinding(
            requirement_id=requirement.requirement_id,
            fact_type=requirement.fact_type,
            state=CoverageState.NOT_APPLICABLE,
            message="Fact is outside this function's applicable domain",
        )
    if requirement.fact_type:
        return _fact_finding(requirement, facts)
    children = tuple(
        _resolve_requirement(child, facts, applicable, (*active, requirement.requirement_id))
        for child in requirement.children
    )
    child_states = {child.state for child in children}
    if requirement.kind is RequirementKind.OPTIONAL:
        state = (
            CoverageState.SATISFIED
            if CoverageState.SATISFIED in child_states
            else CoverageState.NOT_APPLICABLE
        )
    elif requirement.kind in (RequirementKind.ANY_OF, RequirementKind.ONE_OF):
        satisfied = sum(child.state in _SATISFIED for child in children)
        if requirement.kind is RequirementKind.ONE_OF and satisfied > 1:
            state = CoverageState.PARTIAL
        elif satisfied:
            state = CoverageState.SATISFIED
        else:
            state = _aggregate_failure(child_states)
    else:
        state = (
            CoverageState.SATISFIED
            if children and all(child.state in _SATISFIED for child in children)
            else _aggregate_failure(child_states)
        )
    return RequirementFinding(
        requirement_id=requirement.requirement_id,
        fact_type=requirement.fact_type,
        state=state,
        message=f"{requirement.kind.value} requirement is {state.value.lower()}",
        children=children,
    )


_SATISFIED = frozenset(
    {
        CoverageState.SATISFIED,
        CoverageState.SATISFIED_BY_AGGREGATION,
        CoverageState.SATISFIED_BY_APPROVED_ALLOCATION,
        CoverageState.NOT_APPLICABLE,
    }
)


def _fact_finding(
    requirement: DependencyRequirement, facts: tuple[InputCoverage, ...]
) -> RequirementFinding:
    candidates = tuple(fact for fact in facts if fact.fact_id == requirement.fact_type)
    if not candidates:
        state = CoverageState.MISSING
        message = "Required fact is missing"
    else:
        candidate = candidates[0]
        missing_dimensions = requirement.required_dimensions - candidate.dimensions
        if missing_dimensions and not candidate.approved_allocation:
            state = CoverageState.INCOMPATIBLE_GRAIN
            message = f"Missing required dimensions: {', '.join(sorted(missing_dimensions))}"
        elif requirement.valid_period and candidate.valid_period != requirement.valid_period:
            state = CoverageState.INCOMPATIBLE_TIME
            message = "Fact period is not compatible with the requested period"
        elif requirement.unit and candidate.unit != requirement.unit:
            state = CoverageState.PARTIAL
            message = "Fact exists but unit conversion is required"
        elif candidate.stale:
            state = CoverageState.STALE
            message = "Fact exists but is stale"
        elif not candidate.evidence_complete:
            state = CoverageState.PARTIAL
            message = "Fact exists but its evidence packet is incomplete"
        else:
            state = (
                CoverageState.SATISFIED_BY_APPROVED_ALLOCATION
                if candidate.approved_allocation
                else CoverageState.SATISFIED
            )
            message = "Required fact is available at a compatible scope"
    return RequirementFinding(
        requirement_id=requirement.requirement_id,
        fact_type=requirement.fact_type,
        state=state,
        message=message,
    )


def _aggregate_failure(states: set[CoverageState]) -> CoverageState:
    for state in (
        CoverageState.CYCLE,
        CoverageState.INCOMPATIBLE_GRAIN,
        CoverageState.INCOMPATIBLE_TIME,
        CoverageState.UNAPPROVED,
        CoverageState.STALE,
        CoverageState.PARTIAL,
        CoverageState.MISSING,
    ):
        if state in states:
            return state
    return CoverageState.MISSING
