"""Reviewed ObjectBinding mappings over immutable shared Function receipts."""

import json
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.ontology_definitions import BindingDefinition
from finai_api.domain.resources import CalculatedBinding
from finai_api.services.workspace import WorkspaceError


def binding_properties(spec):
    model = BindingDefinition.model_validate(spec)
    refs = ([model.display_property] if model.display_property else []) + [
        field.derived_property for field in model.fields if field.derived_property
    ]
    result = {}
    for ref in refs:
        key = str(ref.resource_id)
        if key in result and result[key].version_id != ref.version_id:
            raise WorkspaceError(
                422, "Binding cannot select two versions of one calculated property"
            )
        result[key] = ref
    return list(result.values())


def resolve(principal, binding, query, input_result):
    from finai_api.services import function_execution, function_invocations, ontology_definitions
    from finai_api.services.resources import resource_connection
    from finai_api.services.upstream_authority import upstream_authority

    refs = binding_properties(binding["attributes"]["definition"])
    if not refs or input_result is None:
        raise WorkspaceError(422, "Calculated binding requires explicit retained calculated input")
    retained = function_invocations.history(principal, input_result.invocation_id)
    output = retained.get("output")
    if retained["status"] != "SUCCEEDED" or not isinstance(output, dict):
        raise WorkspaceError(409, "Binding input requires a successful Function receipt")
    from finai_api.domain.object_sets import ObjectSetQuery

    if query != ObjectSetQuery.model_validate(output["query"]):
        raise WorkspaceError(409, "Binding query must equal the exact retained source query")
    if (
        query.offset != 0
        or output.get("next_offset") is not None
        or output.get("total") != len(output.get("objects", []))
        or not 1 <= len(output.get("objects", [])) <= 100
    ):
        raise WorkspaceError(
            422, "Binding requires a complete retained set of 1-100 source objects"
        )
    configured = []
    for ref in refs:
        prop = ontology_definitions.definition(principal, ref.resource_id, ref.version_id)
        pins = [p for p in prop["dependencies"] if p["relation"] == "FIELD:schema_id"]
        if prop["object_type"] != "DerivedProperty" or len(pins) != 1:
            raise WorkspaceError(409, "Binding calculated property schema is unavailable")
        configured.append(
            {**function_execution._pin(prop), "schema": function_execution._pin(pins[0])}
        )
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT set_config('finai.exact_scope',%s,true)",
            (json.dumps(principal.scope.model_dump(mode="json")),),
        )
        row = cursor.execute(
            "SELECT plan FROM function_invocations WHERE tenant_id=%s "
            "AND request_id=%s AND exact_scope=%s::jsonb",
            (
                principal.scope.tenant_id,
                input_result.invocation_id,
                json.dumps(principal.scope.model_dump(mode="json")),
            ),
        ).fetchone()
        if row is None:
            raise WorkspaceError(404, "Binding input unavailable in exact scope")
        plan = row["plan"]
        from finai_api.domain.resource_lifecycle import VersionReference
        from finai_api.services.certification import _current

        _current(
            cursor,
            principal,
            VersionReference(**{k: plan["function"][k] for k in ("resource_id", "version_id")}),
        )
        _current(
            cursor,
            principal,
            VersionReference(resource_id=binding["resource_id"], version_id=binding["version_id"]),
        )
        upstream_authority(cursor, principal.scope.tenant_id, UUID(plan["function"]["version_id"]))
        upstream_authority(cursor, principal.scope.tenant_id, UUID(str(binding["version_id"])))
    request = FunctionInvocation.model_validate(retained["receipt"]["request"]).model_copy(
        update={"input_result": input_result, "limit": max(query.limit, 1)}
    )
    verified = function_execution._retained_input(
        principal, request, {**plan, "retained_properties": configured}
    )
    verified["source_function"] = plan["function"]
    if any(value["status"] != "AVAILABLE" for value in verified["consumed_property_values"]):
        raise WorkspaceError(
            409, "Every mapped calculated value must be AVAILABLE; no fallback is permitted"
        )
    return verified, configured


