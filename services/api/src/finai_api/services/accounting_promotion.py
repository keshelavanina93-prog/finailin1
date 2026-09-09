"""Journal publication must consume a reviewed, current source accounting interpretation."""

import re
from datetime import date
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services.source_accounting_context import validate_active_selection
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError


def validate_posting_date(attrs, period):
    value = attrs.get("posting_date")
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise WorkspaceError(
            422, "Journal publication requires an explicit posting_date in YYYY-MM-DD format"
        )
    try:
        posting_date = date.fromisoformat(value)
    except ValueError as exc:
        raise WorkspaceError(422, "Journal posting_date must be a valid calendar date") from exc
    try:
        if period["object_type"] != "FiscalPeriod":
            raise ValueError("Not a fiscal period")
        starts = date.fromisoformat(period["attributes"]["starts_on"])
        ends = date.fromisoformat(period["attributes"]["ends_on"])
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError(
            422, "Journal requires a reviewed FiscalPeriod with valid date bounds"
        ) from exc
    if not starts <= posting_date <= ends:
        raise WorkspaceError(
            422, "Journal posting_date must fall within its reviewed fiscal period (inclusive)"
        )


def validate_journal(item, target):
    """Resolve through publication's shared target callback, recording exact dependency pins."""
    attrs, key = item.attributes, str(item.resource_id)
    identity = attrs.get("accounting_binding_id")
    if not identity:
        raise WorkspaceError(
            422, "Journal publication requires an accepted source accounting binding"
        )
    binding = target(identity, key, "ACCOUNTING_INTERPRETATION")
    if binding["object_type"] != "SourceAccountingBinding":
        raise WorkspaceError(422, "Journal interpretation must reference SourceAccountingBinding")
    config = binding["attributes"]
    scope = target(config["scope_id"], key, "ACCOUNTING_SCOPE")
    if config.get("granularity") != "SOURCE_ROW":
        raise WorkspaceError(422, "Journal publication requires source-row journal evidence")
    if scope["attributes"].get("source_profile") != "1c_journal":
        if not attrs.get("source_compatibility_id"):
            raise WorkspaceError(422, "Journal publication requires source-row journal evidence")
        from finai_api.services.source_journal_compatibility import require

        require(item, binding, scope, target)
    validate_active_selection(
        config, scope["attributes"], lambda ref: target(ref, key, "ACCOUNTING_CONTEXT:" + ref)
    )
    if item.object_type == "JournalEntry":
        journal_attrs = attrs
        if any(
            attrs[field] != expected
            for field, expected in {
                "legal_entity_id": scope["attributes"]["legal_entity_id"],
                "ledger_id": config["ledger_id"],
                "period_id": config["period_id"],
            }.items()
        ):
            raise WorkspaceError(
                422, "Journal company, ledger and period disagree with its source binding"
            )
    else:
        journal = target(attrs["journal_id"], key, "ACCOUNTING_JOURNAL")
        journal_attrs = journal["attributes"]
        account = target(attrs["account_id"], key, "ACCOUNTING_ACCOUNT")
        record = target(attrs["source_record_id"], key, "ACCOUNTING_SOURCE_RECORD")
        if (
            journal["attributes"].get("accounting_binding_id") != identity
            or journal["attributes"].get("legal_entity_id")
            != scope["attributes"]["legal_entity_id"]
            or journal["attributes"].get("ledger_id") != config["ledger_id"]
            or journal["attributes"].get("period_id") != config["period_id"]
            or account["attributes"].get("chart_id") != scope["attributes"]["chart_id"]
            or record["attributes"].get("evidence_id") != scope["attributes"]["evidence_id"]
            or attrs["amount"]["currency_id"] != config["currency_id"]
        ):
            raise WorkspaceError(
                422, "Journal line account, currency or retained source disagrees with its binding"
            )
    period = target(config["period_id"], key, "ACCOUNTING_POSTING_PERIOD")
    validate_posting_date(journal_attrs, period)
    return binding


def validate_current_binding(conn, principal, binding):
    """Run at proposal and promotion under the canonical publication transaction lock."""
    from finai_api.services.resource_lifecycle import ORDER, _latest, _version

    reference = VersionReference(
        resource_id=UUID(str(binding["resource_id"])), version_id=UUID(str(binding["version_id"]))
    )
    with conn.cursor(row_factory=dict_row) as cursor:
        _version(cursor, principal, reference)
        event = _latest(cursor, principal, reference.version_id)
        if (
            not event
            or event["payload"]["target_state"] not in ORDER
            or event["payload"]["availability_state"] != "AVAILABLE"
        ):
            raise WorkspaceError(
                409, "Source accounting binding has no available material authority"
            )
        upstream_authority(cursor, principal.scope.tenant_id, reference.version_id)
