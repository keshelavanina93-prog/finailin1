"""Project retained observation counts without assigning accounting meaning."""

import re

from finai_api.domain.semantic_analysis import (
    Contributor,
    Coverage,
    Descriptor,
    EvidenceCell,
    FieldDefinition,
    Row,
    Value,
)
from finai_api.services.grouped_observations import count_observations
from finai_api.services.semantic_analysis_support import field_label, pin, row_key, value_options
from finai_api.services.workspace import WorkspaceError


def _linked(resolver, row, field, kind=None):
    identity = row["attributes"].get(field)
    matches = {
        str(dep["version_id"]): dep
        for dep in resolver.dependencies(pin(row))
        if dep["relation"] == "FIELD:" + field and str(dep["resource_id"]) == str(identity)
    }
    if len(matches) != 1:
        raise WorkspaceError(409, "Observation requires an unambiguous retained reference")
    linked = next(iter(matches.values()))
    if kind and linked["object_type"] != kind:
        raise WorkspaceError(409, "Observation reference has incompatible semantic type")
    return linked


def _contributor(resolver, obj, schema):
    attrs = obj["attributes"]
    record = (
        _linked(resolver, obj, "source_record_id", "SourceRecord")
        if attrs.get("source_record_id")
        else None
    )
    evidence = None
    if record and record["attributes"].get("evidence_id"):
        evidence = _linked(resolver, record, "evidence_id", "SourceEvidence")
    if attrs.get("evidence_id"):
        direct = _linked(resolver, obj, "evidence_id", "SourceEvidence")
        if evidence and pin(evidence) != pin(direct):
            raise WorkspaceError(409, "Observation source references disagree")
        evidence = direct
    coordinate = record["attributes"].get("coordinate") if record else None
    sheet = coordinate.split("!", 1)[0] if coordinate and "!" in coordinate else None
    cells = []
    original = None
    source_cells = attrs.get("source_details", {}).get("cells", {})
    if source_cells:
        match = re.fullmatch(r".+!(?:row:)?([0-9]+)", attrs.get("source_row_key", ""))
        for column, cell in source_cells.items():
            value = cell.get("value")
            if value is not None and type(value) not in (str, int, bool):
                raise WorkspaceError(409, "Source evidence requires an exact scalar representation")
            cells.append(
                EvidenceCell(
                    label=column,
                    value=value,
                    coordinate=f"{sheet}!{column}{match[1]}" if sheet and match else None,
                    formula=cell.get("formula"),
                )
            )
    else:
        if evidence and coordinate:
            original = resolver.source_cells(pin(evidence), coordinate)
        if original:
            if (
                original["source_sha256"] != evidence["attributes"]["sha256"]
                or original["coordinate"] != coordinate
                or not original["cells"]
            ):
                raise WorkspaceError(409, "Original source cells differ from retained provenance")
            cells = [EvidenceCell.model_validate(cell) for cell in original["cells"]]
        else:
            cells = [
                EvidenceCell(
                    label="Original source cell unavailable",
                    value="The original cell is unavailable in the authorized retained source.",
                )
            ]
        # Canonical attributes remain visible through the object trace; they are
        # never presented as original workbook cells when a source read fails.
    return Contributor(
        label=obj["display_name"],
        reference=pin(obj),
        cells=cells,
        document_id=original["document_id"] if original else None,
        source_sha256=evidence["attributes"].get("sha256") if evidence else None,
        sheet=sheet,
        coordinate=coordinate,
    )


