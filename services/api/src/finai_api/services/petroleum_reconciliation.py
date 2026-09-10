"""Accepted physical-to-financial petroleum reconciliation projection.

This is a read-only bridge over approved canonical resource versions. It never
turns a physical variance into an accounting posting or an external action.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from itertools import pairwise
from typing import Any
from uuid import UUID

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

SOURCE_TYPES = ("InventoryBalance", "PhysicalMovement", "PhysicalMeasurement", "RetailSale")
MARGIN_SOURCE_TYPES = ("RetailSale", "ProductCost")
JOURNAL_RECONCILIATION_TYPES = ("PhysicalMovement", "JournalLine")
DIMENSIONS = (
    "tenant_id",
    "enterprise_id",
    "legal_entity_id",
    "facility_id",
    "warehouse_id",
    "tank_id",
    "station_id",
    "product_id",
    "batch_id",
    "movement_id",
    "route_id",
    "carrier_id",
    "period_id",
    "unit",
    "measurement_basis",
)

VARIANCE_STATES = (
    "RECONCILED", "WITHIN_TOLERANCE", "REVIEW_REQUIRED", "EVIDENCE_MISSING",
    "INVESTIGATION_OPEN", "EXPLANATION_ACCEPTED", "ADJUSTMENT_PROPOSED",
    "APPROVAL_REQUIRED", "RESOLVED",
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


def reconcile(
    principal: Principal,
    company_id: UUID | None = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    company = str(company_id) if company_id else None
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    counts = {kind: 0 for kind in SOURCE_TYPES}
    for object_type in SOURCE_TYPES:
        for resource in resources.list_resources(principal, object_type, "", 0, limit=1000):
            attrs = resource.attributes
            if not _in_snapshot(attrs, valid_at, known_at):
                continue
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
            bucket.setdefault("source_resource_ids", []).append(str(resource.resource_id))
            evidence = bucket.setdefault(
                "evidence",
                {"waybill_ids": [], "tank_dip_ids": [], "retail_sale_ids": [],
                 "telemetry_ids": [], "source_hashes": []},
            )
            for field, target in (
                ("waybill_id", "waybill_ids"), ("tank_dip_id", "tank_dip_ids"),
                ("sale_id", "retail_sale_ids"), ("measurement_id", "telemetry_ids"),
                ("source_hash", "source_hashes"), ("source_sha256", "source_hashes"),
            ):
                value = attrs.get(field)
                if value not in (None, "") and str(value) not in evidence[target]:
                    evidence[target].append(str(value))
            if object_type == "RetailSale":
                evidence["retail_sale_ids"].append(str(resource.resource_id))
            elif object_type == "PhysicalMeasurement":
                evidence["telemetry_ids"].append(str(resource.resource_id))
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
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        expected = values["opening"] + values["receipts"] - values["dispatches"] - values["losses"]
        variance = values["closing"] - expected
        rows.append(
            {
                "dimensions": dict(zip(DIMENSIONS, key, strict=True)),
                **{
                    name: format(value, "f")
                    for name, value in values.items()
                    if name not in {"source_resource_ids", "evidence"}
                },
                "expected_closing": format(expected, "f"),
                "variance": format(variance, "f"),
                "status": "RECONCILED" if variance == 0 else "REVIEW_REQUIRED",
                "source_resource_ids": values.get("source_resource_ids", []),
                "evidence": values.get("evidence", {}),
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


def _in_snapshot(
    attrs: dict[str, Any], valid_at: datetime | None, known_at: datetime | None
) -> bool:
    """Exclude evidence first known after the requested replay instant."""
    if valid_at is not None:
        raw_valid = attrs.get("valid_at", attrs.get("valid_from"))
        if raw_valid:
            try:
                if datetime.fromisoformat(str(raw_valid)) > valid_at:
                    return False
            except (TypeError, ValueError):
                return False
    if known_at is not None:
        raw_known = attrs.get("known_at", attrs.get("recorded_at", attrs.get("system_from")))
        if raw_known:
            try:
                if datetime.fromisoformat(str(raw_known)) > known_at:
                    return False
            except (TypeError, ValueError):
                return False
    return True


def variances(
    principal: Principal,
    company_id: UUID | None = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    """Return first-class, fully scoped petroleum control objects.

    This is deliberately a deterministic projection.  It records the physical
    control and its evidence/authority boundaries, but never creates a GL
    adjustment or executes an operational action.
    """
    result = reconcile(principal, company_id, valid_at, known_at)
    costs: list[Any] = []
    try:
        costs = resources.list_resources(principal, "ProductCost", "", 0, limit=1000)
    except (KeyError, WorkspaceError):
        costs = []
    if company_id is not None:
        costs = [
            item for item in costs
            if any(str(item.attributes.get(key)) == str(company_id)
                   for key in ("legal_entity_id", "company_id"))
            and _in_snapshot(item.attributes, valid_at, known_at)
        ]
    rows: list[dict[str, Any]] = []
    for row in result["rows"]:
        dimensions = row["dimensions"]
        source_ids = list(row.get("source_resource_ids", []))
        evidence = dict(row.get("evidence", {}))
        missing: list[str] = []
        if not dimensions.get("unit"):
            missing.append("UNKNOWN_UNIT")
        if not dimensions.get("facility_id"):
            missing.append("UNKNOWN_FACILITY")
        if not dimensions.get("tank_id") and not dimensions.get("station_id"):
            missing.append("UNKNOWN_STORAGE_OR_STATION")
        if row["receipts"] != "0" and not source_ids:
            missing.append("MISSING_MOVEMENT_EVIDENCE")
        if row["closing"] == "0" and row["opening"] != "0":
            missing.append("MISSING_CLOSING_MEASUREMENT")
        if row["receipts"] != "0" and not evidence.get("waybill_ids"):
            missing.append("MISSING_WAYBILL")
        if row["closing"] != "0" and not evidence.get("tank_dip_ids"):
            missing.append("MISSING_TANK_DIP")
        physical_status = "EVIDENCE_MISSING" if missing else row["status"]
        if physical_status == "RECONCILED":
            lifecycle = "CONSERVATION_CHECKED"
        else:
            lifecycle = "VARIANCE_FLAGGED"
        valuation = _valuation_candidate(row, costs)
        rows.append({
            "variance_id": "petroleum-variance:" + sha256(
                "|".join(f"{key}={value}" for key, value in dimensions.items()).encode()
            ).hexdigest(),
            "contract": "petroleum-variance/1",
            "dimensions": dimensions,
            "physical": {
                "opening": row["opening"], "receipts": row["receipts"],
                "dispatches": row["dispatches"], "losses": row["losses"],
                "expected_closing": row["expected_closing"], "measured_closing": row["closing"],
                "variance_quantity": row["variance"],
                "variance_pct": format(
                    (Decimal(row["variance"]) / Decimal(row["expected_closing"]) * 100)
                    if Decimal(row["expected_closing"]) else Decimal(0), ".6f"
                ),
                "equation": "opening + receipts - dispatches - losses = expected_closing",
            },
            "evidence": {"source_resource_ids": source_ids, **evidence, "gaps": missing},
            "time": {
                "valid_at": valid_at.isoformat()
                if valid_at
                else dimensions.get("period_id") or None,
                     "known_at": known_at.isoformat() if known_at else None,
                     "recorded_at": known_at.isoformat() if known_at else None,
                     "approved_at": None, "corrected_at": None,
                     "replay_as_of": known_at.isoformat() if known_at else None},
            "review": {"status": physical_status, "lifecycle": lifecycle,
                       "investigation": "NOT_OPEN", "action": "NOT_PROPOSED",
                       "readback": "NOT_APPLICABLE"},
            "financial": valuation,
            "authority": {"observed": True, "validated": not bool(missing),
                          "accounting_authorized": False, "business_effect_authorized": False,
                          "canonical_adjustment_created": False},
        })
    return {**result, "contract": "petroleum-variance-collection/1", "rows": rows,
            "bitemporal": True, "action_execution": "GOVERNED_ADAPTER_REQUIRED"}


def variance_detail(
    principal: Principal,
    variance_id: str,
    company_id: UUID | None = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    """Return one variance with its bounded evidence and lineage packet."""
    require_permission(principal, "ontology_read")
    collection = variances(principal, company_id, valid_at, known_at)
    row = next((item for item in collection["rows"] if item["variance_id"] == variance_id), None)
    if row is None:
        raise WorkspaceError(404, "Petroleum variance unavailable in authorized scope")
    lineage_packets: list[dict[str, Any]] = []
    for source_id in row["evidence"].get("source_resource_ids", []):
        try:
            lineage_packets.append(lineage(principal, UUID(str(source_id)), company_id))
        except (ValueError, WorkspaceError):
            continue
    return {
        "contract": "petroleum-variance-detail/1",
        "variance": row,
        "evidence_packet": row["evidence"],
        "lineage": lineage_packets,
        "authority": row["authority"],
        "accounting_effect": "NOT_YET_AUTHORITATIVE",
    }


def _valuation_candidate(row: dict[str, Any], costs: list[Any]) -> dict[str, Any]:
    dimensions = row["dimensions"]
    matches = []
    for item in costs:
        attrs = item.attributes
        if all(not dimensions.get(field) or not attrs.get(field)
               or str(dimensions[field]) == str(attrs[field])
               for field in ("legal_entity_id", "facility_id", "tank_id", "station_id",
                             "product_id", "period_id", "unit")):
            matches.append(attrs)
    if not matches:
        return {"status": "FINANCIAL_BRIDGE_PARTIAL", "estimated_value": None,
                "valuation_basis": None, "cogs_effect_candidate": None,
                "margin_effect_candidate": None}
    cost = matches[0]
    unit_cost = _quantity(cost, ("unit_cost", "cost_per_unit"))
    if unit_cost == 0:
        quantity = _quantity(cost, ("quantity", "volume"))
        total = _quantity(cost, ("cost_amount", "valuation_amount"))
        unit_cost = total / quantity if quantity else Decimal(0)
    estimated = abs(Decimal(row["variance"])) * unit_cost
    signed = Decimal(row["variance"]) * unit_cost
    return {"status": "FINANCIAL_BRIDGED" if unit_cost else "FINANCIAL_BRIDGE_PARTIAL",
            "estimated_value": format(estimated, "f") if unit_cost else None,
            "valuation_basis": str(cost.get("valuation_basis", "ACCEPTED_PRODUCT_COST"))
            if unit_cost else None,
            "cogs_effect_candidate": format(signed, "f") if unit_cost else None,
            "margin_effect_candidate": format(-signed, "f") if unit_cost else None}


def margin(principal: Principal, company_id: UUID | None = None) -> dict[str, Any]:
    """Project sales volume, revenue and available product cost by exact dimensions."""
    require_permission(principal, "ontology_read")
    company = str(company_id) if company_id else None
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    counts = {kind: 0 for kind in MARGIN_SOURCE_TYPES}
    dimensions = ("legal_entity_id", "station_id", "product_id", "period_id", "currency")
    for object_type in MARGIN_SOURCE_TYPES:
        for resource in resources.list_resources(principal, object_type, "", 0, limit=1000):
            attrs = resource.attributes
            if company is not None and not any(
                str(attrs.get(key)) == company for key in ("legal_entity_id", "company_id")
            ):
                continue
            counts[object_type] += 1
            key = tuple(str(attrs.get(field, "")) for field in dimensions)
            bucket = grouped.setdefault(
                key,
                {
                    "volume": Decimal(0),
                    "revenue": Decimal(0),
                    "cogs": Decimal(0),
                    "cost_count": 0,
                    "source_resource_ids": [],
                },
            )
            bucket["source_resource_ids"].append(str(resource.resource_id))
            if object_type == "RetailSale":
                bucket["volume"] += _quantity(attrs, ("quantity", "volume", "sold_quantity"))
                bucket["revenue"] += _quantity(
                    attrs, ("net_amount", "revenue_amount", "gross_amount")
                )
            else:
                bucket["cogs"] += _quantity(
                    attrs, ("cogs_amount", "cost_amount", "valuation_amount")
                )
                bucket["cost_count"] += 1
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        revenue, cogs = values["revenue"], values["cogs"]
        cost_available = values["cost_count"] > 0
        rows.append(
            {
                "dimensions": dict(zip(dimensions, key, strict=True)),
                "volume": format(values["volume"], "f"),
                "revenue": format(revenue, "f"),
                "cogs": format(cogs, "f") if cost_available else None,
                "gross_margin": format(revenue - cogs, "f") if cost_available else None,
                "status": "COMPLETE" if cost_available else "COGS_UNAVAILABLE",
                "source_resource_ids": values["source_resource_ids"],
            }
        )
    return {
        "contract": "petroleum-margin-bridge/1",
        "company_id": company,
        "coverage": "APPROVED_CANONICAL_RESOURCES",
        "counts": counts,
        "rows": rows,
        "accounting_authorized": False,
        "business_effect_authorized": False,
        "warning": (
            "Revenue and physical volume are projections; COGS is shown only when "
            "an accepted ProductCost source exists."
        ),
    }


def movement_journal_reconciliation(
    principal: Principal, company_id: UUID | None = None
) -> dict[str, Any]:
    """Reconcile accepted physical movements to booked journal-line references.

    This read-only bridge proves evidence coverage only; it never posts or
    promotes a movement into accounting authority.
    """
    require_permission(principal, "ontology_read")
    company = str(company_id) if company_id else None

    def in_company(attrs: dict[str, Any]) -> bool:
        return company is None or any(
            str(attrs.get(key)) == company for key in ("legal_entity_id", "company_id")
        )

    movements = [
        resource
        for resource in resources.list_resources(principal, "PhysicalMovement", "", 0, limit=1000)
        if in_company(resource.attributes)
    ]
    lines = [
        resource
        for resource in resources.list_resources(principal, "JournalLine", "", 0, limit=1000)
        if in_company(resource.attributes)
    ]

    def refs(attrs: dict[str, Any]) -> set[str]:
        return {
            str(attrs[key])
            for key in (
                "source_record_id",
                "movement_id",
                "document_id",
                "source_document_id",
                "reference",
            )
            if attrs.get(key) not in (None, "")
        }

    def quantity(attrs: dict[str, Any]) -> Decimal | None:
        for name in ("quantity", "volume", "moved_quantity", "source_quantity"):
            if attrs.get(name) not in (None, ""):
                return _decimal(attrs[name], name)
        return None

    rows: list[dict[str, Any]] = []
    for movement in movements:
        movement_refs = refs(movement.attributes)
        candidates = [line for line in lines if movement_refs & refs(line.attributes)]
        line = candidates[0] if candidates else None
        movement_quantity = quantity(movement.attributes)
        journal_quantity = quantity(line.attributes) if line else None
        if line is None:
            status = "MISSING_JOURNAL"
            reason = "No accepted JournalLine shares the movement evidence or document identity."
        elif movement_quantity is None or journal_quantity is None:
            status = "QUANTITY_UNAVAILABLE"
            reason = "Reference coverage exists, but both sides lack a comparable quantity."
        elif movement_quantity != journal_quantity:
            status = "QUANTITY_MISMATCH"
            reason = (
                "Movement and journal quantities differ; review source and accounting dimensions."
            )
        else:
            status = "MATCHED"
            reason = (
                "Movement evidence is referenced by an accepted journal line with equal quantity."
            )
        rows.append(
            {
                "movement_resource_id": str(movement.resource_id),
                "movement_identity": next(iter(sorted(movement_refs)), ""),
                "journal_line_resource_id": str(line.resource_id) if line else None,
                "dimensions": {
                    key: str(movement.attributes.get(key, ""))
                    for key in ("legal_entity_id", "product_id", "unit", "period_id", "currency")
                },
                "movement_quantity": format(movement_quantity, "f")
                if movement_quantity is not None
                else None,
                "journal_quantity": format(journal_quantity, "f")
                if journal_quantity is not None
                else None,
                "status": status,
                "reason": reason,
                "accounting_authorized": False,
                "business_effect_authorized": False,
            }
        )
    return {
        "contract": "movement-journal-reconciliation/1",
        "company_id": company,
        "coverage": "ACCEPTED_PHYSICAL_MOVEMENTS_AND_JOURNAL_LINES",
        "counts": {"PhysicalMovement": len(movements), "JournalLine": len(lines)},
        "rows": rows,
        "accounting_authorized": False,
        "business_effect_authorized": False,
        "warning": (
            "Reference coverage is not posting authority; movement promotion remains "
            "governed review."
        ),
    }


def telemetry(principal: Principal, company_id: UUID | None = None) -> dict[str, Any]:
    """Project accepted physical measurements into deterministic meter series."""
    require_permission(principal, "ontology_read")
    company = str(company_id) if company_id else None
    measurements = resources.list_resources(principal, "PhysicalMeasurement", "", 0, limit=5000)
    if company is not None:
        measurements = [
            item
            for item in measurements
            if any(
                str(item.attributes.get(key)) == company
                for key in ("legal_entity_id", "company_id")
            )
        ]
    grouped: dict[tuple[str, ...], list[Any]] = {}
    dimensions = (
        "legal_entity_id",
        "meter_id",
        "asset_id",
        "location_id",
        "measurement_type",
        "unit",
        "pressure_basis",
        "temperature_basis",
    )
    for item in measurements:
        key = tuple(str(item.attributes.get(field, "")) for field in dimensions)
        grouped.setdefault(key, []).append(item)
    rows: list[dict[str, Any]] = []
    for key, items in sorted(grouped.items()):
        readings: list[tuple[datetime, Decimal, Any]] = []
        invalid = 0
        for item in items:
            attrs = item.attributes
            try:
                timestamp = datetime.fromisoformat(str(attrs.get("measurement_timestamp", "")))
                value = _decimal(attrs.get("value"), "value")
                if timestamp.tzinfo is None:
                    raise ValueError
                readings.append((timestamp, value, item))
            except (ValueError, TypeError, WorkspaceError):
                invalid += 1
        readings.sort(key=lambda entry: (entry[0], str(entry[2].resource_id)))
        intervals = [
            (right[0] - left[0]).total_seconds()
            for left, right in pairwise(readings)
            if right[0] >= left[0]
        ]
        median = sorted(intervals)[(len(intervals) - 1) // 2] if intervals else None
        gap_count = sum(1 for interval in intervals if median and interval > max(2 * median, 3600))
        basis_complete = bool(key[6] and key[7] and key[5])
        if invalid:
            status = "INVALID_READING_REVIEW"
        elif not basis_complete:
            status = "MEASUREMENT_BASIS_REVIEW"
        elif gap_count:
            status = "GAP_REVIEW_REQUIRED"
        else:
            status = "SERIES_ORDERED"
        rows.append(
            {
                "dimensions": dict(zip(dimensions, key, strict=True)),
                "reading_count": len(readings),
                "invalid_readings": invalid,
                "first_timestamp": readings[0][0].isoformat() if readings else None,
                "last_timestamp": readings[-1][0].isoformat() if readings else None,
                "minimum_value": format(min((row[1] for row in readings), default=Decimal(0)), "f"),
                "maximum_value": format(max((row[1] for row in readings), default=Decimal(0)), "f"),
                "median_interval_seconds": median,
                "gap_count": gap_count,
                "basis_state": "COMPLETE" if basis_complete else "INCOMPLETE",
                "status": status,
                "source_resource_ids": [str(row[2].resource_id) for row in readings],
            }
        )
    return {
        "contract": "petroleum-telemetry-bridge/1",
        "company_id": company,
        "coverage": "ACCEPTED_PHYSICAL_MEASUREMENTS",
        "rows": rows,
        "measurement_count": len(measurements),
        "live_connector": False,
        "accounting_authorized": False,
        "business_effect_authorized": False,
        "warning": (
            "This is an accepted measurement snapshot; it is not a live connector or "
            "booked financial truth."
        ),
    }


def lineage(
    principal: Principal, resource_id: UUID, company_id: UUID | None = None
) -> dict[str, Any]:
    """Return a bounded directed lineage path over accepted physical resources."""
    require_permission(principal, "ontology_read")
    company = str(company_id) if company_id else None
    nodes: dict[str, Any] = {}
    for object_type in SOURCE_TYPES:
        for resource in resources.list_resources(principal, object_type, "", 0, limit=1000):
            attrs = resource.attributes
            if company is not None and not any(
                str(attrs.get(key)) == company for key in ("legal_entity_id", "company_id")
            ):
                continue
            nodes[str(resource.resource_id)] = resource
    root = str(resource_id)
    if root not in nodes:
        raise WorkspaceError(404, "Petroleum resource unavailable in authorized scope")
    edges: list[dict[str, str]] = []
    reference_fields = (
        "source_resource_id",
        "source_id",
        "origin_id",
        "destination_id",
        "destination_asset_id",
        "shipment_id",
        "waybill_id",
        "tank_id",
        "station_id",
        "movement_id",
        "sale_id",
    )
    for source_id, resource in nodes.items():
        for field in reference_fields:
            target_id = str(resource.attributes.get(field, ""))
            if target_id in nodes and target_id != source_id:
                edges.append({"source_id": source_id, "target_id": target_id, "field": field})
    seen = {root}
    queue = [root]
    selected_edges: list[dict[str, str]] = []
    while queue and len(seen) < 250:
        current = queue.pop(0)
        for edge in edges:
            if edge["source_id"] != current:
                continue
            selected_edges.append(edge)
            if edge["target_id"] not in seen:
                seen.add(edge["target_id"])
                queue.append(edge["target_id"])
    return {
        "contract": "petroleum-lineage/1",
        "root_resource_id": root,
        "resources": [nodes[node].model_dump(mode="json") for node in sorted(seen)],
        "edges": selected_edges,
        "bounded": len(seen) >= 250,
        "authority": "ACCEPTED_CANONICAL_RESOURCE_LINEAGE",
        "accounting_authorized": False,
        "business_effect_authorized": False,
    }
