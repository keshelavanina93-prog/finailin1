"""Bounded canonical journal readback; never posting or current-use authority."""

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from psycopg.errors import QueryCanceled
from psycopg.rows import dict_row

from finai_api.domain.journal_balance import JournalManifest, balanced_amounts
from finai_api.domain.resources import CanonicalResource
from finai_api.security import require_permission
from finai_api.services import accounting_binding_status, company_context
from finai_api.services.accounting_promotion import validate_posting_date
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def canonical(row):
    return CanonicalResource.model_validate(row).model_dump(mode="json")


@contextmanager
def journal_connection(principal):
    try:
        with resource_connection(principal) as conn:
            yield conn
    except QueryCanceled as exc:
        raise WorkspaceError(
            409, "Journal read exceeded its execution budget; no partial result returned"
        ) from exc


def read_time(snapshot_at=None):
    now = datetime.now(UTC)
    if snapshot_at is not None and (snapshot_at.tzinfo is None or snapshot_at > now):
        raise WorkspaceError(422, "Journal snapshot requires an aware, non-future timestamp")
    return snapshot_at or now


def selection(principal, company_id, ledger_id, book_id, period_id, at):
    require_permission(principal, "ontology_read")
    result = company_context.resolve(
        principal,
        company_id,
        valid_at=at,
        known_at=at,
        ledger_id=ledger_id,
        book_id=book_id,
        period_id=period_id,
    )
    return result["accounting_selection"]


def start_snapshot(cursor, principal, selected, at):
    cursor.execute(
        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0)), "
        "set_config('statement_timeout','10000',true)",
        (f"canonical:{principal.scope.tenant_id}",),
    )
    for pin in selected.values():
        row = cursor.execute(
            "SELECT version_id FROM resource_versions WHERE tenant_id=%s AND resource_id=%s "
            "AND system_from<=%s AND valid_from<=%s AND (valid_to IS NULL OR valid_to>%s) "
            "ORDER BY system_from DESC,version_id LIMIT 1",
            (principal.scope.tenant_id, UUID(pin["resource_id"]), at, at, at),
        ).fetchone()
        if not row or str(row["version_id"]) != pin["version_id"]:
            raise WorkspaceError(409, "Accounting context changed; refresh company selection")
    return at


def exact(cursor, principal, identity, version, known_at):
    row = cursor.execute(
        "SELECT v.*,i.identity_key FROM resource_versions v "
        "JOIN canonical_identities i USING(tenant_id,resource_id) "
        "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.version_id=%s AND v.system_from<=%s",
        (principal.scope.tenant_id, identity, version, known_at),
    ).fetchone()
    return canonical(row) if row else None


def preload(cursor, principal, nodes, fields, at):
    if not nodes:
        return {}
    edges = cursor.execute(
        "SELECT version_id,relation,target_resource_id,target_version_id "
        "FROM resource_dependencies WHERE tenant_id=%s AND version_id=ANY(%s::uuid[]) "
        "AND relation=ANY(%s) LIMIT 50001",
        (
            principal.scope.tenant_id,
            [UUID(n["version_id"]) for n in nodes],
            ["FIELD:" + f for f in fields],
        ),
    ).fetchall()
    if len(edges) > 50000:
        raise WorkspaceError(409, "Journal dependency projection exceeds its bound")
    targets = cursor.execute(
        "SELECT v.*,i.identity_key FROM resource_versions v "
        "JOIN canonical_identities i USING(tenant_id,resource_id) "
        "WHERE v.tenant_id=%s AND v.version_id=ANY(%s::uuid[]) AND v.system_from<=%s LIMIT 50001",
        (principal.scope.tenant_id, list({e["target_version_id"] for e in edges}), at),
    ).fetchall()
    by_version = {str(n["version_id"]): canonical(n) for n in targets}
    grouped = {}
    for edge in edges:
        key = (str(edge["version_id"]), edge["relation"][6:])
        grouped.setdefault(key, []).append(edge)
    cache = {}
    for node in nodes:
        for field in fields:
            key = (node["version_id"], field)
            matches = grouped.get(key, [])
            target = (
                by_version.get(str(matches[0]["target_version_id"])) if len(matches) == 1 else None
            )
            cache[key] = (
                target
                if target and target["resource_id"] == node["attributes"].get(field)
                else None
            )
    return cache


