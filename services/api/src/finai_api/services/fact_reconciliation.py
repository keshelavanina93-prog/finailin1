"""Compare independently aggregated representations without creating a joined financial fact."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal, DecimalException, Inexact, localcontext
from typing import Any
from uuid import UUID

from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.ontology_definitions import FactReconciliation
from finai_api.domain.review import Principal
from finai_api.services.fact_aggregation import aggregate_facts
from finai_api.services.ontology_definitions import definition
from finai_api.services.workspace import WorkspaceError


def compare_groups(spec: FactReconciliation, left: list[dict], right: list[dict]) -> list[dict]:
    def index(groups):
        result = {}
        for group in groups:
            key = json.dumps(group["dimensions"], sort_keys=True)
            if key in result:
                raise WorkspaceError(409, "Repeated reconciliation coordinate")
            result[key] = group
        return result

    a, b = index(left), index(right)
    results = []
    with localcontext() as context:
        context.prec = 50
        context.traps[Inexact] = True
        for key in sorted(a.keys() | b.keys()):
            left_group, right_group = a.get(key), b.get(key)
            difference = None
            if left_group is None or right_group is None:
                state = "MISSING_LEFT" if left_group is None else "MISSING_RIGHT"
            elif left_group.get("value") is None or right_group.get("value") is None:
                state = "UNAVAILABLE"
            else:
                try:
                    difference = Decimal(left_group["value"]) - Decimal(right_group["value"])
                    if not difference.is_finite():
                        raise ValueError("Non-finite difference")
                    state = (
                        "MATCHED"
                        if abs(difference) <= Decimal(spec.absolute_tolerance)
                        else "DIFFERENCE"
                    )
                except (DecimalException, ValueError) as exc:
                    raise WorkspaceError(422, "Invalid reconciliation amounts") from exc
            results.append(
                {
                    "dimensions": json.loads(key),
                    "state": state,
                    "difference": format(difference, "f") if difference is not None else None,
                    "left": left_group,
                    "right": right_group,
                    "designated_authority": left_group
                    if spec.authority_side == "left"
                    else right_group,
                }
            )
    return results


def reconcile_facts(
    principal: Principal,
    identity: UUID,
    left: ObjectSetQuery,
    right: ObjectSetQuery,
    as_of: date | None,
) -> dict[str, Any]:
    rule = definition(principal, identity)
    if rule["object_type"] != "FactReconciliation":
        raise WorkspaceError(422, "Reconciliation requires an accepted reconciliation contract")
    spec = FactReconciliation.model_validate(rule["attributes"]["definition"])
    pins = {p["relation"]: p for p in rule["dependencies"]}
    now = datetime.now(UTC)
    valid_at, known_at = (
        left.valid_at or right.valid_at or now,
        left.known_at or right.known_at or now,
    )
    if (left.valid_at and right.valid_at and left.valid_at != right.valid_at) or (
        left.known_at and right.known_at and left.known_at != right.known_at
    ):
        raise WorkspaceError(422, "Reconciliation needs one legal and knowledge snapshot")
    outputs = []
    for side, query in (("left", left), ("right", right)):
        pin = pins.get("FIELD:" + side + "_contract_id")
        if pin is None:
            raise WorkspaceError(409, "Reconciliation contract dependency unavailable")
        contract = definition(principal, UUID(str(rule["attributes"][side + "_contract_id"])))
        if str(contract["version_id"]) != str(pin["version_id"]):
            raise WorkspaceError(
                409, "Fact contract changed; review reconciliation against new version"
            )
        outputs.append(
            aggregate_facts(
                principal,
                contract["resource_id"],
                query.model_copy(update={"valid_at": valid_at, "known_at": known_at}),
                spec.group_by,
                as_of,
                expected_contract_version=UUID(str(pin["version_id"])),
            )
        )
    comparisons = compare_groups(spec, outputs[0]["groups"], outputs[1]["groups"])
    return {
        "contract_id": identity,
        "contract_version_id": rule["version_id"],
        "relationship": spec.relationship,
        "authority_side": spec.authority_side,
        "left": outputs[0],
        "right": outputs[1],
        "comparisons": comparisons,
        "state": "UNAVAILABLE"
        if not comparisons
        else ("MATCHED" if all(c["state"] == "MATCHED" for c in comparisons) else "UNRECONCILED"),
        "financial_certification": None,
        "accounting_effects_created": False,
    }