def build(history, plan, resolver, company_id):
    """Only reinterpret the view; recomputation below verifies retained integrity."""
    output = history["output"]
    grouping = plan.get("group_count")
    if history["status"] != "SUCCEEDED" or not grouping or not output.get("group_counts"):
        raise WorkspaceError(409, "A retained grouped-observation result is required")
    counts = output["group_counts"]
    if type(counts.get("object_count")) is not int or any(
        type(group.get("count")) is not int for group in counts.get("groups", [])
    ):
        raise WorkspaceError(409, "Retained observation counts must be exact integers")
    function = resolver.version(plan["function"])
    spec = function["attributes"]["definition"]
    if (
        function["object_type"] != "FunctionDefinition"
        or spec.get("implementation_id") != "ontology.object-set-derived/v1"
        or spec.get("group_count")
        != {"schema_id": grouping["schema"]["resource_id"], "fields": grouping["fields"]}
        or output["function"] != plan["function"]
        or output["plan_hash"] != plan["plan_hash"]
    ):
        raise WorkspaceError(
            409, "Retained count result differs from its exact Function declaration"
        )
    schema = resolver.version(grouping["schema"])
    verified = count_observations(
        output, grouping, schema, materialized=bool(plan.get("materialization"))
    )
    if verified != output["group_counts"]:
        raise WorkspaceError(409, "Retained count contributors or grouping values are inconsistent")
    if not 1 <= len(output["objects"]) <= 1000:
        raise WorkspaceError(409, "Observation company scope requires a nonempty bounded result")
    definitions = {
        str(pin(function).version_id): pin(function),
        str(pin(schema).version_id): pin(schema),
    }
    objects, companies, evidence = {}, {}, {}
    for retained in output["objects"]:
        obj = resolver.version(retained)
        if (
            obj["attributes"] != retained["attributes"]
            or obj["display_name"] != retained["display_name"]
            or str(obj["schema_version_id"]) != str(schema["version_id"])
            or obj["object_type"] != schema["identity_key"]
        ):
            raise WorkspaceError(
                409, "Retained contributor differs from its exact canonical version"
            )
        # An access envelope or a source label is not an economic company link.
        company = _linked(resolver, obj, "legal_entity_id", "LegalEntity")
        if str(company["resource_id"]) != str(company_id):
            raise WorkspaceError(409, "Observation result belongs to another canonical company")
        companies[str(company["version_id"])] = company
        objects[str(obj["resource_id"])] = obj
        evidence[str(obj["resource_id"])] = _contributor(resolver, obj, schema)
    if len(companies) != 1:
        raise WorkspaceError(409, "Observation result mixes canonical company versions")
    company = next(iter(companies.values()))
    definitions[str(company["version_id"])] = pin(company)
    specs = schema["attributes"]["fields"]
    fields = []
    schema_deps = resolver.dependencies(pin(schema))
    for name in grouping["fields"]:
        field = specs[name]
        semantics = {
            str(dep["version_id"]): dep
            for dep in schema_deps
            if dep["relation"] == "SEMANTIC:" + name
            and str(dep["resource_id"]) == str(field["semantic_id"])
        }
        if len(semantics) != 1:
            raise WorkspaceError(409, "Grouping field requires its exact schema semantic contract")
        semantic = next(iter(semantics.values()))
        if semantic["object_type"] != "SemanticContract":
            raise WorkspaceError(409, "Grouping semantic reference is not a semantic contract")
        definitions[str(semantic["version_id"])] = pin(semantic)
        fields.append(
            FieldDefinition(
                key=name,
                label=field_label(name, field),
                kind=field["kind"],
                role="DIMENSION",
                definition=pin(schema),
                semantic_id=field["semantic_id"],
                field_id=field.get("field_id"),
                filterable=True,
                groupable=True,
            )
        )
    measure = "observation_count"
    if measure in grouping["fields"]:
        raise WorkspaceError(409, "Grouping field collides with the retained count projection")
    fields.append(
        FieldDefinition(
            key=measure,
            label="Source observations",
            kind="integer",
            role="MEASURE",
            unit="Source observations",
            definition=pin(function),
            aggregation="RETAINED_VALUE_ONLY",
        )
    )
    rows, contributors = [], {}
    for group in output["group_counts"]["groups"]:
        key = row_key(output["run_id"], group["key"])
        values = {}
        members = [objects[str(ref["resource_id"])] for ref in group["contributors"]]
        for part in group["key"]:
            value = Value(state=part["state"], value=part.get("value"))
            if part["state"] == "VALUE" and specs[part["field"]]["kind"] == "reference":
                linked = [_linked(resolver, member, part["field"]) for member in members]
                if len({str(row["version_id"]) for row in linked}) != 1:
                    raise WorkspaceError(409, "Grouped references mix exact canonical versions")
                value = value.model_copy(
                    update={"label": linked[0]["display_name"], "reference": pin(linked[0])}
                )
            values[part["field"]] = value
        values[measure] = Value(value=group["count"])
        label = " · ".join(
            str(value.label or value.value) if value.state == "VALUE" else value.state.capitalize()
            for name, value in values.items()
            if name != measure
        )
        rows.append(
            Row(
                key=key,
                label=label,
                values=values,
                contributor_count=len(members),
                trace=pin(function),
            )
        )
        contributors[key] = [evidence[str(member["resource_id"])] for member in members]
    fields = [
        field.model_copy(update={"options": value_options(rows, field.key)})
        if field.filterable
        else field
        for field in fields
    ]
    descriptor = Descriptor(
        invocation_id=history["invocation_id"],
        receipt_hash=history["receipt_hash"],
        run_id=output["run_id"],
        function=pin(function),
        company=pin(company),
        company_label=company["display_name"],
        title=function["display_name"],
        grain=grouping["fields"],
        fields=fields,
        measure=measure,
        authority="Observation counts only; no accounting amounts authorized",
        coverage=[
            Coverage(
                label="Source observations", value=str(output["group_counts"]["object_count"])
            ),
            Coverage(label="Count coverage", value=output["group_counts"]["coverage"]),
            Coverage(label="Result coverage", value=output["coverage"]),
        ],
        valid_at=output["query"]["valid_at"],
        known_at=output["query"]["known_at"],
        recorded_at=history["receipt"]["recorded_at"],
        definitions=list(definitions.values()),
        unavailable_operations=[
            "Financial sums or currency inference",
            "Forecasts and scenarios",
            "Cross-source joins",
            "New aggregation of retained groups",
            "Business actions",
        ],
    )
    return descriptor, rows, contributors
