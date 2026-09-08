"""Deterministic company/account Metric producer over exact accepted reconciliation."""

import re
from datetime import datetime
from decimal import Context, Decimal, DecimalException, Inexact, localcontext
from hashlib import sha256
from pathlib import Path

from finai_api.domain import company_financial_metrics as contract
from finai_api.domain.semantic_analysis import Projection
from finai_api.security import require_permission
from finai_api.services.entity_movement_review import digest
from finai_api.services.workspace import WorkspaceError


def implementation_hash():
    return digest(
        {
            p.name: sha256(p.read_text(encoding="utf-8").encode()).hexdigest()
            for p in (Path(__file__), Path(contract.__file__))
        }
    )


def amount(value):
    if (
        not isinstance(value, str)
        or len(value) > 64
        or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value)
    ):
        raise WorkspaceError(409, "Financial metric requires an exact decimal string")
    return Decimal(value)


def values(debit, credit):
    if debit is None:
        return {
            key: {"state": "UNAVAILABLE", "value": None}
            for key in ("debit_movement", "credit_movement", "net_movement")
        }
    if debit < 0 or credit < 0:
        raise WorkspaceError(409, "Accepted debit/credit movements cannot change sides")
    return {
        key: {"state": "VALUE", "value": format(value, "f")}
        for key, value in (
            ("debit_movement", debit),
            ("credit_movement", credit),
            ("net_movement", debit - credit),
        )
    }


def unique(items, label):
    if len(items) != len(set(items)):
        raise WorkspaceError(409, f"Duplicate {label} in financial metric input")
    return set(items)