def mapped(spec, row, current, calculated):
    """Pure mapping; identity always comes from the original stored source field."""

    def value(ref):
        matches = [
            v
            for v in calculated
            if v["object_id"] == str(row["resource_id"])
            and v["object_version_id"] == str(row["version_id"])
            and v["definition_id"] == str(ref["resource_id"])
            and v["definition_version_id"] == str(ref["version_id"])
        ]
        if len(matches) != 1 or matches[0]["status"] != "AVAILABLE":
            raise WorkspaceError(409, "Exact calculated binding value is unavailable")
        return matches[0]["value"]

    display = (
        value(spec["display_property"])
        if spec.get("display_property")
        else row["attributes"].get(spec["display_field"])
    )
    if not isinstance(display, str) or not display.strip() or len(display) > 200:
        raise WorkspaceError(422, "Binding display must be nonempty text of at most 200 characters")
    if not spec["fields"]:
        if spec.get("identity_mode") != "CANONICAL_REFERENCE" or current is None:
            raise WorkspaceError(422, "Display-only binding requires an existing canonical target")
        attrs = dict(current["attributes"])
    else:
        attrs = {}
        for field in spec["fields"]:
            if field.get("derived_property"):
                attrs[field["target_field"]] = value(field["derived_property"])
            elif field["source_field"] in row["attributes"]:
                attrs[field["target_field"]] = row["attributes"][field["source_field"]]
    return display, attrs


def evidence(binding, row, query, input_result, verified, properties):
    return CalculatedBinding.model_validate(
        {
            "binding": {k: str(binding[k]) for k in ("resource_id", "version_id")},
            "source": {k: str(row[k]) for k in ("resource_id", "version_id")},
            "query": query,
            "input_result": input_result,
            "receipt_hash": verified["input_result"]["receipt_hash"],
            "run_id": verified["input_result"]["run_id"],
            "properties": [
                {k: p[k] for k in ("resource_id", "version_id", "content_hash")} for p in properties
            ],
        }
    )