def linked(cursor, principal, node, field, known_at, cache=None):
    if cache is not None:
        return cache.get((node["version_id"], field))
    relation = "MONEY:amount" if field == "amount" else "FIELD:" + field
    expected = (
        node["attributes"].get("amount", {}).get("currency_id")
        if field == "amount"
        else node["attributes"].get(field)
    )
    rows = cursor.execute(
        "SELECT target_resource_id,target_version_id FROM resource_dependencies "
        "WHERE tenant_id=%s AND version_id=%s AND relation=%s LIMIT 2",
        (principal.scope.tenant_id, UUID(node["version_id"]), relation),
    ).fetchall()
    if len(rows) != 1 or str(rows[0]["target_resource_id"]) != expected:
        return None
    return exact(
        cursor, principal, rows[0]["target_resource_id"], rows[0]["target_version_id"], known_at
    )


def belongs(cursor, principal, journal, selected, at, cache=None):
    if journal["object_type"] != "JournalEntry" or journal["authority_state"] != "APPROVED":
        return None
    for field in ("legal_entity_id", "ledger_id", "period_id"):
        node = linked(cursor, principal, journal, field, at, cache)
        if not node or pin(node) != selected[field]:
            return None
    binding = linked(cursor, principal, journal, "accounting_binding_id", at, cache)
    if (
        not binding
        or binding["object_type"] != "SourceAccountingBinding"
        or binding["authority_state"] != "APPROVED"
    ):
        return None
    book = linked(cursor, principal, binding, "book_id", at, cache)
    if not book or pin(book) != selected["book_id"]:
        return None
    for owner, fields in [
        (binding, ["ledger_id", "period_id", "currency_id"]),
        (book, ["ledger_id"]),
    ]:
        for field in fields:
            target = linked(cursor, principal, owner, field, at, cache)
            if not target or pin(target) != selected[field]:
                return None
    scope = linked(cursor, principal, binding, "scope_id", at, cache)
    if (
        not scope
        or scope["object_type"] != "SourceAccountingScope"
        or scope["authority_state"] != "APPROVED"
    ):
        return None
    for field in ["legal_entity_id", "chart_id"]:
        target = linked(cursor, principal, scope, field, at, cache)
        if not target or pin(target) != selected[field]:
            return None
    return binding, book


