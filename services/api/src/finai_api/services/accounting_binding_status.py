"""Advisory current eligibility of a retained accounting selection, never an execution grant."""

from datetime import UTC, datetime
from uuid import UUID

from finai_api.services.workspace import WorkspaceError


def inspect(principal, binding):
    result = {
        "checked_at": datetime.now(UTC).isoformat(),
        "advisory": True,
        "current_use_authorized": False,
        "eligible_for_accounting": False,
        "reviewed_source_use": binding["attributes"].get("source_use") if binding else "UNSELECTED",
        "binding_version_id": binding["version_id"] if binding else None,
        "effective_from": binding["valid_from"] if binding else None,
        "effective_to": binding["valid_to"] if binding else None,
        "known_from": binding["system_from"] if binding else None,
    }
    if not binding:
        return {
            **result,
            "state": "UNSELECTED",
            "reason": "No source accounting selection has been reviewed",
        }
    if result["reviewed_source_use"] != "ACCOUNTING_INPUT":
        return {
            **result,
            "state": "NOT_ACCOUNTING_INPUT",
            "reason": "The retained selection does not authorize accounting input",
        }
    if binding["attributes"].get("contract_version") != "2":
        return {
            **result,
            "state": "INTERPRETATION_REQUIRED",
            "reason": "The historical selection needs a complete version 2 "
            "accounting interpretation",
        }
    from finai_api.services.accounting_consumption import load_accounting_lineage, validate_bindings
    from finai_api.services.accounting_promotion import validate_current_binding
    from finai_api.services.resources import resource_connection

    key = (UUID(binding["resource_id"]), UUID(binding["version_id"]))
    try:
        with resource_connection(principal, repeatable_read=True) as conn:
            # Same immutable lineage, compatibility and current-use rules as execution.
            rows, edges = load_accounting_lineage(conn, principal, {key})
            scopes = {
                target
                for source, target, relation in edges
                if source == key and relation == "FIELD:scope_id"
            }
            if len(scopes) != 1:
                raise WorkspaceError(409, "Accounting selection has no exact source scope pin")
            validate_bindings(rows, edges, scopes, {key})
            validate_current_binding(conn, principal, rows[key])
    except WorkspaceError as exc:
        return {**result, "state": "CURRENT_USE_BLOCKED", "reason": exc.detail}
    return {
        **result,
        "state": "ELIGIBLE_FOR_GUARDED_USE",
        "eligible_for_accounting": True,
        "reason": "Interpretation is currently compatible and available; "
        "each calculation must recheck its exact consumer contract",
    }
