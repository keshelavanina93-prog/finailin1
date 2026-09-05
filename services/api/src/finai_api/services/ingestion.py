import csv
import io
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.ingest import Candidate, IngestReceipt, IngestRequest


class SourceAuthorityDenied(ValueError):
    pass


def compile_source(request: IngestRequest) -> IngestReceipt:
    """One deterministic, bounded compiler for recognized and unfamiliar CSV evidence."""
    reader = csv.DictReader(
        io.StringIO(request.csv_text.removeprefix("\ufeff"), newline=""), strict=True
    )
    columns = reader.fieldnames
    if (
        not columns
        or any(not name.strip() for name in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("CSV requires unique, nonempty headers")
    if len(columns) > 128:
        raise ValueError("CSV exceeds 128 columns")
    tb = {"account_code", "debit", "credit"}.issubset(columns)
    allowed = {"Account", "PeriodBalance"} if tb else {"SourceRecord"}
    forbidden = set(request.requested_objects) - allowed
    if forbidden:
        raise SourceAuthorityDenied(f"Source cannot create: {', '.join(sorted(forbidden))}")
    candidates: list[Candidate] = []
    rejects: list[str] = []
    warnings = ["Semantic review and governed promotion are required; no canonical facts created."]
    used = ("account_code", "debit", "credit") if tb else tuple(columns)
    debit_total, credit_total = Decimal(0), Decimal(0)
    accounts: set[str] = set()
    with localcontext() as context:
        context.prec = 50
        for row_number, row in enumerate(reader, 2):
            if row_number > 10001:
                raise ValueError("CSV exceeds 10000 rows")
            if None in row or any(value is None for value in row.values()):
                rejects.append(f"row {row_number}: column count differs from header")
                continue
            if not tb:
                candidates.append(
                    Candidate(
                        object_type="SourceRecord",
                        source_row=row_number,
                        epistemic_state="OBSERVED",
                        values=row,
                    )
                )
                continue
            account = row["account_code"]
            if not account.strip() or account in accounts:
                rejects.append(
                    f"row {row_number}: empty or duplicate account; dimensions need review"
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
                        },
                    ),
                ]
            )
        imbalance = str(debit_total - credit_total)
    if not candidates:
        warnings.append("No usable candidate rows")
    if not tb:
        warnings.append("Unfamiliar schema retained without inferred business meaning")
    request_hash = canonical_sha256(request)
    return IngestReceipt(
        receipt_id=f"ir_{request_hash}",
        request_sha256=request_hash,
        source_sha256=sha256(request.csv_text.encode("utf-8")).hexdigest(),
        scope=request.scope,
        source_class="TRIAL_BALANCE" if tb else "UNFAMILIAR_TABULAR",
        authority_contract_version="tb/1" if tb else "tabular/1",
        pack_version="finance/1" if tb else "enterprise-common/1",
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