def list_journals(
    principal, company_id, ledger_id, book_id, period_id, limit=25, offset=0, snapshot_at=None
):
    if not 1 <= limit <= 50 or not 0 <= offset <= 5000:
        raise WorkspaceError(422, "Journal page limit must be 1-50 and offset 0-5000")
    at = read_time(snapshot_at)
    selected = selection(principal, company_id, ledger_id, book_id, period_id, at)
    with journal_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        at = start_snapshot(cursor, principal, selected, at)
        rows = cursor.execute(
            "SELECT v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.object_type='JournalEntry' "
            "AND v.attributes->>'legal_entity_id'=%s AND v.attributes->>'ledger_id'=%s "
            "AND v.attributes->>'period_id'=%s "
            "AND v.version_id=(SELECT h.version_id FROM resource_versions h "
            "WHERE h.tenant_id=v.tenant_id "
            "AND h.resource_id=v.resource_id AND h.system_from<=%s AND h.valid_from<=%s "
            "AND (h.valid_to IS NULL OR h.valid_to>%s) "
            "ORDER BY h.system_from DESC,h.version_id LIMIT 1) "
            "AND v.authority_state='APPROVED' AND v.evidence_class<>'REFERENCE_TEMPLATE' "
            "ORDER BY v.attributes->>'posting_date' DESC NULLS LAST,v.resource_id LIMIT 5001",
            (
                principal.scope.tenant_id,
                str(company_id),
                str(ledger_id),
                str(period_id),
                at,
                at,
                at,
            ),
        ).fetchall()
        if len(rows) > 5000:
            raise WorkspaceError(409, "Journal context exceeds the 5000 entry read bound")
        nodes = [canonical(row) for row in rows]
        cache = preload(
            cursor,
            principal,
            nodes,
            ["legal_entity_id", "ledger_id", "period_id", "accounting_binding_id"],
            at,
        )
        bindings = {
            node["version_id"]: node
            for node in cache.values()
            if node and node["object_type"] == "SourceAccountingBinding"
        }
        next_cache = preload(
            cursor,
            principal,
            list(bindings.values()),
            ["book_id", "ledger_id", "period_id", "currency_id", "scope_id"],
            at,
        )
        cache.update(next_cache)
        next_nodes = {node["version_id"]: node for node in next_cache.values() if node}
        cache.update(
            preload(
                cursor,
                principal,
                list(next_nodes.values()),
                ["legal_entity_id", "chart_id", "ledger_id"],
                at,
            )
        )
        items = []
        unresolved = 0
        for journal in nodes:
            resolved = belongs(cursor, principal, journal, selected, at, cache)
            if resolved:
                binding, book = resolved
                items.append(
                    {"journal": journal, "accounting_binding": pin(binding), "book": pin(book)}
                )
            else:
                binding = linked(cursor, principal, journal, "accounting_binding_id", at, cache)
                book = linked(cursor, principal, binding, "book_id", at, cache) if binding else None
                verified_other = (
                    book
                    and book["object_type"] == "AccountingBook"
                    and book["authority_state"] == "APPROVED"
                    and belongs(
                        cursor, principal, journal, {**selected, "book_id": pin(book)}, at, cache
                    )
                )
                if not verified_other or book["resource_id"] == selected["book_id"]["resource_id"]:
                    unresolved += 1
    return {
        **envelope(selected, at),
        "items": items[offset : offset + limit],
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(items) else None,
        "coverage": {
            "state": "UNRESOLVED" if unresolved else "COMPLETE",
            "unresolved_journal_count": unresolved,
        },
    }


def pin(node):
    return {"resource_id": node["resource_id"], "version_id": node["version_id"]}


def envelope(selected, at):
    return {
        "selection": selected,
        "snapshot_at": at.isoformat(),
        "purpose": "CANONICAL_JOURNAL_READBACK",
        "current_use_authorized": False,
        "erp_posted": False,
    }


def check_integrity(journal, binding, lines, missing):
    issues = list(missing)
    declared = 0
    balance = None
    try:
        manifest = JournalManifest.model_validate(journal["attributes"].get("definition"))
        declared = len(manifest.line_ids)
        if {str(i) for i in manifest.line_ids} != {row["line"]["resource_id"] for row in lines}:
            raise ValueError("Declared journal lines are incomplete or unavailable")
        currencies = set()
        for row in lines:
            line = row["line"]
            if (
                line["authority_state"] != "APPROVED"
                or line["attributes"].get("accounting_binding_id") != binding["resource_id"]
            ):
                raise ValueError("A retained line has incompatible review or accounting binding")
            if (line["valid_from"], line["valid_to"]) != (
                journal["valid_from"],
                journal["valid_to"],
            ):
                raise ValueError("Entry and line effective intervals differ")
            currencies.add(line["attributes"]["amount"]["currency_id"])
        if len(currencies) != 1 or next(iter(currencies)) != binding["attributes"].get(
            "currency_id"
        ):
            raise ValueError("Journal currency does not match its exact binding")
        totals = balanced_amounts([row["line"]["attributes"] for row in lines])
        if not issues:
            balance = {**totals, "currency_id": next(iter(currencies))}
    except (ValueError, KeyError, TypeError) as exc:
        issues.append(str(exc))
    return {
        "state": "INCOMPLETE_OR_UNAVAILABLE" if issues else "COMPLETE_BALANCED",
        "issues": issues,
        "declared_line_count": declared,
        "resolved_line_count": len(lines),
        "balance": balance,
    }


