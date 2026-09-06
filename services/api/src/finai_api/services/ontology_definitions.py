"""Canonical ontology definition publication and execution; no parallel persistence store."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any
from uuid import UUID, uuid4, uuid5

from psycopg.rows import dict_row

from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.ontology_definitions import (
    DEFINITION_MODELS,
    DefinitionWrite,
    DerivedDefinition,
    Expression,
)
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.binding_identity import source_identity_key
from finai_api.services.object_sets import query_objects
from finai_api.services.workspace import WorkspaceError


def definitions(
    principal: Principal, valid_at: datetime | None = None, known_at: datetime | None = None
) -> list[dict[str, Any]]:
    if any(value is not None and value.tzinfo is None for value in (valid_at, known_at)):
        raise WorkspaceError(422, "Definition timestamps must include a timezone")
    now = datetime.now(UTC)
    with resources.resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT * FROM (SELECT DISTINCT ON(v.resource_id) v.*,i.identity_key "
            "FROM resource_versions v JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.object_type=ANY(%s) AND v.system_from<=%s "
            "AND v.valid_from<=%s AND (v.valid_to IS NULL OR v.valid_to>%s) "
            "ORDER BY v.resource_id,v.system_from DESC,v.version_id) effective "
            "WHERE authority_state='APPROVED' ORDER BY object_type,display_name",
            (
                principal.scope.tenant_id,
                list(DEFINITION_MODELS),
                known_at or now,
                valid_at or now,
                valid_at or now,
            ),
        ).fetchall()


def definition(
    principal: Principal,
    identity: UUID,
    version: UUID | None = None,
    *,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    if any(value is not None and value.tzinfo is None for value in (valid_at, known_at)):
        raise WorkspaceError(422, "Definition timestamps must include a timezone")
    with resources.resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cur:
        if version:
            row = cur.execute(
                "SELECT v.*,i.identity_key FROM resource_versions v JOIN canonical_identities i "
                "USING(tenant_id,resource_id) WHERE v.tenant_id=%s AND v.resource_id=%s "
                "AND v.version_id=%s",
                (principal.scope.tenant_id, identity, version),
            ).fetchone()
        else:
            now = datetime.now(UTC)
            row = cur.execute(
                "SELECT v.*,i.identity_key FROM resource_versions v JOIN canonical_identities i "
                "USING(tenant_id,resource_id) WHERE v.tenant_id=%s AND v.resource_id=%s "
                "AND v.system_from<=%s AND v.valid_from<=%s "
                "AND (v.valid_to IS NULL OR v.valid_to>%s) "
                "ORDER BY v.system_from DESC,v.version_id LIMIT 1",
                (
                    principal.scope.tenant_id,
                    identity,
                    known_at or now,
                    valid_at or now,
                    valid_at or now,
                ),
            ).fetchone()
        if (
            not row
            or row["object_type"] not in DEFINITION_MODELS
            or row["authority_state"] != "APPROVED"
        ):
            raise WorkspaceError(404, "Accepted ontology definition unavailable")
        pins = cur.execute(
            "SELECT d.relation,v.*,i.identity_key FROM resource_dependencies d "
            "JOIN resource_versions v ON v.tenant_id=d.tenant_id "
            "AND v.version_id=d.target_version_id "
            "JOIN canonical_identities i ON i.tenant_id=v.tenant_id "
            "AND i.resource_id=v.resource_id "
            "WHERE d.tenant_id=%s AND d.version_id=%s",
            (principal.scope.tenant_id, row["version_id"]),
        ).fetchall()
        row["dependencies"] = pins
        return row


def prepare_definition(principal: Principal, request: DefinitionWrite) -> ResourceProposal:
    if request.resource_id:
        # Editing still targets the latest publication head, including scheduled
        # definitions. Execution above resolves the currently effective version.
        with resources.resource_connection(principal) as conn:
            current = resources._get(conn, principal.scope.tenant_id, request.resource_id)
        if (
            not current
            or current["object_type"] not in DEFINITION_MODELS
            or current["authority_state"] != "APPROVED"
        ):
            raise WorkspaceError(404, "Accepted ontology definition unavailable")
        if current["object_type"] != request.kind or current["identity_key"] != request.key:
            raise WorkspaceError(409, "Definition type and business identity are immutable")
        entity = current["access_entity"]
    else:
        entity = principal.scope.legal_entity_id
    mutation = ResourceMutation(
        resource_id=request.resource_id or uuid4(),
        expected_version_id=request.expected_version_id,
        object_type=request.kind,
        identity_key=request.key,
        display_name=request.name,
        attributes=request.attributes,
        valid_from=datetime.now(UTC),
    )
    return ResourceProposal(
        title="Publish ontology definition: " + request.name[:160],
        rationale=request.rationale,
        access_entity=entity,
        mutations=[mutation],
    )


def propose_definition(principal: Principal, request: DefinitionWrite) -> Any:
    return resources.propose(principal, prepare_definition(principal, request))


def preview_definition(principal: Principal, request: DefinitionWrite) -> Any:
    proposal = prepare_definition(principal, request)
    with resources.resource_connection(principal) as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"canonical:{principal.scope.tenant_id}",),
        )
        validation = resources._validate(conn, principal, proposal)
    impact = validation["downstream_impact"]
    if impact["requires_tenant_steward"]:
        validation["downstream_impact"] = {**impact, "status": "RESTRICTED", "affected": []}
    return {"status": "VALID_AT_PREVIEW", "validation": validation, "publication_required": True}


def evaluate_expression(expression: Expression, values: dict[str, Any]) -> Any:
    if expression.op == "field":
        assert expression.field is not None
        return values.get(expression.field)
    if expression.op == "literal":
        return expression.value
    if expression.op == "coalesce":
        # An unused fallback must not invalidate an observed value, including zero.
        for argument in expression.args:
            value = evaluate_expression(argument, values)
            if value is not None:
                return value
        return None
    operands = [evaluate_expression(arg, values) for arg in expression.args]
    if any(value is None for value in operands):
        return None
    if expression.op == "concat":
        return "".join(str(value) for value in operands)
    with localcontext() as context:
        context.prec = 38
        numbers = [Decimal(str(value)) for value in operands]
        if not all(number.is_finite() for number in numbers):
            raise ValueError("Non-finite arithmetic input")
        value = numbers[0]
        for other in numbers[1:]:
            if expression.op == "add":
                value += other
            elif expression.op == "subtract":
                value -= other
            elif expression.op == "multiply":
                value *= other
            elif expression.op == "divide":
                if other == 0:
                    raise ValueError("Division by zero")
                value /= other
        return format(value, "f")


def derived_values(
    principal: Principal,
    objects: list[dict[str, Any]],
    ids: list[UUID],
    versions: dict[UUID, UUID] | None = None,
) -> list[dict[str, Any]]:
    result = []
    for identity in ids:
        resource = definition(principal, identity, (versions or {}).get(identity))
        if resource["object_type"] != "DerivedProperty":
            raise WorkspaceError(422, "Requested resource is not a derived property")
        model = DerivedDefinition.model_validate(resource["attributes"]["definition"])
        schema = next(
            (p for p in resource["dependencies"] if p["relation"] == "FIELD:schema_id"), None
        )
        if schema is None:
            raise WorkspaceError(409, "Derived property schema dependency is unavailable")
        for obj in objects:
            computed = {
                "object_id": obj["resource_id"],
                "object_version_id": obj["version_id"],
                "definition_id": resource["resource_id"],
                "definition_version_id": resource["version_id"],
                "name": model.name,
                "kind": model.result_kind,
                "epistemic_state": "DERIVED",
            }
            if obj["object_type"] != schema["identity_key"]:
                computed.update(
                    value=None,
                    status="NOT_APPLICABLE",
                    reason="Property targets another object type",
                )
                result.append(computed)
                continue
            try:
                if str(obj["schema_version_id"]) != str(schema["version_id"]):
                    raise ValueError(
                        "Object schema differs from the published derived-property schema"
                    )
                value = evaluate_expression(model.expression, obj["attributes"])
                computed.update(
                    value=value, status="AVAILABLE" if value is not None else "MISSING_INPUT"
                )
            except (ValueError, InvalidOperation) as exc:
                computed.update(value=None, status="UNAVAILABLE", reason=str(exc))
            result.append(computed)
    return result


def derive_query(
    principal: Principal, query: ObjectSetQuery, ids: list[UUID], versions: dict[UUID, UUID]
) -> dict[str, Any]:
    if (query.valid_at is not None or query.known_at is not None) and not versions:
        raise WorkspaceError(422, "Time-bound derived queries require explicit definition versions")
    if len(ids) != len(set(ids)) or (versions and set(versions) != set(ids)):
        raise WorkspaceError(
            422, "Definition pins must identify every selected property exactly once"
        )
    selected = [definition(principal, identity, versions.get(identity)) for identity in ids]
    if any(row["object_type"] != "DerivedProperty" for row in selected):
        raise WorkspaceError(422, "Requested resource is not a derived property")
    pins = {row["resource_id"]: row["version_id"] for row in selected}
    result = query_objects(principal, query)
    return {
        **result.model_dump(mode="json"),
        "contract": "ontology-derived-result/1",
        "definition_versions": [
            {
                "resource_id": row["resource_id"],
                "version_id": row["version_id"],
                "definition": row["attributes"],
                "schema_versions": [
                    {"resource_id": pin["resource_id"], "version_id": pin["version_id"]}
                    for pin in row["dependencies"]
                    if pin["relation"] == "FIELD:schema_id"
                ],
            }
            for row in selected
        ],
        "derived_values": derived_values(principal, result.objects, ids, pins),
        "coverage": "QUERY_PAGE_ONLY",
    }


def run_set(
    principal: Principal,
    identity: UUID,
    version: UUID | None,
    offset: int,
    limit: int,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    # Explicit pins intentionally support replaying a saved definition over historical data.
    # Without a pin, the caller's as-of context selects the definition as well as its objects.
    resource = definition(principal, identity, version, valid_at=valid_at, known_at=known_at)
    if resource["object_type"] != "ObjectSetDefinition":
        raise WorkspaceError(422, "Resource is not an Object Set")
    query = ObjectSetQuery.model_validate(resource["attributes"]["definition"])
    for name, supplied in (("valid_at", valid_at), ("known_at", known_at)):
        fixed = getattr(query, name)
        if fixed is not None and supplied is not None and fixed != supplied:
            raise WorkspaceError(422, "A fixed Object Set timestamp cannot be overridden")
    query = ObjectSetQuery.model_validate(
        {
            **query.model_dump(),
            "valid_at": query.valid_at or valid_at,
            "known_at": query.known_at or known_at,
        }
    )
    result = query_objects(principal, query.model_copy(update={"offset": offset, "limit": limit}))
    return {
        **result.model_dump(mode="json"),
        "definition_id": resource["resource_id"],
        "definition_version_id": resource["version_id"],
    }


def run_group(
    principal: Principal,
    identity: UUID,
    offset: int,
    limit: int,
    version: UUID | None = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    if any(value is not None and value.tzinfo is None for value in (valid_at, known_at)):
        raise WorkspaceError(422, "Definition timestamps must include a timezone")
    now = datetime.now(UTC)
    query = ObjectSetQuery(
        object_type="ObjectInterface",
        offset=offset,
        limit=limit,
        valid_at=valid_at or now,
        known_at=known_at or now,
    )
    resource = definition(
        principal, identity, version, valid_at=query.valid_at, known_at=query.known_at
    )
    mappings = {}
    if resource["object_type"] == "ObjectTypeGroup":
        types = resource["attributes"]["definition"]["types"]
    elif resource["object_type"] == "ObjectInterface":
        types = []
        for candidate in definitions(principal, query.valid_at, query.known_at):
            if candidate["object_type"] != "ObjectTypeImplementation" or candidate["attributes"][
                "interface_id"
            ] != str(identity):
                continue
            implementation = definition(
                principal, candidate["resource_id"], candidate["version_id"]
            )
            pins = {pin["relation"]: pin for pin in implementation["dependencies"]}
            contract = pins.get("FIELD:interface_id")
            schema = pins.get("FIELD:schema_id")
            if not schema or not contract or contract["version_id"] != resource["version_id"]:
                continue
            if schema["identity_key"] in mappings:
                raise WorkspaceError(
                    409, "Multiple active implementations exist for one interface/type"
                )
            types.append(schema["identity_key"])
            mappings[schema["identity_key"]] = {
                "fields": candidate["attributes"]["definition"]["fields"],
                "implementation_version_id": candidate["version_id"],
                "schema_version_id": schema["version_id"],
            }
    else:
        raise WorkspaceError(422, "Resource is not an interface or type group")
    result = query_objects(principal, query, types)
    values = []
    for obj in result.objects:
        if obj["object_type"] not in mappings:
            continue
        mapping = mappings[obj["object_type"]]
        compatible = str(obj["schema_version_id"]) == str(mapping["schema_version_id"])
        values.append(
            {
                "object_id": obj["resource_id"],
                "object_version_id": obj["version_id"],
                "implementation_version_id": mapping["implementation_version_id"],
                "status": "AVAILABLE" if compatible else "SCHEMA_CHANGED",
                "values": {
                    key: obj["attributes"].get(field) for key, field in mapping["fields"].items()
                }
                if compatible
                else None,
            }
        )
    return {
        **result.model_dump(mode="json"),
        "interface_values": values,
        "definition_id": identity,
        "definition_version_id": resource["version_id"],
    }


def prepare_binding(
    principal: Principal,
    identity: UUID,
    source_query: ObjectSetQuery,
    rationale: str,
    version: UUID | None = None,
    proposal_id: UUID | None = None,
) -> ResourceProposal:
    resource = definition(principal, identity, version)
    if resource["object_type"] != "ObjectBinding":
        raise WorkspaceError(422, "Resource is not an Object Binding")
    pins = {pin["relation"]: pin for pin in resource["dependencies"]}
    source = pins.get("FIELD:source_schema_id")
    target = pins.get("FIELD:target_schema_id")
    if not source or not target:
        raise WorkspaceError(409, "Binding schema dependencies are unavailable")
    result = query_objects(principal, source_query.model_copy(update={"offset": 0, "limit": 100}))
    if not result.total or result.total > 100:
        raise WorkspaceError(422, "Select 1-100 source objects for an atomic binding publication")
    spec = resource["attributes"]["definition"]
    mutations, lineage = [], {}
    for row in result.objects:
        if row["evidence_class"] != "SOURCE_BOUND":
            raise WorkspaceError(
                422,
                "Binding requires source-backed objects; "
                "reference or synthetic objects cannot become source evidence",
            )
        if str(row["schema_version_id"]) != str(source["version_id"]):
            raise WorkspaceError(
                409, "Source object does not match the binding's exact source schema"
            )
        values = row["attributes"]
        business_key = values.get(spec["identity_field"])
        if not isinstance(business_key, str) or not business_key.strip():
            raise WorkspaceError(
                422, "Binding identity field must contain a nonempty stable string"
            )
        canonical_reference = spec.get("identity_mode", "SOURCE_KEY") == "CANONICAL_REFERENCE"
        try:
            object_id = (
                UUID(business_key)
                if canonical_reference
                else uuid5(resource["resource_id"], business_key)
            )
        except ValueError as exc:
            raise WorkspaceError(
                422, "Binding identity must be a canonical resource reference"
            ) from exc
        if object_id in lineage:
            raise WorkspaceError(409, "Multiple source objects resolve to the same target identity")
        try:
            current = resources.get_resource(principal, object_id)["resource"]
        except WorkspaceError as exc:
            if exc.status != 404 or canonical_reference:
                raise
            current = None
        if canonical_reference:
            assert current is not None
            resolved = resources.resolve_identity(principal, object_id)
            if (
                current["object_type"] != target["identity_key"]
                or resolved["canonical_id"] != str(object_id)
                or resolved["version_id"] != str(current["version_id"])
            ):
                raise WorkspaceError(
                    409,
                    "Canonical binding target changed type, effective version or master identity",
                )
        mutation = ResourceMutation(
            resource_id=object_id,
            expected_version_id=current["version_id"] if current else None,
            object_type=target["identity_key"],
            identity_key=current["identity_key"]
            if current
            else source_identity_key(identity, business_key),
            display_name=str(values[spec["display_field"]])[:200],
            attributes={
                field["target_field"]: values[field["source_field"]]
                for field in spec["fields"]
                if field["source_field"] in values
            },
            valid_from=datetime.now(UTC),
            evidence_class=row["evidence_class"],
        )
        mutations.append(mutation)
        lineage[object_id] = {
            UUID(row["resource_id"]): UUID(row["version_id"]),
            resource["resource_id"]: resource["version_id"],
        }
        lineage[object_id][target["resource_id"]] = target["version_id"]
    return ResourceProposal(
        proposal_id=proposal_id or uuid4(),
        title="Apply ontology binding: " + resource["display_name"][:160],
        rationale=rationale,
        access_entity=principal.scope.legal_entity_id,
        mutations=mutations,
        source_versions=lineage,
    )


def run_binding(
    principal: Principal, identity: UUID, source_query: ObjectSetQuery, rationale: str
) -> Any:
    return resources.propose(
        principal, prepare_binding(principal, identity, source_query, rationale)
    )
