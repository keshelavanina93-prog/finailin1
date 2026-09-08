"""Read-only, exact source-to-accepted-journal movement reconciliation.

This consumes canonical journal readback, never publishes or repairs a journal.
Source-pair candidates do not establish acceptance. Missing journals remain null.
"""

from decimal import Decimal, Inexact, localcontext
from types import SimpleNamespace
from uuid import UUID

from finai_api.domain.semantic_analysis import ProjectionRequest
from finai_api.security import require_permission
from finai_api.services import company_journals, semantic_analysis
from finai_api.services.accounting_promotion import validate_journal
from finai_api.services.entity_movement_review import digest
from finai_api.services.semantic_analysis_movements import build
from finai_api.services.workspace import WorkspaceError


def resource_pin(node):
    return {key: str(node[key]) for key in ("resource_id", "version_id")}


def compile_reconciliation(review, source, targets, details, selection, snapshot_at):
    """Pure reducer over validated source review and exact canonical readback details."""
    pairs = {pair["source_coordinate"]: pair for pair in review["pairs"]}
    accepted: list[dict] = []
    rejected, seen = [], set()
    totals: dict[str, dict] = {}
    with localcontext() as arithmetic:
        arithmetic.prec = 50
        arithmetic.traps[Inexact] = True
        debit = credit = matched = Decimal(0)
        for detail in sorted(details, key=lambda d: d["journal"]["resource_id"]):
            entry = detail["journal"]
            if entry["resource_id"] in seen:
                raise WorkspaceError(409, "Duplicate journal in reconciliation snapshot")
            seen.add(entry["resource_id"])
            try:
                if detail["selection"] != selection or detail["snapshot_at"] != snapshot_at:
                    raise WorkspaceError(409, "Journal accounting context or snapshot differs")
                if resource_pin(detail["binding"]) != resource_pin(source["binding"]):
                    raise WorkspaceError(409, "Journal does not consume the exact source binding")
                if entry["authority_state"] != "APPROVED":
                    raise WorkspaceError(409, "Journal is not reviewed")
                integrity = company_journals.check_integrity(
                    entry, detail["binding"], detail["lines"], detail["integrity"]["issues"]
                )
                if integrity["state"] != "COMPLETE_BALANCED":
                    raise WorkspaceError(409, "Journal bundle is incomplete or unbalanced")
                validate_journal(
                    SimpleNamespace(
                        resource_id=entry["resource_id"],
                        object_type="JournalEntry",
                        attributes=entry["attributes"],
                    ),
                    lambda identity, *_: targets[str(identity)],
                )
                lines = detail["lines"]
                coordinates = {row["source_record"]["attributes"]["coordinate"] for row in lines}
                if len(lines) != 2 or len(coordinates) != 1:
                    raise WorkspaceError(409, "Journal lacks one exact two-sided source-cell pair")
                coordinate = next(iter(coordinates))
                pair = pairs.get(coordinate)
                if pair is None:
                    raise WorkspaceError(
                        409, "Journal source cell is excluded or outside the retained source"
                    )
                if entry["attributes"].get("posting_date") != pair["entry"]["posting_date"]:
                    raise WorkspaceError(409, "Journal date differs from its exact source row")
                expected = {line["side"]: line for line in pair["lines"]}
                if {row["line"]["attributes"]["side"] for row in lines} != set(expected):
                    raise WorkspaceError(
                        409, "Journal does not contain the exact debit and credit sides"
                    )
                for row in lines:
                    attrs = row["line"]["attributes"]
                    original = expected[attrs["side"]]
                    if (
                        resource_pin(row["account"]) != resource_pin(original["account"])
                        or attrs.get("account_id") != original["account"]["resource_id"]
                        or attrs.get("journal_id") != entry["resource_id"]
                        or attrs["amount"]["currency_id"] != original["amount"]["currency_id"]
                        or Decimal(attrs["amount"]["amount"])
                        != Decimal(original["amount"]["amount"])
                        or row["source_record"]["attributes"].get("evidence_id")
                        != source["evidence"]["resource_id"]
                        or row["dimensions"]["state"] != "COMPLETE"
                    ):
                        raise WorkspaceError(
                            409,
                            "Journal line amount, account, evidence or dimension policy differs",
                        )
            except (WorkspaceError, KeyError, ValueError, TypeError) as exc:
                rejected.append(
                    {
                        "journal": resource_pin(entry),
                        "reason": exc.detail
                        if isinstance(exc, WorkspaceError)
                        else "Incomplete journal evidence",
                    }
                )
                continue
            if any(item["source_coordinate"] == coordinate for item in accepted):
                raise WorkspaceError(
                    409, "More than one accepted journal claims the same source cell"
                )
            accepted.append(
                {
                    "journal": resource_pin(entry),
                    "source_coordinate": coordinate,
                    "lines": [
                        {"line": resource_pin(row["line"]), "dimensions": row["dimensions"]}
                        for row in lines
                    ],
                }
            )
            matched += Decimal(expected["DEBIT"]["amount"]["amount"])
            for row in lines:
                attrs = row["line"]["attributes"]
                amount = Decimal(attrs["amount"]["amount"])
                account = row["account"]
                total = totals.setdefault(
                    account["resource_id"],
                    {
                        "account": resource_pin(account),
                        "debit": Decimal(0),
                        "credit": Decimal(0),
                        "source_coordinates": [],
                    },
                )
                total[attrs["side"].lower()] += amount
                total["source_coordinates"].append(coordinate)
                if attrs["side"] == "DEBIT":
                    debit += amount
                else:
                    credit += amount
        if matched != debit or debit != credit:
            raise WorkspaceError(409, "Accepted source-to-journal controls do not reconcile")
        missing = sorted(set(pairs) - {item["source_coordinate"] for item in accepted})
        movements = [
            {
                "account": total["account"],
                "debit": format(total["debit"], "f"),
                "credit": format(total["credit"], "f"),
                "net_movement": format(total["debit"] - total["credit"], "f"),
                "source_coordinates": sorted(set(total["source_coordinates"])),
                "opening_balance": None,
                "closing_balance": None,
            }
            for _, total in sorted(totals.items())
        ]
        result = {
            "contract": "source-journal-movement-reconciliation/1",
            "basis": "EXACT_SOURCE_MATCHED_CANONICAL_JOURNALS",
            "status": "UNAVAILABLE"
            if not accepted
            else "PARTIAL"
            if missing or rejected
            else "RECONCILED",
            "selection": selection,
            "snapshot_at": snapshot_at,
            "source_receipt_hash": review["reconciliation"]["receipt_hash"],
            "source_sha256": source["sha256"],
            "binding": source["binding"],
            "source_amount_total": review["reconciliation"]["source_amount_total"],
            "matched_source_amount": format(matched, "f") if accepted else None,
            "journal_debit_total": format(debit, "f") if accepted else None,
            "journal_credit_total": format(credit, "f") if accepted else None,
            "unmatched_source_amount": format(
                Decimal(review["reconciliation"]["source_amount_total"]) - matched, "f"
            ),
            "accepted": accepted,
            "rejected": rejected,
            "missing_coordinates": missing,
            "excluded_rows": review["reconciliation"]["excluded_rows"],
            "movement_trial_balance": movements if accepted else None,
            "ledger_completeness": "UNESTABLISHED",
            "certification_available": False,
            "current_use_authorized": False,
            "business_effect_authorized": False,
        }
    result["receipt_hash"] = digest(result)
    return result


