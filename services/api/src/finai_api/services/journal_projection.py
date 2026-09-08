"""Accepted journal movements in the shared analytical presentation contract."""

from finai_api.domain.semantic_analysis import Coverage, Projection, Row, Section, Selection, Value
from finai_api.services import semantic_analysis
from finai_api.services.entity_movement_review import digest
from finai_api.services.semantic_analysis_movements import build
from finai_api.services.workspace import WorkspaceError


def build_projection(source_projection, receipt, contributors, request):
    if request.filters or request.group_by:
        raise WorkspaceError(422, "Journal movements expose exact account rows without regrouping")
    originals = {str(row.trace.resource_id): row for row in source_projection.rows}
    rows, retained = [], {}
    for movement in receipt["movement_trial_balance"] or []:
        original = originals[movement["account"]["resource_id"]]
        coordinates = set(movement["source_coordinates"])
        retained[original.key] = [
            c for c in contributors[original.key] if c.coordinate in coordinates
        ]
        if {c.coordinate for c in retained[original.key]} != coordinates:
            raise WorkspaceError(409, "Accepted movement source-cell coverage is incomplete")
        rows.append(
            Row(
                key=original.key,
                label=original.label,
                trace=original.trace,
                contributor_count=len(retained[original.key]),
                values={
                    **original.values,
                    "debit_movement": Value(value=movement["debit"]),
                    "credit_movement": Value(value=movement["credit"]),
                    "net_movement": Value(value=movement["net_movement"]),
                },
            )
        )
    fields = [
        f.model_copy(
            update={
                "filterable": False,
                "groupable": False,
                "options": [r.values["account"] for r in rows] if f.key == "account" else [],
            }
        )
        for f in source_projection.descriptor.fields
    ]
    descriptor = source_projection.descriptor.model_copy(
        update={
            "receipt_hash": receipt["receipt_hash"],
            "title": "Accepted journal movement trial balance",
            "authority": "Exact source-matched accepted journals; partial source coverage",
            "fields": fields,
            "coverage": [
                Coverage(label="Accepted journals", value=str(len(receipt["accepted"]))),
                Coverage(
                    label="Source rows without an accepted journal",
                    value=str(len(receipt["missing_coordinates"])),
                ),
                Coverage(
                    label="Source rows excluded from matching",
                    value=str(len(receipt["excluded_rows"])),
                ),
                Coverage(
                    label="Journal candidates not matched",
                    value=str(len(receipt["rejected"])),
                ),
                Coverage(
                    label="Source reconciliation",
                    value={
                        "UNAVAILABLE": "No accepted journal movements available",
                        "PARTIAL": "Partial source coverage; unresolved matching remains",
                        "RECONCILED": (
                            "Eligible source rows matched; full-ledger coverage unestablished"
                        ),
                    }[receipt["status"]],
                ),
                Coverage(label="Snapshot", value=receipt["snapshot_at"]),
            ],
            "unavailable_operations": [
                "Opening and closing balances are unavailable.",
                "Statements, certification and full-ledger completeness are unavailable.",
            ],
        }
    )
    revision = digest(descriptor.model_dump(mode="json"))
    if request.descriptor_sha256 is not None and request.descriptor_sha256 != revision:
        raise WorkspaceError(409, "Journal projection changed; refresh its exact snapshot")
    selection = None
    if request.selected_row is not None:
        group = retained.get(request.selected_row)
        if group is None or request.contributor_index >= len(group):
            raise WorkspaceError(422, "Selected source contributor is outside accepted journals")
        selection = Selection(
            row_key=request.selected_row,
            contributor_index=request.contributor_index,
            contributor_count=len(group),
            contributor=group[request.contributor_index],
        )
    return Projection(
        descriptor=descriptor,
        descriptor_sha256=revision,
        rows=rows,
        total_rows=len(rows),
        sections=[Section(label=descriptor.title, row_keys=[r.key for r in rows])],
        selection=selection,
        request=request,
    )


def project(principal, request, snapshot_at=None):
    from finai_api.services.journal_reconciliation import reconcile

    result = reconcile(principal, request.invocation_id, request.company_id, snapshot_at)
    history, plan, resolver = semantic_analysis.load(principal, request.invocation_id)
    with resolver.read_session():
        _, _, contributors = build(history, plan, resolver, request.company_id)
    return build_projection(
        result["source_projection"], result["reconciliation"], contributors, request
    )