def validate_proposal(principal, proposal, target):
    """Called again by the canonical independent-review transaction."""
    from finai_api.services import resources

    versions = {v for lineage in proposal.source_versions.values() for v in lineage.values()}
    bindings = {}
    if versions:
        with (
            resources.resource_connection(principal) as conn,
            conn.cursor(row_factory=dict_row) as cursor,
        ):
            rows = cursor.execute(
                "SELECT resource_id,version_id,attributes FROM resource_versions "
                "WHERE tenant_id=%s AND version_id=ANY(%s::uuid[]) AND object_type='ObjectBinding'",
                (principal.scope.tenant_id, list(versions)),
            ).fetchall()
        bindings = {(str(r["resource_id"]), str(r["version_id"])): r for r in rows}
    verified_inputs = {}
    consumed_sources = {}
    for item in proposal.mutations:
        cache = {}

        def load(identity, version, cache=cache, item=item):
            key = (str(identity), str(version))
            if key not in cache:
                cache[key] = target(
                    key[0], str(item.resource_id), "CALCULATED_BINDING:" + key[0], key[1]
                )
            return cache[key]

        meta = proposal.calculated_bindings.get(item.resource_id)
        # A retained calculated binding cannot lose its calculation evidence.
        for identity, version in proposal.source_versions.get(item.resource_id, {}).items():
            bound = bindings.get((str(identity), str(version)))
            if bound and binding_properties(bound["attributes"]["definition"]) and meta is None:
                raise WorkspaceError(
                    409, "Calculated binding lineage requires retained calculation metadata"
                )
            if (
                bound
                and binding_properties(bound["attributes"]["definition"])
                and meta is not None
                and (identity != meta.binding.resource_id or version != meta.binding.version_id)
            ):
                raise WorkspaceError(
                    409, "One proposed target can apply only one exact calculated binding"
                )
        if meta is None:
            continue
        binding = load(meta.binding.resource_id, meta.binding.version_id)
        if binding["object_type"] != "ObjectBinding":
            raise WorkspaceError(
                409, "Calculated binding evidence does not reference an ObjectBinding"
            )
        input_key = (
            str(meta.binding.version_id),
            str(meta.input_result.invocation_id),
            meta.query.model_dump_json(),
        )
        if input_key not in verified_inputs:
            verified_inputs[input_key] = resolve(principal, binding, meta.query, meta.input_result)
        verified, props = verified_inputs[input_key]
        source_key = (str(meta.source.resource_id), str(meta.source.version_id))
        sources = consumed_sources.setdefault(input_key, set())
        if source_key in sources:
            raise WorkspaceError(409, "Calculated binding source cannot map to multiple targets")
        sources.add(source_key)
        load(verified["source_function"]["resource_id"], verified["source_function"]["version_id"])
        rows = [
            r
            for r in verified["objects"]
            if str(r["resource_id"]) == str(meta.source.resource_id)
            and str(r["version_id"]) == str(meta.source.version_id)
        ]
        if len(rows) != 1:
            raise WorkspaceError(409, "Binding source must be an exact retained input object")
        row = rows[0]
        load(meta.source.resource_id, meta.source.version_id)
        for prop in props:
            load(prop["resource_id"], prop["version_id"])
        expected = evidence(binding, row, meta.query, meta.input_result, verified, props)
        if expected != meta:
            raise WorkspaceError(
                409, "Calculated binding evidence differs from the retained receipt"
            )
        pins = {p["relation"]: p for p in binding["dependencies"]}
        if (
            str(row["schema_version_id"]) != str(pins["FIELD:source_schema_id"]["version_id"])
            or row["evidence_class"] != "SOURCE_BOUND"
        ):
            raise WorkspaceError(
                409, "Calculated binding source schema or evidence is incompatible"
            )
        spec = binding["attributes"]["definition"]
        from uuid import uuid5

        from finai_api.services.binding_identity import source_identity_key

        business_key = row["attributes"].get(spec["identity_field"])
        canonical = spec.get("identity_mode", "SOURCE_KEY") == "CANONICAL_REFERENCE"
        try:
            expected_id = (
                UUID(business_key)
                if canonical
                else uuid5(UUID(str(binding["resource_id"])), business_key)
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise WorkspaceError(409, "Binding original identity value is invalid") from exc
        current = (
            resources.get_resource(principal, item.resource_id)["resource"]
            if item.expected_version_id
            else None
        )
        if current is not None and str(current["version_id"]) != str(item.expected_version_id):
            raise WorkspaceError(
                409, "Calculated binding target changed since proposal preparation"
            )
        display, attrs = mapped(spec, row, current, verified["consumed_property_values"])
        lineage = proposal.source_versions.get(item.resource_id, {})
        required = {
            meta.source.resource_id: meta.source.version_id,
            meta.binding.resource_id: meta.binding.version_id,
            UUID(str(pins["FIELD:target_schema_id"]["resource_id"])): UUID(
                str(pins["FIELD:target_schema_id"]["version_id"])
            ),
        }
        if (
            item.resource_id != expected_id
            or item.object_type != pins["FIELD:target_schema_id"]["identity_key"]
            or item.identity_key
            != (
                current["identity_key"]
                if current
                else source_identity_key(meta.binding.resource_id, business_key)
            )
            or item.attributes != attrs
            or item.display_name != display
            or item.evidence_class != "SOURCE_BOUND"
            or item.authority_state != "APPROVED"
            or any(lineage.get(k) != v for k, v in required.items())
        ):
            raise WorkspaceError(
                409, "Proposed resource differs from the exact reviewed calculated binding"
            )
    for input_key, (verified, _props) in verified_inputs.items():
        expected_sources = {
            (str(row["resource_id"]), str(row["version_id"])) for row in verified["objects"]
        }
        if consumed_sources[input_key] != expected_sources:
            raise WorkspaceError(
                409, "Calculated binding proposal must include the complete retained source set"
            )
