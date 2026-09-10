import csv
import io
import json
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from typing import Any

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.ingest import Candidate, IngestReceipt, IngestRequest
from finai_api.services.operational_source_validation import (
    profile_for,
    validate_row,
    validate_series,
)


class SourceAuthorityDenied(ValueError):
    pass


def compile_source(request: IngestRequest) -> IngestReceipt:
    """One deterministic, bounded compiler for recognized and unfamiliar CSV evidence."""
    if request.xlsx_base64 is not None:
        from finai_api.services.workbook_source import compile_workbook

        return compile_workbook(request)
    if request.xls_base64 is not None:
        from finai_api.services.xls_source import compile_xls

        return compile_xls(request)
    columns: Sequence[str] | None
    if request.json_text is not None:
        parsed = json.loads(request.json_text)
        json_rows = [
            {key: "" if value is None else str(value) for key, value in row.items()}
            for row in parsed
        ]
        columns = list(json_rows[0]) if json_rows else None
        source_rows = [(index + 2, row) for index, row in enumerate(json_rows)]
    else:
        assert request.csv_text is not None
        reader = csv.DictReader(
            io.StringIO(request.csv_text.removeprefix("\ufeff"), newline=""), strict=True
        )
        columns = reader.fieldnames
        source_rows = list(enumerate(reader, 2))
    if (
        not columns
        or any(not name.strip() for name in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("CSV requires unique, nonempty headers")
    if len(columns) > 128:
        raise ValueError("CSV exceeds 128 columns")
    operational = profile_for(request.source_system)
    if operational:
        missing = sorted(operational["required"] - set(columns))
        if missing:
            raise SourceAuthorityDenied(
                f"{operational['profile']} requires columns: {', '.join(missing)}"
            )
    tb = {"account_code", "debit", "credit"}.issubset(columns)
    allowed = {"Account", "PeriodBalance"} if tb else {"SourceRecord"}
    forbidden = set(request.requested_objects) - allowed
    if forbidden:
        raise SourceAuthorityDenied(f"Source cannot create: {', '.join(sorted(forbidden))}")
    candidates: list[Candidate] = []
    rejects: list[str] = []
    warnings = ["Semantic review and governed promotion are required; no canonical facts created."]
    dimension_columns = tuple(name for name in columns if name.startswith("dimension:"))
    if any(not name.removeprefix("dimension:").strip() for name in dimension_columns):
        raise ValueError("Dimension columns require a canonical dimension code after dimension:")
    used = ("account_code", "debit", "credit", *dimension_columns) if tb else tuple(columns)
    debit_total, credit_total = Decimal(0), Decimal(0)
    accounts: set[str] = set()
    grains: set[tuple[str, ...]] = set()
    operational_rows: list[dict[str, Any]] = []
    operational_source_rows: list[dict[str, str]] = []
    seen_operational: set[str] = set()
    with localcontext() as context:
        context.prec = 50
        for row_number, row in source_rows:
            if row_number > 10001:
                raise ValueError("CSV exceeds 10000 rows")
            if None in row or any(value is None for value in row.values()):
                rejects.append(f"row {row_number}: column count differs from header")
                continue
            if not tb:
                validation = (
                    validate_row(request.source_system or "", row, seen_operational)
                    if operational
                    else None
                )
                if validation:
                    validation["source_row"] = row_number
                    operational_rows.append(validation)
                    operational_source_rows.append(row)
                    if validation["status"] == "REJECTED":
                        rejects.append(f"row {row_number}: {', '.join(validation['reasons'])}")
                        continue
                candidates.append(
                    Candidate(
                        object_type="SourceRecord",
                        source_row=row_number,
                        epistemic_state="OBSERVED",
                        values={
                            **row,
                            **(
                                {
                                    "operational_grain": operational["grain"],
                                    "operational_validation": json.dumps(
                                        validation, sort_keys=True, separators=(",", ":")
                                    ),
                                }
                                if operational and validation
                                else {}
                            ),
                        },
                    )
                )
                continue
            account = row["account_code"]
            grain = (account, *(row[name] for name in dimension_columns))
            if not account.strip() or grain in grains:
                rejects.append(
                    f"row {row_number}: empty account or duplicate account/dimension grain"
                )
                continue
            try:
                debit, credit = Decimal(row["debit"]), Decimal(row["credit"])
                if any(
                    not value.is_finite()
                    or value < 0
                    or int(value.as_tuple().exponent) < -6
                    or value >= Decimal("1e24")
                    for value in (debit, credit)
                ):
                    raise ValueError("unsupported amount")
            except (InvalidOperation, ValueError):
                rejects.append(f"row {row_number}: amounts require finite nonnegative decimals")
                continue
            accounts.add(account)
            grains.add(grain)
            debit_total += debit
            credit_total += credit
            candidates.extend(
                [
                    Candidate(
                        object_type="Account",
                        source_row=row_number,
                        epistemic_state="OBSERVED",
                        values={"account_code": account},
                    ),
                    Candidate(
                        object_type="PeriodBalance",
                        source_row=row_number,
                        epistemic_state="DERIVED",
                        function="finance.tb.net-balance/1",
                        values={
                            "account_code": account,
                            "debit": str(debit),
                            "credit": str(credit),
                            "net_balance": str(debit - credit),
                            **{name: row[name] for name in dimension_columns},
                        },
                    ),
                ]
            )
        imbalance = str(debit_total - credit_total)
    if operational:
        validate_series(request.source_system or "", operational_source_rows, operational_rows)
    if not candidates:
        warnings.append("No usable candidate rows")
    if operational:
        warnings.append(
            "Operational measurements are retained as mapped candidates; reviewed unit "
            "normalization and canonical promotion are required."
        )
    elif not tb:
        warnings.append("Unfamiliar schema retained without inferred business meaning")
    request_hash = canonical_sha256(request)
    return IngestReceipt(
        receipt_id=f"ir_{request_hash}",
        request_sha256=request_hash,
        source_sha256=sha256(request.source_bytes()).hexdigest(),
        scope=request.scope,
        source_class="TRIAL_BALANCE" if tb else "UNFAMILIAR_TABULAR",
        source_profile=(
            {
                "profile": operational["profile"],
                "grain": operational["grain"],
                "validation": {
                    "status": (
                        "REJECTED"
                        if any(item["status"] == "REJECTED" for item in operational_rows)
                        else "REVIEW_REQUIRED"
                        if any(item["status"] == "REVIEW_REQUIRED" for item in operational_rows)
                        else "VALID"
                    ),
                    "grain": operational["grain"],
                    "rows": operational_rows,
                    "promotion_eligible": False,
                    "binding_status": "UNRESOLVED",
                },
            }
            if operational
            else {}
        ),
        authority_contract_version="tb/1"
        if tb
        else (operational["profile"] if operational else "tabular/1"),
        pack_version="finance/1"
        if tb
        else ("industrial-operations/1" if operational else "enterprise-common/1"),
        plan=(
            "preserve",
            "classify",
            "authority-check",
            "profile",
            "bind",
            "validate",
            "candidates",
        ),
        observed_bindings={name: f"csv:{name}" for name in used},
        used_fields=used,
        unused_fields=tuple(name for name in columns if name not in used),
        candidates=tuple(candidates),
        rejects=tuple(rejects),
        warnings=tuple(warnings),
        reconciliation={
            "status": "PASS"
            if tb and candidates and not rejects and Decimal(imbalance) == 0
            else "REVIEW_REQUIRED",
            "debit": str(debit_total),
            "credit": str(credit_total),
            "imbalance": imbalance,
        }
        if tb
        else {"status": "NOT_APPLICABLE"},
        functions_executed=("finance.tb.net-balance/1", "finance.tb.balance-check/1")
        if accounts
        else (),
    )