def reconcile(principal, invocation_id, company_id, snapshot_at=None):
    """Shared retained-source projection plus bounded canonical snapshot reconciliation."""
    require_permission(principal, "ontology_read")
    history, plan, resolver = semantic_analysis.load(principal, invocation_id)
    if "entity_movement_review" not in history["output"]:
        raise WorkspaceError(422, "Reconciliation requires a retained source movement review")
    source = history["output"]["source_document"]
    with resolver.read_session():
        # Recomputes source evidence and refuses a changed binding/retained receipt.
        descriptor, _, _ = build(history, plan, resolver, company_id)
        targets = {ref["resource_id"]: resolver.version(ref) for ref in plan["static_dependencies"]}
        scope = resolver.version(source["scope"])
        binding = resolver.version(source["binding"])
        for owner, fields in (
            (scope, ("legal_entity_id", "chart_id")),
            (binding, ("ledger_id", "book_id", "period_id", "currency_id")),
        ):
            for field in fields:
                node = resolver.field(owner, field)
                targets[str(node["resource_id"])] = node
        calendar = resolver.field(targets[source["context"]["ledger_id"]], "calendar_id")
        targets[str(calendar["resource_id"])] = calendar
    if str(descriptor.company.resource_id) != str(company_id):
        raise WorkspaceError(404, "Source result unavailable for this company")
    context = source["context"]
    args = [
        principal,
        company_id,
        *[UUID(context[key]) for key in ("ledger_id", "book_id", "period_id")],
    ]
    at = company_journals.read_time(snapshot_at)
    page = company_journals.list_journals(*args, limit=50, snapshot_at=at)
    selection = page["selection"]
    expected_ids = {
        **context,
        "calendar_id": targets[context["ledger_id"]]["attributes"]["calendar_id"],
        "legal_entity_id": source["company_id"],
        "chart_id": targets[source["scope"]["resource_id"]]["attributes"]["chart_id"],
    }
    if any(ref != resource_pin(targets[expected_ids[key]]) for key, ref in selection.items()):
        raise WorkspaceError(409, "Journal snapshot differs from exact retained source context")
    details, offset = [], 0
    while True:
        if page["coverage"]["state"] != "COMPLETE" or page["selection"] != selection:
            raise WorkspaceError(
                409, "Unresolved canonical journal coverage; no partial scan accepted"
            )
        for item in page["items"]:
            if item["accounting_binding"] != resource_pin(source["binding"]):
                continue  # This is a source-bound movement view, not a full ledger claim.
            entry = item["journal"]
            details.append(
                company_journals.detail(
                    *args, UUID(entry["resource_id"]), UUID(entry["version_id"]), snapshot_at=at
                )
            )
        if page["next_offset"] is None:
            break
        if page["next_offset"] <= offset:
            raise WorkspaceError(409, "Journal scan did not advance")
        offset = page["next_offset"]
        page = company_journals.list_journals(*args, limit=50, offset=offset, snapshot_at=at)
    receipt = compile_reconciliation(
        history["output"]["entity_movement_review"],
        source,
        targets,
        details,
        selection,
        at.isoformat(),
    )
    return {
        "reconciliation": receipt,
        "source_projection": semantic_analysis.project(
            principal, ProjectionRequest(invocation_id=invocation_id, company_id=company_id)
        ),
    }
