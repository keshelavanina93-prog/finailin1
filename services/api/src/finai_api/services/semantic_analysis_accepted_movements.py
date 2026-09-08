"""Read-only worksheet over already computed accepted journal movement evidence."""

from types import SimpleNamespace
from uuid import UUID

from finai_api.domain.company_financial_metrics import FinancialMetricResult
from finai_api.domain.semantic_analysis import (
    Contributor,
    Coverage,
    EvidenceCell,
    FieldDefinition,
    Row,
    Value,
)
from finai_api.services.accepted_movements_function import metric_outputs
from finai_api.services.semantic_analysis_support import digest, pin, row_key, value_options
from finai_api.services.workspace import WorkspaceError

IMPLEMENTATION = "finance.accepted-journal-movements/v1"


def require(condition):
    if not condition:
        raise WorkspaceError(409, "Accepted movement worksheet differs from retained evidence")


def build(history, plan, resolver, company_id):
    from finai_api.services import semantic_analysis
    from finai_api.services.semantic_analysis_movements import build as source_build

    try:
        output = history["output"]
        frozen = plan["accepted_movements"]
        require(output["accepted_movements"] == frozen)
        if frozen["company_id"] != str(company_id):
            raise WorkspaceError(404, "Analysis unavailable for this company")
        source_history, source_plan, source_resolver = semantic_analysis.load(
            resolver.principal, UUID(frozen["source_invocation_id"])
        )
        require(
            source_history["receipt_hash"] == frozen["source_invocation_receipt_hash"]
            and source_history["output"]["entity_movement_review"]["reconciliation"]["receipt_hash"]
            == frozen["source_receipt_hash"]
        )
        with source_resolver.read_session():
            source_descriptor, source_rows, source_contributors = source_build(
                source_history, source_plan, source_resolver, company_id
            )
        return project_retained(
            history,
            plan,
            resolver,
            company_id,
            source_descriptor,
            source_rows,
            source_contributors,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceError(409, "Accepted movement worksheet evidence is incomplete") from exc


def project_retained(
    history, plan, resolver, company_id, source_descriptor, source_rows, source_contributors
):
    output = history["output"]
    frozen = plan["accepted_movements"]
    result = FinancialMetricResult.model_validate(output["financial_metrics"])
    require(
        output["contract"] == "function-result/1"
        and output["implementation"]["implementation_id"] == IMPLEMENTATION
        and output["accepted_movements"] == frozen
        and output["current_use_authorized"] is False
        and output["business_effect_authorized"] is False
        and digest(result.model_dump(mode="json", exclude={"result_sha256"}))
        == result.result_sha256
        and result.result_sha256 == frozen["result_sha256"]
        and str(result.company_id) == frozen["company_id"] == str(company_id)
        and str(result.invocation_id) == frozen["source_invocation_id"]
        and result.reconciliation_receipt_hash == frozen["reconciliation_receipt_hash"]
        and result.source_receipt_hash == frozen["source_receipt_hash"]
        and result.snapshot_at.isoformat()
        == frozen["journal_observed_at"]
        == output["journal_observed_at"]
        and {k: v.model_dump(mode="json") for k, v in result.selection.items()}
        == frozen["selection"]
        and result.binding.model_dump(mode="json") == frozen["binding"]
        and result.source_function == source_descriptor.function
        and result.source_function.model_dump(mode="json") == frozen["source_function"]
        and source_descriptor.company.resource_id == company_id
        and str(source_descriptor.invocation_id) == frozen["source_invocation_id"]
        and source_descriptor.receipt_hash == frozen["source_invocation_receipt_hash"]
        and source_descriptor.valid_at == frozen["source_valid_at"] == output["query"]["valid_at"]
        and source_descriptor.known_at == frozen["source_known_at"] == output["query"]["known_at"]
    )
    from datetime import datetime

    expected = metric_outputs(
        result,
        SimpleNamespace(
            valid_at=datetime.fromisoformat(frozen["source_valid_at"]),
            known_at=datetime.fromisoformat(frozen["source_known_at"]),
        ),
        frozen["contributors"],
    )
    require(output["metric_outputs"] == expected)
    function = pin(resolver.version(plan["function"]))
    currency_id = result.selection["currency_id"]
    currency_refs = [
        r for r in frozen["contributors"] if r["resource_id"] == str(currency_id.resource_id)
    ]
    require(
        len(currency_refs) == 1 and currency_refs[0]["version_id"] == str(currency_id.version_id)
    )
    currency = pin(resolver.version(currency_refs[0]))
    unit = next(f.unit for f in source_descriptor.fields if f.unit_reference == currency)
    require(
        result.nodes
        and result.nodes[0].kind == "COMPANY_MOVEMENTS"
        and result.nodes[0].subject == source_descriptor.company
    )
    originals = {str(row.trace.resource_id): row for row in source_rows}
    journals = {str(j.journal.resource_id): j for j in result.journals}
    require(len(journals) == len(result.journals) == result.coverage.accepted_journals)
    require(len({node.subject.resource_id for node in result.nodes[1:]}) == len(result.nodes) - 1)
    rows, contributors = [], {}
    for node in result.nodes[1:]:
        require(node.kind == "ACCOUNT_MOVEMENTS" and node.parent_key == result.nodes[0].key)
        original = originals[str(node.subject.resource_id)]
        require(original.trace == node.subject)
        available = {c.coordinate: c for c in source_contributors[original.key]}
        require(len(set(node.source_coordinates)) == len(node.source_coordinates))
        evidence = []
        for coordinate in node.source_coordinates:
            require(coordinate in available)
            cell = available[coordinate]
            require(cell.source_sha256 == result.source_sha256)
            evidence.append(cell)
        selected = [journals[key] for key in node.journal_keys]
        require(
            len({str(j.journal.resource_id) for j in selected}) == len(selected)
            and {j.source_coordinate for j in selected} == set(node.source_coordinates)
        )
        for journal in selected:
            refs = [
                r
                for r in frozen["contributors"]
                if r["resource_id"] == str(journal.journal.resource_id)
            ]
            require(len(refs) == 1 and refs[0]["version_id"] == str(journal.journal.version_id))
            exact = pin(resolver.version(refs[0]))
            evidence.append(
                Contributor(
                    label="Accepted journal",
                    reference=exact,
                    basis="CANONICAL_DEFINITION",
                    cells=[
                        EvidenceCell(label="Source coordinate", value=journal.source_coordinate),
                        *[
                            EvidenceCell(label="Journal line version", value=f"{ref.resource_id}@{ref.version_id}")
                            for ref in journal.lines
                        ],
                        *[
                            EvidenceCell(
                                label="Dimension policy version", value=f"{ref.resource_id}@{ref.version_id}"
                            )
                            for ref in journal.dimension_policies
                        ],
                    ],
                )
            )
        require(len(evidence) <= 1000)
        key = row_key(output["run_id"], [node.subject.model_dump(mode="json"), IMPLEMENTATION])
        rows.append(
            Row(
                key=key,
                label=node.label,
                trace=node.subject,
                contributor_count=len(evidence),
                values={
                    "account_code": Value(value=node.account_code),
                    "account": Value(
                        value=str(node.subject.resource_id),
                        label=node.label,
                        reference=node.subject,
                    ),
                    **{
                        k: Value(state="VALUE" if v.state == "VALUE" else "MISSING", value=v.value)
                        for k, v in node.metrics.items()
                    },
                },
            )
        )
        contributors[key] = evidence
    fields = [
        FieldDefinition(
            key="account_code",
            label="Account code",
            kind="identifier",
            role="ATTRIBUTE",
            definition=function,
        ),
        FieldDefinition(
            key="account",
            label="Account",
            kind="reference",
            role="DIMENSION",
            definition=function,
            filterable=True,
            groupable=True,
            options=value_options(rows, "account"),
        ),
    ]
    fields.extend(
        FieldDefinition(
            key=key,
            label=label,
            kind="decimal",
            role="ATTRIBUTE",
            unit=unit,
            unit_reference=currency,
            definition=function,
            aggregation="NONE",
        )
        for key, label in (
            ("debit_movement", "Accepted debit movement"),
            ("credit_movement", "Accepted credit movement"),
            ("net_movement", "Accepted net movement"),
        )
    )
    descriptor = source_descriptor.model_copy(
        update={
            "contract": "semantic-analysis/2",
            "invocation_id": UUID(history["invocation_id"]),
            "receipt_hash": history["receipt_hash"],
            "run_id": output["run_id"],
            "function": function,
            "title": "Accepted journal movements",
            "grain": ["account"],
            "partition_keys": [],
            "fields": fields,
            "measure": None,
            "visual": "NONE",
            "row_noun": "objects",
            "authority": "Retained accepted journal movements; no current-use authority",
            "recorded_at": history["receipt"]["recorded_at"],
            "definitions": list(
                dict.fromkeys([function, currency, *source_descriptor.definitions])
            ),
            "coverage": [
                Coverage(label="Matched source coverage", value=result.coverage.state),
                Coverage(label="Accepted journals", value=str(result.coverage.accepted_journals)),
                Coverage(
                    label="Unmatched source rows", value=str(result.coverage.unmatched_source_rows)
                ),
                Coverage(
                    label="Excluded source rows", value=str(result.coverage.excluded_source_rows)
                ),
                Coverage(label="Ledger completeness", value=result.coverage.ledger_completeness),
            ],
            "context": [
                *source_descriptor.context,
                Coverage(label="Journal observed at", value=frozen["journal_observed_at"]),
            ],
            "unavailable_operations": [
                "Values are retained account movements; do not sum company and account hierarchy.",
                "Opening balances, closing balances, financial statements "
                "and certification are unavailable.",
                "Source and journal observation times are independent; "
                "reopening does not refresh either.",
            ],
        }
    )
    return descriptor, rows, contributors