def detail(
    principal, company_id, ledger_id, book_id, period_id, journal_id, version_id, snapshot_at=None
):
    at = read_time(snapshot_at)
    selected = selection(principal, company_id, ledger_id, book_id, period_id, at)
    with journal_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        at = start_snapshot(cursor, principal, selected, at)
        journal = exact(cursor, principal, journal_id, version_id, at)
        resolved = belongs(cursor, principal, journal, selected, at) if journal else None
        if not resolved:
            raise WorkspaceError(
                404, "Journal unavailable in the selected company accounting context"
            )
        binding, _ = resolved
        scope = linked(cursor, principal, binding, "scope_id", at)
        evidence = linked(cursor, principal, scope, "evidence_id", at)
        rows = cursor.execute(
            "SELECT DISTINCT v.*,i.identity_key FROM resource_dependencies d "
            "JOIN resource_versions v ON v.tenant_id=d.tenant_id AND v.version_id=d.version_id "
            "JOIN canonical_identities i ON i.tenant_id=v.tenant_id "
            "AND i.resource_id=v.resource_id "
            "WHERE d.tenant_id=%s AND d.target_resource_id=%s AND d.target_version_id=%s "
            "AND d.relation='FIELD:journal_id' AND v.object_type='JournalLine' "
            "AND v.system_from<=%s "
            "ORDER BY v.resource_id,v.system_from DESC LIMIT 101",
            (principal.scope.tenant_id, journal_id, version_id, at),
        ).fetchall()
        if len(rows) > 100:
            raise WorkspaceError(409, "Journal line history exceeds its bounded bundle contract")
        lines = []
        issues = []
        seen = set()
        for raw in rows:
            line = canonical(raw)
            if line["resource_id"] in seen:
                continue
            seen.add(line["resource_id"])
            account = linked(cursor, principal, line, "account_id", at)
            record = linked(cursor, principal, line, "source_record_id", at)
            line_binding = linked(cursor, principal, line, "accounting_binding_id", at)
            if (
                not account
                or account["object_type"] != "LocalAccount"
                or not record
                or record["object_type"] != "SourceRecord"
                or not line_binding
                or pin(line_binding) != pin(binding)
            ):
                issues.append(
                    "A line's exact account, source record or accounting binding is unavailable"
                )
                continue
            chart = linked(cursor, principal, account, "chart_id", at)
            source_evidence = linked(cursor, principal, record, "evidence_id", at)
            money_currency = linked(cursor, principal, line, "amount", at)
            if (
                not chart
                or pin(chart) != selected["chart_id"]
                or not evidence
                or evidence["object_type"] != "SourceEvidence"
                or not source_evidence
                or pin(source_evidence) != pin(evidence)
                or not money_currency
                or pin(money_currency) != selected["currency_id"]
                or account["authority_state"] != "APPROVED"
                or record["authority_state"] != "APPROVED"
            ):
                issues.append("A line's exact chart or source evidence does not match its binding")
                continue
            from finai_api.services.journal_dimensions import historical

            lines.append({"line": line, "account": account, "source_record": record,
                          "dimensions": historical(conn, principal, line, account, at)})
        integrity = check_integrity(journal, binding, lines, issues)
        try:
            validate_posting_date(
                journal["attributes"], linked(cursor, principal, journal, "period_id", at)
            )
        except WorkspaceError as exc:
            integrity["state"] = "INCOMPLETE_OR_UNAVAILABLE"
            integrity["issues"].append(str(exc))
            integrity["balance"] = None
    return {
        **envelope(selected, at),
        "journal": journal,
        "binding": binding,
        "lines": lines,
        "integrity": integrity,
        "binding_eligibility": accounting_binding_status.inspect(principal, binding),
    }
