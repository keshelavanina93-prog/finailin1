"""Company-scoped analytical identities and exact source-cell assignments."""

from datetime import UTC, datetime
from uuid import UUID, uuid5

import xlrd

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.services import resources
from finai_api.services.source_documents import document_bytes
from finai_api.services.source_financial_facts import prepare
from finai_api.services.workspace import WorkspaceError

COLUMNS = {"Y": "Region", "Z": "Budget Article New", "AA": "Department"}


def validate_assignment(item, target):
    key, attrs = str(item.resource_id), item.attributes
    observation = target(attrs["observation_id"], key, "ANALYTICAL_OBSERVATION")
    context = target(attrs["company_dimension_id"], key, "ANALYTICAL_CONTEXT")
    member = target(attrs["member_id"], key, "ANALYTICAL_MEMBER")
    record = target(attrs["source_record_id"], key, "ANALYTICAL_SOURCE_CELL")
    a, c, m, r = [x["attributes"] for x in (observation, context, member, record)]
    column = c["source_column"]
    cell = a.get("source_details", {}).get("cells", {}).get(column, {})
    source_key = a["source_row_key"]
    sheet, number = source_key.rsplit("!", 1)
    if (
        item.evidence_class != "SOURCE_BOUND"
        or observation["evidence_class"] != "SOURCE_BOUND"
        or a["legal_entity_id"] != c["legal_entity_id"]
        or m["dimension_id"] != c["dimension_id"]
        or cell.get("type") != xlrd.XL_CELL_TEXT
        or not cell.get("value", "").strip()
        or cell["value"] != m["code"]
        or r["coordinate"] != f"{sheet}!{column}{number}"
        or r["evidence_id"] != a["evidence_id"]
        or attrs.get("evidence_id") != a["evidence_id"]
        or c.get("evidence_id") != a["evidence_id"]
    ):
        raise WorkspaceError(
            422, "Analytical assignment must match its source cell, company and dimension"
        )


