"""Canonical definition tables with explicit absence of analytical measures."""

from finai_api.domain.semantic_analysis import (
    Contributor,
    Coverage,
    Descriptor,
    EvidenceCell,
    FieldDefinition,
    Row,
    Value,
)
from finai_api.services.resources import _check_scalar
from finai_api.services.semantic_analysis_support import field_label, pin, row_key, value_options
from finai_api.services.workspace import WorkspaceError

SCALARS = {"text", "identifier", "reference", "integer", "decimal", "boolean", "date", "datetime"}


def _schema(resolver, obj):
    matches = [
        dep
        for dep in resolver.dependencies(pin(obj))
        if dep["object_type"] == "SchemaDefinition"
        and str(dep["version_id"]) == str(obj["schema_version_id"])
    ]
    if len(matches) != 1 or matches[0]["identity_key"] != obj["object_type"]:
        raise WorkspaceError(409, "Object table requires its exact declared schema")
    return matches[0]


def _company(resolver, obj, schema, depth=0):
    fields = schema["attributes"]["fields"]
    if fields.get("legal_entity_id", {}).get("target_type") == "LegalEntity":
        company = resolver.field(obj, "legal_entity_id")
        if company["object_type"] != "LegalEntity":
            raise WorkspaceError(409, "Object company reference has incompatible semantics")
        return company
    # These existing accounting ownership paths establish scope, not arbitrary joins.
    paths = [
        (name, target)
        for name, target in (
            ("chart_id", "LocalChartOfAccounts"),
            ("ledger_id", "Ledger"),
            ("book_id", "AccountingBook"),
        )
        if fields.get(name, {}).get("target_type") == target
    ]
    if depth >= 2 or not paths:
        raise WorkspaceError(
            422, "Economic company attribution is unresolved for this object table"
        )
    owners = []
    for name, kind in paths:
        parent = resolver.field(obj, name)
        if parent["object_type"] != kind:
            raise WorkspaceError(409, "Object ownership path differs from its exact schema")
        owners.append(_company(resolver, parent, _schema(resolver, parent), depth + 1))
    if len({str(owner["version_id"]) for owner in owners}) != 1:
        raise WorkspaceError(409, "Object ownership paths do not establish one exact company")
    return owners[0]


def _evidence(resolver, obj):
    # Source-bound definition dependencies are retained by the canonical binding
    # compiler; never pair a definition coordinate with another use-source hash.
    sources = [
        dep
        for dep in resolver.dependencies(pin(obj))
        if dep["relation"].startswith("BOUND_SOURCE:")
    ]
    if not sources:
        sources = [obj]
    result = []
    for source in sources:
        attrs = source["attributes"]
        if not attrs.get("source_record_id"):
            continue
        record = resolver.field(source, "source_record_id")
        evidence = resolver.field(record, "evidence_id")
        if record["object_type"] != "SourceRecord" or evidence["object_type"] != "SourceEvidence":
            raise WorkspaceError(409, "Object source evidence has incompatible semantics")
        if attrs.get("evidence_id") and pin(resolver.field(source, "evidence_id")) != pin(evidence):
            raise WorkspaceError(409, "Object source definition and source record disagree")
        original = resolver.source_cells(pin(evidence), record["attributes"]["coordinate"])
        if original and (
            original["source_sha256"] != evidence["attributes"]["sha256"]
            or original["coordinate"] != record["attributes"]["coordinate"]
            or not original["cells"]
        ):
            raise WorkspaceError(409, "Original definition cells differ from retained provenance")
        result.append(
            Contributor(
                label=source["display_name"],
                reference=pin(source),
                basis="ORIGINAL_SOURCE" if original else "UNAVAILABLE",
                cells=[EvidenceCell.model_validate(cell) for cell in original["cells"]]
                if original
                else [
                    EvidenceCell(
                        label="Original source unavailable",
                        value="Its retained definition remains inspectable in Trace.",
                    )
                ],
                document_id=original["document_id"] if original else None,
                source_sha256=evidence["attributes"]["sha256"],
                sheet=original["sheet"] if original else None,
                coordinate=record["attributes"]["coordinate"],
            )
        )
    return result


