"""Exact source-pair reconciliation without bypassing canonical journal promotion.

This is a read-only extension of the shared retained-posting Function. Its source
pairs are not JournalEntry resources. Only the existing canonical publication
guards can accept journals; missing policy/profile/precision gates remain visible.
"""

import json
from decimal import Decimal, Inexact, localcontext
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid5

from finai_api.domain.journal_balance import balanced_amounts
from finai_api.services.accounting_promotion import validate_journal
from finai_api.services.posted_movements_function import calculate
from finai_api.services.workspace import WorkspaceError


def digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def review(parsed, source, targets, policies):
    """Compile immutable source-pair candidates and the strongest supported movement view.

    targets contains exact Function dependencies; policies is a frozen read of
    applicable account policies. It never grants promotion authority to a pair.
    """
    controls = calculate(parsed, source)
    binding = targets[source["binding"]["resource_id"]]
    scope = targets[source["scope"]["resource_id"]]
    config = binding["attributes"]
    if any(config.get(key) != value for key, value in source["context"].items()):
        raise WorkspaceError(409, "Movement context differs from its exact binding")
    from finai_api.services.source_accounting_context import validate_active_selection

    validate_active_selection(config, scope["attributes"], targets.__getitem__)
    company = source["company_id"]
    chart = scope["attributes"]["chart_id"]
    for code, ref in source["accounts"].items():
        account = targets[ref["resource_id"]]
        if (
            str(account["version_id"]) != ref["version_id"]
            or account["object_type"] != "LocalAccount"
            or account["attributes"].get("chart_id") != chart
            or account["attributes"].get("account_code") != code
        ):
            raise WorkspaceError(409, "Movement account differs from its exact chart membership")
    included = set(controls["included_coordinates"])
    account_totals: dict[str, dict] = {}
    pairs, identities = [], set()
    with localcontext() as arithmetic:
        arithmetic.prec = 50
        arithmetic.traps[Inexact] = True
        source_total = debit_total = credit_total = Decimal(0)
        for row in parsed["rows"]:
            observation = row["numeric_observations"].get("source_amount", {})
            coordinate = observation.get("coordinate")
            if coordinate not in included:
                continue
            attrs = row["attributes"]
            amount = observation["literal_decimal"]
            identity = uuid5(
                UUID(company),
                json.dumps(
                    [
                        config["ledger_id"],
                        config["book_id"],
                        attrs["source_recorder"],
                        attrs["source_line_number"],
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            if identity in identities:
                raise WorkspaceError(
                    409, "Repeated source posting identity cannot create a journal pair"
                )
            identities.add(identity)
            entry = {
                "legal_entity_id": company,
                "ledger_id": config["ledger_id"],
                "period_id": config["period_id"],
                "posting_date": attrs["posting_date"],
                "accounting_binding_id": str(binding["resource_id"]),
                "reference": attrs["source_recorder"],
                "definition": {
                    "contract": "balanced-journal/1",
                    "line_ids": [str(uuid5(identity, side)) for side in ("DEBIT", "CREDIT")],
                },
            }
            issues = []
            try:
                validate_journal(
                    SimpleNamespace(
                        resource_id=identity, object_type="JournalEntry", attributes=entry
                    ),
                    lambda resource_id, *_: targets[str(resource_id)],
                )
            except WorkspaceError as exc:
                issues.append(
                    {"code": "JOURNAL_PUBLICATION_CONTEXT_UNAVAILABLE", "detail": exc.detail}
                )
            lines = []
            for side, field in (("DEBIT", "account_code"), ("CREDIT", "credit_account_code")):
                code = attrs[field]
                account = source["accounts"][code]
                matching = policies.get(account["resource_id"], [])
                if not matching:
                    issues.append(
                        {
                            "code": "ACCOUNT_DIMENSION_POLICY_UNESTABLISHED",
                            "side": side,
                            "account": account,
                        }
                    )
                else:
                    # A policy alone is not a reviewed side-specific member assignment.
                    issues.append(
                        {
                            "code": "JOURNAL_DIMENSION_ASSIGNMENTS_REQUIRE_PUBLICATION_VALIDATION",
                            "side": side,
                            "account": account,
                            "policies": matching,
                        }
                    )
                lines.append(
                    {
                        "proposed_resource_id": str(uuid5(identity, side)),
                        "side": side,
                        "account": account,
                        "account_code": code,
                        "amount": {"amount": amount, "currency_id": config["currency_id"]},
                        "source_coordinate": coordinate,
                    }
                )
                totals = account_totals.setdefault(
                    code,
                    {
                        "account": account,
                        "debit": Decimal(0),
                        "credit": Decimal(0),
                        "source_coordinates": [],
                    },
                )
                totals[side.lower()] += Decimal(amount)
                if coordinate not in totals["source_coordinates"]:
                    totals["source_coordinates"].append(coordinate)
            try:
                balanced_amounts(lines)
            except ValueError as exc:
                issues.append(
                    {"code": "CANONICAL_JOURNAL_AMOUNT_CONTRACT_UNSUPPORTED", "detail": str(exc)}
                )
            # Keep the full source precision, including signed corrections. Never
            # round or switch sides to fit the narrower canonical Money contract.
            value = Decimal(amount)
            source_total += value
            debit_total += Decimal(lines[0]["amount"]["amount"])
            credit_total += Decimal(lines[1]["amount"]["amount"])
            pairs.append(
                {
                    "proposed_entry_id": str(identity),
                    "state": "SOURCE_POSTING_PAIR_ONLY",
                    "entry": entry,
                    "book_id": config["book_id"],
                    "lines": lines,
                    "source_row": row["row"],
                    "source_coordinate": coordinate,
                    "source_recorder_line": attrs["source_line_number"],
                    "supplementary_observations": {
                        k: v for k, v in row["numeric_observations"].items() if k != "source_amount"
                    },
                    "unavailable": [
                        "Canonical source document identity",
                        "Subledger drill",
                        "Statement mapping",
                    ],
                    "promotion_blockers": issues,
                }
            )
        if source_total != debit_total or source_total != credit_total:
            raise WorkspaceError(409, "Source pair control totals do not reconcile exactly")
        movements = [
            {
                "account_code": code,
                "account": totals["account"],
                "debit": format(totals["debit"], "f"),
                "credit": format(totals["credit"], "f"),
                "net_movement": format(totals["debit"] - totals["credit"], "f"),
                "source_coordinates": totals["source_coordinates"],
                "opening_balance": None,
                "closing_balance": None,
            }
            for code, totals in sorted(account_totals.items())
        ]
        if sum((Decimal(r["net_movement"]) for r in movements), Decimal(0)) != 0:
            raise WorkspaceError(409, "Entity movement sides do not reconcile")
    reconciliation = {
        "contract": "entity-source-movement-reconciliation/1",
        "basis": "RETAINED_SOURCE_POSTING_PAIRS",
        "source_amount_total": format(source_total, "f"),
        "source_pair_debit_total": format(debit_total, "f"),
        "source_pair_credit_total": format(credit_total, "f"),
        "difference": "0",
        "accepted_canonical_journal_count": 0,
        "canonical_journal_trial_balance": None,
        "journal_debit_total": None,
        "journal_credit_total": None,
        "included_coordinates": controls["included_coordinates"],
        "excluded_rows": controls["excluded_rows"],
        "company_id": company,
        "binding": source["binding"],
        "scope": source["scope"],
        "source_sha256": source["sha256"],
        "context": source["context"],
        "status": "SOURCE_MOVEMENTS_RECONCILED_JOURNAL_PROMOTION_UNAVAILABLE",
    }
    reconciliation["receipt_hash"] = digest(reconciliation)
    return {
        "contract": "entity-movement-review/1",
        "pairs": pairs,
        "movements": movements,
        "reconciliation": reconciliation,
        "coverage": controls["coverage"],
        "opening_balances_available": False,
        "closing_balances_available": False,
        "certification_available": False,
        "business_effect_authorized": False,
    }
