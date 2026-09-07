"""Bounded exact DerivedProperty dependency graphs shared by publication and execution."""

from uuid import UUID

from finai_api.domain.ontology_definitions import DerivedDefinition, Expression
from finai_api.services.workspace import WorkspaceError


def references(expression: Expression):
    if expression.property is not None:
        yield expression.property
    for argument in expression.args:
        yield from references(argument)


def _pin(row):
    return {key: str(row[key]) for key in ("resource_id", "version_id", "content_hash")}


def resolve_with_loader(roots, load, *, draft_root_ids=None):
    drafts = {str(identity) for identity in (draft_root_ids or set())}
    nodes = {}
    identities = {}
    active = set()
    total = 0
    heights = {}

    def visit(row, depth=0):
        nonlocal total
        identity, version = str(row["resource_id"]), str(row["version_id"])
        key = (identity, version)
        if depth > 10:
            raise WorkspaceError(422, "Derived dependency depth exceeds 10")
        if key in active:
            raise WorkspaceError(422, "Derived property dependencies contain a cycle")
        if identity in identities and identities[identity] != version:
            raise WorkspaceError(
                422, "A derived graph cannot select multiple versions of one property"
            )
        if key in nodes:
            if depth + heights[key] > 10:
                raise WorkspaceError(422, "Derived dependency depth exceeds 10")
            return
        if row["object_type"] != "DerivedProperty" or (
            identity not in drafts and row.get("authority_state") != "APPROVED"
        ):
            raise WorkspaceError(409, "Exact reviewed derived property is unavailable")
        identities[identity] = version
        if len(identities) > 32:
            raise WorkspaceError(422, "Derived graph exceeds 32 property versions")
        schema_refs = [d for d in row.get("dependencies", []) if d["relation"] == "FIELD:schema_id"]
        if len(schema_refs) != 1:
            raise WorkspaceError(409, "Derived property requires one exact schema dependency")
        schema = schema_refs[0]
        if (
            schema.get("object_type") != "SchemaDefinition"
            or schema.get("authority_state") != "APPROVED"
            or str(schema["resource_id"]) != str(row["attributes"].get("schema_id"))
        ):
            raise WorkspaceError(409, "Exact reviewed derived schema is unavailable")
        model = DerivedDefinition.model_validate(row["attributes"]["definition"])
        count = 0

        def count_expression(expression, level=0):
            nonlocal count
            count += 1
            if count > 100 or level > 10:
                raise WorkspaceError(422, "Derived expression exceeds its complexity limit")
            for argument in expression.args:
                count_expression(argument, level + 1)

        count_expression(model.expression)
        total += count
        if total > 1000:
            raise WorkspaceError(422, "Derived graph exceeds 1000 expression nodes")
        requested = {
            (str(ref.resource_id), str(ref.version_id)) for ref in references(model.expression)
        }
        if any(rid == identity for rid, _ in requested):
            raise WorkspaceError(422, "Derived property cannot depend on its own identity")
        retained = [
            d for d in row.get("dependencies", []) if d["relation"].startswith("DERIVED_PROPERTY:")
        ]
        if identity not in drafts:
            expected = {(rid, vid, "DERIVED_PROPERTY:" + rid) for rid, vid in requested}
            actual = {
                (str(d["resource_id"]), str(d["version_id"]), d["relation"]) for d in retained
            }
            if actual != expected or len(retained) != len(expected):
                raise WorkspaceError(
                    409, "Derived expression does not match its exact retained dependencies"
                )
        active.add(key)
        dependencies = []
        for rid, vid in sorted(requested):
            dependency = load(UUID(rid), UUID(vid))
            if (
                not dependency
                or str(dependency["resource_id"]) != rid
                or str(dependency["version_id"]) != vid
            ):
                raise WorkspaceError(409, "Exact derived dependency version is unavailable")
            visit(dependency, depth + 1)
            child = nodes[(rid, vid)]
            if child["schema"] != _pin(schema):
                raise WorkspaceError(
                    422, "Composed derived properties require the same exact schema"
                )
            dependencies.append({"resource_id": rid, "version_id": vid})
        active.remove(key)
        nodes[key] = {
            **_pin(row),
            "schema": _pin(schema),
            "dependencies": dependencies,
            "resource": row,
        }
        heights[key] = max((heights[(rid, vid)] + 1 for rid, vid in requested), default=0)

    for root in roots:
        visit(root)
    return {"roots": [_pin(root) for root in roots], "nodes": [nodes[key] for key in sorted(nodes)]}