def build(history, plan, resolver, company_id):
    output = history["output"]
    if plan.get("group_count") or plan.get("derived_properties") or output.get("derived_values"):
        raise WorkspaceError(422, "Calculated outputs require their analytical capability contract")
    objects = output.get("objects", [])
    if not 1 <= len(objects) <= 1000 or len({obj["resource_id"] for obj in objects}) != len(
        objects
    ):
        raise WorkspaceError(
            422, "Object table requires a nonempty bounded set of canonical identities"
        )
    function = resolver.version(plan["function"])
    spec = function["attributes"]["definition"]
    if (
        function["object_type"] != "FunctionDefinition"
        or spec.get("implementation_id") != "ontology.object-set-derived/v1"
        or spec.get("group_count")
        or spec.get("derived_property_ids")
        or output["function"] != plan["function"]
        or output["plan_hash"] != plan["plan_hash"]
    ):
        raise WorkspaceError(409, "Retained objects differ from their exact Function declaration")
    schemas, companies, canonical = {}, {}, []
    for retained in objects:
        obj = resolver.version(retained)
        if (
            obj["attributes"] != retained["attributes"]
            or obj["display_name"] != retained["display_name"]
            or obj["object_type"] != retained["object_type"]
            or str(obj["schema_version_id"]) != str(retained["schema_version_id"])
        ):
            raise WorkspaceError(409, "Object table differs from its original retained result")
        schema = _schema(resolver, obj)
        company = _company(resolver, obj, schema)
        if str(company["resource_id"]) != str(company_id):
            raise WorkspaceError(404, "Object analysis unavailable for this company")
        companies[str(company["version_id"])] = company
        schemas[str(schema["version_id"])] = schema
        canonical.append(obj)
    if len(companies) != 1 or len(schemas) != 1:
        raise WorkspaceError(
            409, "Mixed object schemas or company revisions require explicit interpretation"
        )
    company, schema = next(iter(companies.values())), next(iter(schemas.values()))
    specs = schema["attributes"]["fields"]
    definitions = {str(row["version_id"]): pin(row) for row in (function, schema, company)}
    if "__resource" in specs:
        raise WorkspaceError(422, "The object schema conflicts with the table identity field")
    fields = [
        FieldDefinition(
            key="__resource",
            label="Object",
            role="DIMENSION",
            kind="reference",
            definition=pin(schema),
            filterable=True,
        )
    ]
    unavailable = [
        "No approved measure is present; totals and charts are unavailable.",
        "Stored numbers are attributes, not financial measures.",
        "Cross-source joins, forecasts and business effects require their own authority.",
    ]
    for name, spec in specs.items():
        if spec["kind"] not in SCALARS:
            unavailable.append(
                field_label(name, spec)
                + " is structured; inspect its canonical definition in Trace."
            )
            continue
        semantics = {
            str(dep["version_id"]): dep
            for dep in resolver.dependencies(pin(schema))
            if dep["relation"] == "SEMANTIC:" + name
            and str(dep["resource_id"]) == str(spec.get("semantic_id"))
        }
        if len(semantics) != 1:
            raise WorkspaceError(409, "Object field requires its exact schema semantic contract")
        semantic = next(iter(semantics.values()))
        if semantic["object_type"] != "SemanticContract":
            raise WorkspaceError(409, "Object field semantics have an incompatible type")
        definitions[str(semantic["version_id"])] = pin(semantic)
        fields.append(
            FieldDefinition(
                key=name,
                label=field_label(name, spec),
                kind=spec["kind"],
                role="ATTRIBUTE",
                definition=pin(schema),
                field_id=spec.get("field_id"),
                semantic_id=spec.get("semantic_id"),
                filterable=True,
                groupable=True,
            )
        )
    rows, contributors = [], {}
    for obj in canonical:
        values = {
            "__resource": Value(
                value=str(obj["resource_id"]), label=obj["display_name"], reference=pin(obj)
            )
        }
        for field in fields[1:]:
            present = field.key in obj["attributes"]
            value = obj["attributes"].get(field.key)
            state = "MISSING" if not present else "NULL" if value is None else "VALUE"
            if state == "VALUE" and not _check_scalar(field.kind, value):
                raise WorkspaceError(409, "Object attribute violates its retained schema")
            ref = (
                resolver.field(obj, field.key)
                if field.kind == "reference" and state == "VALUE"
                else None
            )
            if ref and ref["object_type"] != specs[field.key]["target_type"]:
                raise WorkspaceError(409, "Object reference differs from its declared target type")
            values[field.key] = Value(
                state=state,
                value=value,
                label=ref["display_name"] if ref else None,
                reference=pin(ref) if ref else None,
            )
        key = row_key(output["run_id"], [str(obj["resource_id"]), str(obj["version_id"])])
        evidence = _evidence(resolver, obj)
        if not evidence:
            evidence = [
                Contributor(
                    label=obj["display_name"],
                    reference=pin(obj),
                    basis="CANONICAL_DEFINITION",
                    cells=[
                        EvidenceCell(
                            label=field.label,
                            value=values[field.key].label or values[field.key].value,
                        )
                        for field in fields
                    ],
                )
            ]
        rows.append(
            Row(
                key=key,
                label=obj["display_name"],
                values=values,
                contributor_count=len(evidence),
                trace=pin(obj),
            )
        )
        contributors[key] = evidence
    fields = [
        field.model_copy(update={"options": value_options(rows, field.key)}) for field in fields
    ]
    descriptor = Descriptor(
        contract="semantic-analysis/2",
        invocation_id=history["invocation_id"],
        receipt_hash=history["receipt_hash"],
        run_id=output["run_id"],
        function=pin(function),
        company=pin(company),
        company_label=company["display_name"],
        title=function["display_name"],
        row_noun="objects",
        grain=["__resource"],
        fields=fields,
        measure=None,
        visual="NONE",
        authority="Retained canonical definitions; no analytical measure authority",
        coverage=[
            Coverage(label="Retained objects", value=str(len(rows))),
            Coverage(
                label="Query result coverage",
                value={
                    "QUERY_PAGE_ONLY": "Returned query page only",
                    "COMPLETE_BOUNDED_MATERIALIZATION": "Complete bounded saved query",
                }.get(output["coverage"], "Unresolved coverage; inspect the retained result"),
            ),
            Coverage(
                label="Further query pages",
                value="Available" if output.get("next_offset") is not None else "None",
            ),
            Coverage(label="Financial report completeness", value="Not established"),
        ],
        valid_at=output["query"]["valid_at"],
        known_at=output["query"]["known_at"],
        recorded_at=history["receipt"]["recorded_at"],
        definitions=list(definitions.values()),
        unavailable_operations=unavailable,
    )
    return descriptor, rows, contributors
