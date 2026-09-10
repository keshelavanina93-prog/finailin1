"""Authoritative, versioned domain verbs available to executable preflight."""

from __future__ import annotations

from typing import Final

from finai_api.domain.executable_enterprise_model import (
    DependencyRequirement,
    ExecutableFunctionDefinition,
    RequirementKind,
)
from finai_api.services.workspace import WorkspaceError


def _fact(requirement_id: str, fact_type: str) -> DependencyRequirement:
    return DependencyRequirement(requirement_id=requirement_id, fact_type=fact_type)


def _all(requirement_id: str, *children: DependencyRequirement) -> DependencyRequirement:
    return DependencyRequirement(
        requirement_id=requirement_id, kind=RequirementKind.ALL_OF, children=children
    )


def _any(requirement_id: str, *children: DependencyRequirement) -> DependencyRequirement:
    return DependencyRequirement(
        requirement_id=requirement_id, kind=RequirementKind.ANY_OF, children=children
    )


def _optional(requirement_id: str, child: DependencyRequirement) -> DependencyRequirement:
    return DependencyRequirement(
        requirement_id=requirement_id, kind=RequirementKind.OPTIONAL, children=(child,)
    )


REGISTRY: Final[tuple[ExecutableFunctionDefinition, ...]] = (
    ExecutableFunctionDefinition(
        function_id="ConsolidateGroup",
        domain="consolidation",
        version="1",
        required_authority="APPROVED_CANONICAL",
        requirements=(
            _all(
                "consolidation-inputs",
                _fact("company-statements", "CompanyStatement"),
                _fact("group-coa-mapping", "GroupCOAMapping"),
                _fact("intercompany-matching", "IntercompanyMatch"),
                _fact("consolidation-policy", "ConsolidationPolicy"),
                _fact("closing-fx-rates", "ClosingFXRateSet"),
                _fact("average-fx-rates", "AverageFXRateSet"),
            ),
        ),
    ),
    ExecutableFunctionDefinition(
        function_id="ReconcilePhysicalStock",
        domain="petroleum",
        version="1",
        required_authority="VALIDATED_OBSERVATION",
        requirements=(
            _all(
                "conservation-inputs",
                _fact("opening-stock", "OpeningInventoryBalance"),
                _fact("receipts", "PhysicalReceipt"),
                _fact("dispatches", "PhysicalDispatch"),
                _fact("closing-measurement", "ClosingInventoryMeasurement"),
                _optional("approved-loss", _fact("losses", "ApprovedPhysicalLoss")),
            ),
        ),
    ),
    ExecutableFunctionDefinition(
        function_id="CalculateGrossMargin",
        domain="finance",
        version="1",
        required_authority="APPROVED_CANONICAL",
        requirements=(
            _all(
                "margin-inputs",
                _fact("revenue", "RevenueFact"),
                _fact("cogs", "COGSFact"),
                _optional("physical-variance", _fact("variance", "PetroleumVariance")),
            ),
        ),
    ),
    ExecutableFunctionDefinition(
        function_id="ForecastLiquidity",
        domain="treasury",
        version="1",
        required_authority="APPROVED_CANONICAL",
        requirements=(
            _all(
                "liquidity-inputs",
                _fact("opening-cash", "OpeningCash"),
                _any(
                    "expected-inflows",
                    _fact("contractual-collections", "ContractualCollectionSchedule"),
                    _fact("approved-ar-profile", "ApprovedARAgingProfile"),
                    _fact("approved-cash-model", "ApprovedForecastModel"),
                ),
                _fact("expected-outflows", "ExpectedOutflows"),
            ),
        ),
    ),
    ExecutableFunctionDefinition(
        function_id="CalculateDepreciation",
        domain="fixed_assets",
        version="1",
        required_authority="APPROVED_CANONICAL",
        requirements=(
            _all(
                "depreciation-inputs",
                _fact("asset-register", "AssetRegister"),
                _fact("asset-class", "AssetClass"),
                _fact("useful-life", "UsefulLifePolicy"),
                _fact("depreciation-method", "DepreciationMethodPolicy"),
                _fact("in-service-date", "AssetInServiceDate"),
            ),
        ),
    ),
    ExecutableFunctionDefinition(
        function_id="TranslateCurrency",
        domain="treasury",
        version="1",
        required_authority="APPROVED_CANONICAL",
        requirements=(
            _all(
                "translation-inputs",
                _fact("foreign-currency-facts", "ForeignCurrencyFact"),
                _fact("closing-rate", "ClosingFXRateSet"),
                _fact("average-rate", "AverageFXRateSet"),
                _fact("translation-policy", "TranslationPolicy"),
            ),
        ),
    ),
    ExecutableFunctionDefinition(
        function_id="CalculateROIC",
        domain="finance",
        version="1",
        required_authority="APPROVED_CANONICAL",
        requirements=(
            _all(
                "roic-inputs",
                _fact("ebit", "EBIT"),
                _fact("effective-tax", "ApprovedEffectiveTaxCalculation"),
                _fact("operating-assets", "OperatingAssets"),
                _fact("operating-liabilities", "OperatingLiabilities"),
                _fact("capital-policy", "InvestedCapitalPolicy"),
            ),
        ),
    ),
)

_BY_ID: Final[dict[str, ExecutableFunctionDefinition]] = {
    item.function_id: item for item in REGISTRY
}


def list_registered_functions() -> tuple[ExecutableFunctionDefinition, ...]:
    return REGISTRY


def get_registered_function(function_id: str) -> ExecutableFunctionDefinition:
    try:
        return _BY_ID[function_id]
    except KeyError as exc:
        raise WorkspaceError(404, "Executable function is not registered") from exc
