"""Account-owned analytical rules, resolved through reviewed canonical versions."""

from typing import Any

from psycopg.rows import dict_row

from finai_api.domain.ingest import CanonicalReference, IngestReceipt, IngestRequest
from finai_api.domain.review import Principal
from finai_api.services.resources import HEAD_SELECT
from finai_api.services.workspace import WorkspaceError


def rules_for_account(
    conn: Any, principal: Principal, account: dict[str, Any]
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            HEAD_SELECT + "WHERE h.tenant_id=%s AND v.object_type='AccountDimensionRule' "
            "AND v.attributes->>'account_id'=%s AND v.authority_state='APPROVED' "
            "AND v.valid_from<=now() AND (v.valid_to IS NULL OR v.valid_to>now()) "
            "ORDER BY v.resource_id",
            (principal.scope.tenant_id, str(account["resource_id"])),
        ).fetchall()


def choices(conn: Any, principal: Principal, account: dict[str, Any]) -> list[dict[str, Any]]:
    from finai_api.services.ingest_binding import _dependency

    result = []
    for rule in rules_for_account(conn, principal, account):
        dimension = _dependency(conn, principal, rule, "dimension_id", "DimensionDefinition")
        with conn.cursor(row_factory=dict_row) as cursor:
            members = cursor.execute(
                HEAD_SELECT + "WHERE h.tenant_id=%s AND v.object_type='DimensionMember' "
                "AND v.attributes->>'dimension_id'=%s AND v.authority_state='APPROVED' "
                "AND v.valid_from<=now() AND (v.valid_to IS NULL OR v.valid_to>now()) "
                "ORDER BY v.resource_id LIMIT 1001",
                (principal.scope.tenant_id, str(dimension["resource_id"])),
            ).fetchall()
        if len(members) > 1000:
            raise WorkspaceError(
                422, "Dimension exceeds the intake selection limit of 1000 members"
            )
        result.append(
            {
                "rule_version_id": str(rule["version_id"]),
                "dimension_code": dimension["attributes"]["code"],
                "required": rule["attributes"]["required"],
                "members": [
                    {"code": m["attributes"]["code"], "version_id": str(m["version_id"])}
                    for m in members
                ],
            }
        )
    return result


def bind_dimensions(
    conn: Any,
    principal: Principal,
    request: IngestRequest,
    receipt: IngestReceipt,
    accounts: dict[str, dict[str, Any]],
) -> IngestReceipt:
    from finai_api.services.ingest_binding import _accepted_version, _dependency, _reference

    if set(request.account_dimension_rule_version_ids) - set(accounts):
        raise WorkspaceError(422, "Dimension rule mappings contain an unknown source account")
    policies: dict[str, dict[str, Any]] = {}
    for code, account in accounts.items():
        rules = rules_for_account(conn, principal, account)
        pins = request.account_dimension_rule_version_ids.get(code, ())
        if len(set(pins)) != len(pins) or set(pins) != {rule["version_id"] for rule in rules}:
            raise WorkspaceError(
                409, f"Account {code}: dimension rules changed; prepare intake again"
            )
        by_code = {}
        for rule in rules:
            bound_account = _dependency(conn, principal, rule, "account_id", "LocalAccount")
            if bound_account["version_id"] != account["version_id"]:
                raise WorkspaceError(
                    409, f"Account {code}: review dimension rules against its current version"
                )
            dimension = _dependency(conn, principal, rule, "dimension_id", "DimensionDefinition")
            name = dimension["attributes"]["code"]
            if name in by_code:
                raise WorkspaceError(
                    409, f"Account {code}: ambiguous canonical dimension code {name}"
                )
            by_code[name] = (rule, dimension)
        policies[code] = by_code

    rejects = list(receipt.rejects)
    candidates = []
    used_members: set[tuple[str, str]] = set()
    resolved_members: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in receipt.candidates:
        if candidate.object_type != "PeriodBalance":
            candidates.append(candidate)
            continue
        code = candidate.values["account_code"]
        policy = policies[code]
        refs: dict[str, CanonicalReference] = dict(candidate.canonical_references)
        prefix = f"row {candidate.source_row}, account {code}: "
        for field, value in candidate.values.items():
            if field.startswith("dimension:") and value.strip() and field[10:] not in policy:
                rejects.append(prefix + f"{field} is not allowed by the reviewed account rules")
        for name, (rule, dimension) in policy.items():
            refs["dimension_rule:" + name] = _reference(rule)
            refs["dimension_definition:" + name] = _reference(dimension)
            value = candidate.values.get("dimension:" + name, "")
            if not value.strip():
                if rule["attributes"]["required"]:
                    rejects.append(prefix + f"missing required dimension:{name}")
                continue
            used_members.add((name, value))
            version = request.dimension_member_version_ids.get(name, {}).get(value)
            if version is None:
                rejects.append(
                    prefix + f"dimension:{name} value {value!r} needs an accepted member mapping"
                )
                continue
            cache_key = (name, value)
            if cache_key not in resolved_members:
                resolved_members[cache_key] = _accepted_version(
                    conn, principal, version, "DimensionMember"
                )
            member = resolved_members[cache_key]
            member_dimension = _dependency(
                conn, principal, member, "dimension_id", "DimensionDefinition"
            )
            if (
                member_dimension["version_id"] != dimension["version_id"]
                or member["attributes"]["code"] != value
            ):
                raise WorkspaceError(
                    422,
                    prefix
                    + f"dimension:{name} member does not match its definition and source code",
                )
            refs["dimension:" + name] = _reference(member)
        candidates.append(candidate.model_copy(update={"canonical_references": refs}))
    supplied = {
        (name, value)
        for name, mappings in request.dimension_member_version_ids.items()
        for value in mappings
    }
    if supplied - used_members:
        raise WorkspaceError(422, "Dimension member mappings must correspond to used source values")
    return receipt.model_copy(
        update={
            "candidates": tuple(candidates),
            "rejects": tuple(dict.fromkeys(rejects)),
            "reconciliation": {**receipt.reconciliation, "status": "REVIEW_REQUIRED"}
            if rejects
            else receipt.reconciliation,
        }
    )
