"""Accepted physical-to-financial petroleum reconciliation projection.

This is a read-only bridge over approved canonical resource versions. It never
turns a physical variance into an accounting posting or an external action.
"""

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

SOURCE_TYPES = ("InventoryBalance", "PhysicalMovement", "PhysicalMeasurement", "RetailSale")
DIMENSIONS = (
    "legal_entity_id",
    "facility_id",
    "tank_id",
    "station_id",
    "product_id",
    "period_id",
    "unit",
)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise WorkspaceError(409, f"Accepted petroleum resource has invalid {field}") from exc
    if not result.is_finite():
        raise WorkspaceError(409, f"Accepted petroleum resource has non-finite {field}")
    return result


def _quantity(attrs: dict[str, Any], names: tuple[str, ...]) -> Decimal:
    for name in names:
        if name in attrs and attrs[name] not in (None, ""):
            return _decimal(attrs[name], name)
    return Decimal(0)


def reconcile(principal: Principal, company_id: UUID | None = None) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    company = str(company_id) if company_id else None
    grouped: dict[tuple[str, ...], dict[str, Decimal]] = {}
    counts = {kind: 0 for kind in SOURCE_TYPES}
    for object_type in SOURCE_TYPES:
        for resource in resources.list_resources(principal, object_type, "", 0, limit=1000):
            attrs = resource.attributes
            if company is not None and not any(
                str(attrs.get(key)) == company for key in ("legal_entity_id", "company_id")
            ):
                continue
            counts[object_type] += 1
            key = tuple(str(attrs.get(field, "")) for field in DIMENSIONS)
            bucket = grouped.setdefault(
                key,
                {
                    name: Decimal(0)
                    for name in ("opening", "receipts", "dispatches", "losses", "closing", "sales")
                },
            )
            if object_type == "InventoryBalance":
                bucket["opening"] += _quantity(attrs, ("opening_quantity", "opening"))
                bucket["receipts"] += _quantity(
                    attrs, ("receipts", "received_quantity", "inbound_quantity")
                )
                bucket["dispatches"] += _quantity(
                    attrs, ("dispatches", "dispatched_quantity", "outbound_quantity")
                )
                bucket["losses"] += _quantity(attrs, ("losses", "loss_quantity", "measured_loss"))
                bucket["closing"] += _quantity(attrs, ("closing_quantity", "closing"))
            elif object_type == "PhysicalMovement":
                direction = str(attrs.get("direction", attrs.get("movement_type", ""))).upper()
                bucket[
                    "receipts" if direction in {"IN", "RECEIPT", "RECEIVED"} else "dispatches"
                ] += _quantity(attrs, ("quantity", "volume"))
            elif object_type == "RetailSale":
                bucket["sales"] += _quantity(attrs, ("quantity", "volume", "sold_quantity"))
            else:
                bucket["closing"] += _quantity(attrs, ("quantity", "volume", "measured_quantity"))
    rows = []
    for key, values in sorted(grouped.items()):
        expected = values["opening"] + values["receipts"] - values["dispatches"] - values["losses"]
        variance = values["closing"] - expected
        rows.append(
            {
                "dimensions": dict(zip(DIMENSIONS, key, strict=True)),
                **{name: format(value, "f") for name, value in values.items()},
                "expected_closing": format(expected, "f"),
                "variance": format(variance, "f"),
                "status": "RECONCILED" if variance == 0 else "REVIEW_REQUIRED",
            }
        )
    return {
        "contract": "petroleum-reconciliation/1",
        "company_id": company,
        "coverage": "APPROVED_CANONICAL_RESOURCES",
        "source_types": list(SOURCE_TYPES),
        "counts": counts,
        "rows": rows,
        "accounting_authorized": False,
        "business_effect_authorized": False,
        "telemetry_connected": bool(sum(counts.values())),
        "warning": "Physical measurements and booked accounting remain separate authorities.",
    }