def compute(request, reconciliation, source_projection):
    """Pure bounded calculation. Caller supplies a verified journal reconciliation result."""
    receipt = reconciliation
    try:
        source = Projection.model_validate(source_projection)
        if (
            receipt["contract"] != "source-journal-movement-reconciliation/1"
            or receipt["basis"] != "EXACT_SOURCE_MATCHED_CANONICAL_JOURNALS"
        ):
            raise WorkspaceError(409, "Financial metrics require accepted journal reconciliation")
        if (
            digest({k: v for k, v in receipt.items() if k != "receipt_hash"})
            != receipt["receipt_hash"]
        ):
            raise WorkspaceError(409, "Financial metric reconciliation receipt changed")
        selected = receipt["selection"]
        if (
            str(request.company_id) != selected["legal_entity_id"]["resource_id"]
            or source.descriptor.company.resource_id != request.company_id
            or source.descriptor.invocation_id != request.invocation_id
            or request.snapshot_at != datetime.fromisoformat(receipt["snapshot_at"])
            or str(source.descriptor.company.version_id)
            != selected["legal_entity_id"]["version_id"]
        ):
            raise WorkspaceError(409, "Financial metric company, invocation or snapshot differs")
        if (
            request.expected_reconciliation_sha256
            and request.expected_reconciliation_sha256 != receipt["receipt_hash"]
        ):
            raise WorkspaceError(409, "Financial metric reconciliation revision is stale")
        if set(selected) != {
            "legal_entity_id",
            "ledger_id",
            "book_id",
            "period_id",
            "chart_id",
            "currency_id",
            "calendar_id",
        }:
            raise WorkspaceError(409, "Financial metric accounting scope is incomplete")
        definitions = {str(ref.resource_id): ref for ref in source.descriptor.definitions}
        for reference in [
            receipt["binding"],
            *[selected[k] for k in ("ledger_id", "book_id", "period_id", "currency_id")],
        ]:
            pinned = definitions.get(reference["resource_id"])
            if pinned is None or str(pinned.version_id) != reference["version_id"]:
                raise WorkspaceError(
                    409, "Financial metric differs from retained accounting definitions"
                )
            if "content_hash" in reference and pinned.content_hash != reference["content_hash"]:
                raise WorkspaceError(409, "Financial metric binding content hash differs")
        missing = unique(receipt["missing_coordinates"], "missing source coordinate")
        excluded = unique(
            [r["coordinate"] for r in receipt["excluded_rows"]], "excluded source coordinate"
        )
        accepted = unique(
            [r["source_coordinate"] for r in receipt["accepted"]], "accepted source coordinate"
        )
        if missing & excluded or accepted & (missing | excluded):
            raise WorkspaceError(409, "Financial metric source coverage overlaps")
        expected_status = (
            "UNAVAILABLE"
            if not accepted
            else "PARTIAL"
            if missing or receipt["rejected"]
            else "RECONCILED"
        )
        if receipt["status"] != expected_status:
            raise WorkspaceError(
                409, "Financial metric coverage status disagrees with its evidence"
            )
        originals = {str(row.trace.resource_id): row for row in source.rows}
        unique([str(row.trace.resource_id) for row in source.rows], "source account")
        root_key = "company:" + str(request.company_id)
        nodes, journals = [], []
        unique([a["journal"]["resource_id"] for a in receipt["accepted"]], "accepted journal")
        line_ids = []
        for entry in sorted(receipt["accepted"], key=lambda e: e["journal"]["resource_id"]):
            policies = {}
            for line in entry["lines"]:
                line_ids.append(line["line"]["resource_id"])
                dimensions = line["dimensions"]
                if dimensions["state"] != "COMPLETE":
                    raise WorkspaceError(409, "Financial metric journal dimensions are incomplete")
                policy = dimensions["policy"]
                policies[(policy["resource_id"], policy["version_id"])] = {
                    k: policy[k] for k in ("resource_id", "version_id")
                }
            journals.append(
                {
                    "journal": entry["journal"],
                    "lines": [r["line"] for r in entry["lines"]],
                    "dimension_policies": list(policies.values()),
                    "source_coordinate": entry["source_coordinate"],
                }
            )
        unique(line_ids, "accepted journal line")
        with localcontext(Context(prec=50)) as arithmetic:
            arithmetic.traps[Inexact] = True
            debit = credit = Decimal(0)
            covered = set()
            movements = receipt["movement_trial_balance"] or []
            unique([m["account"]["resource_id"] for m in movements], "movement account")
            for movement in sorted(movements, key=lambda m: m["account"]["resource_id"]):
                account_id = movement["account"]["resource_id"]
                row = originals[account_id]
                if str(row.trace.version_id) != movement["account"]["version_id"]:
                    raise WorkspaceError(409, "Financial metric account version differs")
                coords = unique(movement["source_coordinates"], "account source coordinate")
                if not coords or not coords <= accepted:
                    raise WorkspaceError(409, "Financial metric account includes unmatched source")
                covered |= coords
                dr, cr = amount(movement["debit"]), amount(movement["credit"])
                if amount(movement["net_movement"]) != dr - cr:
                    raise WorkspaceError(
                        409, "Financial metric account movement does not reconcile"
                    )
                debit += dr
                credit += cr
                code = row.values.get("account_code")
                nodes.append(
                    {
                        "key": "account:" + account_id,
                        "parent_key": root_key,
                        "kind": "ACCOUNT_MOVEMENTS",
                        "label": row.label,
                        "subject": row.trace,
                        "account_code": code.value if code else None,
                        "metrics": values(dr, cr),
                        "source_coordinates": sorted(coords),
                        "journal_keys": [
                            j["journal"]["resource_id"]
                            for j in journals
                            if j["source_coordinate"] in coords
                        ],
                        "analysis_row_key": row.key,
                    }
                )
            if covered != accepted or (not accepted and movements):
                raise WorkspaceError(409, "Financial metric account coverage is incomplete")
            if accepted:
                if not (
                    debit
                    == credit
                    == amount(receipt["journal_debit_total"])
                    == amount(receipt["journal_credit_total"])
                    == amount(receipt["matched_source_amount"])
                ):
                    raise WorkspaceError(409, "Financial metric totals do not reconcile")
            elif any(
                receipt[k] is not None
                for k in ("journal_debit_total", "journal_credit_total", "matched_source_amount")
            ):
                raise WorkspaceError(409, "Unavailable financial movements cannot have totals")
            nodes.insert(
                0,
                {
                    "key": root_key,
                    "parent_key": None,
                    "kind": "COMPANY_MOVEMENTS",
                    "label": source.descriptor.company_label,
                    "subject": source.descriptor.company,
                    "metrics": values(debit if accepted else None, credit),
                    "source_coordinates": sorted(accepted),
                    "journal_keys": [j["journal"]["resource_id"] for j in journals],
                },
            )
        result = contract.FinancialMetricResult(
            invocation_id=request.invocation_id,
            company_id=request.company_id,
            snapshot_at=request.snapshot_at,
            selection=selected,
            binding=receipt["binding"],
            source_function=source.descriptor.function,
            source_sha256=receipt["source_sha256"],
            source_receipt_hash=receipt["source_receipt_hash"],
            reconciliation_receipt_hash=receipt["receipt_hash"],
            implementation_sha256=implementation_hash(),
            definitions=[
                contract.MetricRecipe(
                    code=code,
                    label=label,
                    operation=operation,
                    unit=selected["currency_id"],
                    unit_label=next(
                        (
                            field.unit
                            for field in source.descriptor.fields
                            if field.unit_reference is not None
                            and str(field.unit_reference.resource_id)
                            == selected["currency_id"]["resource_id"]
                        ),
                        None,
                    ),
                )
                for code, label, operation in [
                    ("debit_movement", "Accepted debit movement", "ACCEPTED_DEBIT"),
                    ("credit_movement", "Accepted credit movement", "ACCEPTED_CREDIT"),
                    ("net_movement", "Accepted net movement", "DEBIT_MINUS_CREDIT"),
                ]
            ],
            nodes=nodes,
            journals=journals,
            coverage={
                "state": receipt["status"],
                "source_rows": len(accepted | missing | excluded),
                "literal_source_rows": len(accepted | missing),
                "accepted_journals": len(journals),
                "unmatched_source_rows": len(missing),
                "excluded_source_rows": len(excluded),
                "rejected_journals": len(receipt["rejected"]),
                "missing_coordinates": sorted(missing),
                "excluded_rows": receipt["excluded_rows"],
                "rejected": receipt["rejected"],
            },
            result_sha256="0" * 64,
        )
        revision = digest(result.model_dump(mode="json", exclude={"result_sha256"}))
        if request.expected_result_sha256 and request.expected_result_sha256 != revision:
            raise WorkspaceError(409, "Financial metric result revision is stale")
        return result.model_copy(update={"result_sha256": revision})
    except (KeyError, ValueError, TypeError, DecimalException) as exc:
        raise WorkspaceError(409, "Financial metric input is incomplete or invalid") from exc


def produce(principal, request):
    from finai_api.services.journal_reconciliation import reconcile

    require_permission(principal, "ontology_read")
    result = reconcile(principal, request.invocation_id, request.company_id, request.snapshot_at)
    return compute(request, result["reconciliation"], result["source_projection"])