def inspect(principal, document_id: str, sheet: str, company_id: UUID, offset: int):
    page = prepare(principal, document_id, sheet, "1c_journal", company_id, offset)
    metadata, content = document_bytes(principal, document_id)
    book = xlrd.open_workbook(file_contents=content, on_demand=True)
    try:
        source = book.sheet_by_name(sheet)
        for index, label in zip((24, 25, 26), COLUMNS.values(), strict=True):
            if source.cell_value(1, index) != label:
                raise WorkspaceError(
                    422, "Analytical column headers differ from the source profile"
                )
    finally:
        book.release_resources()
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"])
    selected = page["rows"][:10]
    specs = {}
    pins = {}
    assignments = []
    now = datetime.now(UTC)

    def add(identity, kind, name, attrs):
        specs[str(identity)] = ResourceMutation(
            resource_id=identity,
            object_type=kind,
            identity_key="source-dimension:" + str(identity),
            display_name=name[:200],
            attributes={**attrs, "evidence_id": str(evidence)},
            valid_from=now,
            evidence_class="SOURCE_BOUND",
        )

    for column, label in COLUMNS.items():
        dimension = uuid5(company_id, "source-dimension:" + label)
        header = uuid5(evidence, f"{sheet}!{column}2")
        context = uuid5(evidence, f"company-dimension:{company_id}:{sheet}:{column}")
        add(header, "SourceRecord", f"{sheet}!{column}2", {"coordinate": f"{sheet}!{column}2"})
        add(dimension, "DimensionDefinition", label, {"code": f"{company_id}:{label}"})
        add(
            context,
            "CompanyDimension",
            label,
            {
                "legal_entity_id": str(company_id),
                "dimension_id": str(dimension),
                "source_record_id": str(header),
                "source_column": column,
                "source_header": label,
            },
        )
        for row in selected:
            if row["publication_state"] != "APPROVED":
                raise WorkspaceError(
                    409, "Publish the exact source observations before assigning analytics"
                )
            attrs = row["attributes"]
            cell = attrs["source_details"]["cells"][column]
            number = attrs["source_row_key"].rsplit("!", 1)[1]
            if not cell["value"].strip():
                assignments.append(
                    {
                        "source_row": attrs["source_row_key"],
                        "dimension": label,
                        "value": None,
                        "state": "MISSING",
                    }
                )
                continue
            if cell["type"] != xlrd.XL_CELL_TEXT:
                raise WorkspaceError(
                    422, "Analytical source values must be explicit text identities"
                )
            member = uuid5(dimension, cell["value"])
            record = uuid5(evidence, f"{sheet}!{column}{number}")
            identity = uuid5(UUID(row["resource_id"]), "dimension:" + str(context))
            add(
                member,
                "DimensionMember",
                cell["value"],
                {
                    "dimension_id": str(dimension),
                    "code": cell["value"],
                },
            )
            add(
                record,
                "SourceRecord",
                f"{sheet}!{column}{number}",
                {
                    "coordinate": f"{sheet}!{column}{number}",
                },
            )
            add(
                identity,
                "SourceDimensionAssignment",
                label + ": " + cell["value"],
                {
                    "observation_id": row["resource_id"],
                    "company_dimension_id": str(context),
                    "member_id": str(member),
                    "source_record_id": str(record),
                },
            )
            pins[identity] = {UUID(row["resource_id"]): UUID(row["published_version_id"])}
            assignments.append(
                {
                    "resource_id": str(identity),
                    "source_row": attrs["source_row_key"],
                    "dimension": label,
                    "value": cell["value"],
                    "member_id": str(member),
                }
            )
    existing = resources.current_resources(principal, [UUID(key) for key in specs])
    mutations = []
    for identity, spec in specs.items():
        prior = existing.get(identity)
        if prior:
            if (
                prior["attributes"] != spec.attributes
                or prior["object_type"] != spec.object_type
                or (
                    prior["authority_state"] != "APPROVED"
                    or prior["evidence_class"] != "SOURCE_BOUND"
                )
            ):
                raise WorkspaceError(
                    409, "Existing analytical binding differs; review a new version"
                )
        else:
            mutations.append(spec)
    for item in assignments:
        if "resource_id" in item:
            prior = existing.get(item["resource_id"])
            item.update(
                state="APPROVED" if prior else "UNPUBLISHED",
                version_id=prior["version_id"] if prior else None,
            )
    return {
        "document_id": document_id,
        "company_id": str(company_id),
        "offset": offset,
        "source_rows": len(selected),
        "total_rows": page["total_rows"],
        "next_offset": offset + 10 if offset + 10 < page["total_rows"] else None,
        "assignments": assignments,
        "new_resources": len(mutations),
        "mutations": mutations,
        "source_versions": {
            m.resource_id: pins[m.resource_id] for m in mutations if m.resource_id in pins
        },
    }


def propose(principal, document_id, sheet, company_id, offset):
    result = inspect(principal, document_id, sheet, company_id, offset)
    if not result["mutations"]:
        raise WorkspaceError(409, "This analytical page is already published")
    return resources.propose(
        principal,
        ResourceProposal(
            title="Bind procurement movements to company analytical identities",
            rationale="Preserve explicit source Region, Budget Article and Department labels as "
            "company-scoped canonical dimensions, with exact source movement and cell lineage. "
            "These are source classifications, not inferred debit/credit subconto "
            "or mandatory account rules.",
            access_entity=principal.scope.legal_entity_id,
            mutations=result["mutations"],
            source_versions=result["source_versions"],
        ),
    )


def movements(principal, document_id, sheet, company_id, member_id, offset):
    from finai_api.domain.object_sets import ObjectSetQuery, PropertyFilter, Traversal
    from finai_api.services.object_sets import query_objects

    # Reuse the source/company check; the query below resolves shared canonical
    # references and returns distinct movement objects, never one amount per dimension.
    page = prepare(principal, document_id, sheet, "1c_journal", company_id, 0)
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", page["source_sha256"])
    member = resources.current_resources(principal, [member_id]).get(str(member_id))
    allowed = {str(uuid5(company_id, "source-dimension:" + label)) for label in COLUMNS.values()}
    if (
        not member
        or member["object_type"] != "DimensionMember"
        or (member["attributes"]["dimension_id"] not in allowed)
    ):
        raise WorkspaceError(422, "Select an analytical member belonging to this source company")
    return query_objects(
        principal,
        ObjectSetQuery(
            object_type="SourceDimensionAssignment",
            filters=[
                PropertyFilter(field="member_id", value=str(member_id)),
                PropertyFilter(field="evidence_id", value=str(evidence)),
            ],
            traversal=[Traversal(name="observation_id")],
            offset=offset,
            limit=50,
        ),
    )