def public_graph(graph):
    return {
        "roots": graph["roots"],
        "nodes": [
            {key: value for key, value in node.items() if key != "resource"}
            for node in graph["nodes"]
        ],
    }


def evaluate_graph(graph, objects):
    from decimal import DecimalException, InvalidOperation

    from finai_api.services.ontology_definitions import evaluate_expression

    nodes = {(n["resource_id"], n["version_id"]): n for n in graph["nodes"]}
    models = {
        key: DerivedDefinition.model_validate(n["resource"]["attributes"]["definition"])
        for key, n in nodes.items()
    }
    evaluated = {}
    for obj in objects:
        memo = {}
        invoked = {}

        def compute(key, obj=obj, memo=memo, invoked=invoked):
            if key in memo:
                return memo[key]
            node, model = nodes[key], models[key]
            schema = next(
                d for d in node["resource"]["dependencies"] if d["relation"] == "FIELD:schema_id"
            )
            row = {
                "object_id": obj["resource_id"],
                "object_version_id": obj["version_id"],
                "definition_id": node["resource_id"],
                "definition_version_id": node["version_id"],
                "name": model.name,
                "kind": model.result_kind,
                "epistemic_state": "DERIVED",
            }
            fields = {}
            used = []

            def field_value(name):
                state = (
                    "MISSING"
                    if name not in obj["attributes"]
                    else ("NULL" if obj["attributes"][name] is None else "VALUE")
                )
                fields[name] = {
                    "object_id": obj["resource_id"],
                    "object_version_id": obj["version_id"],
                    "object_content_hash": obj["content_hash"],
                    "schema_version_id": obj["schema_version_id"],
                    "field": name,
                    "state": state,
                    "value": obj["attributes"].get(name),
                }
                return obj["attributes"].get(name)

            def derived_value(reference):
                child_key = (str(reference.resource_id), str(reference.version_id))
                if child_key not in used:
                    used.append(child_key)
                child = compute(child_key)
                if child["status"] not in {"AVAILABLE", "MISSING_INPUT"}:
                    raise ValueError("Exact derived dependency is unavailable")
                return child["value"]

            if obj["object_type"] != schema["identity_key"]:
                row.update(
                    value=None,
                    status="NOT_APPLICABLE",
                    reason="Property targets another object type",
                )
            else:
                try:
                    if str(obj["schema_version_id"]) != str(schema["version_id"]):
                        raise ValueError(
                            "Object schema differs from the published derived-property schema"
                        )
                    value = evaluate_expression(
                        model.expression, obj["attributes"], derived_value, field_value
                    )
                    row.update(
                        value=value, status="AVAILABLE" if value is not None else "MISSING_INPUT"
                    )
                except (ValueError, InvalidOperation) as exc:
                    row.update(value=None, status="UNAVAILABLE", reason=str(exc))
                except DecimalException as exc:
                    row.update(
                        value=None,
                        status="UNAVAILABLE",
                        reason=f"Decimal arithmetic range failure: {type(exc).__name__}",
                    )
            row["source_fields"] = list(fields.values())
            invoked[key] = used
            memo[key] = row
            return row

        for root in graph["roots"]:
            key = (root["resource_id"], root["version_id"])
            row = dict(compute(key))
            if nodes[key]["dependencies"]:
                dependencies = {}

                def trace(selected, invoked=invoked, dependencies=dependencies, memo=memo):
                    for child in invoked[selected]:
                        if child not in dependencies:
                            dependencies[child] = {
                                **memo[child],
                                "content_hash": nodes[child]["content_hash"],
                                "schema": nodes[child]["schema"],
                            }
                            trace(child)

                trace(key)
                row["dependency_values"] = list(dependencies.values())
            else:
                row.pop("source_fields")
            evaluated[(key, str(obj["resource_id"]), str(obj["version_id"]))] = row
    return [
        evaluated[
            (
                (root["resource_id"], root["version_id"]),
                str(obj["resource_id"]),
                str(obj["version_id"]),
            )
        ]
        for root in graph["roots"]
        for obj in objects
    ]
