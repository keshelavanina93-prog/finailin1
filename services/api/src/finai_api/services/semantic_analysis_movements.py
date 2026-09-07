"""Movement-only paired account table through the existing semantic workspace."""

from finai_api.domain.semantic_analysis import Coverage, FieldDefinition, Row, Value
from finai_api.services.entity_movement_review import review
from finai_api.services.semantic_analysis_posted import build as posted_build
from finai_api.services.semantic_analysis_support import pin, row_key, value_options
from finai_api.services.workspace import WorkspaceError


def build(history, plan, resolver, company_id):
    descriptor, posted_rows, posted_contributors = posted_build(history, plan, resolver, company_id)
    output = history["output"]
    source = output["source_document"]
    function = resolver.version(plan["function"])
    if function["attributes"]["definition"].get("entity_movement_review") is not True:
        raise WorkspaceError(409, "Entity movement review is absent from the exact Function")
    targets = {ref["resource_id"]: resolver.version(ref) for ref in plan["static_dependencies"]}
    expected = review(
        {
            "source_sha256": source["sha256"],
            "sheet": source["sheet"],
            "headers": output["source_headers"],
            "rows": output["source_rows"],
            "posting_identity_ready": True,
        },
        source,
        targets,
        source["entity_movement_review"]["policies"],
    )
    if expected != output["entity_movement_review"]:
        raise WorkspaceError(
            409, "Entity movement reconciliation differs from retained source pairs"
        )
    by_account: dict[str, dict] = {}
    for row in posted_rows:
        account = row.values["account"].value
        by_account.setdefault(account, {}).update(
            {c.coordinate: c for c in posted_contributors[row.key]}
        )
    rows, contributors = [], {}
    for movement in expected["movements"]:
        account = resolver.version(movement["account"])
        key = row_key(output["run_id"], [movement["account"], "entity-movement/1"])
        rows.append(
            Row(
                key=key,
                label=account["display_name"],
                trace=pin(account),
                contributor_count=len(movement["source_coordinates"]),
                values={
                    "account": Value(
                        value=str(account["resource_id"]),
                        label=account["display_name"],
                        reference=pin(account),
                    ),
                    "debit_movement": Value(value=movement["debit"]),
                    "credit_movement": Value(value=movement["credit"]),
                    "net_movement": Value(value=movement["net_movement"]),
                },
            )
        )
        contributors[key] = [
            by_account[str(account["resource_id"])][coordinate]
            for coordinate in movement["source_coordinates"]
        ]
    currency = next(f for f in descriptor.fields if f.role == "MEASURE")
    fields = [descriptor.fields[0].model_copy(update={"options": value_options(rows, "account")})]
    for key, label in (
        ("debit_movement", "Debit movement"),
        ("credit_movement", "Credit movement"),
        ("net_movement", "Net movement"),
    ):
        fields.append(
            FieldDefinition(
                key=key,
                label=label,
                kind="decimal",
                role="ATTRIBUTE",
                definition=descriptor.function,
                unit=currency.unit,
                unit_reference=currency.unit_reference,
                aggregation="NONE",
            )
        )
    reconciliation = expected["reconciliation"]
    descriptor = descriptor.model_copy(
        update={
            "fields": fields,
            "grain": ["account"],
            "partition_keys": [],
            "contract": "semantic-analysis/2",
            "row_noun": "objects",
            "measure": None,
            "visual": "NONE",
            "authority": "Reconciled source movements; canonical journals unavailable",
            "coverage": [
                *descriptor.coverage,
                Coverage(
                    label="Source debit and credit control",
                    value=reconciliation["source_amount_total"] + " " + str(currency.unit),
                ),
                Coverage(
                    label="Accepted canonical journals", value="None; publication gates unresolved"
                ),
                Coverage(label="Opening and closing balances", value="Unavailable"),
            ],
            "unavailable_operations": [
                "This movement view is not a trial balance from accepted canonical journals.",
                "Journal publication needs a supported profile and reviewed dimension assignments.",
                "Source precision and signs stay as posted; incompatible amounts are not rounded.",
                "Opening balances, closing balances, statements and certification are unavailable.",
            ],
        }
    )
    return descriptor, rows, contributors
